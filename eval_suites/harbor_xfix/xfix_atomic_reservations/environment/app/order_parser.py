import json


def load_orders(path):
    with open(path) as fh:
        return json.load(fh)
