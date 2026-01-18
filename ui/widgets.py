from textual.widgets import ListItem, DataTable, Label
from textual.containers import Horizontal
from textual.binding import Binding
from sqlalchemy import select
from models.finance import Transaction

class AccountItem(ListItem):
    def __init__(self, account):
        super().__init__()
        self.account = account

    def compose(self):
        # We calculate balance here. Note: In a production app with millions of rows,
        # you'd use a SQL SUM() query instead of sum(list comprehension).
        balance = sum(t.original_value for t in self.account.transactions)
        yield Horizontal(
            Label(self.account.name, classes="acc-name"),
            Label(f"{balance:.2f} {self.account.currency.value}", classes="acc-bal"),
        )

class TransactionTable(DataTable):
    BINDINGS = [
        Binding("escape", "focus_sidebar", "Sidebar", show=True),
    ]

    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns("Date", "Description", "Amount", "Currency")

    def action_focus_sidebar(self):
        self.app.action_focus_sidebar()

    def update_account(self, account, session):
        """Populate table from DB. We use the session to query transactions."""
        self.clear()
        
        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account.id)
            .order_by(Transaction.date_str.desc())
            .limit(100) 
        )
        
        transactions = session.execute(stmt).scalars().all()

        for tx in transactions:
            self.add_row(
                tx.date_str, 
                tx.description, 
                f"{tx.original_value:>10.2f}", 
                tx.original_currency.value
            )