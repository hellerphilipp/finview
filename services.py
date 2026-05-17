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

import os
import tempfile
from datetime import datetime
from decimal import Decimal

import yaml
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

import db
import queries
from importers.schema import ImporterMapping
from models.finance import Account, Currency, Transaction


def create_account(
    session: Session,
    name: str,
    currency: Currency,
    mapping_spec: str | None,
    initial_amount: Decimal,
    initial_date: datetime,
) -> Account:
    """Create a new account with an initial balance transaction."""
    new_acc = Account(
        name=name,
        currency=currency,
        mapping_spec=mapping_spec,
    )
    session.add(new_acc)
    session.flush()

    initial_tx = Transaction(
        account_id=new_acc.id,
        description="Initial Balance",
        original_value=initial_amount,
        original_currency=currency,
        value_in_account_currency=initial_amount,
        date=initial_date,
    )
    session.add(initial_tx)
    session.commit()
    db.mark_dirty()
    return new_acc


def apply_split(
    session: Session, root: Transaction, splits: list[dict]
) -> None:
    """Apply split changes to a root transaction.

    Each split dict has keys: id (int|None), description (str), amount (str|float).
    Existing children not in splits are deleted. New children (id=None) are created.
    """
    existing_ids = {c.id for c in (root.split_children or [])}
    returned_ids = {s["id"] for s in splits if s["id"] is not None}

    # Delete removed children
    for child in list(root.split_children):
        if child.id not in returned_ids:
            session.delete(child)

    # Compute proportional ratio (original → account currency)
    if float(root.original_value) != 0:
        ratio = Decimal(str(root.value_in_account_currency)) / Decimal(
            str(root.original_value)
        )
    else:
        ratio = Decimal("1")

    # Update or create children
    for s in splits:
        amount = Decimal(str(s["amount"]))
        acc_amount = float(amount * ratio)

        if s["id"] is not None and s["id"] in existing_ids:
            child = session.get(Transaction, s["id"])
            if child:
                child.description = s["description"]
                child.original_value = float(amount)
                child.value_in_account_currency = acc_amount
        else:
            child = Transaction(
                account_id=root.account_id,
                description=s["description"],
                original_value=float(amount),
                original_currency=root.original_currency,
                value_in_account_currency=acc_amount,
                date=root.date,
                split_parent_id=root.id,
            )
            session.add(child)

    session.commit()
    db.mark_dirty()


def discover_mapping_specs(
    base_path: str | None = None,
) -> list[tuple[str, str | None]]:
    if base_path is None:
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "importers")
    """Scan importers directory for valid YAML mapping specs.

    Returns list of (display_name, relative_path_or_None) tuples.
    First entry is always ("No Mapping / Manual", None).
    """
    options: list[tuple[str, str | None]] = [("No Mapping / Manual", None)]

    if not os.path.exists(base_path):
        return options

    for root, _, files in os.walk(base_path):
        for f in files:
            if f.endswith((".yaml", ".yml")):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, base_path)

                try:
                    with open(full_path, "r") as stream:
                        config_data = yaml.safe_load(stream)
                        mapping = ImporterMapping(**config_data)
                        display_name = f"{mapping.name} ({rel_path})"
                        options.append((display_name, rel_path))
                except (yaml.YAMLError, ValidationError, TypeError):
                    continue

    return options


def import_csv_from_bytes(
    session: Session, file_bytes: bytes, filename: str, account: Account
) -> int:
    """Import CSV transactions from raw bytes (for Streamlit file uploads).

    Writes bytes to a temp file, runs the importer, and cleans up.
    Returns the number of imported transactions.
    """
    suffix = os.path.splitext(filename)[1] or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        count = queries.import_csv_transactions(session, tmp_path, account)
        db.mark_dirty()
        return count
    finally:
        os.unlink(tmp_path)


def get_latest_transaction_date(
    session: Session, account_id: int
) -> datetime | None:
    """Return the date of the most recent transaction for an account, or None."""
    result = session.execute(
        select(func.max(Transaction.date)).where(
            Transaction.account_id == account_id
        )
    ).scalar()
    return result
