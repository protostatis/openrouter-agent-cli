"""Render the merged evaluation report for a suite from the command line.

Usage:
    python -m openrouter_agent_cli.eval.report [--eval-dir DIR] [--suite-id ID]

Defaults: eval dir ``.agent-eval``, suite id ``coding-smoke-v1``. Prints the
descriptive paired report with uncertainty intervals and the leaderboard.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .compare import render_report
from .records import load_records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="openrouter-agent-eval-report", description=__doc__)
    ap.add_argument("--eval-dir", default=".agent-eval")
    ap.add_argument("--suite-id", default="coding-smoke-v1")
    args = ap.parse_args(argv)
    runs_path = Path(args.eval_dir) / "runs" / f"{args.suite_id}.jsonl"
    records = load_records(runs_path)
    if not records:
        print(f"no records at {runs_path}", file=sys.stderr)
        return 1
    print(render_report(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
