#!/usr/bin/env python3
"""Verifier for the sum_upto bugfix task. argv[1] = agent workspace."""
import subprocess
import sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    src = workspace / "sumlib2.py"
    test = workspace / "test_sum_upto.py"
    if not src.is_file():
        print("missing sumlib2.py"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from sumlib2 import sum_upto; "
         "assert sum_upto(3) == 6; assert sum_upto(1) == 1; "
         "assert sum_upto(10) == 55" % workspace],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        print("sum_upto still broken"); return 2
    if not test.is_file():
        print("missing test_sum_upto.py"); return 2
    if "sum_upto(3) == 6" not in test.read_text(encoding="utf-8"):
        print("test_sum_upto.py missing assertion"); return 2
    print("sum_upto verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
