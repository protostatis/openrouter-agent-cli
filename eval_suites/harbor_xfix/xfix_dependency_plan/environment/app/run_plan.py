import json
import sys

from job_loader import load_jobs
from planner import plan


try:
    result = plan(load_jobs(sys.argv[1]))
except ValueError as exc:
    print(json.dumps({"error": str(exc)}, separators=(",", ":")))
    raise SystemExit(2)
print(json.dumps(result, separators=(",", ":")))
