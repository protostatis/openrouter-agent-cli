#!/usr/bin/env python3
"""Verifier for the dedup task. argv[1] = agent workspace. 0=pass, 2=fail."""
import subprocess, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    if not (workspace / "dedup.py").is_file():
        print("missing dedup.py"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from dedup import dedup; "
         "assert dedup([1, 2, 1, 3, 2]) == [1, 2, 3]; "
         "assert dedup([]) == []; assert dedup(['a', 'a']) == ['a']" % workspace],
        capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("dedup() behavior wrong"); return 2
    if not (workspace / "test_dedup.py").is_file():
        print("missing test_dedup.py"); return 2
    print("dedup verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
