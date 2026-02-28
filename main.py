import argparse
import os

from db import init_db
from ui.app import FinViewApp

def main():
    parser = argparse.ArgumentParser(
        description="FinView — a terminal-based personal finance manager. "
        "Manage bank accounts, import transactions from CSV files, "
        "review transactions, and track balances — all from the terminal.",
    )
    parser.add_argument(
        "database",
        help="path to the SQLite database file (e.g. ~/finances.db)",
    )

    args = parser.parse_args()
    db_path = os.path.abspath(os.path.expanduser(args.database))

    init_db(db_path)

    app = FinViewApp()
    app.run()

if __name__ == "__main__":
    main()
