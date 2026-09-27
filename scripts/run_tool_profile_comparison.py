#!/usr/bin/env python3
"""Run randomized, paired Harbor trials for the two tool profiles.

Each repetition runs one fresh full7 trial and one fresh core4 trial. The
profile order is randomized with a recorded seed, while model, task, prompt,
turn limit, verifier, and local agent wheel remain fixed.

Example:
    uv run python scripts/run_tool_profile_comparison.py \
        --task eval_suites/harbor_xfix/report_pipeline \
        --local-wheel /tmp/ora-dist/openrouter_agent_cli-0.2.1-py3-none-any.whl \
        --repeats 3
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
DEFAULT_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_PROMPT = (
    "You are a careful coding agent. Inspect the repository, make the requested "
    "changes, run relevant tests, and stop only after verifying the result."
)


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
    parser.add_argument("--task", required=True, help="Local Harbor task directory.")
    parser.add_argument("--local-wheel", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--max-turns", type=int, default=32)
    parser.add_argument("--system-prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--proxy-url", default="http://host.docker.internal:8789/v1")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--jobs-dir", type=Path, default=Path("jobs/tool-profile-comparison"))
    parser.add_argument("--agent", default="openrouter_agent_cli.harbor_agent:OraAgent")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    task = Path(args.task)
    wheel = args.local_wheel.expanduser().resolve()
    if not task.exists():
        print(f"task does not exist: {task}", file=sys.stderr)
        return 2
    if not wheel.is_file() or wheel.suffix != ".whl":
        print(f"local wheel does not exist or is not a wheel: {wheel}", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("--repeats must be at least 1", file=sys.stderr)
        return 2
    if args.max_turns < 1:
        print("--max-turns must be at least 1", file=sys.stderr)
        return 2

    jobs_dir = args.jobs_dir.expanduser().resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    wheel_mount_dir = wheel.parent
    wheel_container_path = f"/opt/ora-dist/{wheel.name}"
    mounts = json.dumps(
        [
            {
                "type": "bind",
                "source": str(wheel_mount_dir),
                "target": "/opt/ora-dist",
                "read_only": True,
            }
        ],
        separators=(",", ":"),
    )
    source_digest = _sha256_file(wheel)
    manifest_path = jobs_dir / "tool-profile-comparison-manifest.json"
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "task": str(task),
        "model": args.model,
        "max_turns": args.max_turns,
        "system_prompt_sha256": _sha256_text(args.system_prompt),
        "source_digest": source_digest,
        "local_wheel": str(wheel),
        "proxy_url": args.proxy_url,
        "trials": [],
    }
    rng = random.Random(args.seed)
    run_env = os.environ.copy()
    run_env["OPENROUTER_BASE_URL"] = args.proxy_url

    for repetition in range(1, args.repeats + 1):
        order = ["full7", "core4"]
        rng.shuffle(order)
        for position, profile in enumerate(order, start=1):
            run_id = f"tool-profile-{args.seed}-r{repetition}-{position}-{profile}"
            job_name = f"{profile}-r{repetition}-p{position}"
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
                f"tool_profile={profile}",
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
            record = {
                "repetition": repetition,
                "position": position,
                "profile": profile,
                "run_id": run_id,
                "job_name": job_name,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "command": command,
            }
            print(f"[{repetition}/{args.repeats}] {profile} ({position}/2)", flush=True)
            completed = subprocess.run(
                command, cwd=PROJECT_ROOT, env=run_env, check=False
            )
            record["return_code"] = completed.returncode
            job_path = jobs_dir / job_name
            trial_result = next(
                (
                    child / "result.json"
                    for child in job_path.iterdir()
                    if child.is_dir() and (child / "result.json").is_file()
                ),
                None,
            ) if job_path.is_dir() else None
            if trial_result is not None and trial_result.is_file():
                try:
                    result = json.loads(trial_result.read_text(encoding="utf-8"))
                    record["task_checksum"] = result.get("task_checksum")
                    record["trial_name"] = result.get("trial_name")
                except (OSError, json.JSONDecodeError):
                    record["task_checksum"] = None
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            manifest["trials"].append(record)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    return 0 if all(t["return_code"] == 0 for t in manifest["trials"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
