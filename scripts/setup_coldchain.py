"""Explicit opt-in setup of a NEW Aiven database; never reset an existing database.

Reads privileged MYSQL_* and COLDCHAIN_READONLY_PASSWORD from local .env/environment.
Creates the fixture database and a new SELECT-only user, then writes private URL settings
to the ignored .env file. No credentials are printed or passed as CLI arguments.
"""
import argparse
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv, set_key
import pymysql
from pymysql.constants import CLIENT
from sqlalchemy.engine import URL


def valid_identifier(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", value):
        raise ValueError("Use a database/user name containing letters, numbers and underscores only.")
    return value


def setup(database, readonly_user):
    load_dotenv(ROOT / ".env")
    database, readonly_user = valid_identifier(database), valid_identifier(readonly_user)
    if database.lower() in {os.getenv("MYSQL_DATABASE", "").lower(), "mysql", "information_schema", "performance_schema", "sys"}:
        raise ValueError("Choose a NEW database, separate from the existing employee database.")
    password = os.getenv("COLDCHAIN_READONLY_PASSWORD", "")
    if len(password) < 16:
        raise ValueError("Set COLDCHAIN_READONLY_PASSWORD to a new password of at least 16 characters in local .env first.")
    certificate = ROOT / "ca.pem"
    if not certificate.exists():
        raise ValueError("Put the Aiven CA certificate at ca.pem before setup.")
    connection = pymysql.connect(host=os.environ["MYSQL_HOST"], port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        ssl={"ca": str(certificate), "check_hostname": True},
        client_flag=CLIENT.MULTI_STATEMENTS, autocommit=True, connect_timeout=10, read_timeout=60)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (database,))
            if cursor.fetchone():
                raise ValueError("Database already exists. Nothing was reset; choose a new name.")
            # No IF NOT EXISTS: a concurrent creation must fail rather than reset existing tables.
            cursor.execute(f"CREATE DATABASE `{database}`")
            cursor.execute(f"USE `{database}`")
            for filename in ("schema.sql", "seed.sql"):
                cursor.execute((ROOT / "golden_eval" / filename).read_text(encoding="utf-8"))
                while cursor.nextset():
                    pass
            # CREATE USER fails if the name already exists; never rotate/reuse another identity.
            cursor.execute("CREATE USER %s@'%%' IDENTIFIED BY %s", (readonly_user, password))
            cursor.execute(f"GRANT SELECT ON `{database}`.* TO %s@'%%'", (readonly_user,))
    finally:
        connection.close()
    url = URL.create("mysql+pymysql", username=readonly_user, password=password,
        host=os.environ["MYSQL_HOST"], port=int(os.getenv("MYSQL_PORT", "3306")), database=database,
        query={"ssl_ca": "ca.pem", "ssl_verify_cert": "true", "ssl_verify_identity": "true"})
    # .env is gitignored. The existing MYSQL_* settings remain unchanged.
    for key in ("COLDCHAIN_DB_URL", "EVAL_DB_URL"):
        set_key(str(ROOT / ".env"), key, url.render_as_string(hide_password=False))
    print("Created the new ColdChain database and SELECT-only user. Private URLs saved to local .env.")
    print("The existing employee database was not modified. Run the oracle check before deploying.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--readonly-user", required=True)
    args = parser.parse_args()
    try:
        setup(args.database, args.readonly_user)
    except Exception as exc:
        # Driver errors can include connection details; print only a safe local validation message.
        message = str(exc) if type(exc) is ValueError else type(exc).__name__
        print("Setup stopped: " + message)
        print("A partial NEW database/user may remain if provisioning failed. No existing database was reset.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
