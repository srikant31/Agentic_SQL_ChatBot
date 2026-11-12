# RBAC interview demonstration

| Username | Password | Permissions |
|---|---|---|
| employee | employee123 | Engineering rows only; salary hidden; read-only |
| hr | hr123 | All departments and salary; read-only; Data Explorer |
| admin | admin123 | All departments except salary; Data Explorer; approved job-title updates and audit log |

Sign in on the main page. Click **Show my permitted data**, then use **Demonstrate a denied query** to prove restrictions. Employee/admin salary SQL is denied; HR can run it. Only admin can use the Admin page to review and confirm a title update, which is persisted to Aiven and audited. Logout clears pending queries and edits before switching accounts. Deep links to restricted pages also require authentication and authorization.

Accounts and data are intentionally public and fictional. This is basic application-level RBAC, not database GRANT-based identities. Replace demo authentication before connecting private data. Password verification uses PBKDF2 hashes. The backend resolves roles from server-owned identities, not a UI role selector. No credentials or Aiven secrets are committed.

The existing Aiven service hosts RBAC_DEMO_EMPLOYEES and RBAC_DEMO_AUDIT. Original EMPLOYEES records are unchanged. Generated SELECT SQL runs in a read-only, per-query SQLite snapshot fetched fresh from Aiven with only authorized rows and columns. SQLite authorization blocks other tables and file/extension access. This prevents prompt-generated SQL from accessing hidden salary values or other departments. Arbitrary AI writes are blocked for every role. One parameterized backend action permits admin to update JOB_TITLE after confirmation and records an audit event in the same transaction.

Run tests: `python -m pytest tests -q`.
