"""Department access policy for ColdChain: which tables and columns each department may query.

One place defines access. The schema loader shows the model only the allowed tables and columns,
and the SQL validator rejects anything outside them, so a cleverly worded question cannot reach
another department's data even if the model is tricked into writing such SQL.

Keys are ColdChain roles. "viewer" is the general business role (all business tables, no personal
or salary data); "admin" sees everything. Admin is never inherited from an account: it is granted
only through the COLDCHAIN_ADMIN_USERS allowlist.
"""
ALL_TABLES = ("regions", "warehouses", "carriers", "products", "customers", "employees",
              "orders", "order_items", "shipments", "temperature_readings")
MONEY_COLUMNS = {"unit_price", "discount_pct", "freight_cost"}

POLICY = {
    "viewer": {"label": "General", "tables": set(ALL_TABLES) - {"employees"}, "hidden": {"email", "salary_inr"}},
    "sales": {"label": "Sales", "tables": {"customers", "orders", "order_items", "products", "regions"},
              "hidden": {"email"}},
    "operations": {"label": "Operations", "tables": {"shipments", "carriers", "warehouses", "temperature_readings",
                                                     "orders", "products", "regions"},
                   "hidden": set(MONEY_COLUMNS)},
    "finance": {"label": "Finance", "tables": {"orders", "order_items", "products", "customers", "regions",
                                               "shipments", "carriers", "warehouses"}, "hidden": {"email"}},
    "hr": {"label": "HR", "tables": {"employees", "warehouses", "regions"}, "hidden": set()},
    "admin": {"label": "Admin", "tables": set(ALL_TABLES), "hidden": set()},
}
ROLES = tuple(POLICY)

# Which team to ask when a table is outside your department (shown in refusals).
TABLE_OWNERS = {"customers": "Sales", "orders": "Sales", "order_items": "Sales or Finance", "products": "Sales",
                "shipments": "Operations", "carriers": "Operations", "warehouses": "Operations",
                "temperature_readings": "Operations", "employees": "HR", "regions": "any department"}
COLUMN_OWNERS = {"email": "an admin", "salary_inr": "HR", "unit_price": "Finance", "discount_pct": "Finance",
                 "freight_cost": "Finance"}

# Demo account -> department. Admin comes only from the allowlist, never from this mapping.
ACCOUNT_DEPARTMENTS = {"employee": "viewer", "sales": "sales", "ops": "operations", "finance": "finance", "hr": "hr",
                       "admin": "viewer"}

PLAIN_NAMES = {"regions": "regions", "warehouses": "warehouses", "carriers": "carriers", "products": "products",
               "customers": "customers", "employees": "employees", "orders": "orders", "order_items": "order lines",
               "shipments": "shipments", "temperature_readings": "temperature readings"}
PLAIN_COLUMNS = {"email": "customer emails", "salary_inr": "salaries", "unit_price": "prices",
                 "discount_pct": "discounts", "freight_cost": "freight costs"}


def check_role(role):
    if role not in POLICY:
        raise ValueError("Unknown analytics role.")
    return POLICY[role]


def allowed_tables(role):
    return set(check_role(role)["tables"])


def hidden_columns(role):
    return set(check_role(role)["hidden"])


def label(role):
    return check_role(role)["label"]


def scope_text(role):
    """Plain-English description of what this department can ask about."""
    policy = check_role(role)
    if role == "admin":
        return "Admin: every table and column, plus the Data Explorer and conversation logs. Read-only."
    tables = ", ".join(PLAIN_NAMES[t] for t in ALL_TABLES if t in policy["tables"])
    hidden = ", ".join(PLAIN_COLUMNS[c] for c in sorted(policy["hidden"]))
    return f"{policy['label']}: you can ask about {tables}." + (f" Not included: {hidden}." if hidden else "") + " Read-only."


def outside_scope_text(role):
    """For the model: what this department cannot see and which team owns it (no data, names only)."""
    policy = check_role(role)
    missing = [t for t in ALL_TABLES if t not in policy["tables"]]
    if not missing and not policy["hidden"]:
        return ""
    parts = [f"{PLAIN_NAMES[t]} ({TABLE_OWNERS[t]})" for t in missing]
    parts += [f"{PLAIN_COLUMNS[c]} ({COLUMN_OWNERS[c]})" for c in sorted(policy["hidden"])]
    return ("The user's department is " + policy["label"] + ". Not available to this department: " + "; ".join(parts)
            + ". If the question needs any of these, refuse and say which team can answer it.")
