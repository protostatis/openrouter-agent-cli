#!/usr/bin/env python3
"""Hard task v4: NO crash — silently wrong counts; boundary rule inclusive."""
import hashlib, subprocess, sys
from pathlib import Path

DATA_SHA256 = "6449da709e92c0dad9a4ab46605e8da6078fa1d092a817def1ccc037715642bb"

def main() -> int:
    workspace = Path(sys.argv[1])
    data = workspace / "attendees.json"
    if not data.is_file() or not (workspace / "eligible.py").is_file():
        print("missing files"); return 2
    if hashlib.sha256(data.read_bytes()).hexdigest() != DATA_SHA256:
        print("attendees.json was modified — fix the script, not the data"); return 2
    proc = subprocess.run([sys.executable, "eligible.py"], cwd=str(workspace),
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("script crashes: " + (proc.stderr or "").strip().splitlines()[-1][:100]); return 2
    if proc.stdout.strip() != "ELIGIBLE: 4":
        print("wrong count: " + repr(proc.stdout.strip()) + " (rule is 18 through 65 inclusive)"); return 2
    print("silent off-by-one fix verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
