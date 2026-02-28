import os
from decimal import Decimal

from rich.style import Style
from textual.css.query import NoMatches
from textual.widgets import ListItem, ListView, DataTable, Label, Static
from textual.containers import Horizontal
from textual.binding import Binding

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from models.finance import Transaction
from .screens import ImportFileDialog, SplitTransactionScreen
import db
import queries

REVIEWED_BG = Style(bgcolor="dark_green")
UNREVIEWED_BG = Style(bgcolor="dark_red")

BASE_COLUMNS = [
    ("#", "row_num"),
    ("Date & Time", "date"),
    ("Description", "description"),
    ("Amount", "amount"),
    ("Currency", "currency"),
    ("Reviewed", "reviewed"),
]

ACCOUNT_COLUMN = ("Account", "account")


class AccountSidebar(ListView):
    BINDINGS = [
        Binding("c", "create_account", "New Account", show=True),
    ]

    def action_create_account(self):
        self.app.action_create_account()


class AllAccountsItem(ListItem):
    def compose(self):
        yield Label("All Accounts")


class AccountItem(ListItem):
    def __init__(self, account, balance: Decimal = Decimal("0")):
        super().__init__()
        self.account = account
        self._balance = balance

    def compose(self):
        yield Horizontal(
            Label(self.account.name, classes="acc-name"),
            Label(f"{self._balance:.2f} {self.account.currency.value}", classes="acc-bal"),
        )

class TransactionTable(DataTable):
    BINDINGS = [
        Binding("escape", "focus_sidebar", "Sidebar", show=True),
        Binding("i", "import_csv", "Import CSV", show=True),
        Binding("enter", "toggle_reviewed", "Reviewed", show=True),
        Binding("s", "split_transaction", "Split", show=True),
    ]

    def on_mount(self):
        self.cursor_type = "row"
        self.current_account = None
        self._all_accounts_mode = False
        self._row_styles: dict[str, Style] = {}
        self._total_count = 0
        self._total_unreviewed = 0
        self._session = None
        self._count_buffer: str = ""
        self._pending_g: bool = False
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

    def _row_cells(self, tx, row_num, account_name=None):
        """Return plain cell values for a transaction."""
        cells = [
            str(row_num),
            tx.date.strftime("%Y-%m-%d %H:%M"),
        ]
        if account_name is not None:
            cells.append(account_name)
        desc = f"{tx.description} (split)" if tx.parent_id is not None else tx.description
        cells.extend([
            desc,
            f"{tx.original_value:>10.2f}",
            tx.original_currency.value,
            "Yes" if tx.reviewed_at else "No",
        ])
        return tuple(cells)

    def _update_banner(self):
        """Update the review banner and page info."""
        try:
            banner = self.app.query_one("#review-banner", Static)
        except NoMatches:
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
        """Update the entry count at the bottom right."""
        try:
            info = self.app.query_one("#page-info", Static)
        except NoMatches:
            return

        parts = []
        if self._count_buffer:
            parts.append(f"{self._count_buffer}>")
        elif self._pending_g:
            parts.append("g>")
        if db.db_file_path:
            parts.append(os.path.basename(db.db_file_path))
        else:
            parts.append("[No File]")
        if db.is_dirty():
            parts.append("[+]")
        parts.append(f"Showing {self.row_count} of {self._total_count} entries")
        info.update(" | ".join(parts))

    def _load_transactions(self):
        """Load all transactions and update counts from DB."""
        session = self._session
        account_id = None if self._all_accounts_mode else self.current_account.id
        total_count, total_unreviewed, rows = queries.load_transaction_page(
            session, account_id=account_id, all_accounts=self._all_accounts_mode
        )
        self._total_count = total_count
        self._total_unreviewed = total_unreviewed

        # Clear rows only, keep columns
        self.clear()
        self._row_styles = {}

        if self._all_accounts_mode:
            for i, (tx, account_name) in enumerate(rows, start=1):
                key = str(tx.id)
                self.add_row(*self._row_cells(tx, i, account_name=account_name), key=key)
                self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
        else:
            for i, tx in enumerate(rows, start=1):
                key = str(tx.id)
                self.add_row(*self._row_cells(tx, i), key=key)
                self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG

        self._update_banner()

    def update_account(self, account, session):
        """Populate table with a single account's transactions."""
        self.current_account = account
        self._all_accounts_mode = False
        self._session = session
        self._setup_columns(all_accounts=False)
        self._load_transactions()

    def update_all_accounts(self, session):
        """Populate table with transactions from all accounts."""
        self.current_account = None
        self._all_accounts_mode = True
        self._session = session
        self._setup_columns(all_accounts=True)
        self._load_transactions()

    # --- Vim-style navigation ---

    def on_key(self, event):
        key = event.key

        # Accumulate digits into count buffer (0 only in non-leading position)
        if key in "0123456789" and (self._count_buffer or key != "0"):
            self._count_buffer += key
            event.prevent_default()
            self._update_page_info()
            return

        count = int(self._count_buffer) if self._count_buffer else None
        self._count_buffer = ""

        if key == "j":
            self._move_relative(count or 1)
            event.prevent_default()
        elif key == "k":
            self._move_relative(-(count or 1))
            event.prevent_default()
        elif key == "g":
            if self._pending_g:
                self._move_to_display_line(1)
                self._pending_g = False
            elif count is not None:
                self._move_to_display_line(count)
            else:
                self._pending_g = True
                self._update_page_info()
                return
            event.prevent_default()
        elif key == "G":
            if count is not None:
                self._move_to_display_line(count)
            else:
                self._move_to(self.row_count - 1)
            event.prevent_default()
        elif key == "enter" and count is not None:
            self._batch_toggle(count)
            event.prevent_default()
            event.stop()

        self._pending_g = False
        self._update_page_info()

    def _move_relative(self, delta: int):
        target = self.cursor_coordinate.row + delta
        self._move_to(target)

    def _move_to(self, row: int):
        if self.row_count == 0:
            return
        row = max(0, min(row, self.row_count - 1))
        self.move_cursor(row=row)

    def _move_to_display_line(self, display_num: int):
        self._move_to(display_num - 1)

    # --- Toggle reviewed ---

    def _toggle_row_at(self, row_index: int):
        """Toggle reviewed status on a specific row. Returns True if toggled."""
        if row_index < 0 or row_index >= self.row_count:
            return False
        row_key = self._row_locations.get_key(row_index)
        if row_key is None:
            return False
        session = self._session or self.app.db
        tx = queries.toggle_reviewed(session, int(row_key.value))
        if tx is None:
            return False
        db.mark_dirty()
        self._row_styles[row_key.value] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
        self.update_cell(row_key, "reviewed", "Yes" if tx.reviewed_at else "No")
        self._clear_caches()
        self._total_unreviewed += -1 if tx.reviewed_at else 1
        return True

    def _batch_toggle(self, count: int):
        """Toggle reviewed status on count consecutive rows, stopping at end."""
        start = self.cursor_coordinate.row
        end = min(start + count, self.row_count)
        for row_idx in range(start, end):
            self._toggle_row_at(row_idx)
        # Move cursor to last toggled row
        self.move_cursor(row=end - 1)
        self._update_banner()

    def action_toggle_reviewed(self):
        row = self.cursor_coordinate.row
        if self._toggle_row_at(row):
            self._update_banner()
            if row < self.row_count - 1:
                self.move_cursor(row=row + 1)

    def action_focus_sidebar(self):
        self.app.action_focus_sidebar()

    def action_import_csv(self):
        if not self.current_account:
            self.notify("No account selected", severity="error")
            return

        if not self.current_account.mapping_spec:
            self.notify("This account has no mapping spec!", severity="error")
            return

        def handle_import(csv_path: str | None):
            if not csv_path:
                return
            
            # Call a processing method on the app or handle it here
            # Since we need the DB session, let's trigger an app method
            self.app.process_csv_import(csv_path, self.current_account)

        self.app.push_screen(ImportFileDialog(), handle_import)

    def action_split_transaction(self):
        if self.row_count == 0:
            return

        row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        session = self._session or self.app.db
        tx = session.get(Transaction, int(row_key.value))
        if tx is None:
            return

        # Navigate to root parent if this is a child
        root = tx
        while root.parent_id is not None:
            root = session.get(Transaction, root.parent_id)
            if root is None:
                return

        # Eager-load children
        root = session.execute(
            select(Transaction)
            .where(Transaction.id == root.id)
            .options(selectinload(Transaction.children))
        ).scalar_one()

        existing = list(root.children) if root.children else None

        def handle_split(splits: list[dict] | None):
            if splits is None:
                return

            existing_ids = {c.id for c in (existing or [])}
            returned_ids = {s["id"] for s in splits if s["id"] is not None}

            # Delete removed children
            for child in list(root.children):
                if child.id not in returned_ids:
                    session.delete(child)

            # Compute proportional ratio
            if float(root.original_value) != 0:
                ratio = Decimal(str(root.value_in_account_currency)) / Decimal(
                    str(root.original_value)
                )
            else:
                ratio = Decimal("1")

            # Update or create children
            for s in splits:
                amount = Decimal(str(s["amount"]))
                acc_amount = float(amount * ratio)

                if s["id"] is not None and s["id"] in existing_ids:
                    # Update existing child
                    child = session.get(Transaction, s["id"])
                    if child:
                        child.description = s["description"]
                        child.original_value = float(amount)
                        child.value_in_account_currency = acc_amount
                else:
                    # Create new child
                    child = Transaction(
                        account_id=root.account_id,
                        description=s["description"],
                        original_value=float(amount),
                        original_currency=root.original_currency,
                        value_in_account_currency=acc_amount,
                        date=root.date,
                        parent_id=root.id,
                    )
                    session.add(child)

            session.commit()
            db.mark_dirty()
            self._load_transactions()

        self.app.push_screen(
            SplitTransactionScreen(root, existing), handle_split
        )