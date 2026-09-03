"""Verifier for the format_duration web task.

Imports the agent's duration.py from the workspace (argv[1]) and checks the
spec's examples exactly. Exit 0 = pass, exit 2 = task_fail.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

EXAMPLES = [
    (3661, "1h 1m 1s"),
    (7200, "2h"),
    (90, "1m 30s"),
    (45, "45s"),
    (0, ""),
    (3601, "1h 1s"),
    (86400, "24h"),
]


def main() -> int:
    workspace = Path(sys.argv[1])
    module_path = workspace / "duration.py"
    if not module_path.is_file():
        print("missing file: duration.py")
        return 2
    spec = importlib.util.spec_from_file_location("duration", module_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        print(f"import failed: {type(exc).__name__}: {exc}")
        return 2
    if not hasattr(module, "format_duration"):
        print("missing function: format_duration")
        return 2
    for seconds, expected in EXAMPLES:
        try:
            got = module.format_duration(seconds)
        except Exception as exc:
            print(f"call failed: format_duration({seconds}) -> {type(exc).__name__}: {exc}")
            return 2
        if got != expected:
            print(f"wrong output: format_duration({seconds}) = {got!r}, expected {expected!r}")
            return 2
    print("verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())