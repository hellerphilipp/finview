import os
import yaml
from decimal import Decimal
from pydantic import ValidationError
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, Input, Button, Select, Static
from textual.containers import Vertical, Horizontal, VerticalScroll
from datetime import datetime
from models.finance import Account, Currency, Transaction
from importers.schema import ImporterMapping

class CreateAccountScreen(ModalScreen[dict]):
    """
    A Modal Screen to create a new account.
    Returns a dictionary with the form data or None if cancelled.
    """
    def get_mapping_options(self) -> list[tuple[str, str | None]]:
        """Scans ./importers, validates YAMLs, and returns list of (Display Name, Path)."""
        base_path = "./importers"
        options = [("No Mapping / Manual", None)]
        
        if not os.path.exists(base_path):
            return options

        for root, _, files in os.walk(base_path):
            for f in files:
                if f.endswith((".yaml", ".yml")):
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, base_path)
                    
                    try:
                        with open(full_path, "r") as stream:
                            config_data = yaml.safe_load(stream)
                            # Validate using Pydantic
                            mapping = ImporterMapping(**config_data)
                            
                            # Success: Use the 'name' from YAML for the display
                            display_name = f"{mapping.name} ({rel_path})"
                            options.append((display_name, rel_path))
                    except (yaml.YAMLError, ValidationError, TypeError):
                        # Skip invalid files silently or log them
                        continue
        return options

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Create New Account", id="title")
            
            yield Label("Account Name:")
            yield Input(placeholder="e.g. Personal Checking", id="name")
            
            yield Label("Currency:")
            yield Select([(c.value, c) for c in Currency], id="currency")
            
            yield Label("Import Mapping Spec:")
            yield Select(self.get_mapping_options(), id="mapping_spec", value=None)
            
            yield Label("Starting Amount:")
            yield Input(placeholder="0.00", id="amount", type="number")
            
            yield Label("Date (YYYY-MM-DD HH:MM:SS):")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            yield Input(value=now_str, id="date")
            
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Create", variant="primary", id="submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "submit":
            # Basic validation
            if not self.query_one("#name").value:
                self.notify("Name is required", severity="error")
                return
                
            self.dismiss({
                "name": self.query_one("#name").value,
                "currency": self.query_one("#currency").value,
                "mapping_spec": self.query_one("#mapping_spec").value,
                "amount": float(self.query_one("#amount").value or 0),
                "date": datetime.strptime(self.query_one("#date").value, "%Y-%m-%d %H:%M:%S")
            })

class MigrationPromptScreen(ModalScreen[bool]):
    """Modal asking whether to apply pending database migrations."""

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Pending database migrations detected.")
            yield Label("Apply migrations now? (Required to use this database)")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Apply", variant="warning", id="apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "apply")


class ImportFileDialog(ModalScreen[str]):
    """A simple modal to input a file path."""
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Enter absolute path to CSV file:")
            yield Input(placeholder="/path/to/transactions.csv", id="file_path")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Import", variant="primary", id="submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self.dismiss(self.query_one("#file_path").value)
        else:
            self.dismiss(None)


class SplitTransactionScreen(ModalScreen[list | None]):
    """Modal for splitting a transaction into multiple child transactions.

    Returns a list of dicts with keys: id (int|None), description (str), amount (float).
    Returns empty list to unsplit. Returns None on cancel.
    """

    CSS = """
    SplitTransactionScreen {
        align: center middle;
    }

    #split-dialog {
        padding: 1 2;
        width: 75;
        max-height: 80%;
        border: thick $background 80%;
        background: $surface;
    }

    #split-header {
        margin-bottom: 1;
    }

    #split-header Label {
        margin-bottom: 0;
    }

    #split-rows {
        max-height: 40;
        min-height: 5;
    }

    .split-row {
        height: 3;
        margin-bottom: 1;
    }

    .split-row Input {
        margin: 0 1 0 0;
    }

    .split-desc {
        width: 2fr;
    }

    .split-amount {
        width: 1fr;
    }

    .split-delete {
        width: 5;
        min-width: 5;
    }

    #unallocated-label {
        margin-top: 1;
        text-style: bold;
    }

    #split-buttons {
        width: 100%;
        padding-top: 1;
        align: center middle;
    }

    #split-buttons Button {
        margin: 0 2;
    }

    #add-row-btn {
        margin-top: 1;
    }
    """

    def __init__(
        self,
        transaction: Transaction,
        existing_children: list[Transaction] | None = None,
    ):
        super().__init__()
        self._transaction = transaction
        self._existing_children = existing_children or []
        self._row_counter = 0
        self._row_child_ids: dict[str, int | None] = {}

    def compose(self) -> ComposeResult:
        tx = self._transaction
        with Vertical(id="split-dialog"):
            with Vertical(id="split-header"):
                yield Label(f"Split Transaction", id="split-title")
                yield Label(
                    f"Date: {tx.date.strftime('%Y-%m-%d %H:%M')}  |  "
                    f"{tx.description}  |  "
                    f"{tx.original_value:.2f} {tx.original_currency.value}"
                )

            rows_container = VerticalScroll(id="split-rows")
            with rows_container:
                if self._existing_children:
                    for child in self._existing_children:
                        yield self._make_row(
                            child_id=child.id,
                            description=child.description,
                            amount=f"{child.original_value:.2f}",
                        )
                else:
                    yield self._make_row()
                    yield self._make_row()

            yield Button("+ Add Row", id="add-row-btn", variant="default")
            yield Label("", id="unallocated-label")

            with Horizontal(id="split-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save", disabled=True)

    def _make_row(
        self,
        child_id: int | None = None,
        description: str = "",
        amount: str = "",
    ) -> Horizontal:
        self._row_counter += 1
        idx = self._row_counter
        desc_input = Input(
            placeholder="Description",
            value=description,
            id=f"split-desc-{idx}",
            classes="split-desc",
        )
        amount_input = Input(
            placeholder="0.00",
            value=amount,
            id=f"split-amount-{idx}",
            classes="split-amount",
            type="number",
        )
        delete_btn = Button("X", id=f"split-del-{idx}", classes="split-delete", variant="error")
        row = Horizontal(desc_input, amount_input, delete_btn, classes="split-row", id=f"split-row-{idx}")
        self._row_child_ids[f"split-row-{idx}"] = child_id
        return row

    def on_mount(self) -> None:
        self._update_unallocated()

    def on_input_changed(self, event: Input.Changed) -> None:
        if "split-amount" in (event.input.id or ""):
            self._update_unallocated()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id == "cancel":
            self.dismiss(None)
            return

        if btn_id == "save":
            self.dismiss(self._collect_splits())
            return

        if btn_id == "add-row-btn":
            container = self.query_one("#split-rows", VerticalScroll)
            new_row = self._make_row()
            container.mount(new_row)
            self.call_later(self._update_unallocated)
            return

        if btn_id.startswith("split-del-"):
            row_idx = btn_id.replace("split-del-", "")
            try:
                row = self.query_one(f"#split-row-{row_idx}", Horizontal)
                row.remove()
                self.call_later(self._update_unallocated)
            except Exception:
                pass

    def _update_unallocated(self) -> None:
        total = Decimal(str(self._transaction.original_value))
        allocated = Decimal("0")
        rows = self.query(".split-row")

        for row in rows:
            try:
                amount_input = row.query_one(".split-amount", Input)
            except Exception:
                continue
            try:
                allocated += Decimal(amount_input.value or "0")
            except Exception:
                pass

        unallocated = total - allocated
        label = self.query_one("#unallocated-label", Label)
        label.update(
            f"Unallocated: {unallocated:.2f} {self._transaction.original_currency.value}"
        )

        save_btn = self.query_one("#save", Button)
        row_count = len(rows)
        # Enable save when fully allocated OR when all rows deleted (unsplit)
        save_btn.disabled = not (abs(unallocated) < Decimal("0.005") or row_count == 0)

    def _collect_splits(self) -> list[dict]:
        result = []
        for row in self.query(".split-row"):
            desc_input = row.query_one(".split-desc", Input)
            amount_input = row.query_one(".split-amount", Input)
            try:
                amount = float(amount_input.value or "0")
            except ValueError:
                amount = 0.0
            result.append({
                "id": self._row_child_ids.get(row.id),
                "description": desc_input.value,
                "amount": amount,
            })
        return result


class MergeTransactionScreen(ModalScreen[str | None]):
    """Modal for creating a new merge group from two transactions.

    Shows both transactions' summaries and an input for the group name.
    Returns the group name string or None on cancel.
    """

    CSS = """
    MergeTransactionScreen {
        align: center middle;
    }

    #merge-dialog {
        padding: 1 2;
        width: 75;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }

    #merge-dialog Label {
        margin-bottom: 1;
    }

    .merge-tx-summary {
        margin-bottom: 1;
        padding: 0 1;
    }

    #merge-buttons {
        width: 100%;
        padding-top: 1;
        align: center middle;
    }

    #merge-buttons Button {
        margin: 0 2;
    }
    """

    def __init__(
        self,
        tx1: Transaction,
        tx2: Transaction,
        acc1: Account | None = None,
        acc2: Account | None = None,
    ):
        super().__init__()
        self._tx1 = tx1
        self._tx2 = tx2
        self._acc1 = acc1
        self._acc2 = acc2

    def compose(self) -> ComposeResult:
        with Vertical(id="merge-dialog"):
            yield Label("Merge Transactions")

            yield Label(self._tx_summary(self._tx1, self._acc1), classes="merge-tx-summary")
            yield Label(self._tx_summary(self._tx2, self._acc2), classes="merge-tx-summary")

            yield Label("Group name:")
            default_name = f"{self._tx1.description} + {self._tx2.description}"
            yield Input(value=default_name, id="merge-name")

            with Horizontal(id="merge-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Merge", variant="primary", id="merge")

    def _tx_summary(self, tx: Transaction, acc: Account | None) -> str:
        acc_name = acc.name if acc else "?"
        return (
            f"{tx.date.strftime('%Y-%m-%d %H:%M')}  |  "
            f"{acc_name}  |  "
            f"{tx.description}  |  "
            f"{tx.original_value:.2f} {tx.original_currency.value}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "merge":
            name = self.query_one("#merge-name", Input).value.strip()
            if not name:
                self.notify("Group name is required", severity="error")
                return
            self.dismiss(name)


class MergeActionScreen(ModalScreen[str | None]):
    """Mini-modal for managing an existing merge group.

    Shows three options: Add to group, Remove from group, Rename.
    Returns "add", "remove", "rename:<new_name>", or None on cancel.
    """

    CSS = """
    MergeActionScreen {
        align: center middle;
    }

    #merge-action-dialog {
        padding: 1 2;
        width: 50;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }

    #merge-action-dialog Label {
        margin-bottom: 1;
    }

    #merge-action-buttons {
        width: 100%;
        padding-top: 1;
        align: center middle;
    }

    #merge-action-buttons Button {
        margin: 0 1;
    }

    #rename-row {
        display: none;
        height: 3;
        margin-top: 1;
    }

    #rename-row.visible {
        display: block;
    }
    """

    def __init__(self, merge_parent: Transaction, show_remove: bool = True):
        super().__init__()
        self._merge_parent = merge_parent
        self._show_remove = show_remove

    def compose(self) -> ComposeResult:
        with Vertical(id="merge-action-dialog"):
            yield Label(f"Merge Group: {self._merge_parent.description}")

            with Horizontal(id="merge-action-buttons"):
                yield Button("Add to group", id="add", variant="primary")
                if self._show_remove:
                    yield Button("Remove from group", id="remove", variant="error")
                yield Button("Rename", id="rename-btn", variant="default")
                yield Button("Cancel", id="cancel")

            with Horizontal(id="rename-row"):
                yield Input(
                    value=self._merge_parent.description,
                    id="rename-input",
                    placeholder="New group name",
                )
                yield Button("Save", id="rename-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id == "cancel":
            self.dismiss(None)
        elif btn_id == "add":
            self.dismiss("add")
        elif btn_id == "remove":
            self.dismiss("remove")
        elif btn_id == "rename-btn":
            rename_row = self.query_one("#rename-row", Horizontal)
            rename_row.add_class("visible")
            self.query_one("#rename-input", Input).focus()
        elif btn_id == "rename-save":
            new_name = self.query_one("#rename-input", Input).value.strip()
            if not new_name:
                self.notify("Name cannot be empty", severity="error")
                return
            self.dismiss(f"rename:{new_name}")