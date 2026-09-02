"""Run an evaluation suite against prompt profiles from the command line.

Examples::

    # Mock model (no tokens, fully offline):
    openrouter-agent-eval --suite eval_suites/coding_smoke_v1/suite.json \
        --profile worker=eval_suites/mock_worker.json

    # Existing records only:
    openrouter-agent-eval --suite eval_suites/coding_smoke_v1/suite.json \
        --report-only

Each ``--profile`` is ``NAME=PATH`` where PATH is either a mock-script JSON
(top-level ``responses`` list) or a system-prompt text file. The runner reuses
the real CLI engine (one execution path); a paired, counterbalanced report is
printed at the end.

Mock profiles execute the real tool and verifier layers but make no provider
calls. Prompt-file profiles use OpenRouter and require deliberate operator
configuration, including an API key and an execution-containment decision.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..cli import _load_dotenv

_load_dotenv(None)

from .compare import render_report
from .records import TREATMENT_MODEL_ALONE, TREATMENT_MODEL_PLUS_POLICY
from .runner import Profile, SuiteRunner
from .suite import load_suite


def _load_profile(name: str, path: str) -> Profile:
    profile_path = Path(path)
    text = profile_path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return Profile(name=name, prompt=text.strip())
    if isinstance(data, dict) and "responses" in data:
        return Profile(name=name, prompt="(mock-script driven)", mock_script=data)
    return Profile(name=name, prompt=text.strip())


def _parse_profiles(
    specs: list[str] | None,
    model: str | None,
    *,
    treatment: str = TREATMENT_MODEL_ALONE,
    assisted_profiles: set[str] | None = None,
) -> list[Profile]:
    known = {spec.partition("=")[0] for spec in specs or []}
    unknown = (assisted_profiles or set()) - known
    if unknown:
        raise SystemExit(f"unknown --assisted-profile name(s): {sorted(unknown)}")
    profiles: list[Profile] = []
    for spec in specs or []:
        name, _, path_and_model = spec.partition("=")
        if not name or not path_and_model:
            raise SystemExit(f"bad --profile {spec!r}; expected NAME=PATH[@MODEL]")
        path, _, model_override = path_and_model.partition("@")
        if not path:
            raise SystemExit(f"bad --profile {spec!r}; missing PATH")
        profile = _load_profile(name, path)
        if profile.uses_mock:
            if model_override:
                raise SystemExit(f"profile {name!r} is a mock; @MODEL not allowed")
        else:
            profile.model = model_override or model or ""
            if not profile.model:
                raise SystemExit(
                    f"profile {name!r} is a real prompt; give @MODEL or --model"
                )
        profile.treatment = (
            TREATMENT_MODEL_PLUS_POLICY
            if name in (assisted_profiles or set())
            else treatment
        )
        profiles.append(profile)
    return profiles


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", required=True, help="suite manifest JSON path")
    ap.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        metavar="NAME=PATH",
        help="profile as NAME=(mock-script.json | prompt.md); repeatable",
    )
    ap.add_argument("--model", default=None, help="OpenRouter model id for real profiles")
    ap.add_argument(
        "--treatment",
        choices=(TREATMENT_MODEL_ALONE, TREATMENT_MODEL_PLUS_POLICY),
        default=TREATMENT_MODEL_ALONE,
        help="treatment applied to profiles unless --assisted-profile overrides it",
    )
    ap.add_argument(
        "--assisted-profile",
        action="append",
        default=[],
        metavar="NAME",
        help="mark this profile as verifier-assisted; repeatable",
    )
    ap.add_argument("--eval-dir", default=None, help="evaluation output directory")
    ap.add_argument("--max-turns", type=int, default=10)
    ap.add_argument("--repeats", type=int, default=1, help="repeat the paired schedule")
    ap.add_argument(
        "--tasks",
        default=None,
        help="comma-separated task ids to run (default: all)",
    )
    ap.add_argument(
        "--report-only",
        action="store_true",
        help="print the merged report from existing records and exit",
    )
    args = ap.parse_args(argv)

    suite = load_suite(args.suite)
    eval_dir = Path(args.eval_dir) if args.eval_dir else Path.cwd() / ".agent-eval"
    if args.report_only:
        from .records import load_records

        runs_path = eval_dir / "runs" / f"{suite.suite_id}.jsonl"
        print(render_report(load_records(runs_path)))
        return 0

    if not args.profiles:
        raise SystemExit("at least one --profile is required unless --report-only is used")

    if args.tasks:
        wanted = {task.strip() for task in args.tasks.split(",")}
        missing = wanted - {task.id for task in suite.tasks}
        if missing:
            raise SystemExit(f"unknown task ids: {sorted(missing)}")
        suite.tasks = [task for task in suite.tasks if task.id in wanted]

    profiles = _parse_profiles(
        args.profiles,
        args.model,
        treatment=args.treatment,
        assisted_profiles=set(args.assisted_profile),
    )
    runner = SuiteRunner(
        suite,
        profiles,
        eval_dir=Path(args.eval_dir) if args.eval_dir else None,
        max_turns=args.max_turns,
        repeats=max(1, args.repeats),
    )
    records = runner.run_and_verify_sync()
    print(f"\n[{len(records)} attempts recorded -> {runner.runs_path}]")
    print(render_report(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
