#!/usr/bin/env python3
"""Verifier for the csv-total task: total.txt must hold the exact sum."""
from pathlib import Path
import sys

def main() -> int:
    workspace = Path(sys.argv[1])
    total = workspace / "total.txt"
    if not total.is_file():
        print("missing total.txt"); return 2
    if total.read_text(encoding="utf-8").strip() != "150":
        print("total.txt wrong value (expected 150)"); return 2
    print("csv total verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
