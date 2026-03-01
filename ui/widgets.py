import os
from decimal import Decimal

from rich.style import Style
from textual.css.query import NoMatches
from textual.widgets import ListItem, ListView, DataTable, Label, Static
from textual.containers import Horizontal
from textual.binding import Binding

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from models.finance import Account, Transaction
from .screens import ImportFileDialog, SplitTransactionScreen, MergeTransactionScreen, MergeActionScreen
import db
import queries

REVIEWED_BG = Style(bgcolor="dark_green")
UNREVIEWED_BG = Style(bgcolor="dark_red")
MERGE_CHILD_STYLE = Style(color="grey50")

BASE_COLUMNS = [
    ("#", "row_num"),
    ("Date & Time", "date"),
    ("Description", "description"),
    ("Amount", "amount"),
    ("Currency", "currency"),
    ("Reviewed", "reviewed"),
]

ACCOUNT_COLUMN = ("Account", "account")

# Prefix for merge header row keys in the DataTable
MERGE_HEADER_KEY_PREFIX = "merge_header_"


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
        Binding("m", "merge_transaction", "Merge", show=True),
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
        self._search_term: str = ""
        self._search_matches: list[int] = []
        self._search_index: int = -1
        # Merge pending state
        self._merge_pending_tx_id: int | None = None  # for new merges
        self._merge_pending_parent_id: int | None = None  # for add-to-group
        self._merge_pending_desc: str = ""  # description for page-info
        # Track which rows are merge children or headers
        self._merge_child_rows: set[str] = set()  # row keys that are merge children
        self._merge_header_rows: set[str] = set()  # row keys that are merge headers
        self._merge_child_to_parent: dict[str, int] = {}  # child row key → merge parent id
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

    def _row_cells(self, tx, row_num, account_name=None, merge_net=None,
                   merge_reviewed=None, merge_group_name=None,
                   is_last_merge_child=False):
        """Return plain cell values for a transaction."""
        cells = [
            str(row_num),
            tx.date.strftime("%Y-%m-%d %H:%M"),
        ]
        if account_name is not None:
            cells.append(account_name)

        # Build description with merge/split prefixes
        desc = tx.description
        if tx.parent_id is not None:
            desc = f"{desc} (split)"
        if tx.merge_parent_id is not None:
            # Tree prefix for merge children
            prefix = "  └─ " if is_last_merge_child else "  ├─ "
            desc = f"{prefix}{desc}"

        cells.extend([
            desc,
            f"{tx.original_value:>10.2f}",
            tx.original_currency.value,
        ])

        # Reviewed column: merge children inherit from parent
        if tx.merge_parent_id is not None and merge_reviewed is not None:
            cells.append("Yes" if merge_reviewed else "No")
        else:
            cells.append("Yes" if tx.reviewed_at else "No")

        return tuple(cells)

    def _merge_header_cells(self, parent_tx, row_num, net, currency, account_name=None):
        """Return cell values for a merge group header row."""
        cells = [
            str(row_num),
            parent_tx.date.strftime("%Y-%m-%d %H:%M"),
        ]
        if account_name is not None:
            cells.append(account_name)
        cells.extend([
            parent_tx.description,
            f"{net:>10.2f}",
            currency,
            "Yes" if parent_tx.reviewed_at else "No",
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
        if self._search_term:
            if self._search_matches:
                parts.append(
                    f"/{self._search_term} [{self._search_index + 1}/{len(self._search_matches)}]"
                )
            else:
                parts.append(f"/{self._search_term} [0/0]")
        # Merge pending indicator (escape brackets to avoid Rich markup interpretation)
        if self._merge_pending_parent_id is not None:
            parts.append(f"\\[merge+: {self._merge_pending_desc[:20]}]")
        elif self._merge_pending_tx_id is not None:
            parts.append(f"\\[merge: {self._merge_pending_desc[:20]}]")
        info.update(" | ".join(parts))

    def _is_last_merge_child(self, rows, idx):
        """Check if the row at idx is the last merge child before a non-child row (all-accounts mode)."""
        tx = rows[idx][0]
        if tx.merge_parent_id is None:
            return False
        # Look at the next row
        if idx + 1 >= len(rows):
            return True
        next_tx = rows[idx + 1][0]
        # Last child if next row is not a merge child of the same parent
        return next_tx.merge_parent_id != tx.merge_parent_id

    def _is_last_merge_child_single(self, rows, idx):
        """Check if the row at idx is the last merge child (single-account mode)."""
        tx = rows[idx][0]
        if tx.merge_parent_id is None:
            return False
        # In single-account mode, merge children may not be grouped contiguously.
        # Check if there's another child with the same parent after this one.
        parent_id = tx.merge_parent_id
        for j in range(idx + 1, len(rows)):
            if rows[j][0].merge_parent_id == parent_id:
                return False
        return True

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
        self._clear_search()
        self._merge_child_rows = set()
        self._merge_header_rows = set()
        self._merge_child_to_parent = {}

        if self._all_accounts_mode:
            for i, row in enumerate(rows, start=1):
                tx = row[0]
                account_name = row[1]
                merge_net = row[2]
                merge_reviewed = row[3]
                merge_group_name = row[4]

                # Check if this is a merge header row
                is_header = (account_name == "–")

                if is_header:
                    key = f"{MERGE_HEADER_KEY_PREFIX}{tx.id}"
                    net = merge_net if merge_net is not None else 0
                    currency = tx.original_currency.value
                    cells = self._merge_header_cells(tx, i, net, currency, account_name="–")
                    self.add_row(*cells, key=key)
                    # Merge parent gets normal reviewed/unreviewed background
                    self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
                    self._merge_header_rows.add(key)
                else:
                    key = str(tx.id)
                    # Determine if this is the last child in its merge group
                    is_last = self._is_last_merge_child(rows, i - 1)
                    cells = self._row_cells(tx, i, account_name=account_name,
                                           merge_net=merge_net,
                                           merge_reviewed=merge_reviewed,
                                           merge_group_name=merge_group_name,
                                           is_last_merge_child=is_last)
                    self.add_row(*cells, key=key)
                    if tx.merge_parent_id is not None:
                        # Merge children: gray text, no background
                        self._row_styles[key] = MERGE_CHILD_STYLE
                        self._merge_child_rows.add(key)
                        self._merge_child_to_parent[key] = tx.merge_parent_id
                    else:
                        self._row_styles[key] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
        else:
            for i, row in enumerate(rows, start=1):
                tx = row[0]
                merge_net = row[1]
                merge_reviewed = row[2]
                merge_group_name = row[3]
                key = str(tx.id)
                is_last = self._is_last_merge_child_single(rows, i - 1)
                cells = self._row_cells(tx, i, merge_net=merge_net,
                                       merge_reviewed=merge_reviewed,
                                       merge_group_name=merge_group_name,
                                       is_last_merge_child=is_last)
                self.add_row(*cells, key=key)
                if tx.merge_parent_id is not None:
                    # Merge children: gray text, no background
                    self._row_styles[key] = MERGE_CHILD_STYLE
                    self._merge_child_rows.add(key)
                    self._merge_child_to_parent[key] = tx.merge_parent_id
                else:
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
        elif key == "n":
            if self._search_matches:
                self._search_next()
            event.prevent_default()
        elif key == "N":
            if self._search_matches:
                self._search_prev()
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

    # --- Search ---

    def search(self, term: str):
        """Search all visible rows for term (case-insensitive)."""
        self._search_term = term
        self._search_matches = []
        self._search_index = -1
        term_lower = term.lower()

        for row_idx in range(self.row_count):
            row_key = self._row_locations.get_key(row_idx)
            if row_key is None:
                continue
            for col_key in self.columns:
                cell_value = str(self.get_cell(row_key, col_key))
                if term_lower in cell_value.lower():
                    self._search_matches.append(row_idx)
                    break

        if self._search_matches:
            self._search_index = 0
            self._move_to(self._search_matches[0])
        else:
            self.app.notify(f"Pattern not found: {term}", severity="warning")

        self._update_page_info()

    def _search_next(self):
        if not self._search_matches:
            return
        self._search_index += 1
        if self._search_index >= len(self._search_matches):
            self._search_index = 0
            self.app.notify("Search wrapped to top")
        self._move_to(self._search_matches[self._search_index])

    def _search_prev(self):
        if not self._search_matches:
            return
        self._search_index -= 1
        if self._search_index < 0:
            self._search_index = len(self._search_matches) - 1
            self.app.notify("Search wrapped to bottom")
        self._move_to(self._search_matches[self._search_index])

    def _clear_search(self):
        self._search_term = ""
        self._search_matches = []
        self._search_index = -1

    # --- Toggle reviewed ---

    def _toggle_row_at(self, row_index: int):
        """Toggle reviewed status on a specific row. Returns True if toggled."""
        if row_index < 0 or row_index >= self.row_count:
            return False
        row_key = self._row_locations.get_key(row_index)
        if row_key is None:
            return False

        key_value = row_key.value

        # Merge children are not independently reviewable
        if key_value in self._merge_child_rows:
            self.app.notify(
                "This transaction is part of a merge group — review the group instead",
                severity="warning",
            )
            return False

        # Merge header: toggle the parent and update its children visually
        if key_value in self._merge_header_rows:
            parent_id = int(key_value.replace(MERGE_HEADER_KEY_PREFIX, ""))
            session = self._session or self.app.db
            tx = queries.toggle_reviewed(session, parent_id)
            if tx is None:
                return False
            db.mark_dirty()
            reviewed = tx.reviewed_at is not None
            self._row_styles[key_value] = REVIEWED_BG if reviewed else UNREVIEWED_BG
            self.update_cell(row_key, "reviewed", "Yes" if reviewed else "No")
            # Update only this parent's child rows' reviewed text (keep gray style)
            from textual.widgets._data_table import RowKey
            for child_key_value, child_parent_id in self._merge_child_to_parent.items():
                if child_parent_id != parent_id:
                    continue
                try:
                    child_row_key = RowKey(child_key_value)
                    self.update_cell(child_row_key, "reviewed", "Yes" if reviewed else "No")
                except Exception:
                    pass
            self._clear_caches()
            self._total_unreviewed += -1 if reviewed else 1
            return True

        session = self._session or self.app.db
        tx = queries.toggle_reviewed(session, int(key_value))
        if tx is None:
            return False
        db.mark_dirty()
        self._row_styles[key_value] = REVIEWED_BG if tx.reviewed_at else UNREVIEWED_BG
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
        # Layered escape: clear merge pending first
        if self._merge_pending_tx_id is not None or self._merge_pending_parent_id is not None:
            self._clear_merge_pending()
            self._update_page_info()
            return
        self.app.action_focus_sidebar()

    # --- Merge ---

    def _clear_merge_pending(self):
        self._merge_pending_tx_id = None
        self._merge_pending_parent_id = None
        self._merge_pending_desc = ""

    def action_merge_transaction(self):
        if self.row_count == 0:
            return

        row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        key_value = row_key.value
        session = self._session or self.app.db

        # Case 1: cursor is on a merge header row
        if key_value in self._merge_header_rows:
            parent_id = int(key_value.replace(MERGE_HEADER_KEY_PREFIX, ""))
            parent = session.get(Transaction, parent_id)
            if parent is None:
                return
            # If there's a pending ungrouped tx, add it to this group
            if self._merge_pending_tx_id is not None:
                try:
                    queries.add_to_merge(session, parent_id, self._merge_pending_tx_id)
                    db.mark_dirty()
                    self.app.notify("Transaction added to merge group")
                except ValueError as e:
                    self.app.notify(str(e), severity="error")
                self._clear_merge_pending()
                self._load_transactions()
                return
            self._show_merge_action_screen(parent)
            return

        tx_id = int(key_value)
        tx = session.get(Transaction, tx_id)
        if tx is None:
            return

        # Case 2: transaction is already in a merge group
        if tx.merge_parent_id is not None:
            parent = session.get(Transaction, tx.merge_parent_id)
            if parent is None:
                return
            # If there's a pending ungrouped tx, add it to this group
            if self._merge_pending_tx_id is not None:
                try:
                    queries.add_to_merge(session, parent.id, self._merge_pending_tx_id)
                    db.mark_dirty()
                    self.app.notify("Transaction added to merge group")
                except ValueError as e:
                    self.app.notify(str(e), severity="error")
                self._clear_merge_pending()
                self._load_transactions()
                return
            self._show_merge_action_screen(parent, tx)
            return

        # Case 3: pending merge, same transaction → cancel
        if self._merge_pending_tx_id == tx_id:
            self._clear_merge_pending()
            self._update_page_info()
            return

        # Case 4: pending merge (add-to-group), different ungrouped tx
        if self._merge_pending_parent_id is not None:
            try:
                queries.add_to_merge(session, self._merge_pending_parent_id, tx_id)
                db.mark_dirty()
                self.app.notify("Transaction added to merge group")
            except ValueError as e:
                self.app.notify(str(e), severity="error")
            self._clear_merge_pending()
            self._load_transactions()
            return

        # Case 5: pending merge (new merge), different tx
        if self._merge_pending_tx_id is not None:
            pending_tx = session.get(Transaction, self._merge_pending_tx_id)
            if pending_tx is None:
                self._clear_merge_pending()
                return
            self._show_create_merge_screen(pending_tx, tx)
            return

        # Case 6: no pending → start pending
        self._merge_pending_tx_id = tx_id
        self._merge_pending_desc = tx.description
        self._update_page_info()

    def _show_create_merge_screen(self, tx1, tx2):
        session = self._session or self.app.db

        # Eager-load accounts
        from models.finance import Account
        acc1 = session.get(Account, tx1.account_id)
        acc2 = session.get(Account, tx2.account_id)

        def handle_merge(name: str | None):
            if name is None:
                self._clear_merge_pending()
                self._update_page_info()
                return
            try:
                queries.create_merge(session, [tx1.id, tx2.id], name)
                db.mark_dirty()
                self.app.notify(f"Created merge group: {name}")
            except ValueError as e:
                self.app.notify(str(e), severity="error")
            self._clear_merge_pending()
            self._load_transactions()

        self.app.push_screen(
            MergeTransactionScreen(tx1, tx2, acc1, acc2), handle_merge
        )

    def _show_merge_action_screen(self, parent, child_tx=None):
        def handle_action(result: str | None):
            if result is None:
                return
            session = self._session or self.app.db

            if result == "add":
                self._merge_pending_parent_id = parent.id
                self._merge_pending_desc = parent.description
                self._update_page_info()
                return

            if result == "remove" and child_tx is not None:
                dissolved_name = queries.remove_from_merge(session, child_tx.id)
                db.mark_dirty()
                if dissolved_name:
                    self.app.notify(
                        f"Group '{dissolved_name}' dissolved — only one transaction remained"
                    )
                else:
                    self.app.notify("Transaction removed from merge group")
                self._load_transactions()
                return

            if result.startswith("rename:"):
                new_name = result[7:]
                try:
                    queries.rename_merge(session, parent.id, new_name)
                    db.mark_dirty()
                    self.app.notify(f"Group renamed to: {new_name}")
                except ValueError as e:
                    self.app.notify(str(e), severity="error")
                self._load_transactions()
                return

        self.app.push_screen(
            MergeActionScreen(parent, show_remove=(child_tx is not None)), handle_action
        )

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

        # Can't split merge headers
        if row_key.value in self._merge_header_rows:
            return

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
