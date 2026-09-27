def process_orders(orders, inventory):
    stock = dict(inventory)
    accepted = []
    rejected = []
    for order in orders:
        needed = {}
        for line in order["lines"]:
            sku = line["sku"]
            needed[sku] = needed.get(sku, 0) + line["quantity"]
        ok = True
        for sku, quantity in needed.items():
            if sku not in stock or stock[sku] < quantity:
                ok = False
        if ok:
            for sku, quantity in needed.items():
                stock[sku] -= quantity
            accepted.append(order["id"])
        else:
            rejected.append(order["id"])
    return {"accepted": accepted, "rejected": rejected, "inventory": stock}
