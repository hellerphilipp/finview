# FinView — personal finance manager
# Copyright (C) 2026 Philipp Heller
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

import questionary

import db
import excel_export
import queries
import services
from models.finance import Account, Currency


def run(session_factory):
    """Main interactive loop."""
    while True:
        _print_accounts_table(session_factory)

        choices = [
            questionary.Choice("Manage Accounts", value="accounts"),
            questionary.Choice("Import Transactions", value="import"),
            questionary.Choice("Open in Excel", value="excel"),
        ]
        if db.db_file_path:
            choices.append(questionary.Choice("Save", value="save"))
        choices.append(questionary.Choice("Quit", value="quit"))

        choice = questionary.select("FinView — What would you like to do?", choices=choices).ask()

        if choice is None or choice == "quit":
            _handle_quit()
            break
        elif choice == "accounts":
            _accounts_menu(session_factory)
        elif choice == "import":
            _import_menu(session_factory)
        elif choice == "excel":
            _open_in_excel(session_factory)
        elif choice == "save":
            _save()


def _handle_quit():
    if not db.is_dirty():
        return

    if db.db_file_path:
        save = questionary.confirm(
            "You have unsaved changes. Save before quitting?", default=True
        ).ask()
        if save:
            db.save_to_file()
            print(f"Saved to {db.db_file_path}")
    else:
        path = questionary.text("Save database to (leave empty to discard):").ask()
        if path and path.strip():
            db.save_to_file(os.path.expanduser(path.strip()))
            print(f"Saved to {path.strip()}")


def _save():
    if db.db_file_path:
        db.save_to_file()
        print(f"Saved to {db.db_file_path}")
    else:
        path = questionary.text("Save database to:").ask()
        if path and path.strip():
            db.save_to_file(os.path.expanduser(path.strip()))
            print(f"Saved to {path.strip()}")


# --- Accounts sub-menu ---


def _accounts_menu(session_factory):
    while True:
        choice = questionary.select(
            "Accounts",
            choices=[
                questionary.Choice("Create account", value="create"),
                questionary.Choice("Edit account", value="edit"),
                questionary.Choice("Back", value="back"),
            ],
        ).ask()

        if choice is None or choice == "back":
            return
        elif choice == "create":
            _create_account(session_factory)
        elif choice == "edit":
            _edit_account(session_factory)


def _print_accounts_table(session_factory):
    with session_factory() as session:
        accounts = queries.get_all_accounts_with_balances(session)
        if not accounts:
            print("  No accounts yet.")
            return

        rows = []
        for acc, balance in accounts:
            latest = services.get_latest_transaction_date(session, acc.id)
            rows.append(
                (
                    acc.name,
                    acc.currency.value,
                    f"{balance:,.2f}",
                    latest.strftime("%Y-%m-%d %H:%M") if latest else "-",
                    acc.mapping_spec or "(no schema)",
                )
            )

    headers = ("Name", "Currency", "Balance", "Latest Txn", "Schema")
    col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    header_line = "  ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "  ".join("-" * w for w in col_widths)

    print()
    print(f"  {header_line}")
    print(f"  {separator}")
    for row in rows:
        line = "  ".join(row[i].rjust(col_widths[i]) if i == 2 else row[i].ljust(col_widths[i]) for i in range(len(headers)))
        print(f"  {line}")
    print()


def _create_account(session_factory):
    name = questionary.text("Account name:").ask()
    if not name or not name.strip():
        return

    currency = questionary.select(
        "Currency:",
        choices=[c.value for c in Currency],
    ).ask()
    if currency is None:
        return

    mapping_specs = services.discover_mapping_specs()
    spec_choice = questionary.select(
        "Import schema:",
        choices=[questionary.Choice(display, value=path) for display, path in mapping_specs],
    ).ask()

    initial_balance = questionary.text("Initial balance:", default="0.00").ask()
    if initial_balance is None:
        return

    try:
        amount = Decimal(initial_balance)
    except InvalidOperation:
        print(f"  Invalid number: {initial_balance}")
        return

    with session_factory() as session:
        services.create_account(
            session,
            name=name.strip(),
            currency=Currency(currency),
            mapping_spec=spec_choice,
            initial_amount=amount,
            initial_date=datetime.now(),
        )
    print(f"  Created account '{name.strip()}'.")


def _edit_account(session_factory):
    with session_factory() as session:
        accounts = queries.get_all_accounts_with_balances(session)

    if not accounts:
        print("  No accounts to edit.")
        return

    acc_choice = questionary.select(
        "Select account to edit:",
        choices=[
            questionary.Choice(f"{acc.name} ({acc.currency.value})", value=acc.id)
            for acc, _ in accounts
        ],
    ).ask()
    if acc_choice is None:
        return

    with session_factory() as session:
        account = session.get(Account, acc_choice)

        new_name = questionary.text("Name:", default=account.name).ask()
        if new_name is None:
            return

        new_currency = questionary.select(
            "Currency:",
            choices=[c.value for c in Currency],
            default=account.currency.value,
        ).ask()
        if new_currency is None:
            return

        mapping_specs = services.discover_mapping_specs()
        current_display = None
        for display, path in mapping_specs:
            if path == account.mapping_spec:
                current_display = display
                break

        new_spec = questionary.select(
            "Import schema:",
            choices=[questionary.Choice(display, value=path) for display, path in mapping_specs],
            default=current_display or mapping_specs[0][0],
        ).ask()

        account.name = new_name.strip()
        account.currency = Currency(new_currency)
        account.mapping_spec = new_spec
        session.commit()
        db.mark_dirty()

    print("  Account updated.")


# --- Excel export ---


def _open_in_excel(session_factory):
    path = excel_export.export_to_excel(session_factory)
    print(f"  Opened {path}")
    print("  Edit the file in Excel, then choose an action below.")

    while True:
        choice = questionary.select(
            "Excel",
            choices=[
                questionary.Choice("Import edits", value="import"),
                questionary.Choice("Go back (discard edits)", value="back"),
            ],
        ).ask()

        if choice is None or choice == "back":
            return

        if choice == "import":
            _do_excel_import(session_factory)
            return


def _do_excel_import(session_factory):
    try:
        cats, reviewed, unreviewed = excel_export.import_from_excel(session_factory)
    except FileNotFoundError as e:
        print(f"  Import failed: {e}")
        return
    print(
        f"  Updated categories for {cats} transaction(s). "
        f"Marked {reviewed} as reviewed, {unreviewed} as unreviewed."
    )


# --- Import sub-menu ---


def _import_menu(session_factory):
    with session_factory() as session:
        accounts = queries.get_all_accounts_with_balances(session)

    if not accounts:
        print("  No accounts. Create one first.")
        return

    acc_choice = questionary.select(
        "Import into which account?",
        choices=[
            questionary.Choice(f"{acc.name} ({acc.currency.value})", value=acc.id)
            for acc, _ in accounts
        ],
    ).ask()
    if acc_choice is None:
        return

    csv_path = questionary.path("Path to CSV file:").ask()
    if not csv_path or not csv_path.strip():
        return

    csv_path = os.path.expanduser(csv_path.strip())
    if not os.path.exists(csv_path):
        print(f"  File not found: {csv_path}")
        return

    with session_factory() as session:
        account = session.get(Account, acc_choice)
        if not account.mapping_spec:
            print("  This account has no import schema configured. Edit the account first.")
            return

        try:
            count = queries.import_csv_transactions(session, csv_path, account)
            db.mark_dirty()
            print(f"  Imported {count} transactions.")
        except (ValueError, FileNotFoundError) as e:
            print(f"  Import error: {e}")
