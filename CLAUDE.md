# CLAUDE.md

## Project Overview

FinView is a local-first, terminal-based personal finance TUI built with Python and Textual. It lets users manage multiple bank accounts, import transactions from CSV files via declarative YAML+CEL mapping specs, review transactions, and track balances — all from the terminal with no cloud dependencies. Data is stored in a local SQLite database (`db.finview`).

## Architecture

The codebase is organized into layers, though currently the UI accesses the database directly via SQLAlchemy (a repository/services layer is a future goal):

* **Domain Models (`models/`)**: Pure SQLAlchemy data structures and enums. No UI logic.
* **Importers (`importers/`)**: CEL-based CSV parsing engine and Pydantic schema validation for YAML specs.
* **Presentation Layer (`ui/`)**: Textual app, modal screens, and widgets. Currently queries the DB directly.

## Project Structure

```
main.py              # Entry point (minimal — just starts FinViewApp)
db.py                # Session/Engine config (SQLite at ./db.finview)
models/
  base.py            # Declarative base & naming conventions
  finance.py         # Account, Transaction, Currency enum
importers/
  engine.py          # CSVImporter: loads YAML spec, parses CSV rows via CEL
  schema.py          # Pydantic models: ImporterMapping, DataMapping, ParserConfig
  Swisscard/         # Example bank-specific YAML spec
ui/
  app.py             # FinViewApp: layout, keybindings, account/import logic
  app.tcss           # Textual CSS styling
  screens.py         # Modal screens: CreateAccountScreen, ImportFileDialog
  widgets.py         # TransactionTable, AccountItem, AllAccountsItem
alembic/             # Migrations (render_as_batch=True for SQLite)
```

## Tech Stack

* **Python 3.11+** (Type hinting via `Mapped[T]` and `Annotated`)
* **Textual**: TUI Framework
* **SQLAlchemy 2.0**: ORM (SQLite backend, `db.finview`)
* **Alembic**: Migrations (using `render_as_batch=True` for SQLite)
* **CEL (Common Expression Language)**: Declarative CSV field mapping in YAML specs
* **Pydantic**: Validation for YAML importer specs

## Key Bindings

* `q` — Quit
* `r` — Refresh data (reload accounts and transactions)
* `c` — Create new account (opens modal)
* `i` — Import CSV (in transaction table, requires account with mapping spec)
* `a` — Toggle reviewed status on selected transaction
* `n` / `p` — Next / previous page in transaction table
* `Escape` — Return focus to sidebar

## Commands

```bash
# Environment Setup: Work in the .venv!

# Run App
python main.py

# Database Management
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Key Conventions

* **SQLite Compatibility**: Always use `batch_op` in Alembic migrations to handle SQLite's limited `ALTER TABLE` support. Use non-native enums (VARCHAR storage).
* **Importers**: Bank-specific logic lives in YAML files under `importers/` using CEL expressions; avoid hardcoding bank logic in Python. New importers are auto-discovered.
* **Formatting**: Use `black` for formatting and `isort` for imports.
* **DataTable Keys**: Always pass explicit `key=` to `add_row()` and `add_column()` to get stable, value-based keys (see MEMORY.md for details).
* **Session Management**: The app uses a long-lived SQLAlchemy session opened on mount. Use eager loading (`selectinload`) to avoid `LazyInitializationError`.
* **Dynamic Widget Mounting**: When building composite widgets dynamically (after initial compose), pass children to the constructor (e.g. `Horizontal(child1, child2)`) instead of using `compose_add_child()`, which only works during the compose phase. When querying children of a dynamically mounted widget, guard with try/except since children may not be in the DOM yet.
* **App-Level Event Handlers + Modals**: `on_key` and other app-level handlers fire even when a modal screen is active, but `query_one()` for main-screen widgets will raise `NoMatches` because modals have their own DOM. Always guard such queries with `try/except`.
* **Dock Layering**: A `dock: left` sidebar spans the full height and covers `dock: bottom` widgets. For full-width elements (like a command input) between main content and Footer, use normal flow positioning instead of `dock: bottom`.
