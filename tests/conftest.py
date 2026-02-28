import pytest
from datetime import datetime
from decimal import Decimal

import db
from models.base import Base
from models.finance import Account, Currency, Transaction


@pytest.fixture()
def memory_db():
    """Set up a fresh in-memory SQLite DB, bypassing Alembic stamp."""
    db._create_memory_engine()
    Base.metadata.create_all(db.engine)
    db._dirty = False
    db.db_file_path = None

    yield db.engine

    # Teardown: reset module-level state
    if db.engine:
        db.engine.dispose()
    db.engine = None
    db.SessionLocal = None
    db._dirty = False
    db.db_file_path = None


@pytest.fixture()
def session(memory_db):
    """Provide a fresh SQLAlchemy session, closed on teardown."""
    s = db.SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def sample_account(session):
    """Create an account with a few transactions for reuse."""
    acc = Account(name="Test Checking", currency=Currency.CHF)
    session.add(acc)
    session.flush()

    txs = [
        Transaction(
            account_id=acc.id,
            description="Initial Balance",
            original_value=Decimal("1000.00"),
            original_currency=Currency.CHF,
            value_in_account_currency=Decimal("1000.00"),
            date=datetime(2025, 1, 1),
        ),
        Transaction(
            account_id=acc.id,
            description="Grocery Store",
            original_value=Decimal("-50.00"),
            original_currency=Currency.CHF,
            value_in_account_currency=Decimal("-50.00"),
            date=datetime(2025, 1, 5),
        ),
        Transaction(
            account_id=acc.id,
            description="Salary",
            original_value=Decimal("3000.00"),
            original_currency=Currency.CHF,
            value_in_account_currency=Decimal("3000.00"),
            date=datetime(2025, 1, 15),
            reviewed_at=datetime(2025, 1, 16),
        ),
    ]
    session.add_all(txs)
    session.commit()
    return acc


@pytest.fixture()
def account_with_10_txs(session):
    """Create an account with 10 transactions for navigation tests."""
    acc = Account(name="Nav Test", currency=Currency.CHF)
    session.add(acc)
    session.flush()

    for i in range(1, 11):
        session.add(
            Transaction(
                account_id=acc.id,
                description=f"Transaction {i}",
                original_value=Decimal(str(i * 10)),
                original_currency=Currency.CHF,
                value_in_account_currency=Decimal(str(i * 10)),
                date=datetime(2025, 1, i),
            )
        )
    session.commit()
    return acc


@pytest.fixture()
def finview_app(memory_db):
    """Return a FinViewApp instance ready for run_test()."""
    from ui.app import FinViewApp

    return FinViewApp()
