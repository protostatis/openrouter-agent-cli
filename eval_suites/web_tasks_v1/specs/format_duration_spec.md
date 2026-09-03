# format_duration specification

Implement `duration.py` in the workspace with one function:

```
def format_duration(seconds: int) -> str
```

Rules:

- Split the seconds into hours, minutes, and remaining seconds.
- Omit any unit whose value is zero.
- Use `h`, `m`, `s` suffixes; join non-empty parts with a single space.
- Zero seconds returns the empty string `""`.

Examples (what the hidden test checks):

- `format_duration(3661)` → `"1h 1m 1s"`
- `format_duration(7200)` → `"2h"`
- `format_duration(90)` → `"1m 30s"`
- `format_duration(45)` → `"45s"`
- `format_duration(0)` → `""`

Do not print anything at import time. The workspace starts empty.
