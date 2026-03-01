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

import yaml
import cel
from .schema import ImporterMapping


def _double(val):
    if not val or str(val).strip() == "":
        return 0.0
    return float(str(val).replace(",", "."))


def _split(s, d):
    return s.split(d)


class CSVImporter:
    def __init__(self, yaml_path: str):
        with open(yaml_path, 'r') as f:
            raw_config = yaml.safe_load(f)
            self.config = ImporterMapping(**raw_config)

    def parse_row(self, row: list[str]) -> dict:
        context = {
            "row": row,
            "double": _double,
            "split": _split,
        }

        results = {}
        for field, expr_str in self.config.mappings.model_dump().items():
            try:
                results[field] = cel.evaluate(expr_str, context)
            except Exception as e:
                raise ValueError(f"Error evaluating field '{field}': {e}")

        return results
