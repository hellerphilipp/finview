from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, Input, Button, Select
from textual.containers import Vertical, Horizontal
from datetime import datetime
from models.finance import Currency

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

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Create New Account", id="title")
            
            yield Label("Account Name:")
            yield Input(placeholder="e.g., Main Checking", id="name")
            
            yield Label("Currency:")
            # Convert Enum to list of (label, value)
            currencies = [(c.value, c) for c in Currency]
            yield Select(currencies, prompt="Select Currency", id="currency")
            
            yield Label("Starting Amount:")
            yield Input(placeholder="0.00", type="number", id="amount")
            
            yield Label("Date (YYYY-MM-DD HH:MM:SS):")
            # Pre-fill with current time
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            yield Input(value=now_str, id="date")
            
            with Horizontal(classes="buttons"):
                yield Button("Cancel", variant="default", id="cancel")
                yield Button("Create", variant="primary", id="submit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        
        elif event.button.id == "submit":
            # Validation
            name = self.query_one("#name", Input).value
            currency = self.query_one("#currency", Select).value
            amount_str = self.query_one("#amount", Input).value
            date_str = self.query_one("#date", Input).value
            
            if not name or currency is Select.BLANK:
                self.notify("Name and Currency are required", severity="error")
                return

            try:
                amount = float(amount_str) if amount_str else 0.0
                date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                
                result = {
                    "name": name,
                    "currency": currency,
                    "amount": amount,
                    "date": date_obj
                }
                self.dismiss(result)
                
            except ValueError:
                self.notify("Invalid Amount or Date format", severity="error")