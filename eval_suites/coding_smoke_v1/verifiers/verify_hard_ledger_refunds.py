#!/usr/bin/env python3
"""Hard task: ledger with refunds; refund applies only if it does not overdraw."""
import json, sys
from pathlib import Path

EXPECTED = {"x": 30, "y": 80}

def main() -> int:
    workspace = Path(sys.argv[1])
    out = workspace / "final_balances.json"
    if not out.is_file():
        print("missing final_balances.json"); return 2
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        print("invalid JSON"); return 2
    if data != EXPECTED:
        print(f"balances wrong: expected {EXPECTED}, got {data}"); return 2
    print("refund ledger verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
