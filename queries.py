import csv
import datetime
import os
from decimal import Decimal

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from importers.engine import CSVImporter
from models.finance import Account, Currency, Transaction


def get_all_accounts_with_balances(session: Session) -> list[tuple[Account, Decimal]]:
    """Return all accounts with their computed balance via SQL SUM()."""
    stmt = (
        select(Account, func.coalesce(func.sum(Transaction.value_in_account_currency), 0))
        .outerjoin(Transaction, Account.id == Transaction.account_id)
        .group_by(Account.id)
        .order_by(Account.id)
    )
    return [(acc, Decimal(str(bal))) for acc, bal in session.execute(stmt).all()]


def _parent_ids_subquery():
    """Subquery returning transaction ids that have children (are split parents)."""
    return (
        select(Transaction.parent_id)
        .where(Transaction.parent_id.is_not(None))
        .distinct()
        .scalar_subquery()
    )


def load_transaction_page(
    session: Session,
    account_id: int | None = None,
    all_accounts: bool = False,
) -> tuple[int, int, list]:
    """Load transactions and counts.

    Returns (total_count, total_unreviewed, rows) where rows is a list of
    Transaction (single account) or (Transaction, account_name) tuples (all accounts).
    """
    no_children = ~Transaction.id.in_(_parent_ids_subquery())

    where = None if all_accounts else (Transaction.account_id == account_id)

    # Count totals
    count_stmt = select(
        func.count(Transaction.id),
        func.sum(case((Transaction.reviewed_at.is_(None), 1), else_=0)),
    ).where(no_children)
    if all_accounts:
        count_stmt = count_stmt.join(Account, Transaction.account_id == Account.id)
    if where is not None:
        count_stmt = count_stmt.where(where)
    total_count, total_unreviewed = session.execute(count_stmt).one()
    total_count = total_count or 0
    total_unreviewed = int(total_unreviewed or 0)

    # Fetch rows
    if all_accounts:
        stmt = (
            select(Transaction, Account.name)
            .join(Account, Transaction.account_id == Account.id)
            .where(no_children)
        )
    else:
        stmt = select(Transaction).where(no_children)
        if where is not None:
            stmt = stmt.where(where)

    stmt = stmt.order_by(Transaction.date.desc())

    if all_accounts:
        rows = session.execute(stmt).all()
    else:
        rows = session.execute(stmt).scalars().all()

    return total_count, total_unreviewed, rows


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
