import subprocess
import sys

expected = '0 -> 1\n1 -> 2\n2 -> 0'
script = 'chain.py'
proc = subprocess.run(["python3", script], cwd="/app", capture_output=True, text=True)
out = proc.stdout.rstrip("\n")
expected = expected.rstrip("\n")
if proc.returncode != 0:
    print(f"script crashed: {proc.stderr.strip()}")
    sys.exit(2)
if out != expected:
    print(f"wrong output: {out!r}, expected {expected!r}")
    sys.exit(2)
print("verified")
