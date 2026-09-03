import json
def build_invoice(items_json):
    items = json.loads(items_json)
    lines = []
    for it in items:
        unit = it["unit_price"] * it["quantity"]
        lines.append({"name": it["name"], "total": unit})
    subtotal = round(sum(l["total"] for l in lines), 2)
    tax = round(subtotal * 0.08, 2)
    return {"lines": lines, "subtotal": subtotal, "tax": tax, "total": round(subtotal + tax, 2)}
