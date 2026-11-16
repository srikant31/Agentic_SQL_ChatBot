"""Historical employee UI test harness; never registered in production navigation."""
import streamlit as st
import config
from app_auth import require_login
from employee_chat_ui import render_employee_chat

st.set_page_config(page_title="Historical employee test harness")
render_employee_chat(require_login())
