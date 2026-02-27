# CLAUDE.md

## Project Overview

FinView is a streamlined personal finance TUI built with Python and Textual. It prioritizes a "local-first" approach for importing, managing, and visualizing bank transactions.

## Architecture Principles

To keep the codebase maintainable as it grows, we follow a simplified **Clean Architecture**:

* **Domain Models (`models/`)**: Pure data structures (SQLAlchemy) and enums. No UI logic.
* **Data Access Layer (`repository/`)**: Encapsulates all SQL queries. The UI should not call `session.execute()` directly.
* **Services (`services/`)**: Orchestrates business logic (e.g., the import process, balance calculations).
* **Presentation Layer (`ui/`)**: Textual widgets and screens. Only talks to **Services** or **Repositories**.

## Project Structure

```
main.py              # Entry point
db.py                # Session/Engine configuration
models/              # Core entities
  base.py            # Declarative base & naming conventions
  finance.py         # Account, Transaction, Currency
repository/          # NEW: Data persistence logic
  finance_repo.py    # CRUD operations for accounts/transactions
services/            # NEW: Business logic
  import_service.py  # Coordinates CSV parsing -> DB saving
importers/           # Parsing engine
  engine.py          # CEL-based CSV parser
  schema.py          # Pydantic validation
ui/                  # Textual TUI layer
  app.py             # App orchestration
  screens/           # Screen-specific logic (Modals, Dashboards)
  widgets/           # Reusable Textual components
alembic/             # Migrations

```

## Tech Stack

* **Python 3.11+** (Type hinting via `Mapped[T]` and `Annotated`)
* **Textual**: TUI Framework
* **SQLAlchemy 2.0**: ORM (SQLite backend)
* **Alembic**: Migrations (using `render_as_batch=True` for SQLite)
* **CEL (Common Expression Language)**: Logic for dynamic CSV field mapping
* **Pydantic**: Validation for YAML importer specs

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

* **Repository Pattern**: UI components should use a repository instance to fetch data.
* **SQLite Compatibility**: Always use `batch_op` in Alembic migrations to handle SQLite's limited `ALTER TABLE` support.
* **Importers**: Bank-specific logic lives in YAML files using CEL; avoid hardcoding bank logic in Python.
* **Formatting**: Use `black` for formatting and `isort` for imports.
