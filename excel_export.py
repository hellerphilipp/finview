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

import subprocess
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from sqlalchemy import select

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

    # Auto-filter on header row
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last_row}"
