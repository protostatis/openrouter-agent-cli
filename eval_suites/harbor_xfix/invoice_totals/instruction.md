Fix the pricing system so run_invoice.py prints EXACTLY this report:
```
widget 90.00
gadget 23.75
trinket 6.00
SUBTOTAL: 119.75
TAX: 9.58
TOTAL: 129.33
```
Do not modify orders.json. The report is built by run_invoice.py, which uses pricing.py and invoices.py. Do not modify run_invoice.py. Note that some items in orders.json may not be real line items.
