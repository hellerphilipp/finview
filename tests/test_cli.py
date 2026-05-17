from unittest.mock import patch, MagicMock
from decimal import Decimal

import pytest

import db
import cli
import queries
from models.finance import Currency


@pytest.fixture
def session_factory(memory_db):
    """Provide a session factory backed by the in-memory test DB."""
    return db.SessionLocal


class TestAccountsMenu:
    def test_print_accounts_table_empty(self, session_factory, capsys):
        cli._print_accounts_table(session_factory)
        assert "No accounts yet" in capsys.readouterr().out

    @patch("cli.questionary")
    def test_create_account(self, mock_q, session_factory):
        mock_q.text.return_value.ask.side_effect = ["Test Account", "100.00"]
        mock_q.select.return_value.ask.side_effect = ["CHF", None]  # currency, spec
        mock_q.Choice = MagicMock(side_effect=lambda label, value=None: MagicMock(value=value))

        with patch("cli.services") as mock_svc:
            mock_svc.discover_mapping_specs.return_value = [("No Mapping / Manual", None)]
            cli._create_account(session_factory)
            mock_svc.create_account.assert_called_once()
            call_kwargs = mock_svc.create_account.call_args
            assert call_kwargs[1]["name"] == "Test Account"
            assert call_kwargs[1]["currency"] == Currency.CHF
            assert call_kwargs[1]["initial_amount"] == Decimal("100.00")

    @patch("cli.questionary")
    def test_create_account_cancelled(self, mock_q, session_factory):
        mock_q.text.return_value.ask.return_value = None

        with patch("cli.services") as mock_svc:
            cli._create_account(session_factory)
            mock_svc.create_account.assert_not_called()

    @patch("cli.questionary")
    def test_create_account_invalid_balance(self, mock_q, session_factory, capsys):
        mock_q.text.return_value.ask.side_effect = ["Test", "not_a_number"]
        mock_q.select.return_value.ask.side_effect = ["CHF", None]
        mock_q.Choice = MagicMock(side_effect=lambda label, value=None: MagicMock(value=value))

        with patch("cli.services") as mock_svc:
            mock_svc.discover_mapping_specs.return_value = [("No Mapping / Manual", None)]
            cli._create_account(session_factory)
            mock_svc.create_account.assert_not_called()
            assert "Invalid number" in capsys.readouterr().out


class TestImportMenu:
    def test_import_no_accounts(self, session_factory, capsys):
        with patch("cli.questionary"):
            cli._import_menu(session_factory)
            assert "No accounts" in capsys.readouterr().out


class TestMainLoop:
    @patch("cli.questionary")
    def test_quit_clean(self, mock_q, session_factory):
        mock_q.select.return_value.ask.return_value = "quit"
        mock_q.Choice = MagicMock(side_effect=lambda label, value=None: MagicMock(value=value))

        with patch("cli.db") as mock_db:
            mock_db.is_dirty.return_value = False
            mock_db.db_file_path = None
            cli.run(session_factory)

    @patch("cli.questionary")
    def test_quit_dirty_with_save(self, mock_q, session_factory):
        mock_q.select.return_value.ask.return_value = "quit"
        mock_q.confirm.return_value.ask.return_value = True
        mock_q.Choice = MagicMock(side_effect=lambda label, value=None: MagicMock(value=value))

        with patch("cli.db") as mock_db:
            mock_db.is_dirty.return_value = True
            mock_db.db_file_path = "/tmp/test.db"
            cli.run(session_factory)
            mock_db.save_to_file.assert_called_once()
