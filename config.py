import os
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()


# Streamlit Cloud has no way to "upload" ca.pem alongside secrets — only
# key/value strings. So: if ca.pem isn't already sitting on disk (which it
# will be locally), write it from an AIVEN_CA_CERT secret instead.
if not os.path.exists("ca.pem"):
    _ca_cert = os.getenv("AIVEN_CA_CERT")
    if _ca_cert:
        with open("ca.pem", "w") as _f:
            _f.write(_ca_cert)


MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ktl")

DB_URI = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?ssl_ca=ca.pem"

SAMPLE_QUESTIONS = [
    "Select a sample question...",
    "Tell me the manager's name for each employee along with their employee ID and manager ID. If no manager exists, return 'CEO' as the manager name and 0 as the manager ID.",
    "Who is Bob Brown's manager?",
    "How many employees report directly to Jane Smith?",
    "List all employees who have no manager.",
    "Which employee has the most direct reports?",
    "Show me the full reporting chain for Hannah Clark.",
]

MAX_QUESTIONS_PER_SESSION = 15