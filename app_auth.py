import os
import streamlit as st
from rbac import USERS, authenticate, require, scope_description

def coldchain_role(user):
    """New-domain sensitive access is explicit, never inherited from employee roles."""
    admins = {name.strip() for name in os.getenv("COLDCHAIN_ADMIN_USERS", "").split(",") if name.strip()}
    return "admin" if user.username in admins else "viewer"


def require_login(permission="query", *, domain="employee"):
    coldchain = domain == "coldchain"
    user = USERS.get(st.session_state.get("authenticated_username"))
    if user is None:
        st.title("ColdChain SQL Agent" if coldchain else "SQL Agent · RBAC Demo")
        st.caption("Public interview demo. Accounts and records are fictional and intentionally shared.")
        st.table([
            {"Username": name, "Password": password,
             "Permissions": (f"ColdChain {coldchain_role(USERS[name])}; read-only queries; separate execution approval"
                             if coldchain else permissions)}
            for name, password, permissions in [
                ("employee", "employee123", "Engineering department only; no salaries; no edits"),
                ("hr", "hr123", "All departments and salaries; no edits"),
                ("admin", "admin123", "All departments; edit job titles; no salaries"),
            ]
        ])
        with st.form("login"):
            name = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            authenticated = authenticate(name.strip().lower(), password)
            if authenticated:
                st.session_state.clear()
                st.session_state.authenticated_username = authenticated.username
                st.rerun()
            else:
                st.error("Incorrect username or password.")
        st.stop()
    with st.sidebar:
        st.subheader(f"Signed in: {user.username}")
        st.caption(f"Role: {coldchain_role(user) if coldchain else user.role}")
        if coldchain:
            st.info("ColdChain analytics · read-only. Viewer access excludes employee records, email and salaries. Sensitive access requires an explicit admin allowlist.")
        else:
            st.info(scope_description(user))
        if st.button("Log out / switch account"):
            st.session_state.clear()
            st.rerun()
    try:
        require(user, permission)
    except PermissionError as exc:
        st.error(f"Access denied: {exc}")
        st.stop()
    return user
