import json
import sys

from config_loader import load_config


try:
    result = load_config(sys.argv[1:])
except ValueError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(2)
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
