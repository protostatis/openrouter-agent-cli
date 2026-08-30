"""Suite manifests: tasks, fresh workspaces, and verifier contracts.

A suite is a JSON file::

    {
      "schema_version": "agent-eval-suite-v1",
      "suite_id": "coding-smoke-v1",
      "tasks": [
        {
          "id": "t01",
          "cluster_id": "greet",            // optional; links paired task copies
          "prompt": "Create greet.py that prints hello when run.",
          "setup": [                        // optional; applied to a fresh workspace
            {"write_file": {"path": "README.md", "content": "..."}},
            {"run_command": {"command": "git init -q"}}
          ],
          "verifier": {
            "command": "python3 /abs/path/to/verify_t01.py",  // runs OUTSIDE agent cwd? no -
            // the verifier command runs host-side with cwd = a trusted directory
            // (the suite directory), and receives the agent workspace path as
            // argv[1]. This keeps verifier code and expected answers outside
            // the agent-writable workspace.
            "timeout_s": 30
          }
        }
      ]
    }

Verifier contract: exit 0 -> pass; exit 2 -> task_fail; anything else (or
timeout / verifier crash) -> infrastructure_error. The verifier's last stdout
line (<= 500 chars) is kept as evidence.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUITE_SCHEMA_VERSION = "agent-eval-suite-v1"

_SETUP_KEYS = ("write_file", "run_command")


@dataclass
class Task:
    id: str
    prompt: str
    verifier_command: str
    verifier_timeout_s: int = 30
    cluster_id: str | None = None
    setup: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Suite:
    suite_id: str
    path: Path
    tasks: list[Task]


def load_suite(path: str | Path) -> Suite:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise ValueError(
            f"suite {p} has schema_version {data.get('schema_version')!r}; "
            f"expected {SUITE_SCHEMA_VERSION!r}"
        )
    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for i, t in enumerate(data.get("tasks") or []):
        tid = str(t.get("id") or f"task_{i + 1:02d}")
        if tid in seen_ids:
            raise ValueError(f"duplicate task id in suite: {tid}")
        seen_ids.add(tid)
        verifier = t.get("verifier") or {}
        command = str(verifier.get("command") or "").strip()
        if not command:
            raise ValueError(f"task {tid} has no verifier command")
        if t.get("setup"):
            for step in t["setup"]:
                if (
                    not isinstance(step, dict)
                    or len(step) != 1
                    or set(step) - set(_SETUP_KEYS)
                ):
                    raise ValueError(
                        f"task {tid} setup steps must each contain exactly one of "
                        f"{_SETUP_KEYS}: {step}"
                    )
        tasks.append(
            Task(
                id=tid,
                prompt=str(t.get("prompt") or "").strip(),
                verifier_command=command,
                verifier_timeout_s=int(verifier.get("timeout_s", 30)),
                cluster_id=(str(t["cluster_id"]) if t.get("cluster_id") else None),
                setup=list(t.get("setup") or []),
            )
        )
    if not tasks:
        raise ValueError(f"suite {p} has no tasks")
    return Suite(suite_id=str(data.get("suite_id") or p.stem), path=p.resolve(), tasks=tasks)


def _apply_setup(workspace: Path, setup: list[dict[str, Any]]) -> None:
    for step in setup:
        if "write_file" in step:
            spec = step["write_file"]
            target = workspace / str(spec["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(spec.get("content", "")), encoding="utf-8")
        elif "run_command" in step:
            import subprocess

            subprocess.run(
                str(step["run_command"]["command"]),
                shell=True,
                cwd=str(workspace),
                check=True,
                timeout=60,
                capture_output=True,
            )


def make_fresh_workspace(
    suite: Suite, task: Task, base_dir: Path | None = None
) -> Path:
    """Create a brand-new disposable workspace for one attempt. The verifier
    never lives here; the agent may do its worst without damaging anything."""
    root = base_dir if base_dir is not None else Path(tempfile.gettempdir())
    workspace = Path(tempfile.mkdtemp(prefix=f"agent-eval-{task.id}-", dir=str(root)))
    _apply_setup(workspace, task.setup)
    return workspace
