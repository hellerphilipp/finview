from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView
from textual.containers import Horizontal  # <--- Add this import
from textual.binding import Binding
from .widgets import AccountItem, TransactionTable
from mock import get_mock_data

CSS = """
Screen {
    layers: sidebar main;
}

#sidebar {
    dock: left;
    width: 35;
    background: $panel;
    border-right: tall $primary;
}

AccountItem {
    height: 1;
    padding: 0 1;
}

AccountItem > Horizontal {
    height: 1;
}

.acc-name { width: 60%; }
.acc-bal { width: 40%; text-align: right; color: $accent; }

#main-content {
    width: 1fr;
}
"""

class FinViewApp(App):
    CSS = CSS
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "focus_sidebar", "Sidebar", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield ListView(id="sidebar")
            yield TransactionTable(id="main-content")
        yield Footer()

    def on_mount(self) -> None:
        self.accounts = get_mock_data()
        sidebar = self.query_one("#sidebar", ListView)
        for acc in self.accounts:
            sidebar.append(AccountItem(acc))
        sidebar.focus()

    def on_list_view_selected(self, message: ListView.Selected):
        """Update table when an account is clicked or Enter is pressed."""
        account = message.item.account
        table = self.query_one(TransactionTable)
        table.update_account(account)
        table.focus()

    def action_focus_sidebar(self):
        self.query_one("#sidebar").focus()

    def action_quit(self):
        self.exit()
