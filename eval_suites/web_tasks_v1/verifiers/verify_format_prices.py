"""Verifier for the format_prices web task.

Imports the agent's format_prices.py from the workspace (argv[1]) and checks
the spec's examples exactly. Exit 0 = pass, exit 2 = task_fail.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

EXAMPLES = [
    ([1234.5], "$1,234.50"),
    ([0.1, 1000], "$0.10, $1,000.00"),
    ([], ""),
    ([2], "$2.00"),
    ([1234567.891], "$1,234,567.89"),
]


def main() -> int:
    workspace = Path(sys.argv[1])
    module_path = workspace / "format_prices.py"
    if not module_path.is_file():
        print("missing file: format_prices.py")
        return 2
    spec = importlib.util.spec_from_file_location("format_prices", module_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        print(f"import failed: {type(exc).__name__}: {exc}")
        return 2
    if not hasattr(module, "format_prices"):
        print("missing function: format_prices")
        return 2
    for args, expected in EXAMPLES:
        try:
            got = module.format_prices(list(args))
        except Exception as exc:
            print(f"call failed: format_prices({args!r}) -> {type(exc).__name__}: {exc}")
            return 2
        if got != expected:
            print(f"wrong output: format_prices({args!r}) = {got!r}, expected {expected!r}")
            return 2
    print("verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())