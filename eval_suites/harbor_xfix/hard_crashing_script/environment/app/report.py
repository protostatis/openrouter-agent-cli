import json

with open("sales.json") as fh:
    sales = json.load(fh)

total = sum(row["amount"] for row in sales)
print(f"TOTAL: {total:.2f}")
