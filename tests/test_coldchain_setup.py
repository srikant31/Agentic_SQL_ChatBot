from unittest.mock import Mock, MagicMock, patch
import pytest
from scripts.setup_coldchain import setup, valid_identifier


@pytest.mark.parametrize("name", ["coldchain;DROP", "../mysql", "a`b", ""])
def test_rejects_unsafe_identifiers(name):
    with pytest.raises(ValueError): valid_identifier(name)


def test_existing_database_is_never_reset(monkeypatch):
    monkeypatch.setenv("MYSQL_HOST", "example.invalid")
    monkeypatch.setenv("MYSQL_USER", "setup-user")
    monkeypatch.setenv("MYSQL_PASSWORD", "not-a-real-password")
    monkeypatch.setenv("MYSQL_DATABASE", "employee_demo")
    monkeypatch.setenv("COLDCHAIN_READONLY_PASSWORD", "test-password-not-real")
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value = Mock()
    cursor.fetchone.return_value = ("existing_fixture",)
    with patch("scripts.setup_coldchain.pymysql.connect", return_value=connection), patch("pathlib.Path.exists", return_value=True):
        with pytest.raises(ValueError, match="already exists"):
            setup("existing_fixture", "new_fixture_user")
    assert cursor.execute.call_count == 1
    assert "SELECT SCHEMA_NAME" in cursor.execute.call_args.args[0]
