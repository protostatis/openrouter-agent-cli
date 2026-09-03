import subprocess, sys
proc = subprocess.run(["python3","run_report.py"], cwd="/app", capture_output=True, text=True)
expected = 'gadget,55.00,1\nwidget,260.00,4'
sys.exit(0 if proc.stdout.rstrip("\n") == expected else 1)
