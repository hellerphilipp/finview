import os
import pytest
from pydantic import ValidationError

from importers.schema import ImporterMapping, DataMapping, ParserConfig
from importers.engine import CSVImporter


SWISSCARD_PATH = os.path.join(
    os.path.dirname(__file__), "..", "importers", "Swisscard", "swisscard.yaml"
)


class TestImporterSchema:
    def test_valid_swisscard_yaml(self):
        importer = CSVImporter(SWISSCARD_PATH)
        assert importer.config.name == "Swisscard"
        assert importer.config.version == "1.0"
        assert importer.config.parser.delimiter == ","
        assert importer.config.parser.skip_rows == 1

    def test_invalid_schema_missing_fields(self):
        with pytest.raises(ValidationError):
            ImporterMapping(version="1.0", name="Bad")

    def test_invalid_schema_missing_mapping_fields(self):
        with pytest.raises(ValidationError):
            ImporterMapping(
                version="1.0",
                name="Bad",
                parser=ParserConfig(delimiter=",", skip_rows=0),
                mappings=DataMapping(timestamp="row[0]"),  # missing other fields
            )


class TestCSVImporterParseRow:
    @pytest.fixture()
    def importer(self):
        return CSVImporter(SWISSCARD_PATH)

    def test_parse_swisscard_row(self, importer):
        # Simulate a Swisscard CSV row with all fields populated
        row = [
            "15.01.2025",  # row[0] - date
            "COOP Store",  # row[1] - merchant
            "COOP Zurich",  # row[2] - extra description
            "",  # row[3]
            "CHF",  # row[4] - account currency
            "42.50",  # row[5] - amount in account currency
            "CHF",  # row[6] - original currency
            "42.50",  # row[7] - original amount
        ]
        result = importer.parse_row(row)

        assert result["timestamp"] == "2025-01-15"
        assert "COOP Zurich" in result["description"]
        assert "COOP Store" in result["description"]
        assert result["amount_original"] == -42.50
        assert result["currency_original"] == "CHF"
        assert result["amount_in_account_currency"] == -42.50

    def test_parse_row_without_extra_description(self, importer):
        row = [
            "20.02.2025",
            "SBB Ticket",
            "",  # no extra description
            "",
            "CHF",
            "15.00",
            "",  # no original currency
            "",  # no original amount
        ]
        result = importer.parse_row(row)

        assert result["timestamp"] == "2025-02-20"
        assert result["description"] == "SBB Ticket"
        assert result["amount_original"] == -15.00
        assert result["currency_original"] == "CHF"

    def test_empty_amount_fields(self, importer):
        row = [
            "01.03.2025",
            "Test",
            "",
            "",
            "CHF",
            "",  # empty amount
            "",
            "",  # empty original amount
        ]
        result = importer.parse_row(row)

        # double("") returns 0.0, then *-1.0 = -0.0 or 0.0
        assert result["amount_original"] == 0.0
        assert result["amount_in_account_currency"] == 0.0


class TestCSVImporterErrors:
    def test_invalid_yaml_path(self):
        with pytest.raises(FileNotFoundError):
            CSVImporter("/nonexistent/path.yaml")
