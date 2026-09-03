import json
from invoices import build_invoice
items = open("orders.json").read()
inv = build_invoice(items)
for line in inv["lines"]:
    print(f'{line["name"]} {line["total"]:.2f}')
print(f'SUBTOTAL: {inv["subtotal"]:.2f}')
print(f'TAX: {inv["tax"]:.2f}')
print(f'TOTAL: {inv["total"]:.2f}')
