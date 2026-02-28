from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from models.finance import Account, Currency, Transaction


class TestCurrencyEnum:
    def test_all_expected_values(self):
        values = {c.value for c in Currency}
        assert values == {"USD", "EUR", "GBP", "CHF"}


class TestAccountTransactionRelationship:
    def test_account_has_transactions(self, sample_account, session):
        session.refresh(sample_account)
        assert len(sample_account.transactions) == 3

    def test_transaction_backref(self, sample_account, session):
        tx = sample_account.transactions[0]
        assert tx.account is sample_account
        assert tx.account.name == "Test Checking"

    def test_unique_account_name(self, session):
        session.add(Account(name="Unique", currency=Currency.USD))
        session.flush()
        session.add(Account(name="Unique", currency=Currency.EUR))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


class TestTransactionSplitting:
    def test_parent_children_relationship(self, sample_account, session):
        parent = sample_account.transactions[0]

        child1 = Transaction(
            account_id=sample_account.id,
            description="Split A",
            original_value=600.00,
            original_currency=Currency.CHF,
            value_in_account_currency=600.00,
            date=parent.date,
            parent_id=parent.id,
        )
        child2 = Transaction(
            account_id=sample_account.id,
            description="Split B",
            original_value=400.00,
            original_currency=Currency.CHF,
            value_in_account_currency=400.00,
            date=parent.date,
            parent_id=parent.id,
        )
        session.add_all([child1, child2])
        session.commit()

        session.refresh(parent)
        assert len(parent.children) == 2
        assert {c.description for c in parent.children} == {"Split A", "Split B"}

    def test_cascade_delete(self, sample_account, session):
        parent = sample_account.transactions[0]
        child = Transaction(
            account_id=sample_account.id,
            description="Child",
            original_value=500.00,
            original_currency=Currency.CHF,
            value_in_account_currency=500.00,
            date=parent.date,
            parent_id=parent.id,
        )
        session.add(child)
        session.commit()
        child_id = child.id

        session.delete(parent)
        session.commit()

        assert session.get(Transaction, child_id) is None
