import subprocess, sys, hashlib
data = open("/app/sales.json","rb").read()
if hashlib.sha256(data).hexdigest() != "829821803ff9479381842ebd9f366ab10292bf435209d056f03ff6d228ac4a41":
    print("sales.json was modified"); sys.exit(2)
proc = subprocess.run(["python3","report.py"], cwd="/app", capture_output=True, text=True)
if proc.returncode != 0:
    print("still crashes:", proc.stderr.strip().splitlines()[-1][:120]); sys.exit(2)
if proc.stdout.strip() != "TOTAL: 245.50":
    print("wrong output:", repr(proc.stdout.strip())); sys.exit(2)
print("verified")
