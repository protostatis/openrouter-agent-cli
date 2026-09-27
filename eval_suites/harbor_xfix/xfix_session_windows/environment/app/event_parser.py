import json


def load_events(path):
    events = []
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            events.append({"user": row["user"], "ts": row["ts"]})
    return events
