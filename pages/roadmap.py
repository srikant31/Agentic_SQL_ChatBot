import streamlit as st

st.set_page_config(page_title="Roadmap", page_icon="🚧")
st.title("🚧 What's being built next")
st.caption("This app is a work in progress — here's what's actively planned.")

st.markdown("""
- **Multi-database support** — connect your own DB, not just the demo Employees table
- **Authentication** — a login so the app knows who's asking
- **Role-based access control** — different users see different data
- **Permission-aware UI** — show each user what they can actually query
""")