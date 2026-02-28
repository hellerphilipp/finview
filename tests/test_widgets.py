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


class TestSplitTransaction:
    async def test_split_screen_opens(self, sample_account, finview_app):
        async with finview_app.run_test() as pilot:
            await pilot.pause()
            table = pilot.app.query_one(TransactionTable)
            table.update_account(sample_account, pilot.app.db)
            await pilot.pause()
            table.focus()
            await pilot.pause()
            table.move_cursor(row=0)
            await pilot.pause()

            await pilot.press("s")
            await pilot.pause()

            from ui.screens import SplitTransactionScreen

            assert len(pilot.app.screen_stack) > 1
            assert isinstance(pilot.app.screen_stack[-1], SplitTransactionScreen)


class TestVimNavigation:
    """Tests for vim-style j/k/g/G navigation with count prefixes."""

    async def _setup_table(self, pilot, account):
        """Focus table in single-account mode and return it."""
        await pilot.pause()
        table = pilot.app.query_one(TransactionTable)
        table.update_account(account, pilot.app.db)
        await pilot.pause()
        table.focus()
        await pilot.pause()
        table.move_cursor(row=0)
        await pilot.pause()
        return table

    async def test_j_moves_down(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            assert table.cursor_coordinate.row == 0
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_coordinate.row == 1

    async def test_k_moves_up(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            table.move_cursor(row=5)
            await pilot.pause()
            await pilot.press("k")
            await pilot.pause()
            assert table.cursor_coordinate.row == 4

    async def test_count_j_moves_down_n(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            await pilot.press("5")
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_coordinate.row == 5

    async def test_count_j_clamps_at_end(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            table.move_cursor(row=8)
            await pilot.pause()
            await pilot.press("5")
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_coordinate.row == 9

    async def test_count_k_moves_up_n(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            table.move_cursor(row=7)
            await pilot.pause()
            await pilot.press("3")
            await pilot.press("k")
            await pilot.pause()
            assert table.cursor_coordinate.row == 4

    async def test_count_k_clamps_at_start(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            table.move_cursor(row=2)
            await pilot.pause()
            await pilot.press("5")
            await pilot.press("k")
            await pilot.pause()
            assert table.cursor_coordinate.row == 0

    async def test_gg_jumps_to_first_row(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            table.move_cursor(row=7)
            await pilot.pause()
            await pilot.press("g")
            await pilot.press("g")
            await pilot.pause()
            assert table.cursor_coordinate.row == 0

    async def test_G_jumps_to_last_row(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            await pilot.press("G")
            await pilot.pause()
            assert table.cursor_coordinate.row == 9

    async def test_number_g_jumps_to_display_line(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            # 3g should go to display line 3 (row index 2)
            await pilot.press("3")
            await pilot.press("g")
            await pilot.pause()
            assert table.cursor_coordinate.row == 2

    async def test_number_G_jumps_to_display_line(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            await pilot.press("5")
            await pilot.press("G")
            await pilot.pause()
            assert table.cursor_coordinate.row == 4

    async def test_count_resets_after_motion(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            # 3j then j should move 3+1=4 total
            await pilot.press("3")
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_coordinate.row == 3
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_coordinate.row == 4

    async def test_count_discards_on_unrelated_key(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            # Type 5 then some unrelated key, then j should move by 1
            await pilot.press("5")
            await pilot.press("x")  # not a vim motion
            await pilot.pause()
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_coordinate.row == 1

    async def test_pending_g_shown_in_page_info(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            await pilot.press("g")
            await pilot.pause()
            from textual.widgets import Static
            info = pilot.app.query_one("#page-info", Static)
            assert "g>" in info.renderable

    async def test_count_shown_in_page_info(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            await pilot.press("5")
            await pilot.pause()
            from textual.widgets import Static
            info = pilot.app.query_one("#page-info", Static)
            assert "5>" in info.renderable

    async def test_batch_toggle(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            # All start unreviewed; batch-toggle 3
            await pilot.press("3")
            await pilot.press("enter")
            await pilot.pause()
            # Check first 3 rows are now reviewed
            for row_idx in range(3):
                row_key = table._row_locations.get_key(row_idx)
                tx = pilot.app.db.get(Transaction, int(row_key.value))
                pilot.app.db.refresh(tx)
                assert tx.reviewed_at is not None, f"Row {row_idx} should be reviewed"
            # Row 3 should still be unreviewed
            row_key = table._row_locations.get_key(3)
            tx = pilot.app.db.get(Transaction, int(row_key.value))
            pilot.app.db.refresh(tx)
            assert tx.reviewed_at is None

    async def test_batch_toggle_stops_at_end(self, account_with_10_txs, finview_app):
        async with finview_app.run_test() as pilot:
            table = await self._setup_table(pilot, account_with_10_txs)
            table.move_cursor(row=8)
            await pilot.pause()
            # Try to toggle 5 from row 8 (only 2 remaining: 8, 9)
            await pilot.press("5")
            await pilot.press("enter")
            await pilot.pause()
            for row_idx in [8, 9]:
                row_key = table._row_locations.get_key(row_idx)
                tx = pilot.app.db.get(Transaction, int(row_key.value))
                pilot.app.db.refresh(tx)
                assert tx.reviewed_at is not None


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
