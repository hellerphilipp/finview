import argparse
import os
import sys

from db import init_memory_db, load_db_from_file, init_new_db, has_pending_migrations, run_migrations
from ui.app import FinViewApp


def main():
    parser = argparse.ArgumentParser(
        description="FinView — a terminal-based personal finance manager. "
        "Manage bank accounts, import transactions from CSV files, "
        "review transactions, and track balances — all from the terminal.",
    )
    parser.add_argument(
        "database",
        nargs="?",
        default=None,
        help="path to the SQLite database file (e.g. ~/finances.db). "
        "If omitted, starts with a pure in-memory database.",
    )

    args = parser.parse_args()

    if args.database is None:
        init_memory_db()
    else:
        db_path = os.path.abspath(os.path.expanduser(args.database))
        if os.path.exists(db_path):
            load_db_from_file(db_path)
            if has_pending_migrations():
                print(f"Database '{db_path}' has pending migrations.")
                answer = input("Apply migrations now? [y/N] ").strip().lower()
                if answer in ("y", "yes"):
                    run_migrations()
                    print("Migrations applied successfully.")
                else:
                    print("Cannot open database without applying migrations. Exiting.")
                    sys.exit(0)
        else:
            init_new_db(db_path)

    app = FinViewApp()
    app.run()


if __name__ == "__main__":
    main()
