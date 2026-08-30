#!/usr/bin/env python3
"""Verifier for the json config update task."""
import json, sys
from pathlib import Path

def main() -> int:
    workspace = Path(sys.argv[1])
    target = workspace / "config_new.json"
    if not target.is_file():
        print("missing config_new.json"); return 2
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        print("config_new.json is not valid JSON"); return 2
    if data.get("retries") != 5:
        print("retries must be 5"); return 2
    if data.get("host") != "api.example.com" or data.get("port") != 8080:
        print("other fields must be unchanged"); return 2
    print("config update verified"); return 0

if __name__ == "__main__":
    raise SystemExit(main())
