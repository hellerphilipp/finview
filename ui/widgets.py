from datetime import datetime
from math import ceil

from rich.style import Style
from textual.widgets import ListItem, DataTable, Label, Static
from textual.containers import Horizontal
from textual.binding import Binding
from sqlalchemy import select, func, case
from models.finance import Account, Transaction

REVIEWED_BG = Style(bgcolor="dark_green")
UNREVIEWED_BG = Style(bgcolor="dark_red")

BASE_COLUMNS = [
    ("Date & Time", "date"),
    ("Description", "description"),
    ("Amount", "amount"),
    ("Currency", "currency"),
    ("Reviewed", "reviewed"),
]

ACCOUNT_COLUMN = ("Account", "account")


class AllAccountsItem(ListItem):
    def compose(self):
        yield Label("All Accounts")


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
    PAGE_SIZE = 100

    BINDINGS = [
        Binding("escape", "focus_sidebar", "Sidebar", show=True),
        Binding("i", "import_csv", "Import CSV", show=True),
        Binding("a", "toggle_reviewed", "Reviewed", show=True),
        Binding("n", "next_page", "Next Page", show=True),
        Binding("p", "prev_page", "Prev Page", show=True),
    ]

    def on_mount(self):
        self.cursor_type = "row"
        self.current_account = None
        self._all_accounts_mode = False
        self._row_styles: dict[str, Style] = {}
        self._page = 0
        self._total_count = 0
        self._total_unreviewed = 0
        self._session = None
        for label, key in BASE_COLUMNS:
            self.add_column(label, key=key)

    def _get_row_style(self, row_index: int, base_style: Style) -> Style:
        style = super()._get_row_style(row_index, base_style)
        if row_index < 0:
            return style
        row_key = self._row_locations.get_key(row_index)
        if row_key is not None and row_key.value in self._row_styles:
            style += self._row_styles[row_key.value]
        return style

    def _setup_columns(self, all_accounts: bool):
        """Remove all columns and re-add in correct order for the mode."""
        for col_key in list(self.columns.keys()):
            self.remove_column(col_key)
        cols = list(BASE_COLUMNS)
        if all_accounts:
            cols.insert(1, ACCOUNT_COLUMN)
        for label, key in cols:
            self.add_column(label, key=key)

    def _row_cells(self, tx, account_name=None):
        """Return plain cell values for a transaction."""
        cells = [
            tx.date.strftime("%Y-%m-%d %H:%M"),
        ]
        if account_name is not None:
            cells.append(account_name)
        cells.extend([
            tx.description,
            f"{tx.original_value:>10.2f}",
            tx.original_currency.value,
            "Yes" if tx.reviewed_at else "No",
        ])
        return tuple(cells)

    def _update_banner(self):
        """Update the review banner and page info."""
        try:
            banner = self.app.query_one("#review-banner", Static)
        except Exception:
            return
        if self._total_unreviewed > 0:
            s = "s" if self._total_unreviewed != 1 else ""
            banner.update(f" {self._total_unreviewed} unreviewed transaction{s} ")
            banner.add_class("has-unreviewed")
            banner.remove_class("all-reviewed")
        else:
            banner.update(" All transactions reviewed ")
            banner.add_class("all-reviewed")
            banner.remove_class("has-unreviewed")

        self._update_page_info()

    def _update_page_info(self):
        """Update the page indicator at the bottom right."""
        try:
            info = self.app.query_one("#page-info", Static)
        except Exception:
            return
        total_pages = max(1, ceil(self._total_count / self.PAGE_SIZE))
        showing = self.row_count
        info.update(f"Page {self._page + 1}/{total_pages} showing {showing} of {self._total_count} entries")

    def _base_filter(self):
        """Return the WHERE clause for the current mode."""
        if self._all_accounts_mode:
            return None
        return Transaction.account_id == self.current_account.id

    def _load_page(self):
        """Load the current page of transactions and update counts from DB."""
        session = self._session
        where = self._base_filter()

        # Count totals
        count_stmt = select(
            func.count(Transaction.id),
            func.sum(case((Transaction.reviewed_at.is_(None), 1), else_=0)),
        )
        if where is not None:
            count_stmt = count_stmt.where(where)
        total_count, total_unreviewed = session.execute(count_stmt).one()
        self._total_count = total_count or 0
        self._total_unreviewed = int(total_unreviewed or 0)

        # Clamp page
        total_pages = max(1, ceil(self._total_count / self.PAGE_SIZE))
        if self._page >= total_pages:
            self._page = total_pages - 1

        # Fetch page rows
        if self._all_accounts_mode:
            stmt = (
                select(Transaction, Account.name)
                .join(Account, Transaction.account_id == Account.id)
            )
        else:
            stmt = select(Transaction)
            if where is not None:
                stmt = stmt.where(where)

        stmt = (
            stmt.order_by(Transaction.date.desc())
            .offset(self._page * self.PAGE_SIZE)
            .limit(self.PAGE_SIZE)
        )

        # Clear rows only, keep columns
        self.clear()
        self._row_styles = {}

        if self._all_accounts_mode:
            rows = session.execute(stmt).all()
            for tx, account_name in rows:
                key = str(tx.id)
                self.add_row(*self._row_cells(tx, account_name=account_name), key=key)
                self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
        else:
            transactions = session.execute(stmt).scalars().all()
            for tx in transactions:
                key = str(tx.id)
                self.add_row(*self._row_cells(tx), key=key)
                self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG

        self._update_banner()

    def update_account(self, account, session):
        """Populate table with a single account's transactions."""
        self.current_account = account
        self._all_accounts_mode = False
        self._page = 0
        self._session = session
        self._setup_columns(all_accounts=False)
        self._load_page()

    def update_all_accounts(self, session):
        """Populate table with transactions from all accounts."""
        self.current_account = None
        self._all_accounts_mode = True
        self._page = 0
        self._session = session
        self._setup_columns(all_accounts=True)
        self._load_page()

    def action_toggle_reviewed(self):
        if self.row_count == 0:
            return

        row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        session = self._session or self.app.db
        tx = session.get(Transaction, int(row_key.value))
        if tx is None:
            return

        tx.reviewed_at = None if tx.reviewed_at else datetime.now()
        session.commit()

        self._row_styles[row_key.value] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
        self.update_cell(row_key, "reviewed", "Yes" if tx.reviewed_at else "No")
        self._clear_caches()

        self._total_unreviewed += -1 if tx.reviewed_at else 1
        self._update_banner()

    def action_next_page(self):
        total_pages = max(1, ceil(self._total_count / self.PAGE_SIZE))
        if self._page < total_pages - 1:
            self._page += 1
            self._load_page()

    def action_prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._load_page()
    
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