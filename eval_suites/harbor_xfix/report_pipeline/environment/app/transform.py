def process(records, config):
    # BUG 1: uses > instead of >= (the exactly-at-threshold record is dropped)
    # BUG 2: groups by region, ignoring config.group ("product")
    eligible = [r for r in records if r["status"] != config.exclude and r["amount"] > config.threshold]
    groups = {}
    for r in eligible:
        key = r["region"]
        groups.setdefault(key, []).append(r)
    return groups
