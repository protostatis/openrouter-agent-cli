import subprocess, sys
proc = subprocess.run(["python3","pairs.py"], cwd="/app", capture_output=True, text=True)
if proc.returncode != 0:
    print("still crashes:", proc.stderr.strip().splitlines()[-1][:120]); sys.exit(2)
out = proc.stdout.rstrip("\n")
expected = 'a 1\nb 2'
if out != expected:
    print(f"wrong output: {out!r}, expected {expected!r}"); sys.exit(2)
print("verified")
