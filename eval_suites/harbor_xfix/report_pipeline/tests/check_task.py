import subprocess, sys
proc = subprocess.run(["python3","run_report.py"], cwd="/app", capture_output=True, text=True)
expected_lines = ["gadget,55.00,1", "widget,260.00,4"]
if proc.returncode != 0:
    print("crashed:", proc.stderr.strip()[-150:]); sys.exit(2)
out_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
if out_lines != expected_lines:
    print("wrong report:", out_lines); sys.exit(2)
print("verified")
