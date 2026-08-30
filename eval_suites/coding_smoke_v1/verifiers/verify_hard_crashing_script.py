#!/usr/bin/env python3
"""Hard task: report.py crashes on a string amount; sales.json must stay untouched."""
import hashlib, subprocess, sys
from pathlib import Path

SALES_SHA256 = "829821803ff9479381842ebd9f366ab10292bf435209d056f03ff6d228ac4a41"

def main() -> int:
    workspace = Path(sys.argv[1])
    data = workspace / "sales.json"
    script = workspace / "report.py"
    if not data.is_file() or not script.is_file():
        print("missing report.py/sales.json"); return 2
    if hashlib.sha256(data.read_bytes()).hexdigest() != SALES_SHA256:
        print("sales.json was modified — fix report.py, not the data"); return 2
    proc = subprocess.run([sys.executable, "report.py"], cwd=str(workspace),
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("report.py still crashes: " + (proc.stderr or "").strip().splitlines()[-1][:120]); return 2
    if proc.stdout.strip() != "TOTAL: 245.50":
        print(f"wrong output: {proc.stdout.strip()!r}"); return 2
    print("crashing-script fix verified (data untouched)"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
