from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView
from textual.containers import Horizontal
from textual.binding import Binding
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .widgets import AccountItem, TransactionTable
from .screens import CreateAccountScreen
from db import SessionLocal
from models.finance import Account, Transaction, Currency

class FinViewApp(App):
    CSS_PATH = "app.tcss"
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh Data", show=True),
        Binding("c", "create_account", "New Account", show=True),
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
        stmt = select(Account).options(selectinload(Account.transactions)).order_by(Account.id)
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
        table.update_account(account, self.db)
        table.focus()

    def action_refresh(self):
        self.refresh_accounts()

    def action_focus_sidebar(self):
        self.query_one("#sidebar").focus()

    def action_create_account(self):
        def handle_result(data: dict):
            if data is None:
                return # User cancelled
            
            try:
                # 1. Create Account
                new_acc = Account(
                    name=data["name"],
                    currency=data["currency"]
                )
                self.db.add(new_acc)
                self.db.flush() # Flush to assign new_acc.id
                
                # 2. Create Initial Transaction
                # Only if amount is not 0 (or strictly required by your logic)
                initial_tx = Transaction(
                    account_id=new_acc.id,
                    description="Initial Balance",
                    original_value=data["amount"],
                    original_currency=data["currency"],
                    value_in_account_currency=data["amount"],
                    date=data["date"]
                )
                self.db.add(initial_tx)
                
                self.db.commit()
                self.notify(f"Created account: {new_acc.name}")
                self.refresh_accounts()
                
            except Exception as e:
                self.db.rollback()
                self.notify(f"Error creating account: {e}", severity="error")

        self.push_screen(CreateAccountScreen(), handle_result)