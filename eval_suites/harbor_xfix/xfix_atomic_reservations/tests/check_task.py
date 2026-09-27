import json
import os
import subprocess
import sys
import tempfile


def run(inventory, orders):
    with tempfile.TemporaryDirectory() as directory:
        inventory_path = os.path.join(directory, "inventory.json")
        orders_path = os.path.join(directory, "orders.json")
        with open(inventory_path, "w") as fh:
            json.dump(inventory, fh)
        with open(orders_path, "w") as fh:
            json.dump(orders, fh)
        return subprocess.run(
            ["python3", "run_orders.py", inventory_path, orders_path],
            cwd="/app",
            capture_output=True,
            text=True,
        )


def expect(inventory, orders, expected):
    proc = run(inventory, orders)
    if proc.returncode != 0:
        print("crashed:", proc.stderr.strip()[-200:])
        sys.exit(2)
    try:
        actual = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print("invalid JSON:", exc)
        sys.exit(2)
    if actual != expected:
        print("wrong reservation result:", actual, "expected:", expected)
        sys.exit(2)


expect(
    {"A": 5, "B": 3, "C": 2},
    [
        {"id": "o1", "lines": [{"sku": "A", "quantity": 2}, {"sku": "B", "quantity": 1}]},
        {"id": "o2", "lines": [{"sku": "A", "quantity": 2}, {"sku": "A", "quantity": 2}]},
        {"id": "o3", "lines": [{"sku": "A", "quantity": 3}]},
        {"id": "o4", "lines": [{"sku": "B", "quantity": 2}, {"sku": "C", "quantity": 2}]},
        {"id": "o5", "lines": [{"sku": "B", "quantity": 1}]},
        {"id": "o1", "lines": [{"sku": "C", "quantity": 1}]},
    ],
    {"accepted": ["o1", "o3", "o4"], "rejected": ["o2", "o5"], "inventory": {"A": 0, "B": 0, "C": 0}},
)
expect(
    {"A": 4, "B": 2},
    [
        {"id": "a", "lines": [{"sku": "A", "quantity": 4}]},
        {"id": "b", "lines": [{"sku": "B", "quantity": 1}, {"sku": "B", "quantity": 2}]},
        {"id": "a", "lines": [{"sku": "B", "quantity": 1}]},
        {"id": "c", "lines": [{"sku": "B", "quantity": 2}]},
    ],
    {"accepted": ["a", "c"], "rejected": ["b"], "inventory": {"A": 0, "B": 0}},
)
print("verified")
