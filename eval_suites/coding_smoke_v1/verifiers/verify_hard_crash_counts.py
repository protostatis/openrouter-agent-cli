#!/usr/bin/env python3
"""Hard task v2: KeyError crash on missing key; data file integrity pinned."""
import hashlib, subprocess, sys
from pathlib import Path

DATA_SHA256 = "825d296bd1df88f829b04a621d777768f17fa4ec7fef5520349a44f5c26431d2"

def main() -> int:
    workspace = Path(sys.argv[1])
    data = workspace / "orders.json"
    if not data.is_file() or not (workspace / "count_regions.py").is_file():
        print("missing files"); return 2
    if hashlib.sha256(data.read_bytes()).hexdigest() != DATA_SHA256:
        print("orders.json was modified — fix the script, not the data"); return 2
    proc = subprocess.run([sys.executable, "count_regions.py"], cwd=str(workspace),
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("still crashes: " + (proc.stderr or "").strip().splitlines()[-1][:100]); return 2
    if proc.stdout.strip() != "east 2\nwest 2":
        print("wrong output: " + repr(proc.stdout.strip())); return 2
    print("crash-counts fix verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
