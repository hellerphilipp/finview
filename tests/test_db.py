import os
import pytest

import db
from models.finance import Account, Currency, Transaction
from datetime import datetime


class TestDirtyFlag:
    def test_initially_clean(self, memory_db):
        assert not db.is_dirty()

    def test_mark_and_check_dirty(self, memory_db):
        db.mark_dirty()
        assert db.is_dirty()

    def test_clear_dirty(self, memory_db):
        db.mark_dirty()
        db.clear_dirty()
        assert not db.is_dirty()


class TestSaveAndLoad:
    def test_save_to_file_roundtrip(self, session, tmp_path):
        acc = Account(name="Roundtrip", currency=Currency.USD)
        session.add(acc)
        session.commit()

        save_path = str(tmp_path / "test.db")
        db.save_to_file(save_path)

        assert os.path.exists(save_path)
        assert not db.is_dirty()
        assert db.db_file_path == save_path

        # Reload from file
        db.load_db_from_file(save_path)
        new_session = db.SessionLocal()
        loaded = new_session.query(Account).filter_by(name="Roundtrip").first()
        assert loaded is not None
        assert loaded.currency == Currency.USD
        new_session.close()

    def test_save_to_file_no_path_raises(self, memory_db):
        db.db_file_path = None
        with pytest.raises(ValueError, match="No file path"):
            db.save_to_file()

    def test_swp_file_cleaned_up(self, session, tmp_path):
        session.add(Account(name="SwpTest", currency=Currency.CHF))
        session.commit()

        save_path = str(tmp_path / "clean.db")
        db.save_to_file(save_path)

        swp_path = save_path + ".swp"
        assert not os.path.exists(swp_path)

    def test_save_updates_db_file_path(self, session, tmp_path):
        session.add(Account(name="PathTest", currency=Currency.EUR))
        session.commit()

        path1 = str(tmp_path / "first.db")
        db.save_to_file(path1)
        assert db.db_file_path == path1

        path2 = str(tmp_path / "second.db")
        db.save_to_file(path2)
        assert db.db_file_path == path2
