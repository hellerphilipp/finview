from datetime import datetime

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
        balance = sum(t.value_in_account_currency for t in self.account.transactions)
        yield Horizontal(
            Label(self.account.name, classes="acc-name"),
            Label(f"{balance:.2f} {self.account.currency.value}", classes="acc-bal"),
        )

class TransactionTable(DataTable):
    BINDINGS = [
        Binding("escape", "focus_sidebar", "Sidebar", show=True),
        Binding("i", "import_csv", "Import CSV", show=True),
        Binding("a", "toggle_reviewed", "Reviewed", show=True),
    ]

    def on_mount(self):
        self.cursor_type = "row"
        self.add_column("Date & Time", key="date")
        self.add_column("Description", key="description")
        self.add_column("Amount", key="amount")
        self.add_column("Currency", key="currency")
        self.add_column("Reviewed", key="reviewed")
        self.current_account = None

    def update_account(self, account, session):
        """Populate table from DB. We use the session to query transactions."""
        self.current_account = account
        self.clear()

        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account.id)
            .order_by(Transaction.date.desc())
            .limit(100)
        )

        transactions = session.execute(stmt).scalars().all()

        for tx in transactions:
            self.add_row(
                tx.date.strftime("%Y-%m-%d %H:%M"),
                tx.description,
                f"{tx.original_value:>10.2f}",
                tx.original_currency.value,
                "Yes" if tx.reviewed_at else "No",
                key=str(tx.id),
            )

    def action_toggle_reviewed(self):
        if self.row_count == 0:
            return

        row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        session = self.app.db
        tx = session.get(Transaction, int(row_key.value))
        if tx is None:
            return

        tx.reviewed_at = None if tx.reviewed_at else datetime.now()
        session.commit()

        self.update_cell(row_key, "reviewed", "Yes" if tx.reviewed_at else "No")
    
    def action_focus_sidebar(self):
        self.app.action_focus_sidebar()

    def action_import_csv(self):
        if not self.current_account:
            self.notify("No account selected", severity="error")
            return

        if not self.current_account.mapping_spec:
            self.notify("This account has no mapping spec!", severity="error")
            return

        # We need the screen class, make sure it's imported in widgets.py
        from .screens import ImportFileDialog 

        def handle_import(csv_path: str | None):
            if not csv_path:
                return
            
            # Call a processing method on the app or handle it here
            # Since we need the DB session, let's trigger an app method
            self.app.process_csv_import(csv_path, self.current_account)

        self.app.push_screen(ImportFileDialog(), handle_import)