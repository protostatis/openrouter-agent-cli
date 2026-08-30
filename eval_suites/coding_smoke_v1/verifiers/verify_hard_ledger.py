#!/usr/bin/env python3
"""Hard task: stateful ledger with skip-overdraw rule; order matters."""
import json, sys
from pathlib import Path

EXPECTED = {"a": 0, "b": 50, "c": 40}

def main() -> int:
    workspace = Path(sys.argv[1])
    out = workspace / "final_balances.json"
    if not out.is_file():
        print("missing final_balances.json"); return 2
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        print("final_balances.json invalid JSON"); return 2
    if data != EXPECTED:
        print(f"balances wrong: expected {EXPECTED}, got {data}"); return 2
    print("ledger verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
