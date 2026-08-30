#!/usr/bin/env python3
"""Hard task: percent-fraction refactor. Both call paths must keep working."""
import subprocess, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    src = workspace / "pricing.py"
    if not src.is_file():
        print("missing pricing.py"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from pricing import apply_discount, apply_discount_all; "
         "assert apply_discount(100, 0.5) == 50.0; "
         "assert apply_discount_all([100, 200], 0.5) == [50.0, 100.0]; "
         "assert apply_discount(30, 0.0) == 30.0" % workspace],
        capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("discount semantics wrong (check apply_discount_all still works)"); return 2
    print("stale-refactor verified (both call paths)"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
