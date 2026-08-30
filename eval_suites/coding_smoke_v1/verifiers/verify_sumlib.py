#!/usr/bin/env python3
"""Verifier for the sumlib fix task. argv[1] = agent workspace path."""
import subprocess
import sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    sumlib = workspace / "sumlib.py"
    test = workspace / "test_sumlib.py"
    if not sumlib.is_file():
        print("missing sumlib.py"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from sumlib import add; "
         "assert add(2, 3) == 5, 'add still broken'" % workspace],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        print("add() still broken"); return 2
    if not test.is_file():
        print("missing test_sumlib.py"); return 2
    if "add(2, 3) == 5" not in test.read_text(encoding="utf-8"):
        print("test_sumlib.py missing assertion"); return 2
    print("sumlib verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
