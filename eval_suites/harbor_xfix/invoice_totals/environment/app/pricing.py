def price_with_discount(base_price, quantity):
    discount = 0.10 if quantity > 10 else (0.05 if quantity > 5 else 0.0)
    return round(base_price * quantity * (1 - discount), 2)
