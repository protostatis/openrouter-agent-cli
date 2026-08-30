#!/usr/bin/env python3
"""Hard task v3: ZeroDivisionError on an empty category; data integrity pinned."""
import hashlib, subprocess, sys
from pathlib import Path

DATA_SHA256 = "e56db3ea1a017df64ca5b3a1e251b4b49a132bea1866d0252cb1817dd090abfb"

def main() -> int:
    workspace = Path(sys.argv[1])
    data = workspace / "orders2.json"
    if not data.is_file() or not (workspace / "averages.py").is_file():
        print("missing files"); return 2
    if hashlib.sha256(data.read_bytes()).hexdigest() != DATA_SHA256:
        print("orders2.json was modified — fix the script, not the data"); return 2
    proc = subprocess.run([sys.executable, "averages.py"], cwd=str(workspace),
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("still crashes: " + (proc.stderr or "").strip().splitlines()[-1][:100]); return 2
    if proc.stdout.strip() != "east 15.0\nsouth 5.0":
        print("wrong output: " + repr(proc.stdout.strip())); return 2
    print("zero-division fix verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
