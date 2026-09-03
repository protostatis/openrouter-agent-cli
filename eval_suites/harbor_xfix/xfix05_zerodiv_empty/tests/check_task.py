import subprocess, sys
proc = subprocess.run(["python3","avgshare.py"], cwd="/app", capture_output=True, text=True)
if proc.returncode != 0:
    print("still crashes:", proc.stderr.strip().splitlines()[-1][:120]); sys.exit(2)
out = proc.stdout.rstrip("\n")
expected = 'east 15.0\nsouth 5.0'
if out != expected:
    print(f"wrong output: {out!r}, expected {expected!r}"); sys.exit(2)
print("verified")
