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
queries.py           # Query functions: accounts, categories, transactions, merges
models/
  base.py            # Declarative base & naming conventions
  finance.py         # Account, Transaction, Category, Currency enum
importers/
  engine.py          # CSVImporter: loads YAML spec, parses CSV rows via CEL
  schema.py          # Pydantic models: ImporterMapping, DataMapping, ParserConfig
  Swisscard/         # Example bank-specific YAML spec
ui/
  app.py             # FinViewApp: layout, keybindings, account/category/import logic
  app.tcss           # Textual CSS styling
  screens.py         # Modal screens: account, category, split, merge, import
  widgets.py         # Sidebar sections, TransactionTable, CategoryAutocomplete
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

**Sidebar Navigation**:
* `Tab` — Switch between Accounts ↔ Categories sidebar sections (auto-collapse)
* `Enter` — Select account/category and focus transaction table
* `Escape` — Return focus to last-active sidebar

**Account Sidebar**: `c` — Create new account

**Category Sidebar**: `c` — Create, `d` — Delete, `e` — Rename

**Transaction Table**:
* `q` — Quit
* `r` — Refresh data (reload accounts, categories, and transactions)
* `i` — Import CSV (requires account with mapping spec)
* `t` — Tag/assign category (inline autocomplete)
* `Enter` — Toggle reviewed status
* `s` — Split transaction
* `m` — Merge transactions
* `j` / `k` — Move down / up
* `g` / `G` — Jump to first / last row
* `/` — Search, `n` / `N` — Next / previous match

## Commands

```bash
# Environment Setup: Work in the .venv!

# Run App
python main.py

# Database Management
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Change Checklist

* **README**: If a change affects anything documented in the README (features, key bindings, setup instructions, etc.), update the README to reflect it.
* **Tests**: All new features and behavioral changes must include corresponding tests.

## Key Conventions

* **SQLite Compatibility**: Always use `batch_op` in Alembic migrations to handle SQLite's limited `ALTER TABLE` support. Use non-native enums (VARCHAR storage).
* **Importers**: Bank-specific logic lives in YAML files under `importers/` using CEL expressions; avoid hardcoding bank logic in Python. New importers are auto-discovered.
* **Formatting**: Use `black` for formatting and `isort` for imports.
* **DataTable Keys**: Always pass explicit `key=` to `add_row()` and `add_column()` to get stable, value-based keys (see MEMORY.md for details).
* **Session Management**: The app uses a long-lived SQLAlchemy session opened on mount. Use eager loading (`selectinload`) to avoid `LazyInitializationError`.
* **Dynamic Widget Mounting**: When building composite widgets dynamically (after initial compose), pass children to the constructor (e.g. `Horizontal(child1, child2)`) instead of using `compose_add_child()`, which only works during the compose phase. When querying children of a dynamically mounted widget, guard with try/except since children may not be in the DOM yet.
* **App-Level Event Handlers + Modals**: `on_key` and other app-level handlers fire even when a modal screen is active, but `query_one()` for main-screen widgets will raise `NoMatches` because modals have their own DOM. Always guard such queries with `try/except`.
* **Dock Layering**: A `dock: left` sidebar spans the full height and covers `dock: bottom` widgets. For full-width elements (like a command input) between main content and Footer, use normal flow positioning instead of `dock: bottom`.
* **GPL v3 License Headers**: All `.py` source files (except `__init__.py`, `tests/`, and `alembic/versions/`) must include the standard short-form GPL v3 copyright header at the top. New source files must include it too.

## Testing

Tests **must be run after every change** to catch regressions.

```bash
# Run full test suite
python -m pytest tests/ -v

# Run specific layer
python -m pytest tests/test_models.py -v
python -m pytest tests/test_importers.py -v
python -m pytest tests/test_db.py -v
python -m pytest tests/test_widgets.py -v
python -m pytest tests/test_app.py -v
```

### Test Structure

* `tests/conftest.py` — Shared fixtures: in-memory DB, session, sample account, app instance
* `tests/test_models.py` — Domain models: relationships, constraints, enums
* `tests/test_importers.py` — CSV importer engine + Pydantic schema validation
* `tests/test_db.py` — Database layer: dirty flag, save/load roundtrip
* `tests/test_widgets.py` — Headless TUI tests using Textual's `run_test()`
* `tests/test_app.py` — Integration tests: refresh cycle, CSV import end-to-end, quit behavior

Tests use an in-memory SQLite DB (`Base.metadata.create_all()`) without Alembic to keep them fast and self-contained.
