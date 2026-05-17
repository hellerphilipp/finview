# CLAUDE.md

## Project Overview

FinView is a local-first personal finance manager built with Python. It lets users manage multiple bank accounts and import transactions from CSV files via declarative YAML+CEL mapping specs — all from an interactive CLI with no cloud dependencies. Data is stored in a local SQLite database.

## Architecture

The codebase is organized into layers:

* **Domain Models (`models/`)**: Pure SQLAlchemy data structures and enums. No UI logic.
* **Queries (`queries.py`)**: All database read/write operations (accounts, categories, transactions, merges).
* **Services (`services.py`)**: Higher-level business operations (account creation, split transactions, CSV import, mapping spec discovery).
* **Importers (`importers/`)**: CEL-based CSV parsing engine and Pydantic schema validation for YAML specs.
* **CLI (`cli.py`)**: Interactive questionary-based TUI (inline, not fullscreen).

## Project Structure

```
main.py              # Entry point (CLI args, DB init, launches interactive TUI)
cli.py               # Interactive TUI: account management, CSV import
db.py                # Session/Engine config (in-memory SQLite with file backup)
queries.py           # Query functions: accounts, categories, transactions, merges
services.py          # Business logic: account creation, splits, import, spec discovery
models/
  base.py            # Declarative base & naming conventions
  finance.py         # Account, Transaction, Category, Currency enum
importers/
  engine.py          # CSVImporter: loads YAML spec, parses CSV rows via CEL
  schema.py          # Pydantic models: ImporterMapping, DataMapping, ParserConfig
  Swisscard/         # Example bank-specific YAML spec
alembic/             # Migrations (render_as_batch=True for SQLite)
```

## Tech Stack

* **Python 3.11+** (Type hinting via `Mapped[T]` and `Annotated`)
* **questionary**: Interactive CLI prompts (arrow-key selection, path completion)
* **SQLAlchemy 2.0**: ORM (SQLite backend)
* **Alembic**: Migrations (using `render_as_batch=True` for SQLite)
* **CEL (Common Expression Language)**: Declarative CSV field mapping in YAML specs
* **Pydantic**: Validation for YAML importer specs

## CLI Features

1. **Manage Accounts** — List, create, and edit accounts (name, currency, mapping spec, initial balance)
2. **Import Transactions** — Select account, provide CSV file path, import with mapping spec

## Commands

```bash
# Environment Setup: Work in the .venv!

# Run App
python main.py [database]

# Database Management
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Change Checklist

* **README**: If a change affects anything documented in the README (features, setup instructions, etc.), update the README to reflect it.
* **Tests**: All new features and behavioral changes must include corresponding tests.

## Key Conventions

* **SQLite Compatibility**: Always use `batch_op` in Alembic migrations to handle SQLite's limited `ALTER TABLE` support. Use non-native enums (VARCHAR storage).
* **Importers**: Bank-specific logic lives in YAML files under `importers/` using CEL expressions; avoid hardcoding bank logic in Python. New importers are auto-discovered.
* **Formatting**: Use `black` for formatting and `isort` for imports.
* **Session Management**: Each CLI action opens and closes its own session to avoid stale state. Use `db.mark_dirty()` after any data change.
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
python -m pytest tests/test_services.py -v
python -m pytest tests/test_categories.py -v
python -m pytest tests/test_merge.py -v
```

### Test Structure

* `tests/conftest.py` — Shared fixtures: in-memory DB, session, sample account
* `tests/test_models.py` — Domain models: relationships, constraints, enums
* `tests/test_importers.py` — CSV importer engine + Pydantic schema validation
* `tests/test_db.py` — Database layer: dirty flag, save/load roundtrip
* `tests/test_services.py` — Service layer: account creation, splits, import, spec discovery
* `tests/test_categories.py` — Category CRUD, hierarchy, assignment
* `tests/test_merge.py` — Merge operations: create, add, remove, rename, display

Tests use an in-memory SQLite DB (`Base.metadata.create_all()`) without Alembic to keep them fast and self-contained.
