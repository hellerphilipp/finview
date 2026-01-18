from textual.widgets import ListItem, DataTable, Label
from textual.containers import Horizontal
from textual.binding import Binding

class AccountItem(ListItem):
    """Custom list item to show account name and balance."""
    def __init__(self, account):
        super().__init__()
        self.account = account

    def compose(self):
        yield Horizontal(
            Label(self.account.name, classes="acc-name"),
            Label(f"{sum(t.original_value for t in self.account.transactions):.2f} {self.account.currency.value}", classes="acc-bal"),
        )

class TransactionTable(DataTable):
    """DataTable optimized for transactions."""

    BINDINGS = [
        Binding("escape", "focus_sidebar", "Sidebar", show=True),
    ]

    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns("Date", "Description", "Amount", "Currency")

    def on_mount(self):
        self.cursor_type = "row"
        self.add_columns("Date", "Description", "Amount", "Currency")

    def action_focus_sidebar(self):
        self.app.action_focus_sidebar()
        

    def update_account(self, account):
        self.clear()
        # Sorting: Newest (highest index/date) to oldest
        sorted_txs = sorted(account.transactions, key=lambda x: x.date_str, reverse=True)
        for tx in sorted_txs:
            self.add_row(
                tx.date_str, 
                tx.description, 
                f"{tx.original_value:>10.2f}", 
                tx.original_currency.value
            )
