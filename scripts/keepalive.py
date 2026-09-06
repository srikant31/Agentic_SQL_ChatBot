import os
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = quote_plus(os.getenv("MYSQL_PASSWORD"))
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = os.getenv("MYSQL_PORT")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")

DB_URI = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?ssl_ca=ca.pem"

engine = create_engine(DB_URI)
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
    print("Keepalive ping successful.")