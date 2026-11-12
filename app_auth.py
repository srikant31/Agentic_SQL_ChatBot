import streamlit as st
from rbac import USERS, authenticate, require, scope_description

def require_login(permission="query"):
    user = USERS.get(st.session_state.get("authenticated_username"))
    if user is None:
        st.title("SQL Agent · RBAC Demo")
        st.caption("Public interview demo. Accounts and employee records below are fictional and intentionally shared.")
        st.table([
            {"Username": "employee", "Password": "employee123", "Permissions": "Engineering department only; no salaries; no edits"},
            {"Username": "hr", "Password": "hr123", "Permissions": "All departments and salaries; no edits"},
            {"Username": "admin", "Password": "admin123", "Permissions": "All departments; edit job titles; no salaries"},
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
