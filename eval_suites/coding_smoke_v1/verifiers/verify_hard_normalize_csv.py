#!/usr/bin/env python3
"""Hard task: multi-rule CSV -> JSON normalization; exact match required."""
import json, sys
from pathlib import Path

EXPECTED = [
    {"name": "Ada Lovelace", "email": "a.lovelace@example.com", "joined": "2026-01-05"},
    {"name": "Grace Hopper", "email": "grace.hopper@example.com", "joined": "2026-05-02"},
    {"name": "Alan Turing", "email": "alan.turing@example.com", "joined": "2026-03-03"},
]

def main() -> int:
    workspace = Path(sys.argv[1])
    out = workspace / "clean.json"
    if not out.is_file():
        print("missing clean.json"); return 2
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        print("clean.json invalid JSON"); return 2
    if data != EXPECTED:
        print("clean.json does not match the normalization rules exactly"); return 2
    print("normalize verified (all rules applied)"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
