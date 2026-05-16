"""Tests for the transaction merge feature."""

from datetime import datetime
from decimal import Decimal

import pytest

import db
import queries
from models.finance import Account, Currency, Transaction

# ── Fixtures ──


@pytest.fixture()
def two_accounts(session):
    """Two CHF accounts with transactions for merge testing."""
    acc1 = Account(name="Account A", currency=Currency.CHF)
    acc2 = Account(name="Account B", currency=Currency.CHF)
    session.add_all([acc1, acc2])
    session.flush()

    tx1 = Transaction(
        account_id=acc1.id,
        description="Restaurant dinner",
        original_value=Decimal("-100.00"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("-100.00"),
        date=datetime(2025, 1, 10),
    )
    tx2 = Transaction(
        account_id=acc2.id,
        description="Wire from John",
        original_value=Decimal("50.00"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("50.00"),
        date=datetime(2025, 1, 12),
    )
    session.add_all([tx1, tx2])
    session.commit()
    return acc1, acc2, tx1, tx2


@pytest.fixture()
def same_account_txs(session):
    """Single account with two transactions for same-account merge testing."""
    acc = Account(name="Main", currency=Currency.CHF)
    session.add(acc)
    session.flush()

    tx1 = Transaction(
        account_id=acc.id,
        description="Coffee shop",
        original_value=Decimal("-5.00"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("-5.00"),
        date=datetime(2025, 2, 1),
    )
    tx2 = Transaction(
        account_id=acc.id,
        description="Refund coffee",
        original_value=Decimal("5.00"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("5.00"),
        date=datetime(2025, 2, 3),
    )
    tx3 = Transaction(
        account_id=acc.id,
        description="Groceries",
        original_value=Decimal("-30.00"),
        original_currency=Currency.CHF,
        value_in_account_currency=Decimal("-30.00"),
        date=datetime(2025, 2, 5),
    )
    session.add_all([tx1, tx2, tx3])
    session.commit()
    return acc, tx1, tx2, tx3


@pytest.fixture()
def eur_account(session):
    """An EUR account for cross-currency validation tests."""
    acc = Account(name="Euro Account", currency=Currency.EUR)
    session.add(acc)
    session.flush()
    tx = Transaction(
        account_id=acc.id,
        description="Euro purchase",
        original_value=Decimal("-20.00"),
        original_currency=Currency.EUR,
        value_in_account_currency=Decimal("-20.00"),
        date=datetime(2025, 3, 1),
    )
    session.add(tx)
    session.commit()
    return acc, tx


# ── Query Tests: create_merge ──


class TestCreateMerge:
    def test_basic_merge(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Coffee round-trip")

        assert parent.description == "Coffee round-trip"
        assert parent.value_in_account_currency == 0.0  # -5 + 5
        assert parent.date == datetime(2025, 2, 1)  # earliest child

        session.refresh(tx1)
        session.refresh(tx2)
        assert tx1.merge_parent_id == parent.id
        assert tx2.merge_parent_id == parent.id

    def test_cross_account_same_currency(self, two_accounts, session):
        acc1, acc2, tx1, tx2 = two_accounts
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Dinner split")

        assert parent.value_in_account_currency == -50.0  # -100 + 50
        assert parent.account_id == acc1.id  # first child's account

    def test_rejects_different_currency(self, same_account_txs, eur_account, session):
        _, tx1, _, _ = same_account_txs
        _, eur_tx = eur_account

        with pytest.raises(ValueError, match="different currencies"):
            queries.create_merge(session, [tx1.id, eur_tx.id], "Mixed")

    def test_rejects_already_in_group(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        queries.create_merge(session, [tx1.id, tx2.id], "Group 1")

        with pytest.raises(ValueError, match="already in a merge group"):
            queries.create_merge(session, [tx1.id, tx3.id], "Group 2")

    def test_rejects_merging_merge_parent(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Group 1")

        with pytest.raises(ValueError, match="merge parent"):
            queries.create_merge(session, [parent.id, tx3.id], "Nested")


# ── Query Tests: add_to_merge ──


class TestAddToMerge:
    def test_add_third_transaction(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Group")

        queries.add_to_merge(session, parent.id, tx3.id)
        session.refresh(tx3)
        assert tx3.merge_parent_id == parent.id

        # Parent should be updated
        session.refresh(parent)
        assert parent.value_in_account_currency == -30.0  # -5 + 5 + -30
        assert parent.date == datetime(2025, 2, 1)

    def test_rejects_already_grouped(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Group")

        with pytest.raises(ValueError, match="already in a merge group"):
            queries.add_to_merge(session, parent.id, tx1.id)

    def test_rejects_cross_currency(self, same_account_txs, eur_account, session):
        _, tx1, tx2, _ = same_account_txs
        _, eur_tx = eur_account
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Group")

        with pytest.raises(ValueError, match="different currencies"):
            queries.add_to_merge(session, parent.id, eur_tx.id)


# ── Query Tests: remove_from_merge ──


class TestRemoveFromMerge:
    def test_remove_from_3_member_group(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id, tx3.id], "Group")
        parent_id = parent.id

        result = queries.remove_from_merge(session, tx3.id)
        assert result is None  # not dissolved, 2 remain

        session.refresh(tx3)
        assert tx3.merge_parent_id is None

        session.refresh(parent)
        assert parent.value_in_account_currency == 0.0  # -5 + 5

    def test_dissolve_on_single_remaining(self, same_account_txs, session):
        acc, tx1, tx2, _ = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Temp Group")
        parent_id = parent.id

        result = queries.remove_from_merge(session, tx2.id)
        assert result == "Temp Group"  # dissolved

        session.refresh(tx1)
        assert tx1.merge_parent_id is None
        session.refresh(tx2)
        assert tx2.merge_parent_id is None

        # Parent should be deleted
        assert session.get(Transaction, parent_id) is None


# ── Query Tests: rename_merge ──


class TestRenameMerge:
    def test_rename(self, same_account_txs, session):
        acc, tx1, tx2, _ = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Old Name")
        queries.rename_merge(session, parent.id, "New Name")
        session.refresh(parent)
        assert parent.description == "New Name"


# ── Query Tests: load_transaction_page ──


class TestLoadTransactionPageWithMerge:
    def test_merge_children_excluded_from_count(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        queries.create_merge(session, [tx1.id, tx2.id], "Group")

        total, unreviewed, rows, _ = queries.load_transaction_page(session, account_id=acc.id)
        # 3 original txs → 1 merge parent (counted) + 2 children (not counted) + 1 normal
        # But merge parent is excluded from display rows (it's a merge parent)
        # Count: tx3 (normal) + merge parent = 2
        assert total == 2

    def test_merge_children_shown_in_single_account(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        parent = queries.create_merge(session, [tx1.id, tx2.id], "Group")

        _, _, rows, _ = queries.load_transaction_page(session, account_id=acc.id)
        # Should show: header + tx1, tx2 (merge children) + tx3 (normal) = 4
        assert len(rows) == 4
        tx_ids = [r[0].id for r in rows]
        assert tx1.id in tx_ids
        assert tx2.id in tx_ids
        assert tx3.id in tx_ids
        # Header row should be the merge parent, placed before its children
        header_idx = tx_ids.index(parent.id)
        child_indices = [tx_ids.index(tx1.id), tx_ids.index(tx2.id)]
        assert all(header_idx < ci for ci in child_indices)

    def test_merge_net_returned(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        queries.create_merge(session, [tx1.id, tx2.id], "Group")

        _, _, rows, _ = queries.load_transaction_page(session, account_id=acc.id)
        # Find a merge child and check merge_net
        for row in rows:
            tx = row[0]
            merge_net = row[1]
            if tx.id == tx1.id:
                assert merge_net == 0.0  # -5 + 5
                break
        else:
            pytest.fail("tx1 not found in rows")

    def test_all_accounts_grouping(self, two_accounts, session):
        acc1, acc2, tx1, tx2 = two_accounts
        queries.create_merge(session, [tx1.id, tx2.id], "Dinner")

        _, _, rows, _ = queries.load_transaction_page(session, all_accounts=True)

        # Should have a header row + 2 children
        # Header row has account_name "–"
        header_rows = [r for r in rows if r[1] == "–"]
        assert len(header_rows) == 1
        assert header_rows[0][0].description == "Dinner"


# ── Query Tests: balance ──


class TestBalanceWithMerge:
    def test_merge_parent_excluded_from_balance(self, same_account_txs, session):
        acc, tx1, tx2, tx3 = same_account_txs
        balance_before = dict(queries.get_all_accounts_with_balances(session))
        original_balance = balance_before[acc]

        queries.create_merge(session, [tx1.id, tx2.id], "Group")
        balance_after = dict(queries.get_all_accounts_with_balances(session))

        # Balance should not change — merge parent is virtual, excluded from sum
        assert balance_after[acc] == original_balance


# ── Query Tests: split child in merge ──


class TestSplitChildMerge:
    def test_split_child_can_be_merged(self, session):
        acc = Account(name="Split Test", currency=Currency.CHF)
        session.add(acc)
        session.flush()

        parent = Transaction(
            account_id=acc.id,
            description="Big Purchase",
            original_value=Decimal("100.00"),
            original_currency=Currency.CHF,
            value_in_account_currency=Decimal("100.00"),
            date=datetime(2025, 3, 1),
        )
        session.add(parent)
        session.flush()

        child = Transaction(
            account_id=acc.id,
            description="Split part",
            original_value=Decimal("50.00"),
            original_currency=Currency.CHF,
            value_in_account_currency=Decimal("50.00"),
            date=datetime(2025, 3, 1),
            split_parent_id=parent.id,
        )
        reimbursement = Transaction(
            account_id=acc.id,
            description="Reimbursement",
            original_value=Decimal("50.00"),
            original_currency=Currency.CHF,
            value_in_account_currency=Decimal("50.00"),
            date=datetime(2025, 3, 5),
        )
        session.add_all([child, reimbursement])
        session.commit()

        # Should succeed: split child can be merged
        merge_parent = queries.create_merge(session, [child.id, reimbursement.id], "Split+Merge")
        session.refresh(child)
        assert child.split_parent_id == parent.id  # split relationship preserved
        assert child.merge_parent_id == merge_parent.id  # merge relationship added


# ── Cross-Account Merge Query Tests ──


class TestCrossAccountMergeQuery:
    def test_cross_account_merge_children_marked(self, two_accounts, session):
        """Cross-account merge children have is_cross_account_merge=True in single-account view."""
        acc1, acc2, tx1, tx2 = two_accounts
        queries.create_merge(session, [tx1.id, tx2.id], "Cross Merge")

        _, _, rows, _ = queries.load_transaction_page(session, account_id=acc1.id)
        # tx1 should appear with is_cross_account = True
        for row in rows:
            tx = row[0]
            is_cross = row[4]
            if tx.id == tx1.id:
                assert is_cross, "Cross-account merge child should be marked"
                break
        else:
            pytest.fail("tx1 not found in rows for acc1")

    def test_same_account_merge_not_cross_account(self, same_account_txs, session):
        """Same-account merge children have is_cross_account_merge=False."""
        acc, tx1, tx2, tx3 = same_account_txs
        queries.create_merge(session, [tx1.id, tx2.id], "Same Merge")

        _, _, rows, _ = queries.load_transaction_page(session, account_id=acc.id)
        for row in rows:
            tx = row[0]
            is_cross = row[4]
            if tx.id == tx1.id:
                assert not is_cross, "Same-account merge child should NOT be marked cross-account"
                break
        else:
            pytest.fail("tx1 not found in rows")

    def test_cross_account_merge_in_all_accounts(self, two_accounts, session):
        """Cross-account merge still shows header + children in all-accounts view."""
        acc1, acc2, tx1, tx2 = two_accounts
        queries.create_merge(session, [tx1.id, tx2.id], "Cross Merge")

        _, _, rows, _ = queries.load_transaction_page(session, all_accounts=True)
        header_rows = [r for r in rows if r[1] == "–"]
        assert len(header_rows) == 1
        assert header_rows[0][0].description == "Cross Merge"

        # Both children should be present
        child_ids = {r[0].id for r in rows if r[0].merge_parent_id is not None}
        assert tx1.id in child_ids
        assert tx2.id in child_ids
