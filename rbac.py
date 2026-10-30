"""Server-owned identities for a public interview demo."""
from dataclasses import dataclass
import hashlib
import hmac

class AccessDenied(PermissionError):
    pass

@dataclass(frozen=True)
class User:
    username: str
    role: str
    department: str | None = None

USERS = {
    "employee": User("employee", "employee", "Engineering"),
    "hr": User("hr", "hr"),
    "admin": User("admin", "it_admin"),
}
PERMISSIONS = {
    "employee": {"query"},
    "hr": {"query", "salary", "explorer"},
    "it_admin": {"query", "explorer", "edit_title", "diagnostics"},
}
PASSWORD_HASHES = {'employee': '78e46c21edfe1c22388d785daf07eb0c5e032c4d453fd84ce25d1d7858354c16', 'hr': 'c51f9ec7dee882c2d6f7da122ff37bcd1d5ee983386a28e9df930e10c7974202', 'admin': '901521873fd80a08b5c9556039407cdf3355ca54875bb62bb521b498b31acf09'}  # Populated with PBKDF2 hashes, never real account passwords.

def authenticate(username, password):
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), b"sql-rbac-demo-v1", 120000).hex()
    expected = PASSWORD_HASHES.get(username, "0" * 64)
    return USERS.get(username) if hmac.compare_digest(candidate, expected) else None

def check_user(user):
    if not isinstance(user, User) or USERS.get(user.username) != user:
        raise AccessDenied("Sign in with a valid demo account.")

def allowed(user, permission):
    check_user(user)
    return permission in PERMISSIONS[user.role]

def require(user, permission):
    if not allowed(user, permission):
        raise AccessDenied(f"Your {user.role} role cannot perform this action.")

def visible_columns(user):
    check_user(user)
    columns = ["EMPLOYEE_ID", "NAME", "DEPARTMENT", "JOB_TITLE", "MANAGER_NAME"]
    if allowed(user, "salary"):
        columns.append("SALARY")
    return columns

def scope_description(user):
    check_user(user)
    return {
        "employee": "Engineering rows only. Salaries hidden. Read-only.",
        "hr": "All departments and fictional salaries. Read-only.",
        "it_admin": "All departments. Salaries hidden. Job-title edits require confirmation.",
    }[user.role]
