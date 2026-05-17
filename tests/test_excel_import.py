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

from datetime import datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table

import db
import excel_export
from models.finance import Account, Category, Currency, Transaction


HEADERS = [
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


def _make_workbook(rows, headers=None):
    """Build an openpyxl workbook with a TransactionsTable on the Transactions sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    h = headers or HEADERS
    ws.append(h)
    for row in rows:
        ws.append(row)
    if rows:
        table = Table(
            displayName="TransactionsTable",
            ref=f"A1:{get_column_letter(len(h))}{len(rows) + 1}",
        )
        ws.add_table(table)
    return wb


def _save_workbook(wb, tmp_path):
    path = tmp_path / "finview_transactions.xlsx"
    wb.save(str(path))
    return path


@pytest.fixture()
def session_factory(memory_db):
    return db.SessionLocal


@pytest.fixture()
def seeded_db(session, session_factory):
    """Account + two categories + three transactions with varied state."""
    acc = Account(name="Test", currency=Currency.CHF)
    session.add(acc)
    session.flush()

    cat_food = Category(name="food")
    session.add(cat_food)
    session.flush()
    cat_travel = Category(name="travel")
    session.add(cat_travel)
    session.commit()

    tx_no_cat_unreviewed = Transaction(
        account_id=acc.id,
        description="A",
        original_value=Decimal("10"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("10"),
        date=datetime(2025, 1, 1),
    )
    tx_with_cat_reviewed = Transaction(
        account_id=acc.id,
        description="B",
        original_value=Decimal("20"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("20"),
        date=datetime(2025, 1, 2),
        category_id=cat_food.id,
        reviewed_at=datetime(2025, 1, 3),
    )
    tx_no_cat_reviewed = Transaction(
        account_id=acc.id,
        description="C",
        original_value=Decimal("30"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("30"),
        date=datetime(2025, 1, 3),
        reviewed_at=datetime(2025, 1, 4),
    )
    session.add_all([tx_no_cat_unreviewed, tx_with_cat_reviewed, tx_no_cat_reviewed])
    session.commit()

    return {
        "account": acc,
        "food": cat_food,
        "travel": cat_travel,
        "tx_a": tx_no_cat_unreviewed,
        "tx_b": tx_with_cat_reviewed,
        "tx_c": tx_no_cat_reviewed,
    }


def _row(tx, category_text="", reviewed=False):
    return [
        tx.id,
        tx.account_id,
        "",
        tx.description,
        float(tx.original_value),
        tx.original_currency.value,
        float(tx.value_in_account_currency),
        tx.date,
        category_text,
        "",
        reviewed,
        tx.reviewed_at,
        tx.split_parent_id,
        tx.merge_parent_id,
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_file_not_found_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(excel_export, "EXPORT_PATH", tmp_path / "nonexistent.xlsx")
    with pytest.raises(FileNotFoundError):
        excel_export.import_from_excel(lambda: None)


def test_empty_export_returns_zeros(monkeypatch, tmp_path, session_factory, memory_db):
    """Workbook with no TransactionsTable returns (0, 0, 0) without error."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Transactions"
    ws.append(HEADERS)
    # No table added, no data rows
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    result = excel_export.import_from_excel(session_factory)
    assert result == (0, 0, 0)


def test_category_updated(monkeypatch, tmp_path, session, session_factory, seeded_db):
    tx_a = seeded_db["tx_a"]
    travel = seeded_db["travel"]

    wb = _make_workbook([_row(tx_a, category_text="travel", reviewed=False)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_a.id)
    assert tx.category_id == travel.id


def test_category_cleared(monkeypatch, tmp_path, session, session_factory, seeded_db):
    tx_b = seeded_db["tx_b"]

    wb = _make_workbook([_row(tx_b, category_text="", reviewed=True)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_b.id)
    assert tx.category_id is None


def test_mark_reviewed(monkeypatch, tmp_path, session, session_factory, seeded_db):
    tx_a = seeded_db["tx_a"]
    assert tx_a.reviewed_at is None

    wb = _make_workbook([_row(tx_a, reviewed=True)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_a.id)
    assert tx.reviewed_at is not None


def test_mark_unreviewed(monkeypatch, tmp_path, session, session_factory, seeded_db):
    tx_b = seeded_db["tx_b"]
    assert tx_b.reviewed_at is not None

    wb = _make_workbook([_row(tx_b, category_text="food", reviewed=False)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_b.id)
    assert tx.reviewed_at is None


def test_no_change_returns_zero_counts(
    monkeypatch, tmp_path, session_factory, seeded_db
):
    tx_a = seeded_db["tx_a"]

    # Export exactly as-is: no category, not reviewed
    wb = _make_workbook([_row(tx_a, category_text="", reviewed=False)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    cats, rev, unrev = excel_export.import_from_excel(session_factory)
    assert cats == 0
    assert rev == 0
    assert unrev == 0


def test_reviewed_timestamp_preserved(
    monkeypatch, tmp_path, session, session_factory, seeded_db
):
    """Already-reviewed tx stays reviewed → timestamp must not change."""
    tx_b = seeded_db["tx_b"]
    original_ts = tx_b.reviewed_at

    wb = _make_workbook([_row(tx_b, category_text="food", reviewed=True)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    cats, rev, unrev = excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_b.id)
    assert tx.reviewed_at == original_ts
    assert rev == 0  # no flip occurred


def test_unknown_category_clears(
    monkeypatch, tmp_path, session, session_factory, seeded_db
):
    tx_b = seeded_db["tx_b"]

    wb = _make_workbook([_row(tx_b, category_text="does/not/exist", reviewed=True)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    # Should not raise; unknown path resolves to None (clears category)
    excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_b.id)
    assert tx.category_id is None


def test_rowcount_summary(monkeypatch, tmp_path, session_factory, seeded_db):
    """One category change + one flip to reviewed + one flip to unreviewed."""
    tx_a = seeded_db["tx_a"]  # no cat, unreviewed → set food, mark reviewed
    tx_b = seeded_db["tx_b"]  # has food, reviewed → clear cat, mark unreviewed
    tx_c = seeded_db["tx_c"]  # no cat, reviewed → keep no cat, keep reviewed

    rows = [
        _row(tx_a, category_text="food", reviewed=True),
        _row(tx_b, category_text="", reviewed=False),
        _row(tx_c, category_text="", reviewed=True),
    ]
    wb = _make_workbook(rows)
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    cats, rev, unrev = excel_export.import_from_excel(session_factory)
    assert cats == 2  # tx_a gains food, tx_b loses food
    assert rev == 1   # tx_a flipped to reviewed
    assert unrev == 1  # tx_b flipped to unreviewed


def test_column_discovery_by_name(
    monkeypatch, tmp_path, session, session_factory, seeded_db
):
    """Columns in a different order are still resolved correctly by name."""
    tx_a = seeded_db["tx_a"]

    scrambled_headers = [
        "reviewed",
        "category",
        "id",
        "description",
        "original_value",
        "original_currency",
        "value_in_account_currency",
        "date",
        "account_id",
        "category_id",
        "reviewed_at",
        "account",
        "split_parent_id",
        "merge_parent_id",
    ]
    # reviewed=idx0, category=idx1, id=idx2
    row = [True, "travel", tx_a.id] + [""] * 11

    wb = _make_workbook([row], headers=scrambled_headers)
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    excel_export.import_from_excel(session_factory)

    session.expire_all()
    tx = session.get(Transaction, tx_a.id)
    assert tx.category_id == seeded_db["travel"].id
    assert tx.reviewed_at is not None


def test_db_marked_dirty(monkeypatch, tmp_path, session_factory, seeded_db):
    tx_a = seeded_db["tx_a"]
    db._dirty = False

    wb = _make_workbook([_row(tx_a, reviewed=True)])
    path = _save_workbook(wb, tmp_path)
    monkeypatch.setattr(excel_export, "EXPORT_PATH", path)

    excel_export.import_from_excel(session_factory)
    assert db.is_dirty()
