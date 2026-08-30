#!/usr/bin/env python3
"""Run an evaluation suite against prompt profiles from the command line.

Examples:
  # Mock model (no tokens, fully offline):
  python3 scripts/run_suite.py --suite eval_suites/coding_smoke_v1/suite.json \
      --profile worker=eval_suites/mock_worker.json

  # Real models (reads OPENROUTER_API_KEY):
  python3 scripts/run_suite.py --suite eval_suites/coding_smoke_v1/suite.json \
      --profile default=prompts/system_prompt_control.md --model anthropic/claude-3.5-haiku

Each --profile is NAME=PATH where PATH is either a mock script JSON (top-level
"responses" list) or a system-prompt text file. The runner reuses the real CLI
engine (one execution path); a paired, counterbalanced report prints at the end.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from openrouter_agent_cli.eval.compare import render_report
from openrouter_agent_cli.eval.runner import Profile, SuiteRunner
from openrouter_agent_cli.eval.suite import load_suite


def _load_profile(name: str, path: str) -> Profile:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "responses" in data:
        return Profile(name=name, prompt="(mock-script driven)", mock_script=data)
    return Profile(name=name, prompt=p.read_text(encoding="utf-8").strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", required=True, help="suite manifest JSON path")
    ap.add_argument(
        "--profile",
        action="append",
        required=True,
        dest="profiles",
        metavar="NAME=PATH",
        help="profile as NAME=(mock-script.json | prompt.md); repeatable",
    )
    ap.add_argument("--model", default=None, help="OpenRouter model id (real profiles)")
    ap.add_argument("--eval-dir", default=None, help="evaluation output directory")
    ap.add_argument("--max-turns", type=int, default=10)
    args = ap.parse_args()

    profiles: list[Profile] = []
    for spec in args.profiles:
        name, _, path = spec.partition("=")
        if not name or not path:
            raise SystemExit(f"bad --profile {spec!r}; expected NAME=PATH")
        profile = _load_profile(name, path)
        if not profile.uses_mock:
            if not args.model:
                raise SystemExit(
                    f"profile {name!r} is a real prompt; --model is required"
                )
            profile.model = args.model
        profiles.append(profile)

    suite = load_suite(args.suite)
    runner = SuiteRunner(
        suite,
        profiles,
        eval_dir=Path(args.eval_dir) if args.eval_dir else None,
        max_turns=args.max_turns,
    )
    records = runner.run_and_verify_sync()
    print(f"\n[{len(records)} attempts recorded -> {runner.runs_path}]")
    print(render_report(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
