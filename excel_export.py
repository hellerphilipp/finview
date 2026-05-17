# FinView — personal finance manager
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

import datetime
import subprocess
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from sqlalchemy import select, text

import db
import queries
from models.finance import Account, Transaction


EXPORT_PATH = Path(tempfile.gettempdir()) / "finview_transactions.xlsx"


def export_to_excel(session_factory):
    """Export all data to an Excel workbook and open it."""
    wb = Workbook()

    with session_factory() as session:
        category_paths = queries.get_all_category_paths(session)
        accounts = session.execute(select(Account).order_by(Account.id)).scalars().all()
        transactions = (
            session.execute(select(Transaction).order_by(Transaction.date.desc()))
            .scalars()
            .all()
        )
        category_path_map = queries._build_category_path_map(session)

        _build_categories_sheet(wb, category_paths)
        _build_accounts_sheet(wb, accounts)
        _build_transactions_sheet(wb, transactions, category_path_map, len(category_paths), len(accounts))

    wb.active = wb["Transactions"]
    wb.save(str(EXPORT_PATH))
    subprocess.Popen(["open", str(EXPORT_PATH)])
    return EXPORT_PATH


def _build_categories_sheet(wb, category_paths):
    ws = wb.create_sheet("Categories")
    ws.append(["id", "path"])
    for cat_id, path in category_paths:
        ws.append([cat_id, path])

    # Table for structured references
    if category_paths:
        table = Table(
            displayName="CategoriesTable",
            ref=f"A1:B{len(category_paths) + 1}",
        )
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1")
        ws.add_table(table)

    # Lock all cells and protect
    for row in ws.iter_rows():
        for cell in row:
            cell.protection = cell.protection.copy(locked=True)
    ws.protection.sheet = True

    ws.sheet_state = "hidden"


def _build_accounts_sheet(wb, accounts):
    ws = wb.create_sheet("Accounts")
    ws.append(["id", "name", "currency", "mapping_spec"])
    for acc in accounts:
        ws.append([acc.id, acc.name, acc.currency.value, acc.mapping_spec or ""])

    if accounts:
        table = Table(
            displayName="AccountsTable",
            ref=f"A1:D{len(accounts) + 1}",
        )
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1")
        ws.add_table(table)

    for row in ws.iter_rows():
        for cell in row:
            cell.protection = cell.protection.copy(locked=True)
    ws.protection.sheet = True

    ws.sheet_state = "hidden"


def _build_transactions_sheet(wb, transactions, category_path_map, num_categories, num_accounts):
    # Remove the default sheet created by Workbook()
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    ws = wb.create_sheet("Transactions")

    headers = [
        "id",
        "account_id",
        "account",
        "description",
        "original_value",
        "original_currency",
        "value_in_account_currency",
        "date",
        "category",
        "category_id",
        "reviewed",
        "reviewed_at",
        "split_parent_id",
        "merge_parent_id",
    ]
    ws.append(headers)

    # Column indices (1-based)
    COL_ID = 1
    COL_ACCOUNT_ID = 2
    COL_ACCOUNT = 3
    COL_CATEGORY = 9
    COL_CATEGORY_ID = 10
    COL_REVIEWED = 11
    COL_REVIEWED_AT = 12
    COL_SPLIT_PARENT = 13
    COL_MERGE_PARENT = 14

    for row_idx, tx in enumerate(transactions, start=2):
        account_id_cell = f"{get_column_letter(COL_ACCOUNT_ID)}{row_idx}"
        category_cell = f"{get_column_letter(COL_CATEGORY)}{row_idx}"

        # XLOOKUP for account name
        account_formula = (
            f'=_xlfn.XLOOKUP({account_id_cell},Accounts!A:A,Accounts!B:B,"")'
        )
        # XLOOKUP for category_id from path
        category_id_formula = (
            f'=_xlfn.XLOOKUP({category_cell},Categories!B:B,Categories!A:A,"")'
        )

        category_text = category_path_map.get(tx.category_id, "") if tx.category_id else ""
        reviewed_value = True if tx.reviewed_at else False

        ws.append([
            tx.id,
            tx.account_id,
            account_formula,
            tx.description,
            float(tx.original_value),
            tx.original_currency.value,
            float(tx.value_in_account_currency),
            tx.date,
            category_text,
            category_id_formula,
            reviewed_value,
            tx.reviewed_at,
            tx.split_parent_id,
            tx.merge_parent_id,
        ])

    last_row = len(transactions) + 1

    # Data validation: category dropdown from Categories sheet
    if num_categories > 0:
        cat_dv = DataValidation(
            type="list",
            formula1=f"Categories!$B$2:$B${num_categories + 1}",
            allow_blank=True,
        )
        cat_dv.error = "Please select a valid category"
        cat_dv.errorTitle = "Invalid Category"
        ws.add_data_validation(cat_dv)
        if last_row >= 2:
            cat_dv.add(f"{get_column_letter(COL_CATEGORY)}2:{get_column_letter(COL_CATEGORY)}{last_row}")

    # Data validation: reviewed TRUE/FALSE
    rev_dv = DataValidation(
        type="list",
        formula1='"TRUE,FALSE"',
        allow_blank=False,
    )
    ws.add_data_validation(rev_dv)
    if last_row >= 2:
        rev_dv.add(f"{get_column_letter(COL_REVIEWED)}2:{get_column_letter(COL_REVIEWED)}{last_row}")

    # Protection: lock all cells, then unlock category and reviewed
    from openpyxl.styles import Protection

    locked = Protection(locked=True)
    unlocked = Protection(locked=False)

    for row in ws.iter_rows(min_row=1, max_row=last_row):
        for cell in row:
            cell.protection = locked

    for row_idx in range(2, last_row + 1):
        ws.cell(row=row_idx, column=COL_CATEGORY).protection = unlocked
        ws.cell(row=row_idx, column=COL_REVIEWED).protection = unlocked

    ws.protection.sheet = True

    # Hide columns: account_id, category_id, reviewed_at, split_parent_id, merge_parent_id
    for col in [COL_ACCOUNT_ID, COL_CATEGORY_ID, COL_REVIEWED_AT, COL_SPLIT_PARENT, COL_MERGE_PARENT]:
        ws.column_dimensions[get_column_letter(col)].hidden = True

    # Table (includes auto-filter)
    if last_row >= 2:
        table = Table(
            displayName="TransactionsTable",
            ref=f"A1:{get_column_letter(len(headers))}{last_row}",
        )
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1")
        ws.add_table(table)


def _parse_reviewed(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().upper() == "TRUE"
    return bool(raw)


def _resolve_category_id(cat_text, reverse_map: dict) -> int | None:
    if not cat_text or not str(cat_text).strip():
        return None
    return reverse_map.get(str(cat_text).strip())


def import_from_excel(session_factory) -> tuple[int, int, int]:
    """Read back a user-edited Excel export and commit changes to the database.

    Returns (categories_updated, marked_reviewed, marked_unreviewed).
    """
    if not EXPORT_PATH.exists():
        raise FileNotFoundError(f"Export file not found: {EXPORT_PATH}")

    wb = load_workbook(str(EXPORT_PATH), data_only=True)
    ws = wb["Transactions"]

    if "TransactionsTable" not in ws.tables:
        return 0, 0, 0

    table = ws.tables["TransactionsTable"]
    min_col, min_row, max_col, max_row = range_boundaries(table.ref)

    header_row = next(
        ws.iter_rows(
            min_row=min_row,
            max_row=min_row,
            min_col=min_col,
            max_col=max_col,
            values_only=True,
        )
    )
    col_index = {name: i for i, name in enumerate(header_row)}

    required = {"id", "category", "reviewed"}
    missing = required - col_index.keys()
    if missing:
        raise ValueError(f"TransactionsTable is missing required columns: {missing}")

    idx_id = col_index["id"]
    idx_category = col_index["category"]
    idx_reviewed = col_index["reviewed"]

    rows_data = []
    for row in ws.iter_rows(
        min_row=min_row + 1,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        values_only=True,
    ):
        tx_id = row[idx_id]
        if tx_id is None:
            continue
        rows_data.append((int(tx_id), row[idx_category], row[idx_reviewed]))

    with session_factory() as session:
        pairs = queries.get_all_category_paths(session)
    reverse_map = {path: cat_id for cat_id, path in pairs}

    now = datetime.datetime.now()
    cat_updates = []
    mark_reviewed = []
    mark_unreviewed = []

    for tx_id, cat_text, raw_reviewed in rows_data:
        cat_updates.append(
            {"id": tx_id, "new_cat": _resolve_category_id(cat_text, reverse_map)}
        )
        if _parse_reviewed(raw_reviewed):
            mark_reviewed.append({"id": tx_id, "now": now})
        else:
            mark_unreviewed.append({"id": tx_id})

    with session_factory() as session:
        cat_result = session.execute(
            text(
                "UPDATE transactions SET category_id = :new_cat "
                "WHERE id = :id AND category_id IS NOT :new_cat"
            ),
            cat_updates,
        )
        categories_updated = cat_result.rowcount

        if mark_reviewed:
            rev_result = session.execute(
                text(
                    "UPDATE transactions SET reviewed_at = :now "
                    "WHERE id = :id AND reviewed_at IS NULL"
                ),
                mark_reviewed,
            )
            marked_reviewed = rev_result.rowcount
        else:
            marked_reviewed = 0

        if mark_unreviewed:
            unrev_result = session.execute(
                text(
                    "UPDATE transactions SET reviewed_at = NULL "
                    "WHERE id = :id AND reviewed_at IS NOT NULL"
                ),
                mark_unreviewed,
            )
            marked_unreviewed = unrev_result.rowcount
        else:
            marked_unreviewed = 0

        session.commit()
        db.mark_dirty()

    return categories_updated, marked_reviewed, marked_unreviewed
