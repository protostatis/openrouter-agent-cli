#!/usr/bin/env python3
"""Pure JSON-output verifier. argv: spec.json <workspace>."""
import hashlib
import json
import sys
from pathlib import Path


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    workspace = Path(sys.argv[2])
    for name, expected_hash in spec["input_sha256"].items():
        path = workspace / name
        if not path.is_file():
            print(f"missing input: {name}")
            return 2
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            print(f"{name} was modified")
            return 2
    output = workspace / spec["output_name"]
    if not output.is_file():
        print(f"missing output: {spec['output_name']}")
        return 2
    try:
        actual = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"invalid JSON output: {exc}")
        return 2
    if actual != spec["expected"]:
        print(f"wrong output: {actual!r}")
        return 2
    print(f"{spec['output_name']} verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
