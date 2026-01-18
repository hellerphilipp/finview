from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView
from textual.containers import Horizontal
from textual.binding import Binding
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .widgets import AccountItem, TransactionTable
from db import SessionLocal # Import your session factory
from models.finance import Account

class FinViewApp(App):
    CSS_PATH = "app.tcss" # Recommended: move CSS to a separate file
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh Data", show=True),
    ]

    def on_mount(self) -> None:
        self.db = SessionLocal() # Open a long-lived session for the app instance
        self.refresh_accounts()

    def on_unmount(self) -> None:
        self.db.close() # Clean up connection on exit

    def refresh_accounts(self):
        """Fetch accounts and their transactions from the DB."""
        sidebar = self.query_one("#sidebar", ListView)
        sidebar.clear()
        
        # We use selectinload to eagerly load transactions for the balance sum
        # This prevents "LazyInitializationErrors" after the session scope changes
        stmt = select(Account).options(selectinload(Account.transactions))
        accounts = self.db.execute(stmt).scalars().all()

        for acc in accounts:
            sidebar.append(AccountItem(acc))
        sidebar.focus()

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            sidebar = ListView(id="sidebar")
            sidebar.border_title = "Accounts"
            yield sidebar
            yield TransactionTable(id="main-content")
        yield Footer()

    def on_list_view_selected(self, message: ListView.Selected):
        account = message.item.account
        table = self.query_one(TransactionTable)
        # Pass the active session to the table for querying
        table.update_account(account, self.db)
        table.focus()

    def action_refresh(self):
        self.refresh_accounts()

    def action_focus_sidebar(self):
        self.query_one("#sidebar").focus()