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

import argparse
import os
import sys

_COPYRIGHT = "FinView Copyright (C) 2026 Philipp Heller"

_LICENSE_NOTICE = """\
FinView — personal finance manager
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
        description="FinView — a personal finance manager. "
        "Manage bank accounts, import transactions from CSV files, "
        "review transactions, and track balances.",
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

    import db

    if args.database:
        path = os.path.abspath(os.path.expanduser(args.database))
        if os.path.exists(path):
            db.load_db_from_file(path)
            if db.has_pending_migrations():
                print("Applying database migrations...")
                db.run_migrations()
                print("Migrations applied.")
        else:
            db.init_new_db(path)
    else:
        db.init_memory_db()

    import cli

    try:
        cli.run(db.SessionLocal)
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
