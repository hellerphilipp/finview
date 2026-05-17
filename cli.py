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

COLOR_PALETTE = {
    "red":    "\033[91m",
    "orange": "\033[38;5;208m",
    "yellow": "\033[93m",
    "green":  "\033[92m",
    "teal":   "\033[96m",
    "blue":   "\033[94m",
    "purple": "\033[95m",
    "pink":   "\033[38;5;213m",
    "gray":   "\033[90m",
}
# prompt_toolkit style strings for questionary Choice titles (list-of-tuples FormattedText)
_COLOR_PT_STYLES = {
    "red":    "fg:ansibrightred",
    "orange": "fg:#ff8700",
    "yellow": "fg:ansibrightyellow",
    "green":  "fg:ansibrightgreen",
    "teal":   "fg:ansibrightcyan",
    "blue":   "fg:ansibrightblue",
    "purple": "fg:ansibrightmagenta",
    "pink":   "fg:#ff87ff",
    "gray":   "fg:ansibrightblack",
}
_ANSI_RESET = "\033[0m"
_NO_COLOR_SENTINEL = "__no_color__"


def run(session_factory):
    """Main interactive loop."""
    while True:
        _print_accounts_table(session_factory)

        choices = [
            questionary.Choice("Manage Accounts", value="accounts", shortcut_key="m"),
            questionary.Choice("Manage Categories", value="categories", shortcut_key="c"),
            questionary.Choice("Import Transactions", value="import", shortcut_key="i"),
            questionary.Choice("Open in Excel", value="excel", shortcut_key="o"),
        ]
        if db.db_file_path and db.is_dirty():
            choices.append(questionary.Choice("Save", value="save", shortcut_key="s"))
        choices.append(questionary.Choice("Quit", value="quit", shortcut_key="q"))

        choice = questionary.select("FinView — What would you like to do?", choices=choices, use_shortcuts=True).ask()

        if choice is None or choice == "quit":
            _handle_quit()
            break
        elif choice == "accounts":
            _accounts_menu(session_factory)
        elif choice == "categories":
            _categories_menu(session_factory)
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
                questionary.Choice("Create account", value="create", shortcut_key="c"),
                questionary.Choice("Edit account", value="edit", shortcut_key="e"),
                questionary.Choice("Back", value="back", shortcut_key="b"),
            ],
            use_shortcuts=True,
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
                questionary.Choice("Import edits", value="import", shortcut_key="i"),
                questionary.Choice("Go back (discard edits)", value="back", shortcut_key="b"),
            ],
            use_shortcuts=True,
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


# --- Categories sub-menu ---


def _pick_color(prompt: str = "Choose color:", include_none: bool = False):
    """Show a color picker.

    Returns a color name string, None (if 'no color' selected), or False (cancelled).
    """
    choices = [
        questionary.Choice(title=[(_COLOR_PT_STYLES[name], f"● {name}")], value=name)
        for name in COLOR_PALETTE
    ]
    if include_none:
        choices.append(questionary.Choice("No color", value=_NO_COLOR_SENTINEL))

    result = questionary.select(prompt, choices=choices).ask()
    if result is None:
        return False
    if result == _NO_COLOR_SENTINEL:
        return None
    return result


def _render_category_tree(rows: list) -> str:
    """Render a nested Unicode tree from get_categories_with_transaction_counts() rows."""
    from collections import defaultdict

    children_map = defaultdict(list)
    cat_count = {}
    all_cats = {}

    for cat, count, _ in rows:
        children_map[cat.parent_id].append(cat)
        cat_count[cat.id] = count
        all_cats[cat.id] = cat

    lines = []

    def _color_indicator(cat):
        if cat.color and cat.color in COLOR_PALETTE:
            return f" {COLOR_PALETTE[cat.color]}●{_ANSI_RESET}"
        return ""

    def _tx_label(count):
        return f"({count} transaction{'s' if count != 1 else ''})"

    def _render_node(cat_id: int, prefix: str, is_last: bool):
        cat = all_cats[cat_id]
        count = cat_count[cat_id]
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{cat.name}{_color_indicator(cat)} {_tx_label(count)}")
        child_prefix = prefix + ("    " if is_last else "│   ")
        children = sorted(children_map.get(cat.id, []), key=lambda c: c.name.lower())
        for i, child in enumerate(children):
            _render_node(child.id, child_prefix, i == len(children) - 1)

    roots = sorted(children_map.get(None, []), key=lambda c: c.name.lower())
    for i, root in enumerate(roots):
        count = cat_count[root.id]
        lines.append(f"{root.name}{_color_indicator(root)} {_tx_label(count)}")
        children = sorted(children_map.get(root.id, []), key=lambda c: c.name.lower())
        for j, child in enumerate(children):
            _render_node(child.id, "", j == len(children) - 1)

    return "\n".join(lines)


def _categories_menu(session_factory):
    while True:
        choice = questionary.select(
            "Categories",
            choices=[
                questionary.Choice("List", value="list", shortcut_key="l"),
                questionary.Choice("Create", value="create", shortcut_key="c"),
                questionary.Choice("Rename / Move", value="move", shortcut_key="r"),
                questionary.Choice("Change Color", value="color", shortcut_key="o"),
                questionary.Choice("Delete", value="delete", shortcut_key="d"),
                questionary.Choice("Back", value="back", shortcut_key="b"),
            ],
            use_shortcuts=True,
        ).ask()

        if choice is None or choice == "back":
            return
        elif choice == "list":
            _list_categories(session_factory)
        elif choice == "create":
            _create_category_cli(session_factory)
        elif choice == "move":
            _move_category_cli(session_factory)
        elif choice == "color":
            _change_color_cli(session_factory)
        elif choice == "delete":
            _delete_category_cli(session_factory)


def _list_categories(session_factory):
    with session_factory() as session:
        rows = queries.get_categories_with_transaction_counts(session)
        if not rows:
            print("  No categories yet.")
            return
        tree = _render_category_tree(rows)

    print()
    for line in tree.split("\n"):
        print(f"  {line}")
    print()


def _create_category_cli(session_factory):
    path = questionary.text(
        "Category path (use / for hierarchy, e.g. food/groceries):"
    ).ask()
    if not path or not path.strip():
        return

    color_result = _pick_color("Choose a color (optional):", include_none=True)
    if color_result is False:
        return

    with session_factory() as session:
        try:
            cat = queries.create_category(session, path.strip(), color=color_result)
            db.mark_dirty()
            color_note = f" [{cat.color}]" if cat.color else ""
            print(f"  Created '{cat.full_path}'{color_note}.")
        except ValueError as e:
            print(f"  Error: {e}")


def _move_category_cli(session_factory):
    with session_factory() as session:
        rows = queries.get_categories_with_transaction_counts(session)

    if not rows:
        print("  No categories to edit.")
        return

    cat_choice = questionary.select(
        "Select category to rename / move:",
        choices=[
            questionary.Choice(f"{path}  ({count} txns)", value=cat.id)
            for cat, count, path in rows
        ],
    ).ask()
    if cat_choice is None:
        return

    current_path = next(path for cat, _, path in rows if cat.id == cat_choice)
    new_path = questionary.text("New full path:", default=current_path).ask()
    if new_path is None or not new_path.strip():
        return

    with session_factory() as session:
        try:
            cat = queries.move_category(session, cat_choice, new_path.strip())
            db.mark_dirty()
            print(f"  Moved to '{cat.full_path}'.")
        except ValueError as e:
            print(f"  Error: {e}")


def _change_color_cli(session_factory):
    with session_factory() as session:
        rows = queries.get_categories_with_transaction_counts(session)

    if not rows:
        print("  No categories.")
        return

    cat_choice = questionary.select(
        "Select category:",
        choices=[
            questionary.Choice(f"{path}  [{cat.color or 'no color'}]", value=cat.id)
            for cat, count, path in rows
        ],
    ).ask()
    if cat_choice is None:
        return

    color_result = _pick_color("Choose new color:", include_none=True)
    if color_result is False:
        return

    with session_factory() as session:
        try:
            cat = queries.update_category_color(session, cat_choice, color_result)
            db.mark_dirty()
            note = f"[{cat.color}]" if cat.color else "no color"
            print(f"  Updated '{cat.full_path}' to {note}.")
        except ValueError as e:
            print(f"  Error: {e}")


def _delete_category_cli(session_factory):
    with session_factory() as session:
        rows = queries.get_categories_with_transaction_counts(session)

    if not rows:
        print("  No categories to delete.")
        return

    cat_choice = questionary.select(
        "Select category to delete:",
        choices=[
            questionary.Choice(f"{path}  ({count} txns)", value=cat.id)
            for cat, count, path in rows
        ],
    ).ask()
    if cat_choice is None:
        return

    current_path = next(path for cat, _, path in rows if cat.id == cat_choice)

    with session_factory() as session:
        desc_count, tx_count = queries.get_category_delete_stats(session, cat_choice)

    warnings = []
    if desc_count > 0:
        warnings.append(
            f"{desc_count} subcategor{'ies' if desc_count != 1 else 'y'} will also be deleted"
        )
    if tx_count > 0:
        warnings.append(
            f"{tx_count} transaction{'s' if tx_count != 1 else ''} will be un-categorized"
        )
    if warnings:
        print(f"  Warning: {'; '.join(warnings)}.")

    confirmed = questionary.confirm(
        f"Delete '{current_path}'?",
        default=False,
    ).ask()
    if not confirmed:
        print("  Cancelled.")
        return

    with session_factory() as session:
        try:
            queries.delete_category(session, cat_choice)
            db.mark_dirty()
            print(f"  Deleted '{current_path}'.")
        except ValueError as e:
            print(f"  Error: {e}")
