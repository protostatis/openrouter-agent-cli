import json
import sys

from order_parser import load_orders
from reservation_engine import process_orders


inventory = json.load(open(sys.argv[1]))
orders = load_orders(sys.argv[2])
print(json.dumps(process_orders(orders, inventory), sort_keys=True, separators=(",", ":")))
