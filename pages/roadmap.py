import streamlit as st
from app_auth import require_login
from theme import apply_theme
st.set_page_config(page_title="RBAC demonstration", page_icon="🔐")
apply_theme()
require_login()
st.title("How to demonstrate RBAC")
st.markdown("""
1. **Employee**: Show permitted data → 3 Engineering rows, no SALARY column. Salary SQL and Data Explorer are denied.
2. **HR**: Show permitted data → 6 rows across departments with SALARY. Admin page and SQL UPDATE are denied.
3. **IT admin**: 6 rows without SALARY. Open Admin, review a job-title change, confirm and save; refresh the audit log.

All users can ask the AI questions. SQL execution enforces the same permissions regardless of the wording of a prompt.

This is application-level RBAC using public demo accounts, not Aiven MySQL GRANT-based user roles. Generated SQL runs on a fresh, authorized snapshot from Aiven. The original EMPLOYEES table is unchanged; fictional demo records use separate tables. Replace demo authentication before using this with private records.
""")
