# FinView — terminal-based personal finance manager
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

import argparse
import os
import sys

from db import init_memory_db, load_db_from_file, init_new_db, has_pending_migrations, run_migrations
from ui.app import FinViewApp

_COPYRIGHT = "FinView Copyright (C) 2026 Philipp Heller"

_LICENSE_NOTICE = """\
FinView — terminal-based personal finance manager
Copyright (C) 2026 Philipp Heller

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>."""

_EPILOG = """\
FinView  Copyright (C) 2026  Philipp Heller
This program comes with ABSOLUTELY NO WARRANTY; for details use `--license'.
This is free software, and you are welcome to redistribute it
under certain conditions; see LICENSE.md for details."""


def main():
    parser = argparse.ArgumentParser(
        description="FinView — a terminal-based personal finance manager. "
        "Manage bank accounts, import transactions from CSV files, "
        "review transactions, and track balances — all from the terminal.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "database",
        nargs="?",
        default=None,
        help="path to the SQLite database file (e.g. ~/finances.db). "
        "If omitted, starts with a pure in-memory database.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=_COPYRIGHT,
    )
    parser.add_argument(
        "--license",
        action="store_true",
        help="show license/warranty notice and exit",
    )

    args = parser.parse_args()

    if args.license:
        print(_LICENSE_NOTICE)
        sys.exit(0)

    if args.database is None:
        init_memory_db()
    else:
        db_path = os.path.abspath(os.path.expanduser(args.database))
        if os.path.exists(db_path):
            load_db_from_file(db_path)
            if has_pending_migrations():
                db_name = os.path.basename(db_path)
                print(f"Database '{db_name}' was created by an older version of FinView.")
                answer = input("Apply database upgrade now? [y/N] ").strip().lower()
                if answer in ("y", "yes"):
                    run_migrations()
                    print("Database upgraded successfully.")
                else:
                    print("Cannot open database without upgrading. Exiting.")
                    sys.exit(0)
        else:
            init_new_db(db_path)

    app = FinViewApp()
    app.run()


if __name__ == "__main__":
    main()
