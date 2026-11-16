import os
import streamlit as st
from rbac import USERS, authenticate, require, scope_description

def coldchain_role(user):
    """ColdChain department for this account. Admin is explicit (COLDCHAIN_ADMIN_USERS allowlist) and is
    never inherited from an account; everyone else gets their account's department."""
    from departments import ACCOUNT_DEPARTMENTS
    admins = {name.strip() for name in os.getenv("COLDCHAIN_ADMIN_USERS", "").split(",") if name.strip()}
    return "admin" if user.username in admins else ACCOUNT_DEPARTMENTS.get(user.username, "viewer")


def require_login(permission="query", *, domain="employee"):
    coldchain = domain == "coldchain"
    user = USERS.get(st.session_state.get("authenticated_username"))
    if user is None:
        st.title("ColdChain SQL Agent" if coldchain else "SQL Agent · RBAC Demo")
        st.caption("Public interview demo. Accounts and records are fictional and intentionally shared.")
        accounts = [("employee", "employee123", "Engineering department only; no salaries; no edits"),
                    ("hr", "hr123", "All departments and salaries; no edits"),
                    ("admin", "admin123", "All departments; edit job titles; no salaries")]
        if coldchain:
            from departments import scope_text
            accounts += [("sales", "sales123", ""), ("ops", "ops123", ""), ("finance", "finance123", "")]
        st.table([
            {"Username": name, "Password": password,
             "Access": scope_text(coldchain_role(USERS[name])) if coldchain else permissions}
            for name, password, permissions in accounts
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
        if coldchain:
            from departments import label, scope_text
            st.caption(f"Department: {label(coldchain_role(user))}")
            st.info(scope_text(coldchain_role(user)))
        else:
            st.caption(f"Role: {user.role}")
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
