"""Production entry point: ColdChain is the only registered database workflow."""
import streamlit as st
from observability import load_streamlit_settings

load_streamlit_settings()

# Explicit navigation disables discovery of historical employee pages, including
# direct links to unregistered routes. Never initialize the old demo here.
pages = [st.Page("pages/coldchain.py", title="ColdChain analytics", icon="📦", default=True)]

# The Data Explorer is registered only for a signed-in ColdChain admin, so it has no menu entry and
# no working address for anyone else. The page also re-checks the role itself.
from app_auth import coldchain_role  # noqa: E402
from rbac import USERS  # noqa: E402

user = USERS.get(st.session_state.get("authenticated_username"))
if user is not None and coldchain_role(user) == "admin":
    pages.append(st.Page("pages/coldchain_explorer.py", title="Data Explorer", icon="🔎"))
st.navigation(pages, position="sidebar" if len(pages) > 1 else "hidden").run()
