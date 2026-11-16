"""Item 8: plain-English comparison between two versions of a query. No model calls."""
import query_insight as qi

MARCH = "SELECT COUNT(*) AS orders_placed FROM orders WHERE order_date >= '2026-03-01' AND order_date < '2026-04-01' LIMIT 100"
DELIVERED = ("SELECT COUNT(*) AS delivered_orders FROM orders WHERE status = 'delivered' "
             "AND order_date >= '2026-03-01' AND order_date < '2026-04-01' LIMIT 100")


def test_added_filter_and_renamed_output_are_reported_with_what_stayed_the_same():
    result = qi.compare(MARCH, DELIVERED)
    assert result["changes"] == ["Added filter: order status is delivered",
                                 "Output renamed: 'orders_placed' → 'delivered_orders'"]
    assert "tables read (orders)" in result["unchanged"]
    assert "filters: order date from 2026-03-01 up to (not including) 2026-04-01" in result["unchanged"]


def test_removed_filter_new_tables_grouping_sorting_and_limit():
    regional = ("SELECT r.name AS region, COUNT(*) AS delivered_orders FROM orders o JOIN customers c "
                "ON c.customer_id = o.customer_id JOIN regions r ON r.region_id = c.region_id "
                "WHERE o.order_date >= '2026-03-01' AND o.order_date < '2026-04-01' "
                "GROUP BY r.name ORDER BY delivered_orders DESC LIMIT 10")
    changes = qi.compare(DELIVERED, regional)["changes"]
    for expected in ("Now also reads: customers", "Now also reads: regions", "Removed filter: order status is delivered",
                     "Now grouped by: region name", "New output: region name (shown as 'region')",
                     "Row limit changed: 100 → 10"):
        assert expected in changes
    assert any(c.startswith("Sorting changed: delivered orders (highest first)") for c in changes)


def test_identical_queries_have_no_changes_and_unreadable_sql_returns_none():
    assert qi.compare(MARCH, MARCH)["changes"] == []
    assert qi.compare(MARCH, "SELEC nonsense (((") is None


def test_sql_diff_marks_changed_lines():
    diff = qi.sql_diff(MARCH, DELIVERED)
    assert diff.startswith("--- previous") and "+  status = 'delivered'" in diff.replace("\n", "\n")
