from datetime import datetime

from rich.style import Style
from textual.widgets import ListItem, DataTable, Label, Static
from textual.containers import Horizontal
from textual.binding import Binding
from sqlalchemy import select
from models.finance import Transaction

REVIEWED_BG = Style(bgcolor="dark_green")
UNREVIEWED_BG = Style(bgcolor="dark_red")

COLUMN_KEYS = ["date", "description", "amount", "currency", "reviewed"]

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
        self._row_styles: dict[str, Style] = {}

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        style = super()._get_row_style(row_index, base_style)
        if row_index < 0:
            return style
        row_key = self._row_locations.get_key(row_index)
        if row_key is not None and row_key.value in self._row_styles:
            style += self._row_styles[row_key.value]
        return style

    def _row_cells(self, tx):
        """Return plain cell values for a transaction."""
        return (
            tx.date.strftime("%Y-%m-%d %H:%M"),
            tx.description,
            f"{tx.original_value:>10.2f}",
            tx.original_currency.value,
            "Yes" if tx.reviewed_at else "No",
        )

    def _update_banner(self, unreviewed_count):
        """Update the review banner with the current unreviewed count."""
        try:
            banner = self.app.query_one("#review-banner", Static)
        except Exception:
            return
        if unreviewed_count > 0:
            banner.update(f" {unreviewed_count} unreviewed transaction{'s' if unreviewed_count != 1 else ''} ")
            banner.add_class("has-unreviewed")
            banner.remove_class("all-reviewed")
        else:
            banner.update(" All transactions reviewed ")
            banner.add_class("all-reviewed")
            banner.remove_class("has-unreviewed")

    def update_account(self, account, session):
        """Populate table from DB. We use the session to query transactions."""
        self.current_account = account
        self.clear()
        self._row_styles = {}

        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account.id)
            .order_by(Transaction.date.desc())
            .limit(100)
        )

        transactions = session.execute(stmt).scalars().all()

        self._unreviewed_count = 0
        for tx in transactions:
            key = str(tx.id)
            self.add_row(*self._row_cells(tx), key=key)
            self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
            if not tx.reviewed_at:
                self._unreviewed_count += 1

        self._update_banner(self._unreviewed_count)

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

        self._row_styles[row_key.value] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
        self.update_cell(row_key, "reviewed", "Yes" if tx.reviewed_at else "No")
        self._clear_caches()

        self._unreviewed_count += -1 if tx.reviewed_at else 1
        self._update_banner(self._unreviewed_count)
    
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