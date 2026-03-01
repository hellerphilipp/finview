# FinView — terminal-based personal finance manager
# Copyright (C) 2026 Philipp Heller
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import csv
import datetime
import os
from decimal import Decimal

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session, selectinload

from importers.engine import CSVImporter
from models.finance import Account, Currency, Transaction


def get_all_accounts_with_balances(session: Session) -> list[tuple[Account, Decimal]]:
    """Return all accounts with their computed balance via SQL SUM().

    Excludes merge parents (virtual transactions) from the balance sum.
    """
    stmt = (
        select(Account, func.coalesce(func.sum(Transaction.value_in_account_currency), 0))
        .outerjoin(Transaction, Account.id == Transaction.account_id)
        .where(~Transaction.id.in_(_merge_parent_ids_subquery()) | Transaction.id.is_(None))
        .group_by(Account.id)
        .order_by(Account.id)
    )
    return [(acc, Decimal(str(bal))) for acc, bal in session.execute(stmt).all()]


def _split_parent_ids_subquery():
    """Subquery returning transaction ids that have children (are split parents)."""
    return (
        select(Transaction.split_parent_id)
        .where(Transaction.split_parent_id.is_not(None))
        .distinct()
        .scalar_subquery()
    )


def _merge_parent_ids_subquery():
    """Subquery returning transaction ids that are merge parents."""
    return (
        select(Transaction.merge_parent_id)
        .where(Transaction.merge_parent_id.is_not(None))
        .distinct()
        .scalar_subquery()
    )


def _merge_net_subquery():
    """Scalar subquery that computes the net total of a merge group.

    Returns the sum of value_in_account_currency for all transactions sharing
    the same merge_parent_id as the outer transaction.
    """
    MergeSibling = Transaction.__table__.alias("merge_sibling")
    return (
        select(func.sum(MergeSibling.c.value_in_account_currency))
        .where(MergeSibling.c.merge_parent_id == Transaction.merge_parent_id)
        .correlate(Transaction.__table__)
        .scalar_subquery()
    )


def _merge_parent_reviewed_subquery():
    """Scalar subquery returning the merge parent's reviewed_at for a child."""
    MergeParent = Transaction.__table__.alias("merge_parent")
    return (
        select(MergeParent.c.reviewed_at)
        .where(MergeParent.c.id == Transaction.merge_parent_id)
        .correlate(Transaction.__table__)
        .scalar_subquery()
    )


def _merge_parent_desc_subquery():
    """Scalar subquery returning the merge parent's description for a child."""
    MergeParent = Transaction.__table__.alias("merge_parent_desc")
    return (
        select(MergeParent.c.description)
        .where(MergeParent.c.id == Transaction.merge_parent_id)
        .correlate(Transaction.__table__)
        .scalar_subquery()
    )


def _is_cross_account_merge_subquery():
    """Scalar subquery that returns True when a merge group spans multiple accounts.

    Counts distinct account_id values among all children sharing the same
    merge_parent_id as the outer transaction. Returns > 1 when cross-account.
    """
    MergeSibling = Transaction.__table__.alias("merge_sibling_acc")
    return (
        select(
            func.count(func.distinct(MergeSibling.c.account_id)) > 1
        )
        .where(MergeSibling.c.merge_parent_id == Transaction.merge_parent_id)
        .correlate(Transaction.__table__)
        .scalar_subquery()
    )


def load_transaction_page(
    session: Session,
    account_id: int | None = None,
    all_accounts: bool = False,
) -> tuple[int, int, list]:
    """Load transactions and counts.

    Returns (total_count, total_unreviewed, rows).

    For counting: merge children are excluded, merge parents are counted as 1.
    For display: merge children are included (with merge metadata), merge parents
    are excluded from normal rows but returned for all-accounts grouping.

    Rows are:
    - Single account: list of tuples (Transaction, merge_net|None, merge_reviewed|None, merge_group_name|None, is_cross_account_merge)
    - All accounts: list of tuples (Transaction, account_name, merge_net|None, merge_reviewed|None, merge_group_name|None)
    """
    no_split_parent = ~Transaction.id.in_(_split_parent_ids_subquery())
    no_merge_parent = ~Transaction.id.in_(_merge_parent_ids_subquery())
    is_not_merge_child = Transaction.merge_parent_id.is_(None)

    where = None if all_accounts else (Transaction.account_id == account_id)

    # Count totals: exclude merge children, include merge parents as 1 each
    count_stmt = select(
        func.count(Transaction.id),
        func.sum(case((Transaction.reviewed_at.is_(None), 1), else_=0)),
    ).where(no_split_parent).where(is_not_merge_child)
    if all_accounts:
        count_stmt = count_stmt.join(Account, Transaction.account_id == Account.id)
    if where is not None:
        count_stmt = count_stmt.where(where)
    total_count, total_unreviewed = session.execute(count_stmt).one()
    total_count = total_count or 0
    total_unreviewed = int(total_unreviewed or 0)

    # Subquery labels for merge metadata
    merge_net = _merge_net_subquery().label("merge_net")
    merge_reviewed = _merge_parent_reviewed_subquery().label("merge_reviewed")
    merge_group_name = _merge_parent_desc_subquery().label("merge_group_name")

    # Fetch rows: exclude split parents and merge parents, but include merge children
    if all_accounts:
        stmt = (
            select(Transaction, Account.name, merge_net, merge_reviewed, merge_group_name)
            .join(Account, Transaction.account_id == Account.id)
            .where(no_split_parent)
            .where(no_merge_parent)
        )
    else:
        is_cross_account = _is_cross_account_merge_subquery().label("is_cross_account")
        stmt = (
            select(Transaction, merge_net, merge_reviewed, merge_group_name, is_cross_account)
            .where(no_split_parent)
            .where(no_merge_parent)
        )
        if where is not None:
            stmt = stmt.where(where)

    stmt = stmt.order_by(Transaction.date.desc())
    rows = session.execute(stmt).all()

    if all_accounts:
        rows = _group_merge_children_all_accounts(session, rows)
    else:
        rows = _group_merge_children_single_account(session, rows)

    return total_count, total_unreviewed, rows


def _group_merge_children_all_accounts(session, rows):
    """Post-process All Accounts rows to group merge children under their parent.

    Inserts merge parent header rows and reorders children beneath them
    at the earliest child's position.
    """
    # Separate merge children from normal rows
    normal_rows = []
    merge_groups = {}  # merge_parent_id -> list of row tuples

    for row in rows:
        tx = row[0]
        if tx.merge_parent_id is not None:
            merge_groups.setdefault(tx.merge_parent_id, []).append(row)
        else:
            normal_rows.append(row)

    if not merge_groups:
        return rows

    # Load merge parents
    parent_ids = list(merge_groups.keys())
    parents = {
        p.id: p
        for p in session.execute(
            select(Transaction).where(Transaction.id.in_(parent_ids))
        ).scalars().all()
    }

    # Build result: insert group at earliest child's date position
    result = list(normal_rows)

    for parent_id, children in merge_groups.items():
        parent = parents.get(parent_id)
        if parent is None:
            result.extend(children)
            continue

        # Find earliest child date for positioning
        earliest_date = min(c[0].date for c in children)

        # Find insertion point: after the last row with date >= earliest_date
        insert_idx = len(result)
        for i, r in enumerate(result):
            if r[0].date < earliest_date:
                insert_idx = i
                break

        # Compute net and get account currency
        net = sum(Decimal(str(c[0].value_in_account_currency)) for c in children)
        first_child = children[0][0]
        account_currency = first_child.original_currency.value

        # Insert parent header row: (parent_tx, "–", net, reviewed, group_name)
        # We mark this as a "header" by using the parent transaction
        header_row = (parent, "–", float(net), parent.reviewed_at, parent.description)

        # Sort children by date
        children.sort(key=lambda c: c[0].date)

        # Insert header + children at position
        result.insert(insert_idx, header_row)
        for j, child in enumerate(children):
            result.insert(insert_idx + 1 + j, child)

    return result


def _group_merge_children_single_account(session, rows):
    """Post-process single-account rows to group same-account merge children under their parent.

    Inserts merge parent header rows and reorders children beneath them
    at the earliest child's position.  Cross-account merge children are
    left in place (they display with an [m+] suffix instead of tree chars).

    Each row is (Transaction, merge_net, merge_reviewed, merge_group_name, is_cross_account).
    Header rows use the same shape with sentinel values so the widget can detect them.
    """
    # Separate same-account merge children from everything else
    normal_rows = []
    merge_groups = {}  # merge_parent_id -> list of row tuples

    for row in rows:
        tx = row[0]
        is_cross_account = bool(row[4]) if row[4] else False
        if tx.merge_parent_id is not None and not is_cross_account:
            merge_groups.setdefault(tx.merge_parent_id, []).append(row)
        else:
            normal_rows.append(row)

    if not merge_groups:
        return rows

    # Load merge parents
    parent_ids = list(merge_groups.keys())
    parents = {
        p.id: p
        for p in session.execute(
            select(Transaction).where(Transaction.id.in_(parent_ids))
        ).scalars().all()
    }

    result = list(normal_rows)

    for parent_id, children in merge_groups.items():
        parent = parents.get(parent_id)
        if parent is None:
            result.extend(children)
            continue

        # Find earliest child date for positioning
        earliest_date = min(c[0].date for c in children)

        # Find insertion point: after the last row with date >= earliest_date
        insert_idx = len(result)
        for i, r in enumerate(result):
            if r[0].date < earliest_date:
                insert_idx = i
                break

        # Compute net
        net = sum(Decimal(str(c[0].value_in_account_currency)) for c in children)

        # Header row: use same tuple shape as single-account rows
        # (Transaction, merge_net, merge_reviewed, merge_group_name, is_cross_account)
        # We mark the account_name as "–" via a special flag that the widget detects
        # by checking if the tx is a merge parent (id in merge_parent_ids)
        header_row = (parent, float(net), parent.reviewed_at, parent.description, False)

        # Sort children by date
        children.sort(key=lambda c: c[0].date)

        result.insert(insert_idx, header_row)
        for j, child in enumerate(children):
            result.insert(insert_idx + 1 + j, child)

    return result


# --- Merge operations ---


def create_merge(session: Session, tx_ids: list[int], name: str) -> Transaction:
    """Create a merge group from the given transaction IDs.

    Creates a virtual parent Transaction and sets merge_parent_id on all children.
    Validates same account currency and no existing merge group membership.
    """
    txs = []
    for tx_id in tx_ids:
        tx = session.execute(
            select(Transaction)
            .where(Transaction.id == tx_id)
            .options(selectinload(Transaction.account))
        ).scalar_one_or_none()
        if tx is None:
            raise ValueError(f"Transaction {tx_id} not found")
        txs.append(tx)

    # Validate: none already in a merge group
    for tx in txs:
        if tx.merge_parent_id is not None:
            raise ValueError(f"Transaction '{tx.description}' is already in a merge group")

    # Validate: none are merge parents
    existing_parent_ids = set(
        session.execute(
            select(Transaction.merge_parent_id)
            .where(Transaction.merge_parent_id.in_(tx_ids))
        ).scalars().all()
    )
    for tx in txs:
        if tx.id in existing_parent_ids:
            raise ValueError(f"Transaction '{tx.description}' is a merge parent")

    # Validate: same account currency
    currencies = {tx.account.currency for tx in txs}
    if len(currencies) > 1:
        raise ValueError("Cannot merge transactions from accounts with different currencies")

    # Create virtual parent
    account_currency = txs[0].account.currency
    net = sum(Decimal(str(tx.value_in_account_currency)) for tx in txs)
    earliest_date = min(tx.date for tx in txs)

    parent = Transaction(
        account_id=txs[0].account_id,
        description=name,
        original_value=float(net),
        original_currency=account_currency,
        value_in_account_currency=float(net),
        date=earliest_date,
    )
    session.add(parent)
    session.flush()  # Get parent.id

    for tx in txs:
        tx.merge_parent_id = parent.id

    session.commit()
    return parent


def add_to_merge(session: Session, merge_parent_id: int, tx_id: int) -> None:
    """Add a transaction to an existing merge group."""
    parent = session.get(Transaction, merge_parent_id)
    if parent is None:
        raise ValueError("Merge parent not found")

    tx = session.execute(
        select(Transaction)
        .where(Transaction.id == tx_id)
        .options(selectinload(Transaction.account))
    ).scalar_one_or_none()
    if tx is None:
        raise ValueError("Transaction not found")

    if tx.merge_parent_id is not None:
        raise ValueError("Transaction is already in a merge group")

    # Validate currency match
    parent_account = session.get(Account, parent.account_id)
    if tx.account.currency != parent_account.currency:
        raise ValueError("Cannot merge transactions from accounts with different currencies")

    tx.merge_parent_id = merge_parent_id
    _update_merge_parent(session, parent)
    session.commit()


def remove_from_merge(session: Session, tx_id: int) -> str | None:
    """Remove a transaction from its merge group.

    Returns the dissolved group's name if the group was auto-dissolved, else None.
    """
    tx = session.get(Transaction, tx_id)
    if tx is None or tx.merge_parent_id is None:
        return None

    parent_id = tx.merge_parent_id
    parent = session.get(Transaction, parent_id)
    tx.merge_parent_id = None

    # Count remaining children
    remaining = session.execute(
        select(func.count(Transaction.id))
        .where(Transaction.merge_parent_id == parent_id)
        .where(Transaction.id != tx_id)
    ).scalar() or 0

    if remaining <= 1:
        # Dissolve: clear remaining child's FK and delete parent
        dissolved_name = parent.description if parent else None
        session.execute(
            Transaction.__table__.update()
            .where(Transaction.__table__.c.merge_parent_id == parent_id)
            .values(merge_parent_id=None)
        )
        if parent:
            session.delete(parent)
        session.commit()
        return dissolved_name

    # Update parent totals
    if parent:
        _update_merge_parent(session, parent)
    session.commit()
    return None


def rename_merge(session: Session, merge_parent_id: int, new_name: str) -> None:
    """Rename a merge group."""
    parent = session.get(Transaction, merge_parent_id)
    if parent is None:
        raise ValueError("Merge parent not found")
    parent.description = new_name
    session.commit()


def _update_merge_parent(session: Session, parent: Transaction) -> None:
    """Recompute a merge parent's amounts and date from its children."""
    children = session.execute(
        select(Transaction).where(Transaction.merge_parent_id == parent.id)
    ).scalars().all()

    if not children:
        return

    net = sum(Decimal(str(c.value_in_account_currency)) for c in children)
    parent.original_value = float(net)
    parent.value_in_account_currency = float(net)
    parent.date = min(c.date for c in children)


# --- Existing functions ---


def toggle_reviewed(session: Session, tx_id: int) -> Transaction | None:
    """Toggle reviewed_at on a transaction, commit, and return the updated Transaction."""
    tx = session.get(Transaction, tx_id)
    if tx is None:
        return None
    tx.reviewed_at = None if tx.reviewed_at else datetime.datetime.now()
    session.commit()
    return tx


def import_csv_transactions(session: Session, csv_path: str, account: Account) -> int:
    """Parse a CSV file using the account's mapping spec, insert transactions, and commit.

    Returns the number of imported transactions.
    Raises FileNotFoundError if csv_path doesn't exist.
    Raises ValueError if no transactions found.
    """
    csv_path = os.path.expanduser(csv_path)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"File not found: {csv_path}")

    spec_path = os.path.join("./importers", account.mapping_spec)
    importer = CSVImporter(spec_path)
    new_txs = []

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=importer.config.parser.delimiter)

        for _ in range(importer.config.parser.skip_rows):
            next(reader)

        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue

            data = importer.parse_row(row)

            ts = data["timestamp"]
            if isinstance(ts, str):
                try:
                    ts = datetime.datetime.fromisoformat(ts.replace(" ", "T"))
                except ValueError:
                    ts = datetime.datetime.strptime(ts, "%Y-%m-%d")

            tx = Transaction(
                account_id=account.id,
                description=str(data["description"]),
                original_value=float(data["amount_original"]),
                original_currency=Currency(data["currency_original"]),
                value_in_account_currency=float(data["amount_in_account_currency"]),
                date=ts,
            )
            new_txs.append(tx)

    if not new_txs:
        raise ValueError("No transactions found in file.")

    session.add_all(new_txs)
    session.commit()
    return len(new_txs)
