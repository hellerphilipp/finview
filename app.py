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
            st.session_state["migrated"] = True
    elif db_path:
        db.init_new_db(db_path)
    else:
        db.init_memory_db()

    st.session_state["db_initialized"] = True
    st.session_state["session"] = db.SessionLocal()
    # Clear dirty flag unless migrations ran (those need saving)
    if not st.session_state.get("migrated"):
        db.clear_dirty()


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

    selected_account_label = st.selectbox(
        "Account", account_labels, key="tx_account"
    )

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

        display_rows.append(
            {
                "id": tx.id,
                "select": False,
                "date": tx.date.strftime("%Y-%m-%d"),
                "description": desc,
                "category": cat_path if cat_path else None,
                "amount": float(tx.value_in_account_currency),
                "currency": tx.original_currency.value,
                "reviewed": bool(tx.reviewed_at),
                "account": acc_name or "",
                "_tx": tx,
                "_is_merge_header": has_children,
                "_is_merge_child": is_merge_child,
            }
        )

    if not display_rows:
        st.info("No transactions found.")
        return

    # --- Display table with inline editing ---
    import pandas as pd

    cat_path_list = queries.get_all_category_paths(session)
    cat_options_list = [p for _, p in cat_path_list]
    cat_path_to_id = {p: cid for cid, p in cat_path_list}

    cols = ["select", "date", "description", "category", "amount", "currency", "reviewed"]
    if all_accounts:
        cols.insert(2, "account")

    df = pd.DataFrame(display_rows)[cols]
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        hide_index=True,
        disabled=["date", "account", "description", "amount", "currency"],
        column_config={
            "select": st.column_config.CheckboxColumn("", default=False, width="small"),
            "reviewed": st.column_config.CheckboxColumn("reviewed", default=False),
            "category": st.column_config.SelectboxColumn(
                "category", options=cat_options_list, default=None
            ),
            "amount": st.column_config.NumberColumn(format="%.2f"),
        },
        key="tx_editor",
    )

    # --- Apply inline edits (reviewed + category) on explicit action ---
    edited_rows = st.session_state.get("tx_editor", {}).get("edited_rows", {})
    # Filter to only reviewed/category changes (ignore "select" toggles)
    pending_edits = {
        int(idx): changes
        for idx, changes in edited_rows.items()
        if "reviewed" in changes or "category" in changes
    }

    if pending_edits:
        if st.button("Apply Changes"):
            for idx, changes in pending_edits.items():
                tx = display_rows[idx]["_tx"]
                if "reviewed" in changes:
                    queries.set_reviewed(session, tx.id, bool(changes["reviewed"]))
                if "category" in changes:
                    new_cat = changes["category"]
                    new_cat_id = cat_path_to_id.get(new_cat) if new_cat else None
                    queries.assign_category(session, tx.id, new_cat_id)
            db.mark_dirty()
            st.rerun()

    # --- Actions based on selected rows ---
    selected_mask = edited_df["select"].astype(bool)
    selected_indices = selected_mask[selected_mask].index.tolist()
    selected_rows = [display_rows[i] for i in selected_indices]
    selected_txs = [r["_tx"] for r in selected_rows]
    num_selected = len(selected_rows)

    st.divider()

    if num_selected == 0:
        st.caption("Select one or more rows above to perform actions.")
    else:
        st.markdown(f"**{num_selected} transaction(s) selected**")

        action_cols = st.columns(3)

        # Single-row actions: Split + Edit Description
        if num_selected == 1:
            selected_tx = selected_txs[0]
            selected_row = selected_rows[0]

            with action_cols[0]:
                if st.button("Split"):
                    st.session_state["split_tx_id"] = selected_tx.id

            with action_cols[1]:
                new_desc = st.text_input(
                    "Description", value=selected_tx.description, key="edit_desc"
                )
                if st.button("Update Description"):
                    selected_tx.description = new_desc
                    session.commit()
                    db.mark_dirty()
                    st.rerun()

        # Multi-row action: Merge
        if num_selected >= 2:
            with action_cols[0]:
                if st.button("Merge Selected"):
                    st.session_state["merge_ids"] = [tx.id for tx in selected_txs]

        # Merge child actions (single selection of a merge child)
        if num_selected == 1 and selected_rows[0]["_is_merge_child"]:
            st.divider()
            st.markdown("**Merge Group Actions**")
            mg_col1, mg_col2 = st.columns(2)
            with mg_col1:
                if st.button("Remove from Merge"):
                    dissolved = queries.remove_from_merge(session, selected_txs[0].id)
                    db.mark_dirty()
                    if dissolved:
                        st.info(f"Merge group '{dissolved}' dissolved.")
                    st.rerun()
            with mg_col2:
                parent = session.get(Transaction, selected_txs[0].merge_parent_id)
                if parent:
                    new_merge_name = st.text_input(
                        "Rename group", value=parent.description, key="rename_merge"
                    )
                    if st.button("Rename Merge"):
                        queries.rename_merge(session, parent.id, new_merge_name)
                        db.mark_dirty()
                        st.rerun()

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

    # Migration notice
    if st.session_state.get("migrated"):
        st.info("Database was upgraded to the latest schema. Save to persist.")
        del st.session_state["migrated"]

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
