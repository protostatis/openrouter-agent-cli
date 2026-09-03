# format_prices specification

Implement `format_prices.py` in the workspace with one function:

```
def format_prices(prices: list[float]) -> str
```

Rules:

- Round each price to two decimals.
- Format each as US currency: a `$`, thousands separators, two decimals
  (e.g., `$1,234.50`).
- Join the formatted prices with `", "`.
- An empty list returns the empty string `""`.

Examples (these are what the hidden test checks):

- `format_prices([1234.5])` → `"$1,234.50"`
- `format_prices([0.1, 1000])` → `"$0.10, $1,000.00"`
- `format_prices([])` → `""`

Do not print anything at import time. The workspace starts empty except for
this task.