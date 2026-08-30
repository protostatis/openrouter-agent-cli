#!/usr/bin/env python3
"""Generic crash-family verifier. argv: spec.json <workspace appended>."""
import hashlib, json, subprocess, sys
from pathlib import Path

def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    workspace = Path(sys.argv[2])
    data = workspace / spec["data_name"]
    script = workspace / spec["script_name"]
    if not data.is_file() or not script.is_file():
        print("missing files"); return 2
    if hashlib.sha256(data.read_bytes()).hexdigest() != spec["data_sha256"]:
        print(f"{spec['data_name']} was modified - fix the script, not the data"); return 2
    proc = subprocess.run([sys.executable, spec["script_name"]], cwd=str(workspace),
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("script fails: " + (proc.stderr or "").strip().splitlines()[-1][:120]); return 2
    if proc.stdout.strip() != spec["expected_stdout"].strip():
        print("wrong output: " + repr(proc.stdout.strip()[:200])); return 2
    print("verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
