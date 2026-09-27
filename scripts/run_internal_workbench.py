#!/usr/bin/env python3
"""Run a dependency-aware set of internal tasks without automatic merging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from openrouter_agent_cli.workbench import DEFAULT_WORKER_PROMPT, InternalTask, run_workbench


def _value(args: argparse.Namespace, name: str, defaults: dict[str, Any], fallback: Any) -> Any:
    value = getattr(args, name)
    return defaults.get(name, fallback) if value is None else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo", default=None)
    parser.add_argument("--results-dir", default=None)
    parser.add_argument("--source-ref", default=None)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--max-concurrency", type=int, default=None)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--request-timeout", type=float, default=None)
    parser.add_argument("--provider-retries", type=int, default=None)
    parser.add_argument("--repeat-tool-call-limit", type=int, default=None)
    parser.add_argument("--tool-profile", choices=["core4", "full7"], default=None)
    parser.add_argument("--task-timeout", type=float, default=None)
    parser.add_argument("--verify-timeout", type=float, default=None)
    parser.add_argument("--remove-worktrees", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("tasks"), list):
        parser.error("manifest must be an object containing a tasks list")
    defaults = manifest.get("defaults") or {}
    if not isinstance(defaults, dict):
        parser.error("manifest defaults must be an object")

    tasks = []
    for raw in manifest["tasks"]:
        if not isinstance(raw, dict):
            parser.error("each task must be an object")
        try:
            require_changes = raw.get("require_changes", True)
            if not isinstance(require_changes, bool):
                parser.error("task require_changes must be a boolean")
            allowed_paths = raw.get("allowed_paths", [])
            if not isinstance(allowed_paths, list) or not all(
                isinstance(value, str) for value in allowed_paths
            ):
                parser.error("task allowed_paths must be a list of strings")
            allow_escaped = raw.get("allow_escaped_newlines", False)
            if not isinstance(allow_escaped, bool):
                parser.error("task allow_escaped_newlines must be a boolean")
            test_growth = raw.get("test_growth")
            if test_growth is not None and not isinstance(test_growth, dict):
                parser.error("task test_growth must be an object when present")
            tasks.append(
                InternalTask(
                    task_id=str(raw["id"]),
                    task=str(raw["task"]),
                    verify_command=str(raw["verify_command"]),
                    prompt=str(raw.get("prompt") or DEFAULT_WORKER_PROMPT),
                    depends_on=tuple(str(value) for value in raw.get("depends_on", [])),
                    require_changes=require_changes,
                    allowed_paths=tuple(allowed_paths),
                    test_growth=test_growth,
                    allow_escaped_newlines=allow_escaped,
                )
            )
        except (KeyError, TypeError) as exc:
            parser.error(f"invalid task entry: {exc}")

    repo = Path(args.repo or manifest.get("repo") or ".").expanduser().resolve()
    results_dir = Path(
        args.results_dir
        or manifest.get("results_dir")
        or (Path.home() / ".openrouter-agent-cli" / "workbench")
    ).expanduser()
    env_file_value = args.env_file or manifest.get("env_file")
    result = run_workbench(
        tasks,
        repo=repo,
        results_root=results_dir,
        source_ref=_value(args, "source_ref", manifest, "HEAD"),
        max_concurrency=_value(args, "max_concurrency", defaults, 1),
        max_turns=_value(args, "max_turns", defaults, 32),
        request_timeout=_value(args, "request_timeout", defaults, 60.0),
        provider_retries=_value(args, "provider_retries", defaults, 3),
        repeat_tool_call_limit=_value(args, "repeat_tool_call_limit", defaults, 1),
        tool_profile=_value(args, "tool_profile", defaults, "core4"),
        task_timeout=_value(args, "task_timeout", defaults, 1800.0),
        verify_timeout=_value(args, "verify_timeout", defaults, 120.0),
        keep_worktree=not args.remove_worktrees,
        env_file=Path(env_file_value).expanduser() if env_file_value else None,
    )
    print(
        json.dumps(
            {"tasks": [{"task_id": item.task_id, "status": item.status, "error": item.error} for item in result]},
            indent=2,
        )
    )
    return 0 if result and all(item.status == "verified" for item in result) else 1


if __name__ == "__main__":
    raise SystemExit(main())
