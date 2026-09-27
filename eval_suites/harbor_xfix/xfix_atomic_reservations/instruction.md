Fix the order reservation program run with
`python3 run_orders.py inventory.json orders.json`.

The inventory and orders are JSON files. Each order has an `id` and a `lines`
array of `{ "sku": STRING, "quantity": POSITIVE_INTEGER }` objects. Process
orders in input order. An order is accepted only when every line can be filled
from the inventory state at the start of that order. If it is rejected,
inventory must remain exactly unchanged. Repeated lines for one SKU must be
combined before checking availability. An unknown SKU rejects the order.

Only the first occurrence of an order ID is processed; later occurrences are
ignored completely. An order with exact available quantities is accepted.

Print one JSON object with exactly these keys: `accepted`, `rejected`, and
`inventory`. The two ID arrays preserve input order, and the inventory object
contains the final quantity for every original SKU. Print no other output. Do
not modify `inventory.json` or `orders.json`.
