import subprocess
import sys

expected = '0 -> 1\n1 -> 2\n2 -> 0'
script = 'chain.py'
proc = subprocess.run(["python3", script], cwd="/app", capture_output=True, text=True)
sys.exit(0 if proc.stdout.rstrip("\n") == expected.rstrip("\n") else 1)
