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

from pydantic import BaseModel, ConfigDict

class ParserConfig(BaseModel):
    delimiter: str
    skip_rows: int

class DataMapping(BaseModel):
    timestamp: str
    description: str
    amount_original: str
    currency_original: str
    amount_in_account_currency: str

class ImporterMapping(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    version: str
    name: str
    parser: ParserConfig
    mappings: DataMapping