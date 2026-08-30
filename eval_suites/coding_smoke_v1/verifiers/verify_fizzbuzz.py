#!/usr/bin/env python3
"""Verifier for fizzbuzz: run fizzbuzz.py, compare exact output 1..15."""
import subprocess, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    src = workspace / "fizzbuzz.py"
    if not src.is_file():
        print("missing fizzbuzz.py"); return 2
    expected = "\n".join(
        "fizzbuzz" if n % 15 == 0 else "fizz" if n % 3 == 0 else "buzz" if n % 5 == 0 else str(n)
        for n in range(1, 16)
    ) + "\n"
    proc = subprocess.run([sys.executable, "fizzbuzz.py"], cwd=str(workspace),
                          capture_output=True, text=True, timeout=20)
    if proc.returncode != 0:
        print("fizzbuzz.py crashed: " + (proc.stderr or "").strip().splitlines()[-1][:150]); return 2
    if proc.stdout != expected:
        print("output mismatch"); return 2
    print("fizzbuzz verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
