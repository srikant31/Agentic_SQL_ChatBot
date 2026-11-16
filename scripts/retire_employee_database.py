"""Back up the identified old employee database; deletion requires --retire.

No credentials, URLs or row contents are printed. Backups stay outside the repo.
Run from the repository root. MySQL DDL commits immediately; schedule retirement
after switching the deployed app to ColdChain and stopping old employee writes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import ssl
import tempfile

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url


EXPECTED_TABLES = {"EMPLOYEES", "RBAC_DEMO_AUDIT", "RBAC_DEMO_EMPLOYEES"}


def checked_sources(values):
    old = values.get("MYSQL_DATABASE")
    source = make_url(values.get("COLDCHAIN_DB_URL") or values.get("EVAL_DB_URL") or "")
    if old != "defaultdb" or source.database != "coldchain_eval" or old == source.database:
        raise ValueError("Database identities differ from the audited retirement targets.")
    if source.host != values.get("MYSQL_HOST") or source.port != int(values.get("MYSQL_PORT", "3306")):
        raise ValueError("Old and new databases must be on the audited service.")
    if source.username != "coldchain_ro":
        raise ValueError("ColdChain must use its read-only database identity.")
    if dict(source.query) != {"ssl_ca": "ca.pem", "ssl_check_hostname": "true"}:
        raise ValueError("ColdChain TLS settings differ from the verified configuration.")
    admin = URL.create("mysql+pymysql", username=values["MYSQL_USER"],
                       password=values["MYSQL_PASSWORD"], host=values["MYSQL_HOST"],
                       port=int(values["MYSQL_PORT"]),
                       query={"ssl_ca": str(Path("ca.pem").resolve()), "ssl_check_hostname": "true"})
    return old, source, admin


def verify_tls(connection):
    context = connection.connection.driver_connection._sock.context
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("Verified certificate and hostname checks are required.")


def audit(connection, old):
    tables = connection.execute(text("SELECT TABLE_NAME, TABLE_TYPE, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=:s"), {"s": old}).all()
    if {row[0] for row in tables} != EXPECTED_TABLES:
        raise ValueError("Unexpected or missing old tables; refusing retirement.")
    if any(row[1] != "BASE TABLE" or row[2] != "InnoDB" for row in tables):
        raise ValueError("Backup requires only the audited InnoDB tables.")
    for kind, column in (("TRIGGERS", "TRIGGER_SCHEMA"), ("ROUTINES", "ROUTINE_SCHEMA"), ("EVENTS", "EVENT_SCHEMA")):
        count = connection.execute(text(f"SELECT COUNT(*) FROM information_schema.{kind} WHERE {column}=:s"), {"s": old}).scalar_one()
        if count:
            raise ValueError("Unexpected stored objects; refusing retirement.")
    if connection.execute(text("SELECT COUNT(*) FROM information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_SCHEMA=:s AND TABLE_SCHEMA<>:s"), {"s": old}).scalar_one():
        raise ValueError("Another database depends on the old schema; refusing retirement.")


def backup(connection, old):
    directory = Path(tempfile.mkdtemp(prefix="sql-agent-employee-backup-"))
    if directory.resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError("Backup must be outside the repository.")
    destination = directory / "employee-database.sql"
    counts = {}
    connection.commit()
    connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
    raw = connection.connection.driver_connection
    with destination.open("x", encoding="utf-8", newline="\n") as output:
        output.write(f"-- Employee database backup; contains data, keep private.\nCREATE DATABASE IF NOT EXISTS `{old}`;\nUSE `{old}`;\nSET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n")
        for table in sorted(EXPECTED_TABLES):
            ddl = connection.exec_driver_sql(f"SHOW CREATE TABLE `{old}`.`{table}`").one()[1]
            output.write(ddl + ";\n")
            result = connection.exec_driver_sql(f"SELECT * FROM `{old}`.`{table}`")
            columns = ",".join("`" + name.replace("`", "``") + "`" for name in result.keys())
            counts[table] = 0
            for row in result:
                literals = ",".join(raw.literal(value) for value in row)
                output.write(f"INSERT INTO `{table}` ({columns}) VALUES ({literals});\n")
                counts[table] += 1
        output.write("SET FOREIGN_KEY_CHECKS=1;\n")
    connection.rollback()
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "database": old,
                "rows": counts, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "retired": False}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return directory, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retire", action="store_true", help="Back up, then permanently drop the audited old database.")
    args = parser.parse_args()
    old, source, admin = checked_sources(dotenv_values(".env"))
    engines = [create_engine(url, connect_args={"connect_timeout": 10, "read_timeout": 30}) for url in (source, admin)]
    try:
        with engines[0].connect() as current:
            verify_tls(current)
            if current.execute(text("SELECT COUNT(*) FROM customers")).scalar_one() != 60:
                raise ValueError("ColdChain connectivity/count verification failed.")
        with engines[1].connect() as connection:
            verify_tls(connection)
            audit(connection, old)
            directory, manifest = backup(connection, old)
            print("Outside-repository backup:", directory)
            print("Backed-up row counts:", json.dumps(manifest["rows"], sort_keys=True))
            if args.retire:
                audit(connection, old)
                for table, count in manifest["rows"].items():
                    if connection.exec_driver_sql(f"SELECT COUNT(*) FROM `{old}`.`{table}`").scalar_one() != count:
                        raise ValueError("Old database changed since backup; refusing retirement.")
                connection.exec_driver_sql(f"DROP DATABASE `{old}`")
                if connection.execute(text("SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=:s"), {"s": old}).scalar_one():
                    raise RuntimeError("Old schema still exists.")
                manifest["retired"] = True
                (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                print("Retired database:", old)
            else:
                print("Backup only. No database was deleted.")
        with engines[0].connect() as current:
            print("ColdChain customers:", current.execute(text("SELECT COUNT(*) FROM customers")).scalar_one())
    finally:
        for engine in engines:
            engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # SQLAlchemy exceptions can include URLs, statement parameters and row data.
        print("Retirement/backup stopped:", type(error).__name__)
        raise SystemExit(1)
