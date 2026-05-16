# FinView — personal finance manager
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

import os
import sys
from datetime import datetime
from decimal import Decimal

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

import db
import queries
import services
from models.finance import Account, Category, Currency, Transaction


def init_db():
    """Initialize the database once per Streamlit session."""
    if "db_initialized" in st.session_state:
        return

    # Streamlit consumes the "--" separator and passes remaining args
    # directly in sys.argv[1:], so sys.argv = [script_path, db_path]
    db_path = sys.argv[1] if len(sys.argv) > 1 else None

    if db_path and os.path.exists(db_path):
        db.load_db_from_file(db_path)
        if db.has_pending_migrations():
            db.run_migrations()
    elif db_path:
        db.init_new_db(db_path)
    else:
        db.init_memory_db()

    st.session_state["db_initialized"] = True
    st.session_state["session"] = db.SessionLocal()


def get_session():
    return st.session_state["session"]


# ---------------------------------------------------------------------------
# Tab 1: Accounts & Categories
# ---------------------------------------------------------------------------


def render_accounts_categories():
    session = get_session()

    acct_col, cat_col = st.columns(2)

    # --- Accounts ---
    with acct_col:
        st.subheader("Accounts")

        accounts = queries.get_all_accounts_with_balances(session)
        if accounts:
            for acc, balance in accounts:
                spec_label = f" | Spec: {acc.mapping_spec}" if acc.mapping_spec else ""
                st.markdown(
                    f"**{acc.name}** ({acc.currency.value}) — "
                    f"Balance: {balance:,.2f}{spec_label}"
                )
        else:
            st.info("No accounts yet. Create one below.")

        st.divider()
        st.markdown("**Create Account**")
        with st.form("create_account", clear_on_submit=True):
            name = st.text_input("Account Name")
            currency = st.selectbox("Currency", [c.value for c in Currency])
            mapping_options = services.discover_mapping_specs()
            spec_labels = [o[0] for o in mapping_options]
            spec_idx = st.selectbox(
                "Import Mapping Spec",
                range(len(spec_labels)),
                format_func=lambda i: spec_labels[i],
            )
            amount = st.number_input("Starting Amount", value=0.00, format="%.2f")
            date = st.date_input("Date", value=datetime.now().date())

            if st.form_submit_button("Create Account"):
                if not name:
                    st.error("Name is required.")
                else:
                    try:
                        services.create_account(
                            session,
                            name=name,
                            currency=Currency(currency),
                            mapping_spec=mapping_options[spec_idx][1],
                            initial_amount=Decimal(str(amount)),
                            initial_date=datetime.combine(date, datetime.min.time()),
                        )
                        st.success(f"Created account: {name}")
                        st.rerun()
                    except Exception as e:
                        session.rollback()
                        st.error(f"Error: {e}")

    # --- Categories ---
    with cat_col:
        st.subheader("Categories")

        categories = queries.get_categories_with_transaction_counts(session)
        if categories:
            for cat, count, full_path in categories:
                depth = full_path.count("/")
                indent = "\u2003" * depth
                st.markdown(f"{indent}**{cat.name}** ({count} txns) — `{full_path}`")
        else:
            st.info("No categories yet. Create one below.")

        st.divider()

        # Create category
        st.markdown("**Create Category**")
        with st.form("create_category", clear_on_submit=True):
            cat_path = st.text_input(
                "Category Path", placeholder="e.g. travel/flights"
            )
            if st.form_submit_button("Create"):
                if not cat_path:
                    st.error("Path is required.")
                else:
                    try:
                        queries.create_category(session, cat_path)
                        db.mark_dirty()
                        st.success(f"Created category: {cat_path}")
                        st.rerun()
                    except Exception as e:
                        session.rollback()
                        st.error(f"Error: {e}")

        # Rename / Delete
        if categories:
            st.divider()
            cat_options = {full_path: cat for cat, _, full_path in categories}
            selected_cat_path = st.selectbox(
                "Select category to manage",
                list(cat_options.keys()),
                key="manage_cat",
            )
            selected_cat = cat_options[selected_cat_path]

            rename_col, delete_col = st.columns(2)
            with rename_col:
                new_name = st.text_input("New name", key="rename_cat_input")
                if st.button("Rename"):
                    if not new_name:
                        st.error("Name cannot be empty.")
                    else:
                        try:
                            queries.rename_category(session, selected_cat.id, new_name)
                            db.mark_dirty()
                            st.success(f"Renamed to: {new_name}")
                            st.rerun()
                        except Exception as e:
                            session.rollback()
                            st.error(f"Error: {e}")

            with delete_col:
                child_count, tx_count = queries.get_category_delete_stats(
                    session, selected_cat.id
                )
                st.caption(
                    f"Deleting will affect {child_count} sub-categories "
                    f"and {tx_count} transactions."
                )
                if st.button("Delete", type="primary"):
                    try:
                        queries.delete_category(session, selected_cat.id)
                        db.mark_dirty()
                        st.success(f"Deleted: {selected_cat_path}")
                        st.rerun()
                    except Exception as e:
                        session.rollback()
                        st.error(f"Error: {e}")


# ---------------------------------------------------------------------------
# Tab 2: Import Transactions
# ---------------------------------------------------------------------------


def render_import():
    session = get_session()

    st.subheader("Import Transactions")

    accounts = queries.get_all_accounts_with_balances(session)
    accounts_with_spec = [
        (acc, bal) for acc, bal in accounts if acc.mapping_spec
    ]

    if not accounts_with_spec:
        st.warning(
            "No accounts with a mapping spec found. "
            "Create an account with a mapping spec first."
        )
        return

    account_labels = {
        f"{acc.name} ({acc.currency.value})": acc for acc, _ in accounts_with_spec
    }
    selected_label = st.selectbox("Select Account", list(account_labels.keys()))
    selected_account = account_labels[selected_label]

    # Show latest transaction date for duplicate warning
    latest_date = services.get_latest_transaction_date(session, selected_account.id)
    if latest_date:
        st.info(
            f"Latest transaction for this account: "
            f"**{latest_date.strftime('%Y-%m-%d %H:%M')}**"
        )

    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])

    if uploaded_file is not None:
        st.caption(f"File: {uploaded_file.name} ({uploaded_file.size:,} bytes)")

        if st.button("Import", type="primary"):
            try:
                count = services.import_csv_from_bytes(
                    session,
                    uploaded_file.getvalue(),
                    uploaded_file.name,
                    selected_account,
                )
                st.success(f"Imported {count} transactions.")

                # Check for older transactions warning
                if latest_date:
                    new_latest = services.get_latest_transaction_date(
                        session, selected_account.id
                    )
                    if new_latest and new_latest <= latest_date:
                        st.warning(
                            "All imported transactions are older than or equal to "
                            "the previously latest transaction. "
                            "This may indicate duplicate imports."
                        )
                st.rerun()
            except Exception as e:
                session.rollback()
                st.error(f"Import failed: {e}")


# ---------------------------------------------------------------------------
# Tab 3: Transactions
# ---------------------------------------------------------------------------


def render_transactions():
    session = get_session()

    st.subheader("Transactions")

    # --- Filters ---
    accounts = queries.get_all_accounts_with_balances(session)
    account_labels = ["All Accounts"] + [
        f"{acc.name} ({acc.currency.value})" for acc, _ in accounts
    ]
    account_map = {
        f"{acc.name} ({acc.currency.value})": acc for acc, _ in accounts
    }

    filter_col1, filter_col2 = st.columns([2, 2])
    with filter_col1:
        selected_account_label = st.selectbox(
            "Account", account_labels, key="tx_account"
        )
    with filter_col2:
        search_term = st.text_input("Search", key="tx_search", placeholder="Filter by description...")

    all_accounts = selected_account_label == "All Accounts"
    account_id = (
        None if all_accounts else account_map[selected_account_label].id
    )

    total_count, total_unreviewed, rows, category_paths = (
        queries.load_transaction_page(
            session, account_id=account_id, all_accounts=all_accounts
        )
    )

    st.caption(
        f"{total_count} transactions | {total_unreviewed} unreviewed"
        + (f" | Unsaved changes" if db.is_dirty() else "")
    )

    if not rows:
        st.info("No transactions found.")
        return

    # --- Build display rows ---
    display_rows = []
    for row in rows:
        tx = row[0]

        if all_accounts:
            _, acc_name, merge_net, merge_reviewed, merge_group_name = row
        else:
            _, merge_net, merge_reviewed, merge_group_name, is_cross_account = row
            acc_name = None

        # Determine if this is a merge header
        is_merge_header = tx.merge_parent_id is None and merge_group_name is not None and merge_net is not None
        # Check if this might be a merge parent (header row)
        has_children = session.execute(
            select(Transaction.id).where(Transaction.merge_parent_id == tx.id).limit(1)
        ).first() is not None if is_merge_header else False

        is_split_child = tx.split_parent_id is not None
        is_merge_child = tx.merge_parent_id is not None

        desc = tx.description
        if is_split_child:
            desc = f"  [split] {desc}"
        if is_merge_child and not all_accounts:
            if not all_accounts and row[4]:  # is_cross_account
                desc = f"{desc} [m+]"
            else:
                desc = f"  [merge] {desc}"
        if has_children:
            desc = f"[GROUP] {desc}"

        cat_path = category_paths.get(tx.category_id, "") if tx.category_id else ""

        # Apply search filter
        if search_term:
            term = search_term.lower()
            if (
                term not in desc.lower()
                and term not in cat_path.lower()
                and term not in tx.date.strftime("%Y-%m-%d").lower()
            ):
                continue

        display_rows.append(
            {
                "id": tx.id,
                "date": tx.date.strftime("%Y-%m-%d"),
                "description": desc,
                "category": cat_path,
                "amount": float(tx.value_in_account_currency),
                "currency": tx.original_currency.value,
                "reviewed": "Yes" if tx.reviewed_at else "",
                "account": acc_name or "",
                "_tx": tx,
                "_is_merge_header": has_children,
                "_is_merge_child": is_merge_child,
            }
        )

    if not display_rows:
        st.info("No transactions match the search.")
        return

    # --- Display table ---
    import pandas as pd

    cols = ["date", "description", "category", "amount", "currency", "reviewed"]
    if all_accounts:
        cols.insert(1, "account")

    df = pd.DataFrame(display_rows)[cols]
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "amount": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    # --- Actions ---
    st.divider()
    st.markdown("**Actions**")

    # Transaction selector
    tx_options = {
        f"#{r['id']} | {r['date']} | {r['description'][:50]}": r
        for r in display_rows
        if not r["_is_merge_header"]
    }

    if not tx_options:
        return

    selected_tx_label = st.selectbox(
        "Select transaction", list(tx_options.keys()), key="tx_select"
    )
    selected_row = tx_options[selected_tx_label]
    selected_tx = selected_row["_tx"]

    action_cols = st.columns(5)

    # Toggle reviewed
    with action_cols[0]:
        review_label = "Unreview" if selected_tx.reviewed_at else "Review"
        if st.button(review_label):
            queries.toggle_reviewed(session, selected_tx.id)
            db.mark_dirty()
            st.rerun()

    # Assign category
    with action_cols[1]:
        cat_paths = queries.get_all_category_paths(session)
        if cat_paths:
            cat_options = {"(none)": None} | {
                path: cid for cid, path in cat_paths
            }
            current_cat = category_paths.get(selected_tx.category_id, "(none)")
            current_idx = list(cat_options.keys()).index(current_cat) if current_cat in cat_options else 0
            new_cat = st.selectbox(
                "Category",
                list(cat_options.keys()),
                index=current_idx,
                key="assign_cat",
            )
            if st.button("Assign"):
                queries.assign_category(session, selected_tx.id, cat_options[new_cat])
                db.mark_dirty()
                st.rerun()

    # Split
    with action_cols[2]:
        if st.button("Split"):
            st.session_state["split_tx_id"] = selected_tx.id

    # Merge
    with action_cols[3]:
        if st.button("Merge"):
            if "merge_pending_id" not in st.session_state:
                st.session_state["merge_pending_id"] = selected_tx.id
                st.info(f"Select another transaction and click Merge again.")
            else:
                pending_id = st.session_state.pop("merge_pending_id")
                if pending_id == selected_tx.id:
                    st.warning("Cancelled merge — same transaction selected.")
                else:
                    st.session_state["merge_ids"] = [pending_id, selected_tx.id]

    # Edit description
    with action_cols[4]:
        new_desc = st.text_input("Description", value=selected_tx.description, key="edit_desc")
        if st.button("Update"):
            selected_tx.description = new_desc
            session.commit()
            db.mark_dirty()
            st.rerun()

    # --- Merge pending indicator ---
    if "merge_pending_id" in st.session_state:
        st.info(
            f"Merge pending: transaction #{st.session_state['merge_pending_id']}. "
            "Select another transaction and click Merge to complete, or click Merge on the same to cancel."
        )

    # --- Merge dialog ---
    if "merge_ids" in st.session_state:
        merge_ids = st.session_state["merge_ids"]
        st.markdown("**Create Merge Group**")
        merge_name = st.text_input("Merge group name", key="merge_name")
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            if st.button("Confirm Merge"):
                if not merge_name:
                    st.error("Name is required.")
                else:
                    try:
                        queries.create_merge(session, merge_ids, merge_name)
                        db.mark_dirty()
                        del st.session_state["merge_ids"]
                        st.success(f"Created merge group: {merge_name}")
                        st.rerun()
                    except Exception as e:
                        session.rollback()
                        st.error(f"Error: {e}")
        with m_col2:
            if st.button("Cancel Merge"):
                del st.session_state["merge_ids"]
                st.rerun()

    # --- Split dialog ---
    if "split_tx_id" in st.session_state:
        split_tx_id = st.session_state["split_tx_id"]
        root = session.get(Transaction, split_tx_id)
        if root is None:
            del st.session_state["split_tx_id"]
            st.rerun()
        else:
            # Navigate to root parent
            while root.split_parent_id is not None:
                root = session.get(Transaction, root.split_parent_id)

            root = session.execute(
                select(Transaction)
                .where(Transaction.id == root.id)
                .options(selectinload(Transaction.split_children))
            ).scalar_one()

            st.markdown(
                f"**Split Transaction:** {root.description} "
                f"(Amount: {float(root.original_value):.2f})"
            )

            # Initialize split rows from existing children or empty
            if "split_rows" not in st.session_state:
                if root.split_children:
                    st.session_state["split_rows"] = [
                        {
                            "id": c.id,
                            "description": c.description,
                            "amount": float(c.original_value),
                        }
                        for c in root.split_children
                    ]
                else:
                    st.session_state["split_rows"] = [
                        {"id": None, "description": "", "amount": 0.0}
                    ]

            split_rows = st.session_state["split_rows"]

            for i, sr in enumerate(split_rows):
                c1, c2, c3 = st.columns([3, 2, 1])
                with c1:
                    sr["description"] = st.text_input(
                        "Description", value=sr["description"], key=f"split_desc_{i}"
                    )
                with c2:
                    sr["amount"] = st.number_input(
                        "Amount",
                        value=sr["amount"],
                        format="%.2f",
                        key=f"split_amt_{i}",
                    )
                with c3:
                    if st.button("Remove", key=f"split_rm_{i}"):
                        split_rows.pop(i)
                        st.rerun()

            total_allocated = sum(sr["amount"] for sr in split_rows)
            unallocated = float(root.original_value) - total_allocated
            st.caption(f"Allocated: {total_allocated:.2f} | Unallocated: {unallocated:.2f}")

            s_col1, s_col2, s_col3 = st.columns(3)
            with s_col1:
                if st.button("Add Row"):
                    split_rows.append({"id": None, "description": "", "amount": 0.0})
                    st.rerun()
            with s_col2:
                can_save = abs(unallocated) < 0.005
                if st.button("Save Split", disabled=not can_save):
                    services.apply_split(session, root, split_rows)
                    del st.session_state["split_tx_id"]
                    del st.session_state["split_rows"]
                    st.success("Split saved.")
                    st.rerun()
            with s_col3:
                if st.button("Cancel Split"):
                    del st.session_state["split_tx_id"]
                    if "split_rows" in st.session_state:
                        del st.session_state["split_rows"]
                    st.rerun()

    # --- Merge group management for merge children ---
    if selected_row["_is_merge_child"]:
        st.divider()
        st.markdown("**Merge Group Actions**")
        mg_col1, mg_col2 = st.columns(2)
        with mg_col1:
            if st.button("Remove from Merge"):
                dissolved = queries.remove_from_merge(session, selected_tx.id)
                db.mark_dirty()
                if dissolved:
                    st.info(f"Merge group '{dissolved}' dissolved.")
                st.rerun()
        with mg_col2:
            parent = session.get(Transaction, selected_tx.merge_parent_id)
            if parent:
                new_merge_name = st.text_input(
                    "Rename group", value=parent.description, key="rename_merge"
                )
                if st.button("Rename Merge"):
                    queries.rename_merge(session, parent.id, new_merge_name)
                    db.mark_dirty()
                    st.rerun()


# ---------------------------------------------------------------------------
# Tab 4: Analysis
# ---------------------------------------------------------------------------


def render_analysis():
    st.subheader("Analysis")
    st.info("Coming soon.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


st.set_page_config(page_title="FinView", layout="wide")
init_db()

with st.sidebar:
    st.title("FinView")
    tab = st.radio(
        "Navigation",
        [
            "Accounts & Categories",
            "Import Transactions",
            "Transactions",
            "Analysis",
        ],
    )
    st.divider()

    # Save button
    if db.db_file_path:
        if st.button("Save", disabled=not db.is_dirty()):
            db.save_to_file()
            st.success("Saved!")
            st.rerun()
        if db.is_dirty():
            st.warning("Unsaved changes")
        st.caption(f"File: {os.path.basename(db.db_file_path)}")
    else:
        st.caption("In-memory database (no file)")

if tab == "Accounts & Categories":
    render_accounts_categories()
elif tab == "Import Transactions":
    render_import()
elif tab == "Transactions":
    render_transactions()
else:
    render_analysis()
