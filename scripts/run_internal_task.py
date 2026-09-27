#!/usr/bin/env python3
"""Run one bounded internal task in an isolated worktree.

The command leaves the worktree, patch, logs, changed-file list, and independent
verification result under the results directory. It never merges or pushes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openrouter_agent_cli.workbench import (
    DEFAULT_WORKER_PROMPT,
    InternalTask,
    run_internal_task,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Repository to work in.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--task", required=True, help="Bounded work request.")
    parser.add_argument("--verify-command", required=True)
    parser.add_argument(
        "--allow-path",
        action="append",
        default=[],
        help="Allowed changed-path glob; repeat for multiple patterns.",
    )
    parser.add_argument("--prompt", default=None, help="Optional worker instruction.")
    parser.add_argument("--source-ref", default="HEAD")
    parser.add_argument("--results-dir", default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--max-turns", type=int, default=32)
    parser.add_argument("--request-timeout", type=float, default=60.0)
    parser.add_argument("--provider-retries", type=int, default=3)
    parser.add_argument("--repeat-tool-call-limit", type=int, default=1)
    parser.add_argument("--tool-profile", choices=["core4", "full7"], default="core4")
    parser.add_argument("--task-timeout", type=float, default=1800.0)
    parser.add_argument("--verify-timeout", type=float, default=120.0)
    parser.add_argument(
        "--remove-worktree",
        action="store_true",
        help="Remove the worktree after collecting the patch and evidence.",
    )
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    results_dir = (
        Path(args.results_dir).expanduser()
        if args.results_dir
        else repo / ".agent-workbench"
    )
    task = InternalTask(
        task_id=args.task_id,
        task=args.task,
        verify_command=args.verify_command,
        prompt=args.prompt or DEFAULT_WORKER_PROMPT,
        allowed_paths=tuple(args.allow_path),
    )
    result = run_internal_task(
        task,
        repo=repo,
        results_root=results_dir,
        source_ref=args.source_ref,
        max_turns=args.max_turns,
        request_timeout=args.request_timeout,
        provider_retries=args.provider_retries,
        repeat_tool_call_limit=args.repeat_tool_call_limit,
        tool_profile=args.tool_profile,
        task_timeout=args.task_timeout,
        verify_timeout=args.verify_timeout,
        keep_worktree=not args.remove_worktree,
        env_file=Path(args.env_file).expanduser() if args.env_file else None,
    )
    print(json.dumps(result.__dict__, indent=2))
    return 0 if result.status == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
