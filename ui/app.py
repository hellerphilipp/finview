from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Header, Footer, Static, Input
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from .widgets import AccountItem, AccountSidebar, AllAccountsItem, TransactionTable
from .screens import CreateAccountScreen
import db
import queries
from models.finance import Account, Transaction, Currency


class FinViewApp(App):
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("r", "refresh", "Refresh Data", show=True),
        Binding("colon", "show_command_line", "Command", show=False),
    ]

    def on_mount(self) -> None:
        self.db = db.SessionLocal()
        self.refresh_accounts()

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

        table = self.query_one(TransactionTable)
        table.update_all_accounts(self.db)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            sidebar = AccountSidebar(id="sidebar")
            sidebar.border_title = "Accounts"
            yield sidebar
            with Vertical():
                yield Static("", id="review-banner")
                yield TransactionTable(id="main-content")
                yield Static("", id="page-info")
        yield Input(id="command-input")
        yield Input(id="search-input", placeholder="/")
        yield Footer()

    def on_list_view_selected(self, message: AccountSidebar.Selected):
        table = self.query_one(TransactionTable)
        if isinstance(message.item, AllAccountsItem):
            table.update_all_accounts(self.db)
        else:
            table.update_account(message.item.account, self.db)
        table.focus()

    def action_refresh(self):
        self.refresh_accounts()

    def action_focus_sidebar(self):
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
        self.query_one("#sidebar").focus()

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
