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

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Header, Input, Static

import db
import queries
from models.finance import Account, Category, Currency, Transaction

from .screens import (
    CreateAccountScreen,
    CreateCategoryScreen,
    DeleteCategoryConfirmScreen,
    RenameCategoryScreen,
)
from .widgets import (
    AccountItem,
    AccountSidebar,
    AllAccountsItem,
    AllCategoriesItem,
    CategoryItem,
    CategorySidebar,
    SidebarSection,
    TransactionTable,
)


class FinViewApp(App):
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("r", "refresh", "Refresh Data", show=True),
        Binding("colon", "show_command_line", "Command", show=False),
    ]

    def on_mount(self) -> None:
        self.db = db.SessionLocal()
        self._last_sidebar_id = "sidebar"
        self.refresh_accounts()
        self.refresh_categories()

    def on_unmount(self) -> None:
        self.db.close()

    def refresh_accounts(self):
        """Fetch accounts and their transactions from the DB."""
        sidebar = self.query_one("#sidebar", AccountSidebar)
        sidebar.clear()

        accounts_with_balances = queries.get_all_accounts_with_balances(self.db)

        sidebar.append(AllAccountsItem())
        for acc, balance in accounts_with_balances:
            sidebar.append(AccountItem(acc, balance=balance))
        sidebar.index = 0
        sidebar.focus()

        # Update the accounts section header count
        try:
            section = self.query_one("#accounts-section", SidebarSection)
            section.set_count(len(accounts_with_balances))
        except NoMatches:
            pass

        table = self.query_one(TransactionTable)
        table.update_all_accounts(self.db)

    def refresh_categories(self):
        """Fetch categories and repopulate the category sidebar."""
        try:
            cat_sidebar = self.query_one("#category-sidebar", CategorySidebar)
        except NoMatches:
            return
        cat_sidebar.clear()
        cat_sidebar.append(AllCategoriesItem())

        cats_with_counts = queries.get_categories_with_transaction_counts(self.db)
        # Build tree structure for indented display
        cat_by_id = {cat.id: (cat, count, path) for cat, count, path in cats_with_counts}
        # Track children per parent for is_last_child
        children_by_parent: dict[int | None, list] = {}
        for cat, count, path in cats_with_counts:
            children_by_parent.setdefault(cat.parent_id, []).append(cat.id)

        for cat, count, path in cats_with_counts:
            depth = path.count("/")
            siblings = children_by_parent.get(cat.parent_id, [])
            is_last = siblings[-1] == cat.id if siblings else False
            cat_sidebar.append(
                CategoryItem(
                    cat, full_path=path, depth=depth, transaction_count=count, is_last_child=is_last
                )
            )

        # Update the categories section header count
        try:
            section = self.query_one("#categories-section", SidebarSection)
            section.set_count(len(cats_with_counts))
        except NoMatches:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar-container"):
                with SidebarSection("Accounts", id="accounts-section", collapsed=False):
                    sidebar = AccountSidebar(id="sidebar")
                    yield sidebar
                with SidebarSection("Categories", id="categories-section", collapsed=True):
                    cat_sidebar = CategorySidebar(id="category-sidebar")
                    yield cat_sidebar
            with Vertical():
                yield Static("", id="review-banner")
                yield TransactionTable(id="main-content")
                yield Static("", id="page-info")
        yield Input(id="command-input")
        yield Input(id="search-input", placeholder="/")
        yield Footer()

    def switch_sidebar(self, target: str):
        """Switch between account and category sidebar sections."""
        try:
            acc_section = self.query_one("#accounts-section", SidebarSection)
            cat_section = self.query_one("#categories-section", SidebarSection)
        except NoMatches:
            return

        if target == "categories":
            acc_section.collapse()
            cat_section.expand()
            cat_sidebar = self.query_one("#category-sidebar", CategorySidebar)
            cat_sidebar.focus()
            self._last_sidebar_id = "category-sidebar"
        else:
            cat_section.collapse()
            acc_section.expand()
            acc_sidebar = self.query_one("#sidebar", AccountSidebar)
            acc_sidebar.focus()
            self._last_sidebar_id = "sidebar"

    def on_list_view_selected(self, message):
        table = self.query_one(TransactionTable)
        if isinstance(message.item, AllAccountsItem):
            table.update_all_accounts(self.db)
            table.focus()
        elif isinstance(message.item, AccountItem):
            table.update_account(message.item.account, self.db)
            table.focus()
        elif isinstance(message.item, (AllCategoriesItem, CategoryItem)):
            # TODO: filter transactions by selected category
            table.focus()

    def action_refresh(self):
        self.refresh_accounts()
        self.refresh_categories()

    def action_focus_sidebar(self):
        try:
            self.query_one(f"#{self._last_sidebar_id}").focus()
        except NoMatches:
            self.query_one("#sidebar").focus()

    # --- Command Line ---

    def action_show_command_line(self):
        cmd_input = self.query_one("#command-input", Input)
        cmd_input.value = ":"
        cmd_input.add_class("visible")
        cmd_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            term = event.input.value.strip()
            self._hide_search_input()
            if term:
                table = self.query_one(TransactionTable)
                table.search(term)
                table.focus()
            return
        if event.input.id != "command-input":
            return
        cmd = event.input.value.strip()
        self._hide_command_input()
        if cmd:
            self._handle_command(cmd)

    def on_key(self, event) -> None:
        try:
            cmd_input = self.query_one("#command-input", Input)
            search_input = self.query_one("#search-input", Input)
        except NoMatches:
            return

        if cmd_input.has_class("visible") and event.key == "escape":
            self._hide_command_input()
            event.prevent_default()
            event.stop()
            return

        if search_input.has_class("visible") and event.key == "escape":
            self._hide_search_input()
            event.prevent_default()
            event.stop()
            return

        # `/` opens search (only when neither input is active)
        if (
            event.key == "slash"
            and not cmd_input.has_class("visible")
            and not search_input.has_class("visible")
        ):
            self._show_search_input()
            event.prevent_default()
            event.stop()

    def _hide_command_input(self):
        cmd_input = self.query_one("#command-input", Input)
        cmd_input.value = ""
        cmd_input.remove_class("visible")
        self.action_focus_sidebar()

    # --- Search Input ---

    def _show_search_input(self):
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        search_input.add_class("visible")
        search_input.focus()

    def _hide_search_input(self):
        search_input = self.query_one("#search-input", Input)
        search_input.value = ""
        search_input.remove_class("visible")
        self.query_one(TransactionTable).focus()

    def _handle_command(self, cmd: str):
        # TODO: add colon command aliases for category management
        #   e.g., :cat-new, :cat-del, :cat-rename
        # TODO: add colon command aliases for account management
        #   e.g., :acc-new
        if cmd.startswith(":wq"):
            path = cmd[3:].strip() or None
            self._save_db(path, quit_after=True)
        elif cmd == ":q!":
            self.exit()
        elif cmd == ":q":
            if db.is_dirty():
                self.notify(
                    "Unsaved changes! Use :wq to save and quit, or :q! to discard.",
                    severity="warning",
                )
            else:
                self.exit()
        elif cmd.startswith(":w"):
            path = cmd[2:].strip() or None
            self._save_db(path)
        else:
            self.notify(f"Unknown command: {cmd}", severity="error")

    def _save_db(self, path: str | None = None, quit_after: bool = False):
        target = path or db.db_file_path
        if target is None:
            self.notify("No file name", severity="error")
            return
        self._do_save(target)
        if quit_after and not db.is_dirty():
            self.exit()

    def _do_save(self, path: str):
        try:
            db.save_to_file(path)
            self.notify(f"Saved to {path}")
            self._update_page_info()
        except Exception as e:
            self.notify(f"Save failed: {e}", severity="error")

    def _update_page_info(self):
        table = self.query_one(TransactionTable)
        table._update_page_info()

    # --- Quit Override ---

    def action_quit(self):
        if db.is_dirty():
            self.notify(
                "Unsaved changes! Use :wq to save and quit, or :q! to discard.",
                severity="warning",
            )
        else:
            self.exit()

    # --- Account / Import Actions ---

    def action_create_account(self):
        def handle_result(data: dict):
            if data is None:
                return

            try:
                new_acc = Account(
                    name=data["name"],
                    currency=data["currency"],
                    mapping_spec=data["mapping_spec"],
                )
                self.db.add(new_acc)
                self.db.flush()

                initial_tx = Transaction(
                    account_id=new_acc.id,
                    description="Initial Balance",
                    original_value=data["amount"],
                    original_currency=data["currency"],
                    value_in_account_currency=data["amount"],
                    date=data["date"],
                )
                self.db.add(initial_tx)

                self.db.commit()
                db.mark_dirty()
                self.notify(f"Created account: {new_acc.name}")
                self.refresh_accounts()

            except Exception as e:
                self.db.rollback()
                self.notify(f"Error creating account: {e}", severity="error")

        self.push_screen(CreateAccountScreen(), handle_result)

    def process_csv_import(self, csv_path: str, account):
        """Processes the CSV file using the account's mapping spec."""
        try:
            count = queries.import_csv_transactions(self.db, csv_path, account)
            db.mark_dirty()
            self.notify(f"Successfully imported {count} transactions.")
            self.query_one(TransactionTable).update_account(account, self.db)
            self.refresh_accounts()
        except (FileNotFoundError, ValueError) as e:
            self.notify(str(e), severity="error")
        except Exception as e:
            self.db.rollback()
            self.notify(f"Import failed: {str(e)}", severity="error")

    # --- Category Actions ---

    def action_create_category(self):
        def handle_result(path: str | None):
            if path is None:
                return
            try:
                queries.create_category(self.db, path)
                db.mark_dirty()
                self.notify(f"Created category: {path}")
                self.refresh_categories()
            except Exception as e:
                self.db.rollback()
                self.notify(f"Error: {e}", severity="error")

        self.push_screen(CreateCategoryScreen(), handle_result)

    def action_delete_category(self):
        try:
            cat_sidebar = self.query_one("#category-sidebar", CategorySidebar)
        except NoMatches:
            return
        selected = cat_sidebar.highlighted_child
        if selected is None or isinstance(selected, AllCategoriesItem):
            return
        if not isinstance(selected, CategoryItem):
            return

        cat = selected.category
        child_count, tx_count = queries.get_category_delete_stats(self.db, cat.id)

        def handle_result(confirmed: bool):
            if not confirmed:
                return
            try:
                queries.delete_category(self.db, cat.id)
                db.mark_dirty()
                self.notify(f"Deleted category: {selected.full_path}")
                self.refresh_categories()
                # Reload transactions to clear stale category references
                table = self.query_one(TransactionTable)
                table._load_transactions()
            except Exception as e:
                self.db.rollback()
                self.notify(f"Error: {e}", severity="error")

        self.push_screen(
            DeleteCategoryConfirmScreen(selected.full_path, child_count, tx_count),
            handle_result,
        )

    def action_rename_category(self):
        try:
            cat_sidebar = self.query_one("#category-sidebar", CategorySidebar)
        except NoMatches:
            return
        selected = cat_sidebar.highlighted_child
        if selected is None or isinstance(selected, AllCategoriesItem):
            return
        if not isinstance(selected, CategoryItem):
            return

        cat = selected.category

        def handle_result(new_name: str | None):
            if new_name is None:
                return
            try:
                queries.rename_category(self.db, cat.id, new_name)
                db.mark_dirty()
                self.notify(f"Renamed to: {new_name}")
                self.refresh_categories()
                table = self.query_one(TransactionTable)
                table._load_transactions()
            except ValueError as e:
                self.notify(str(e), severity="error")

        self.push_screen(RenameCategoryScreen(cat.name), handle_result)
