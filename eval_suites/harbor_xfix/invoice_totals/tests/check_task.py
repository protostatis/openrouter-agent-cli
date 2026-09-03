import subprocess, sys
expected = 'widget 90.00\ngadget 23.75\ntrinket 6.00\nSUBTOTAL: 119.75\nTAX: 9.58\nTOTAL: 129.33'
proc = subprocess.run(["python3", "run_invoice.py"], cwd="/app", capture_output=True, text=True)
out = proc.stdout.rstrip("\n")
if proc.returncode != 0:
    print(f"script crashed: {proc.stderr.strip()}"); sys.exit(2)
if out != expected:
    print(f"wrong output:\n{out}\nexpected:\n{expected}"); sys.exit(2)
print("verified")
