from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from models.finance import Account, Category, Currency, Transaction


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
            split_parent_id=parent.id,
        )
        child2 = Transaction(
            account_id=sample_account.id,
            description="Split B",
            original_value=400.00,
            original_currency=Currency.CHF,
            value_in_account_currency=400.00,
            date=parent.date,
            split_parent_id=parent.id,
        )
        session.add_all([child1, child2])
        session.commit()

        session.refresh(parent)
        assert len(parent.split_children) == 2
        assert {c.description for c in parent.split_children} == {"Split A", "Split B"}

    def test_cascade_delete(self, sample_account, session):
        parent = sample_account.transactions[0]
        child = Transaction(
            account_id=sample_account.id,
            description="Child",
            original_value=500.00,
            original_currency=Currency.CHF,
            value_in_account_currency=500.00,
            date=parent.date,
            split_parent_id=parent.id,
        )
        session.add(child)
        session.commit()
        child_id = child.id

        session.delete(parent)
        session.commit()

        assert session.get(Transaction, child_id) is None


class TestCategory:
    def test_category_creation(self, session):
        cat = Category(name="groceries")
        session.add(cat)
        session.commit()
        assert cat.id is not None
        assert cat.name == "groceries"
        assert cat.parent_id is None

    def test_category_hierarchy(self, session):
        parent = Category(name="travel")
        session.add(parent)
        session.flush()
        child = Category(name="flights", parent_id=parent.id)
        session.add(child)
        session.commit()

        session.refresh(parent)
        assert len(parent.children) == 1
        assert parent.children[0].name == "flights"
        assert child.parent is parent

    def test_category_full_path(self, sample_category, session):
        travel, flights = sample_category
        session.refresh(travel)
        session.refresh(flights)
        assert travel.full_path == "travel"
        assert flights.full_path == "travel/flights"

    def test_deep_hierarchy_full_path(self, session):
        a = Category(name="a")
        session.add(a)
        session.flush()
        b = Category(name="b", parent_id=a.id)
        session.add(b)
        session.flush()
        c = Category(name="c", parent_id=b.id)
        session.add(c)
        session.commit()
        session.refresh(c)
        assert c.full_path == "a/b/c"

    def test_category_cascade_delete(self, sample_category, session):
        travel, flights = sample_category
        flights_id = flights.id
        session.delete(travel)
        session.commit()
        assert session.get(Category, flights_id) is None

    def test_category_delete_nullifies_transactions(self, sample_account_with_categories, session):
        acc, travel, flights = sample_account_with_categories
        txs = session.query(Transaction).filter_by(account_id=acc.id).all()
        assert txs[1].category_id == flights.id

        session.delete(flights)
        session.commit()

        session.refresh(txs[1])
        assert txs[1].category_id is None

    def test_transaction_category_relationship(self, sample_account_with_categories, session):
        acc, travel, flights = sample_account_with_categories
        txs = session.query(Transaction).filter_by(account_id=acc.id).all()
        assert txs[0].category is travel
        assert txs[1].category is flights
        assert travel in [t.category for t in txs if t.category]

    def test_unique_sibling_names(self, session):
        parent = Category(name="travel")
        session.add(parent)
        session.flush()
        session.add(Category(name="flights", parent_id=parent.id))
        session.flush()
        session.add(Category(name="flights", parent_id=parent.id))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_unique_root_names_enforced_by_queries(self, session):
        """SQLite treats NULLs as distinct in unique constraints, so root-level
        uniqueness is enforced by create_category/rename_category in Python."""
        import queries

        queries.create_category(session, "travel")
        # Creating same root name reuses the existing one
        cat = queries.create_category(session, "travel")
        assert session.query(Category).filter_by(name="travel", parent_id=None).count() == 1
