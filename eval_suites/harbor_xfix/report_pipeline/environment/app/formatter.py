def format_report(records, groups):
    # BUG 3: count is computed over ALL eligible records, not this group's
    lines = []
    for key in sorted(groups):
        total = round(sum(r["amount"] for r in groups[key]), 2)
        count = len([r for r in records if r["status"] != "void"])
        lines.append(f"{key},{total:.2f},{count}")
    return "\n".join(lines)
