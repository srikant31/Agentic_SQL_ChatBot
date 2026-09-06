"""
Data Explorer
-------------
Shows the raw underlying data the AI is querying against — separate from
the chat flow, so anyone can see exactly what's in the database without
needing to ask a question first.
"""

import streamlit as st

from theme import apply_theme
from database import get_db, run_query

st.set_page_config(page_title="Data Explorer", page_icon="📊", layout="wide")
apply_theme()

st.title("📊 Data Explorer")
st.caption("This is the actual demo data behind the chat.")

try:
    db = get_db()
except Exception as e:
    st.error(f"Couldn't connect to the database: {e}")
    st.stop()

tables = db.get_usable_table_names()

if not tables:
    st.warning("No tables found.")
    st.stop()

selected_table = st.selectbox("Choose a table:", tables)

# One "show all" flag per table, so switching tables doesn't carry over
# an expanded view from a different table.
show_all_key = f"show_all_{selected_table}"
if show_all_key not in st.session_state:
    st.session_state[show_all_key] = False

with st.container(border=True):
    st.subheader(selected_table)

    with st.expander("Schema"):
        st.code(db.get_table_info(table_names=[selected_table]), language="sql")

    try:
        columns, rows = run_query(f"SELECT * FROM {selected_table}")
        total = len(rows)
        preview_limit = 10

        if st.session_state[show_all_key] or total <= preview_limit:
            visible_rows = rows
        else:
            visible_rows = rows[:preview_limit]

        st.dataframe([dict(zip(columns, row)) for row in visible_rows], width="stretch")

        if total > preview_limit:
            if st.session_state[show_all_key]:
                st.caption(f"Showing all {total} rows.")
                if st.button("Show fewer"):
                    st.session_state[show_all_key] = False
                    st.rerun()
            else:
                st.caption(f"Showing {preview_limit} of {total} rows.")
                if st.button(f"Show all {total} rows"):
                    st.session_state[show_all_key] = True
                    st.rerun()
        else:
            st.caption(f"{total} rows total.")

    except Exception as e:
        st.error(f"Couldn't load table: {e}")