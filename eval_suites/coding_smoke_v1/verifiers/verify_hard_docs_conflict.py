#!/usr/bin/env python3
"""Hard task: change behavior per the task spec; refresh the stale doc too."""
import subprocess, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    docs = workspace / "docs.md"
    if not docs.is_file():
        print("missing docs.md"); return 2
    if "First Last" not in docs.read_text(encoding="utf-8"):
        print("docs.md still documents the old behavior"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from formatter import format_name; "
         "assert format_name('Ada', 'Lovelace') == 'Ada Lovelace'" % workspace],
        capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("formatter behavior wrong"); return 2
    print("docs-conflict task verified (code + doc updated)"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
