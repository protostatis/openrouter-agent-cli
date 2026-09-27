import json


def load_jobs(path):
    with open(path) as fh:
        return json.load(fh)
