from datetime import datetime
from decimal import Decimal

import pytest

import queries
from models.finance import Account, Category, Currency, Transaction


class TestGetAllCategoryPaths:
    def test_empty(self, session):
        assert queries.get_all_category_paths(session) == []

    def test_flat_categories(self, session):
        session.add_all([Category(name="b"), Category(name="a")])
        session.commit()
        paths = queries.get_all_category_paths(session)
        assert [p for _, p in paths] == ["a", "b"]

    def test_nested_paths(self, sample_category, session):
        travel, flights = sample_category
        paths = queries.get_all_category_paths(session)
        path_strs = [p for _, p in paths]
        assert "travel" in path_strs
        assert "travel/flights" in path_strs


class TestGetCategoriesWithTransactionCounts:
    def test_empty_categories(self, sample_category, session):
        result = queries.get_categories_with_transaction_counts(session)
        assert len(result) == 2
        for _, count, _ in result:
            assert count == 0

    def test_with_transactions(self, sample_account_with_categories, session):
        result = queries.get_categories_with_transaction_counts(session)
        count_map = {path: count for _, count, path in result}
        assert count_map["travel"] == 1
        assert count_map["travel/flights"] == 1


class TestCreateCategory:
    def test_simple(self, session):
        cat = queries.create_category(session, "groceries")
        assert cat.name == "groceries"
        assert cat.parent_id is None

    def test_hierarchical(self, session):
        cat = queries.create_category(session, "travel/flights")
        assert cat.name == "flights"
        assert cat.parent is not None
        assert cat.parent.name == "travel"

    def test_reuses_existing_parent(self, sample_category, session):
        travel, _ = sample_category
        hotels = queries.create_category(session, "travel/hotels")
        assert hotels.parent_id == travel.id

    def test_reuses_full_existing_path(self, sample_category, session):
        _, flights = sample_category
        result = queries.create_category(session, "travel/flights")
        assert result.id == flights.id

    def test_empty_path_raises(self, session):
        with pytest.raises(ValueError, match="empty"):
            queries.create_category(session, "")

    def test_deep_hierarchy(self, session):
        cat = queries.create_category(session, "a/b/c/d")
        assert cat.full_path == "a/b/c/d"


class TestRenameCategory:
    def test_rename(self, sample_category, session):
        travel, _ = sample_category
        queries.rename_category(session, travel.id, "trips")
        session.refresh(travel)
        assert travel.name == "trips"

    def test_rejects_slash(self, sample_category, session):
        travel, _ = sample_category
        with pytest.raises(ValueError, match="cannot contain"):
            queries.rename_category(session, travel.id, "a/b")

    def test_rejects_empty(self, sample_category, session):
        travel, _ = sample_category
        with pytest.raises(ValueError, match="empty"):
            queries.rename_category(session, travel.id, "")

    def test_rejects_duplicate_sibling(self, session):
        session.add(Category(name="a"))
        session.add(Category(name="b"))
        session.commit()
        cats = session.query(Category).all()
        a = next(c for c in cats if c.name == "a")
        b = next(c for c in cats if c.name == "b")
        with pytest.raises(ValueError, match="already exists"):
            queries.rename_category(session, a.id, "b")


class TestDeleteCategory:
    def test_delete_leaf(self, sample_category, session):
        _, flights = sample_category
        flights_id = flights.id
        queries.delete_category(session, flights_id)
        assert session.get(Category, flights_id) is None

    def test_delete_parent_cascades(self, sample_category, session):
        travel, flights = sample_category
        travel_id, flights_id = travel.id, flights.id
        queries.delete_category(session, travel_id)
        assert session.get(Category, travel_id) is None
        assert session.get(Category, flights_id) is None

    def test_delete_nonexistent_raises(self, session):
        with pytest.raises(ValueError, match="not found"):
            queries.delete_category(session, 9999)


class TestGetCategoryDeleteStats:
    def test_leaf_no_transactions(self, sample_category, session):
        _, flights = sample_category
        children, txs = queries.get_category_delete_stats(session, flights.id)
        assert children == 0
        assert txs == 0

    def test_parent_with_children_and_transactions(self, sample_account_with_categories, session):
        acc, travel, flights = sample_account_with_categories
        children, txs = queries.get_category_delete_stats(session, travel.id)
        assert children == 1  # flights
        assert txs == 2  # one on travel, one on flights


class TestAssignCategory:
    def test_assign(self, sample_account, sample_category, session):
        travel, _ = sample_category
        tx = session.query(Transaction).filter_by(account_id=sample_account.id).first()
        queries.assign_category(session, tx.id, travel.id)
        session.refresh(tx)
        assert tx.category_id == travel.id

    def test_unassign(self, sample_account_with_categories, session):
        acc, travel, _ = sample_account_with_categories
        tx = session.query(Transaction).filter_by(account_id=acc.id, category_id=travel.id).first()
        queries.assign_category(session, tx.id, None)
        session.refresh(tx)
        assert tx.category_id is None

    def test_assign_nonexistent_tx_raises(self, session):
        with pytest.raises(ValueError, match="not found"):
            queries.assign_category(session, 9999, None)


class TestLoadTransactionPageWithCategories:
    def test_returns_category_paths(self, sample_account_with_categories, session):
        acc, travel, flights = sample_account_with_categories
        _, _, _, cat_paths = queries.load_transaction_page(session, account_id=acc.id)
        assert cat_paths[travel.id] == "travel"
        assert cat_paths[flights.id] == "travel/flights"

    def test_empty_categories_returns_empty_dict(self, sample_account, session):
        _, _, _, cat_paths = queries.load_transaction_page(session, account_id=sample_account.id)
        assert cat_paths == {}
