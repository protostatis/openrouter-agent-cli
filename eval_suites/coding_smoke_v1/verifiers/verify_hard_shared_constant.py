#!/usr/bin/env python3
"""Hard task: retry constant must change in config.py AND stay imported by client.py."""
import subprocess, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    config = workspace / "config.py"
    client = workspace / "client.py"
    if not config.is_file() or not client.is_file():
        print("missing config.py/client.py"); return 2
    if "import config" not in client.read_text(encoding="utf-8"):
        print("client.py must keep importing config (no hardcoded retry count)"); return 2
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); from config import MAX_RETRIES; "
         "import client; assert MAX_RETRIES == 5; "
         "assert client.fetch(1) == 'attempt 1 of 5'" % workspace],
        capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("retry policy inconsistent across modules"); return 2
    print("shared-constant verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
