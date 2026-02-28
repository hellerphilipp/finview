import csv
import os
import pytest
from datetime import datetime
from decimal import Decimal

import db
from models.finance import Account, Currency, Transaction
from ui.app import FinViewApp
from ui.widgets import AccountSidebar, AccountItem, TransactionTable
from textual.widgets import Input


class TestRefreshCycle:
    async def test_refresh_updates_sidebar(self, sample_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            sidebar = pilot.app.query_one("#sidebar", AccountSidebar)
            account_items = sidebar.query(AccountItem)
            assert len(account_items) == 1
            assert account_items[0].account.name == "Test Checking"

    async def test_add_account_then_refresh(self, session, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()

            # Add an account directly via DB
            acc = Account(name="Savings", currency=Currency.EUR)
            pilot.app.db.add(acc)
            pilot.app.db.commit()

            pilot.app.action_refresh()
            await pilot.pause()

            sidebar = pilot.app.query_one("#sidebar", AccountSidebar)
            account_items = sidebar.query(AccountItem)
            assert len(account_items) == 1
            assert account_items[0].account.name == "Savings"


class TestCSVImportEndToEnd:
    async def test_import_csv(self, session, finview_app, tmp_path):
        # Create account with Swisscard mapping spec
        acc = Account(
            name="Credit Card",
            currency=Currency.CHF,
            mapping_spec="Swisscard/swisscard.yaml",
        )
        session.add(acc)
        session.commit()

        # Write a test CSV
        csv_path = str(tmp_path / "transactions.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Merchant", "Detail", "", "Currency", "Amount", "OrigCurrency", "OrigAmount"])
            writer.writerow(["10.01.2025", "Migros", "Migros Zurich", "", "CHF", "55.30", "CHF", "55.30"])
            writer.writerow(["12.01.2025", "SBB", "", "", "CHF", "22.00", "", ""])

        async with finview_app.run_test() as pilot:
            await pilot.pause()

            # Refresh the account into the session
            acc = pilot.app.db.merge(acc)
            pilot.app.process_csv_import(csv_path, acc)
            await pilot.pause()

            # Verify transactions were imported
            txs = (
                pilot.app.db.query(Transaction)
                .filter_by(account_id=acc.id)
                .all()
            )
            assert len(txs) == 2
            assert any("Migros" in t.description for t in txs)
            assert any("SBB" in t.description for t in txs)


class TestQuitBehavior:
    async def test_quit_when_clean(self, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            db.clear_dirty()
            pilot.app.action_quit()
            await pilot.pause()

    async def test_quit_blocked_when_dirty(self, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            db.mark_dirty()
            pilot.app.action_quit()
            await pilot.pause()
            # App should still be running
            assert pilot.app.is_running


class TestSearch:
    @pytest.fixture()
    def search_account(self, session):
        """Account with distinct transactions for search testing."""
        acc = Account(name="Search Test", currency=Currency.CHF)
        session.add(acc)
        session.flush()
        txs = [
            Transaction(
                account_id=acc.id,
                description="Grocery Store",
                original_value=Decimal("-50.00"),
                original_currency=Currency.CHF,
                value_in_account_currency=Decimal("-50.00"),
                date=datetime(2025, 1, 1),
            ),
            Transaction(
                account_id=acc.id,
                description="Salary Payment",
                original_value=Decimal("3000.00"),
                original_currency=Currency.CHF,
                value_in_account_currency=Decimal("3000.00"),
                date=datetime(2025, 1, 2),
            ),
            Transaction(
                account_id=acc.id,
                description="Grocery Delivery",
                original_value=Decimal("-30.00"),
                original_currency=Currency.CHF,
                value_in_account_currency=Decimal("-30.00"),
                date=datetime(2025, 1, 3),
            ),
            Transaction(
                account_id=acc.id,
                description="Rent",
                original_value=Decimal("-1500.00"),
                original_currency=Currency.CHF,
                value_in_account_currency=Decimal("-1500.00"),
                date=datetime(2025, 1, 4),
            ),
        ]
        session.add_all(txs)
        session.commit()
        return acc

    async def test_slash_opens_search_input(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            search_input = pilot.app.query_one("#search-input", Input)
            assert not search_input.has_class("visible")

            await pilot.press("slash")
            await pilot.pause()
            assert search_input.has_class("visible")

    async def test_escape_closes_search_input(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            search_input = pilot.app.query_one("#search-input", Input)
            assert search_input.has_class("visible")

            await pilot.press("escape")
            await pilot.pause()
            assert not search_input.has_class("visible")

    async def test_search_moves_cursor_to_first_match(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            # Directly invoke search
            table.search("Grocery")
            await pilot.pause()
            assert len(table._search_matches) == 2
            assert table._search_index == 0
            assert table.cursor_coordinate.row == table._search_matches[0]

    async def test_n_moves_to_next_match(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.search("Grocery")
            await pilot.pause()
            first_match = table._search_matches[0]
            second_match = table._search_matches[1]

            table.focus()
            await pilot.press("n")
            await pilot.pause()
            assert table._search_index == 1
            assert table.cursor_coordinate.row == second_match

    async def test_N_moves_to_previous_match(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.search("Grocery")
            await pilot.pause()

            # Move to second match
            table.focus()
            await pilot.press("n")
            await pilot.pause()
            assert table._search_index == 1

            # Move back
            await pilot.press("N")
            await pilot.pause()
            assert table._search_index == 0
            assert table.cursor_coordinate.row == table._search_matches[0]

    async def test_n_wraps_to_top(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.search("Grocery")
            await pilot.pause()

            table.focus()
            # Advance past last match
            await pilot.press("n")  # index 1
            await pilot.press("n")  # wraps to 0
            await pilot.pause()
            assert table._search_index == 0

    async def test_N_wraps_to_bottom(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.search("Grocery")
            await pilot.pause()

            table.focus()
            # Go backwards from first match
            await pilot.press("N")  # wraps to last
            await pilot.pause()
            assert table._search_index == len(table._search_matches) - 1

    async def test_no_matches_notification(self, search_account, finview_app):
        async with finview_app.run_test(notifications=True) as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.search("nonexistent_xyz")
            await pilot.pause()
            assert len(table._search_matches) == 0
            assert table._search_term == "nonexistent_xyz"

    async def test_search_clears_on_reload(self, search_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.search("Grocery")
            await pilot.pause()
            assert table._search_term == "Grocery"

            # Reload clears search
            table._load_transactions()
            await pilot.pause()
            assert table._search_term == ""
            assert table._search_matches == []
