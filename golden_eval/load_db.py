"""Load schema.sql + seed.sql into a MySQL database (Aiven or local) without the mysql CLI.

PowerShell (one line):
  python load_db.py --host HOST --port PORT --user avnadmin --password PASS --db coldchain --ca ca.pem
--ca is the Aiven CA certificate (download it from your service's Overview page). Omit --ca for a local server.
WARNING: schema.sql DROPs and recreates the ten tables in --db. Use a fresh database, not your current app tables.
"""
import argparse
from pathlib import Path

import pymysql
from pymysql.constants import CLIENT

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=3306)
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--db", default="coldchain")
    ap.add_argument("--ca", help="path to Aiven ca.pem (enables verified SSL)")
    ap.add_argument("--unix-socket")
    ap.add_argument("--ro-user", help="also create this read-only user (SELECT on --db only)")
    ap.add_argument("--ro-password")
    a = ap.parse_args()

    ssl = {"ca": a.ca} if a.ca else None
    kw = dict(user=a.user, password=a.password, ssl=ssl, client_flag=CLIENT.MULTI_STATEMENTS, autocommit=True)
    kw.update({"unix_socket": a.unix_socket} if a.unix_socket else {"host": a.host, "port": a.port})
    conn = pymysql.connect(**kw)
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{a.db}`")
        cur.execute(f"USE `{a.db}`")
        for name in ("schema.sql", "seed.sql"):
            cur.execute((HERE / name).read_text(encoding="utf-8"))
            while cur.nextset():  # drain every statement's result
                pass
            print(f"loaded {name}")
        for t in ("customers", "products", "orders", "order_items", "shipments", "temperature_readings"):
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t:<22} {cur.fetchone()[0]}")
        if a.ro_user:
            cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (a.ro_user, a.ro_password))
            cur.execute(f"GRANT SELECT ON `{a.db}`.* TO %s@'%%'", (a.ro_user,))
            print(f"read-only user '{a.ro_user}' can SELECT on {a.db}.* and nothing else")
    conn.close()
    print("Expected: customers 60, products 30, orders 620, order_items 1448, shipments 589, readings 2945")


if __name__ == "__main__":
    main()
