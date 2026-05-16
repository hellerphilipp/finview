import os
import tempfile
from datetime import datetime
from decimal import Decimal

import pytest

import db
import services
from models.finance import Account, Currency, Transaction


class TestCreateAccount:
    def test_creates_account_and_initial_transaction(self, session, memory_db):
        acc = services.create_account(
            session,
            name="Savings",
            currency=Currency.CHF,
            mapping_spec=None,
            initial_amount=Decimal("500.00"),
            initial_date=datetime(2025, 6, 1),
        )

        assert acc.id is not None
        assert acc.name == "Savings"
        assert acc.currency == Currency.CHF

        txs = session.query(Transaction).filter_by(account_id=acc.id).all()
        assert len(txs) == 1
        assert txs[0].description == "Initial Balance"
        assert txs[0].original_value == Decimal("500.00")
        assert txs[0].date == datetime(2025, 6, 1)

    def test_marks_dirty(self, session, memory_db):
        db.clear_dirty()
        services.create_account(
            session,
            name="Dirty Test",
            currency=Currency.USD,
            mapping_spec=None,
            initial_amount=Decimal("0"),
            initial_date=datetime(2025, 1, 1),
        )
        assert db.is_dirty()

    def test_with_mapping_spec(self, session, memory_db):
        acc = services.create_account(
            session,
            name="Credit Card",
            currency=Currency.CHF,
            mapping_spec="Swisscard/swisscard.yaml",
            initial_amount=Decimal("0"),
            initial_date=datetime(2025, 1, 1),
        )
        assert acc.mapping_spec == "Swisscard/swisscard.yaml"


class TestApplySplit:
    @pytest.fixture()
    def root_tx(self, session, sample_account):
        """Return a transaction suitable for splitting."""
        tx = (
            session.query(Transaction)
            .filter_by(account_id=sample_account.id, description="Salary")
            .one()
        )
        return tx

    def _reload_with_children(self, session, tx_id):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        return session.execute(
            select(Transaction)
            .where(Transaction.id == tx_id)
            .options(selectinload(Transaction.split_children))
        ).scalar_one()

    def test_creates_children(self, session, root_tx):
        services.apply_split(
            session,
            root_tx,
            [
                {"id": None, "description": "Part A", "amount": "2000.00"},
                {"id": None, "description": "Part B", "amount": "1000.00"},
            ],
        )
        root = self._reload_with_children(session, root_tx.id)
        assert len(root.split_children) == 2
        descs = sorted(c.description for c in root.split_children)
        assert descs == ["Part A", "Part B"]

    def test_deletes_removed_children(self, session, root_tx):
        # First create children
        services.apply_split(
            session,
            root_tx,
            [
                {"id": None, "description": "Part A", "amount": "2000.00"},
                {"id": None, "description": "Part B", "amount": "1000.00"},
            ],
        )
        root = self._reload_with_children(session, root_tx.id)
        child_a = next(c for c in root.split_children if c.description == "Part A")

        # Now keep only Part A
        services.apply_split(
            session,
            root,
            [{"id": child_a.id, "description": "Part A", "amount": "2000.00"}],
        )
        root = self._reload_with_children(session, root_tx.id)
        assert len(root.split_children) == 1
        assert root.split_children[0].description == "Part A"

    def test_updates_existing_children(self, session, root_tx):
        services.apply_split(
            session,
            root_tx,
            [{"id": None, "description": "Original", "amount": "3000.00"}],
        )
        root = self._reload_with_children(session, root_tx.id)
        child = root.split_children[0]

        services.apply_split(
            session,
            root,
            [{"id": child.id, "description": "Renamed", "amount": "2500.00"}],
        )
        root = self._reload_with_children(session, root_tx.id)
        assert root.split_children[0].description == "Renamed"
        assert root.split_children[0].original_value == Decimal("2500.00")

    def test_empty_splits_removes_all_children(self, session, root_tx):
        services.apply_split(
            session,
            root_tx,
            [{"id": None, "description": "Temp", "amount": "3000.00"}],
        )
        root = self._reload_with_children(session, root_tx.id)
        assert len(root.split_children) == 1

        services.apply_split(session, root, [])
        root = self._reload_with_children(session, root_tx.id)
        assert len(root.split_children) == 0

    def test_currency_ratio(self, session, sample_account):
        """When original and account currency amounts differ, children use the ratio."""
        tx = Transaction(
            account_id=sample_account.id,
            description="Foreign Purchase",
            original_value=Decimal("100.00"),
            original_currency=Currency.EUR,
            value_in_account_currency=Decimal("110.00"),
            date=datetime(2025, 3, 1),
        )
        session.add(tx)
        session.commit()

        services.apply_split(
            session,
            tx,
            [
                {"id": None, "description": "Half A", "amount": "50.00"},
                {"id": None, "description": "Half B", "amount": "50.00"},
            ],
        )
        tx = self._reload_with_children(session, tx.id)
        for child in tx.split_children:
            assert float(child.original_value) == 50.0
            assert float(child.value_in_account_currency) == 55.0

    def test_marks_dirty(self, session, root_tx):
        db.clear_dirty()
        services.apply_split(
            session,
            root_tx,
            [{"id": None, "description": "X", "amount": "3000.00"}],
        )
        assert db.is_dirty()


class TestDiscoverMappingSpecs:
    def test_always_has_no_mapping_first(self):
        options = services.discover_mapping_specs("/nonexistent")
        assert len(options) == 1
        assert options[0] == ("No Mapping / Manual", None)

    def test_finds_valid_yaml(self, tmp_path):
        spec_dir = tmp_path / "BankX"
        spec_dir.mkdir()
        spec_file = spec_dir / "spec.yaml"
        spec_file.write_text(
            """
version: "1"
name: Bank X
parser:
  delimiter: ","
  skip_rows: 1
mappings:
  timestamp: "row[0]"
  description: "row[1]"
  amount_original: "row[2]"
  currency_original: "'CHF'"
  amount_in_account_currency: "row[2]"
"""
        )
        options = services.discover_mapping_specs(str(tmp_path))
        assert len(options) == 2
        assert options[0][0] == "No Mapping / Manual"
        assert "Bank X" in options[1][0]
        assert options[1][1] is not None

    def test_skips_invalid_yaml(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("not: valid: yaml: [")
        options = services.discover_mapping_specs(str(tmp_path))
        assert len(options) == 1

    def test_finds_real_importers(self):
        """Verify it finds the Swisscard spec in the actual repo."""
        options = services.discover_mapping_specs("./importers")
        names = [o[0] for o in options]
        assert any("Swisscard" in n for n in names)


class TestImportCsvFromBytes:
    def test_imports_transactions(self, session, sample_account):
        import csv
        import io

        sample_account.mapping_spec = "Swisscard/swisscard.yaml"
        session.commit()

        buf = io.BytesIO()
        wrapper = io.TextIOWrapper(buf, encoding="utf-8", newline="")
        writer = csv.writer(wrapper)
        writer.writerow(
            ["Date", "Merchant", "Detail", "", "Currency", "Amount", "OrigCurrency", "OrigAmount"]
        )
        writer.writerow(
            ["10.01.2025", "Migros", "Migros Zurich", "", "CHF", "55.30", "CHF", "55.30"]
        )
        writer.writerow(["12.01.2025", "SBB", "", "", "CHF", "22.00", "", ""])
        wrapper.flush()
        csv_bytes = buf.getvalue()

        db.clear_dirty()
        count = services.import_csv_from_bytes(
            session, csv_bytes, "transactions.csv", sample_account
        )
        assert count == 2
        assert db.is_dirty()


class TestGetLatestTransactionDate:
    def test_returns_latest_date(self, session, sample_account):
        result = services.get_latest_transaction_date(session, sample_account.id)
        assert result == datetime(2025, 1, 15)

    def test_returns_none_for_empty_account(self, session, memory_db):
        acc = Account(name="Empty", currency=Currency.CHF)
        session.add(acc)
        session.commit()
        result = services.get_latest_transaction_date(session, acc.id)
        assert result is None
