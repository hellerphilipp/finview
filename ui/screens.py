import os
import yaml
from pydantic import ValidationError
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, Input, Button, Select
from textual.containers import Vertical, Horizontal
from datetime import datetime
from models.finance import Currency
from importers.schema import ImporterMapping

class CreateAccountScreen(ModalScreen[dict]):
    """
    A Modal Screen to create a new account.
    Returns a dictionary with the form data or None if cancelled.
    """
    
    CSS = """
    CreateAccountScreen {
        align: center middle;
    }

    #dialog {
        padding: 0 1;
        width: 60;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }
    
    #dialog Label {
        margin-top: 1;
        margin-bottom: 1;
    }
    
    .buttons {
        width: 100%;
        padding-top: 2;
        align: center middle;
    }
    
    Button {
        margin: 0 2;
    }
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

class ImportFileDialog(ModalScreen[str]):
    """A simple modal to input a file path."""
    CSS = """
    ImportFileDialog { align: center middle; }
    #dialog { width: 60; height: auto; background: $surface; border: thick $primary; padding: 1; }
    """
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