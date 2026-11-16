"""Production entry point: ColdChain is the only registered database workflow."""
import streamlit as st
from observability import load_streamlit_settings

load_streamlit_settings()

# Explicit navigation disables discovery of historical employee pages, including
# direct links to unregistered routes. Never initialize the old demo here.
st.navigation([
    st.Page("pages/coldchain.py", title="ColdChain analytics", icon="📦", default=True),
], position="hidden").run()
