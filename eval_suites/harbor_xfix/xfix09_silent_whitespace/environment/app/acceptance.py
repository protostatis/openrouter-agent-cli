import subprocess
import sys

expected = 'UNIQUE: 3'
script = 'uniq.py'
proc = subprocess.run(["python3", script], cwd="/app", capture_output=True, text=True)
sys.exit(0 if proc.stdout.rstrip("\n") == expected.rstrip("\n") else 1)
