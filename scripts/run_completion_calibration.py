#!/usr/bin/env python3
"""Run randomized unassisted calibration trials for the Harbor task pool.

The calibration intentionally uses the default full7 tool profile and no
completion policy. Harbor still runs each task's verifier after the agent
stops, so each trial records the ordinary task reward without changing the
agent's stopping behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = PROJECT_ROOT / "eval_suites" / "harbor_xfix"
DEFAULT_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_PROMPT = (
    "You are a careful coding agent. Inspect the repository, make the requested "
    "changes, run relevant tests, and stop only after verifying the result."
)
DEFAULT_TASKS = [
    "hard_crashing_script",
    "hard_ledger_refunds",
    "invoice_totals",
    "report_pipeline",
    "xfix01_indexerror",
    "xfix05_zerodiv_empty",
    "xfix09_silent_whitespace",
    "xfix11_typeerror_items",
    "xfix12_silent_case",
    "xfix_atomic_reservations",
    "xfix_config_precedence",
    "xfix_dependency_plan",
    "xfix_safe_archive_extract",
    "xfix_session_windows",
]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-wheel", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Usable unassisted trials required per task.",
    )
    parser.add_argument(
        "--max-attempts-per-task",
        type=int,
        default=None,
        help="Maximum attempts per task, including provider failures (default: 3x repeats).",
    )
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--max-turns", type=int, default=32)
    parser.add_argument("--system-prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--proxy-url", default="http://host.docker.internal:8789/v1")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--jobs-dir", type=Path, default=Path("jobs/completion-calibration"))
    parser.add_argument("--agent", default="openrouter_agent_cli.harbor_agent:OraAgent")
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        help="Task directory name; repeatable. Defaults to all nine candidates.",
    )
    return parser.parse_args()


def _read_trial_result(job_path: Path) -> dict | None:
    if not job_path.is_dir():
        return None
    result_paths = [
        path / "result.json"
        for path in job_path.iterdir()
        if path.is_dir() and (path / "result.json").is_file()
    ]
    if len(result_paths) != 1:
        return None
    try:
        return json.loads(result_paths[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _classify_trial(trial: dict | None, job_path: Path) -> str:
    if trial is None:
        return "harness_error"
    verifier_result = (trial or {}).get("verifier_result") or {}
    rewards = verifier_result.get("rewards") or {}
    if rewards.get("reward") == 1.0:
        return "pass"
    exception_text = json.dumps((trial or {}).get("exception_info"), ensure_ascii=False)
    logs = list(job_path.glob("*/agent/ora.txt"))
    agent_log = logs[0].read_text(encoding="utf-8", errors="replace") if logs else ""
    combined = f"{exception_text}\n{agent_log}".lower()
    if "provider_error" in combined or "service temporarily overloaded" in combined:
        return "provider_error"
    if trial is not None and trial.get("exception_info"):
        return "harness_error"
    return "task_fail"


def main() -> int:
    args = _parse_args()
    wheel = args.local_wheel.expanduser().resolve()
    tasks = args.tasks or DEFAULT_TASKS
    unknown = sorted(set(tasks) - set(DEFAULT_TASKS))
    if unknown:
        print(f"unknown task(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    if not wheel.is_file() or wheel.suffix != ".whl":
        print(f"local wheel does not exist or is not a wheel: {wheel}", file=sys.stderr)
        return 2
    max_attempts_per_task = args.max_attempts_per_task or args.repeats * 3
    if args.repeats < 1 or args.max_turns < 1 or max_attempts_per_task < args.repeats:
        print("invalid repeats, max-attempts-per-task, or max-turns", file=sys.stderr)
        return 2

    jobs_dir = args.jobs_dir.expanduser().resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    source_digest = _sha256_file(wheel)
    wheel_container_path = f"/opt/ora-dist/{wheel.name}"
    mounts = json.dumps(
        [
            {
                "type": "bind",
                "source": str(wheel.parent),
                "target": "/opt/ora-dist",
                "read_only": True,
            }
        ],
        separators=(",", ":"),
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "tasks": tasks,
        "target_usable_trials_per_task": args.repeats,
        "max_attempts_per_task": max_attempts_per_task,
        "model": args.model,
        "tool_profile": "full7",
        "mode": "unassisted",
        "max_turns": args.max_turns,
        "system_prompt_sha256": _sha256_text(args.system_prompt),
        "source_digest": source_digest,
        "local_wheel": str(wheel),
        "proxy_url": args.proxy_url,
        "attempts_by_task": {task: 0 for task in tasks},
        "usable_trials_by_task": {task: 0 for task in tasks},
        "trials": [],
    }
    manifest_path = jobs_dir / "completion-calibration-manifest.json"
    rng = random.Random(args.seed)
    run_env = os.environ.copy()
    run_env["OPENROUTER_BASE_URL"] = args.proxy_url

    round_number = 0
    while any(
        manifest["usable_trials_by_task"][task] < args.repeats for task in tasks
    ):
        round_number += 1
        order = [
            task
            for task in tasks
            if manifest["usable_trials_by_task"][task] < args.repeats
            and manifest["attempts_by_task"][task] < max_attempts_per_task
        ]
        if not order:
            break
        rng.shuffle(order)
        for position, task_name in enumerate(order, start=1):
            if manifest["usable_trials_by_task"][task_name] >= args.repeats:
                continue
            attempt = manifest["attempts_by_task"][task_name] + 1
            manifest["attempts_by_task"][task_name] = attempt
            task = TASK_ROOT / task_name
            run_id = f"calibration-{args.seed}-r{round_number}-a{attempt}-{task_name}"
            job_name = f"r{round_number:02d}-a{attempt:02d}-{task_name}"
            command = [
                "harbor",
                "run",
                "--path",
                str(task),
                "-a",
                args.agent,
                "-m",
                args.model,
                "--ak",
                "mode=unassisted",
                "--ak",
                "tool_profile=full7",
                "--ak",
                f"max_turns={args.max_turns}",
                "--ak",
                f"system_prompt={args.system_prompt}",
                "--ak",
                f"run_id={run_id}",
                "--ae",
                f"OPENROUTER_AGENT_LOCAL_SOURCE={wheel_container_path}",
                "--ae",
                f"OPENROUTER_AGENT_SOURCE_DIGEST={source_digest}",
                "--mounts",
                mounts,
                "--n-attempts",
                "1",
                "--n-concurrent",
                "1",
                "--yes",
                "--allow-agent-host",
                "host.docker.internal",
                "--env-file",
                args.env_file,
                "--jobs-dir",
                str(jobs_dir),
                "--job-name",
                job_name,
            ]
            print(
                f"[round {round_number}] {position}/{len(order)} {task_name} "
                f"(usable {manifest['usable_trials_by_task'][task_name]}/{args.repeats}, "
                f"attempt {attempt}/{max_attempts_per_task})",
                flush=True,
            )
            record = {
                "round": round_number,
                "position": position,
                "attempt": attempt,
                "task": task_name,
                "run_id": run_id,
                "job_name": job_name,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "command": command,
            }
            completed = subprocess.run(command, cwd=PROJECT_ROOT, env=run_env, check=False)
            record["return_code"] = completed.returncode
            trial = _read_trial_result(jobs_dir / job_name)
            record["outcome"] = _classify_trial(trial, jobs_dir / job_name)
            if record["outcome"] in {"pass", "task_fail"}:
                manifest["usable_trials_by_task"][task_name] += 1
                record["usable_trial_number"] = manifest["usable_trials_by_task"][task_name]
            if trial is not None:
                record["trial_name"] = trial.get("trial_name")
                record["task_checksum"] = trial.get("task_checksum")
                record["reward"] = (trial.get("verifier_result") or {}).get("rewards", {}).get(
                    "reward"
                )
                record["exception_info"] = trial.get("exception_info")
                record["agent_result"] = trial.get("agent_result")
                record["started_at_harbor"] = trial.get("started_at")
                record["finished_at_harbor"] = trial.get("finished_at")
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            manifest["trials"].append(record)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    complete = all(
        manifest["usable_trials_by_task"][task] >= args.repeats for task in tasks
    )
    manifest["complete"] = complete
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
