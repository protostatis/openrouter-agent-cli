#!/usr/bin/env python3
"""Verifier for the greet task. argv[1] = agent workspace path.
Exit 0 = pass, 2 = task_fail. Runs host-side, outside the agent workspace."""
import subprocess
import sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    greet = workspace / "greet.py"
    test = workspace / "test_greet.py"
    if not greet.is_file():
        print("missing greet.py"); return 2
    if "hello from greet" not in greet.read_text(encoding="utf-8"):
        print("greet.py wrong content"); return 2
    if not test.is_file():
        print("missing test_greet.py"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from greet import greet; "
         "assert greet() == 'hello from greet', 'wrong value'" % workspace],
        capture_output=True, text=True, timeout=20,
    )
    if proc.returncode != 0:
        print("greet() failed: " + (proc.stderr or "").strip().splitlines()[-1][:200]); return 2
    print("greet verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
