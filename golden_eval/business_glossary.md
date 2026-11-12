# Business glossary (send this to the LLM together with the schema)

Today's date for all relative questions: **2026-06-30** (the data covers 2025-07-01 to 2026-06-30).
Never use NOW() or CURDATE() in queries; use this date.

| Term | Definition |
|---|---|
| Revenue | SUM(order_items.quantity * order_items.unit_price * (1 - COALESCE(orders.discount_pct, 0) / 100)) over orders whose status is `shipped` or `delivered`. Cancelled and returned orders are excluded. |
| Revenue order | An order with status `shipped` or `delivered`. |
| Average order value (AOV) | Revenue divided by the number of revenue orders. |
| Units sold | SUM(order_items.quantity) for orders whose status is not `cancelled`. |
| Discount | `orders.discount_pct`; NULL means no discount, so treat it as 0. |
| Cancelled | Status value is spelled `cancelled` (British spelling). |
| In transit | A shipment with `delivered_at IS NULL`. |
| Late shipment | A delivered shipment where DATE(delivered_at) > promised_date. Late rate uses delivered shipments only as the denominator. |
| Delivery time | DATEDIFF(delivered_at, shipped_at) in days, delivered shipments only. |
| Temperature excursion | A shipment has an excursion if any of its readings is below `min_temp_c` or above `max_temp_c` of any temperature-controlled product (`requires_cold = 1`) in that shipment's order. |
| Excursion rate | Shipments with an excursion divided by shipments that have at least one temperature reading. |
| Return rate | Returned orders divided by orders that were shipped, delivered or returned. |
| Northern region | `regions.name = 'North'`. Likewise West, South, East, Northeast. |
| Bangalore / Bombay | Stored as `Bengaluru` / `Mumbai`. |
| Sensitive data | `employees` (salaries) is admin-only. `customers.email` is PII: do not list it unless asked by an admin. |
