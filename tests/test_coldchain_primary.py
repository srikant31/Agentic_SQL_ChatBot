"""The primary app fails closed and never provisions the retired employee source."""
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from app_auth import coldchain_role
from rbac import USERS
from scripts.retire_employee_database import checked_sources


ROOT = Path(__file__).resolve().parents[1]


def test_missing_coldchain_configuration_never_falls_back(monkeypatch):
    monkeypatch.delenv("COLDCHAIN_DB_URL", raising=False)
    monkeypatch.delenv("EVAL_DB_URL", raising=False)
    with patch("observability.load_streamlit_settings"), patch("database.ensure_demo") as initialize, patch("database.get_engine") as legacy, patch("coldchain_context.get_coldchain_engine") as source:
        app = AppTest.from_file(str(ROOT / "sqlapp.py"), default_timeout=20)
        app.session_state["authenticated_username"] = "employee"
        app.run()
        assert not app.exception
        assert any("ColdChain is not configured" in item.value for item in app.error)
        initialize.assert_not_called()
        legacy.assert_not_called()
        source.assert_not_called()
        assert not app.chat_input


def test_employee_roles_do_not_grant_coldchain_admin_access(monkeypatch):
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", "")
    roles = {name: coldchain_role(user) for name, user in USERS.items()}
    assert "admin" not in roles.values()                       # no account is admin without the allowlist
    assert roles == {"employee": "viewer", "hr": "hr", "admin": "viewer", "sales": "sales",
                     "ops": "operations", "finance": "finance"}
    monkeypatch.setenv("COLDCHAIN_ADMIN_USERS", " hr ")
    assert coldchain_role(USERS["hr"]) == "admin"
    assert coldchain_role(USERS["admin"]) == "viewer"


@pytest.mark.parametrize("change", [
    {"MYSQL_DATABASE": "coldchain_eval"},
    {"MYSQL_DATABASE": "another_database"},
    {"MYSQL_HOST": "another-host.invalid"},
    {"COLDCHAIN_DB_URL": "mysql+pymysql://coldchain_ro:fixture@host.invalid:3306/coldchain_eval?ssl_ca=ca.pem&ssl_check_hostname=false"},
    {"COLDCHAIN_DB_URL": "mysql+pymysql://root:fixture@host.invalid:3306/coldchain_eval?ssl_ca=ca.pem&ssl_check_hostname=true"},
])
def test_retirement_refuses_changed_targets_or_weaker_tls(change):
    values = {"MYSQL_DATABASE": "defaultdb", "MYSQL_HOST": "host.invalid", "MYSQL_PORT": "3306",
              "MYSQL_USER": "fixture", "MYSQL_PASSWORD": "fixture",
              "COLDCHAIN_DB_URL": "mysql+pymysql://coldchain_ro:fixture@host.invalid:3306/coldchain_eval?ssl_ca=ca.pem&ssl_check_hostname=true"}
    values.update(change)
    with pytest.raises(ValueError):
        checked_sources(values)
