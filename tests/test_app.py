import csv
import os
import pytest
from datetime import datetime

import db
from models.finance import Account, Currency, Transaction
from ui.app import FinViewApp
from ui.widgets import AccountSidebar, AccountItem, TransactionTable


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
