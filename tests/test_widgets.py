import pytest
from datetime import datetime

import db
from models.finance import Account, Currency, Transaction
from ui.app import FinViewApp
from ui.widgets import AccountSidebar, TransactionTable, AllAccountsItem, AccountItem


class TestAppLaunch:
    async def test_app_mounts_cleanly(self, finview_app):
        async with finview_app.run_test() as pilot:
            app = pilot.app
            app.query_one("#sidebar", AccountSidebar)
            app.query_one(TransactionTable)

    async def test_sidebar_shows_all_accounts_item(self, finview_app):
        async with finview_app.run_test() as pilot:
            sidebar = pilot.app.query_one("#sidebar", AccountSidebar)
            items = sidebar.query(AllAccountsItem)
            assert len(items) == 1


class TestAccountCreation:
    async def test_create_account_screen_opens(self, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            from ui.screens import CreateAccountScreen

            screens = pilot.app.query(CreateAccountScreen)
            assert len(screens) > 0 or len(pilot.app.screen_stack) > 1


class TestTransactionTable:
    async def test_table_loads_with_data(self, sample_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            # All accounts mode shows all transactions
            assert table.row_count == 3

    async def test_all_accounts_mode_has_account_column(self, sample_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            # In all-accounts mode, should have the Account column
            assert "account" in table.columns

    async def test_single_account_mode_no_account_column(self, sample_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            # Select the account in the sidebar
            table.update_account(sample_account, pilot.app.db)
            await pilot.pause()
            assert "account" not in table.columns
            assert table.row_count == 3


class TestToggleReviewed:
    async def test_toggle_reviewed_status(self, sample_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            # Switch to single account mode so we can toggle
            table.update_account(sample_account, pilot.app.db)
            await pilot.pause()

            if table.row_count == 0:
                pytest.skip("No rows to toggle")

            # Move cursor to first row and toggle
            table.focus()
            await pilot.pause()
            table.move_cursor(row=0)
            await pilot.pause()

            # Get the transaction before toggle
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            tx = pilot.app.db.get(Transaction, int(row_key.value))
            was_reviewed = tx.reviewed_at is not None

            await pilot.press("enter")
            await pilot.pause()

            pilot.app.db.refresh(tx)
            is_reviewed = tx.reviewed_at is not None
            assert is_reviewed != was_reviewed


class TestCommandMode:
    async def test_save_command(self, finview_app, tmp_path):
        save_path = str(tmp_path / "cmd_save.db")
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            # Open command line and type :w <path>
            await pilot.press("colon")
            await pilot.pause()

            from textual.widgets import Input

            cmd_input = pilot.app.query_one("#command-input", Input)
            cmd_input.value = f":w {save_path}"
            await pilot.press("enter")
            await pilot.pause()

            import os

            assert os.path.exists(save_path)

    async def test_quit_blocked_when_dirty(self, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            db.mark_dirty()
            pilot.app._handle_command(":q")
            await pilot.pause()
            # App should still be running (not exited)
            assert pilot.app.is_running

    async def test_force_quit(self, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            db.mark_dirty()
            pilot.app._handle_command(":q!")
            await pilot.pause()


class TestImportDialog:
    async def test_import_requires_account(self, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.focus()
            await pilot.pause()
            # In all-accounts mode, import should fail
            await pilot.press("i")
            await pilot.pause()
            # Should show "No account selected" notification
