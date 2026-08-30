"""Paired suite runner that reuses the REAL agent engine.

This module contains no agent loop of its own. Each attempt constructs an
``OpenRouterAgentCLI`` exactly as ``--prompt`` mode does (headless, one user
message, tools enabled) and drives it. The only injection points are:

- ``model_transport``: a scripted mock (tests/offline dev) or ``None`` (the
  real OpenRouter HTTP path), and
- ``policy``: allow-all, which is safe ONLY because every attempt runs in a
  brand-new disposable workspace created per attempt.

Schedule: every task runs once per profile (paired), profiles rotate so each
profile leads equally often (counterbalanced), and nothing is ever dropped.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..cli import OpenRouterAgentCLI, ToolPermissionPolicy
from .records import (
    append_record,
    default_runs_dir,
    make_record,
    new_run_id,
    update_verdict,
)
from .suite import Suite, Task, make_fresh_workspace
from .transport import MockTransport
from .verify import run_verifier

_ENGINE_SESSION_ENV = "OPENROUTER_AGENT_SESSION_DIR"


@dataclass
class Profile:
    name: str
    prompt: str
    mock_script: dict[str, Any] | str | Path | None = None
    model: str = "mock-model"  # real-model profiles set their model name
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def uses_mock(self) -> bool:
        return self.mock_script is not None


class SuiteRunner:
    def __init__(
        self,
        suite: Suite,
        profiles: list[Profile],
        *,
        eval_dir: Path | None = None,
        max_turns: int = 10,
        command_timeout: int = 30,
        workspace_root: Path | None = None,
    ):
        if not profiles:
            raise ValueError("at least one profile is required")
        self.suite = suite
        self.profiles = profiles
        self.eval_dir = Path(eval_dir) if eval_dir else Path.cwd() / ".agent-eval"
        self.runs_path = default_runs_dir() if eval_dir is None else self.eval_dir / "runs" / f"{suite.suite_id}.jsonl"
        self.max_turns = max_turns
        self.command_timeout = command_timeout
        self.workspace_root = workspace_root

    # -- schedule -----------------------------------------------------------

    def build_schedule(self) -> list[tuple[Task, Profile, int]]:
        """Paired schedule: task-major, profile order rotated per task."""
        schedule: list[tuple[Task, Profile, int]] = []
        index = 0
        for t_idx, task in enumerate(self.suite.tasks):
            for offset, profile in enumerate(self.profiles):
                chosen = self.profiles[(t_idx + offset) % len(self.profiles)]
                schedule.append((task, chosen, index))
                index += 1
        return schedule

    # -- execution ----------------------------------------------------------

    async def _run_attempt(
        self, task: Task, profile: Profile, index: int
    ) -> dict[str, Any]:
        os.environ.setdefault("AGENT_EVAL_DIR", str(self.eval_dir))
        os.environ[_ENGINE_SESSION_ENV] = str(self.eval_dir / "sessions")
        workspace = make_fresh_workspace(
            self.suite, task, base_dir=self.workspace_root
        )
        record = make_record(
            run_id=new_run_id(),
            suite_id=self.suite.suite_id,
            task_id=task.id,
            cluster_id=task.cluster_id,
            profile_name=profile.name,
            profile_prompt=profile.prompt,
            model=profile.model,
            transport=(f"mock:script" if profile.uses_mock else "openrouter"),
            workdir=str(workspace),
            scheduled_index=index,
        )
        started = time.time()
        record["timing"]["started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)
        )
        engine: OpenRouterAgentCLI | None = None
        try:
            engine = OpenRouterAgentCLI(
                api_key="eval-not-a-real-key" if profile.uses_mock
                else os.environ.get("OPENROUTER_API_KEY", ""),
                model=profile.model,
                session_id=record["run_id"],
                workdir=str(workspace),
                max_turns=self.max_turns,
                max_history_messages=64,
                command_timeout=self.command_timeout,
                tools_enabled=True,
                system_prompt=profile.prompt,
                discovery_mode="off",
            )
            # Disposable workspace => allow-all is the documented eval contract.
            engine.policy = ToolPermissionPolicy(allow={"*"})
            engine.non_interactive_mode = True
            engine.one_shot_prompt = task.prompt
            if profile.uses_mock:
                script = profile.mock_script
                if isinstance(script, (str, Path)):
                    engine.model_transport = MockTransport.from_file(script)
                else:
                    engine.model_transport = MockTransport(script)
            await engine.run()
            record["engine"]["error"] = None
        except Exception as exc:  # factual capture; the record survives failures
            record["engine"]["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            record["timing"]["ended_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )
            record["timing"]["latency_seconds"] = round(time.time() - started, 3)
            if engine is not None:
                record["usage"].update(
                    {
                        "prompt_tokens": engine.session_tokens.get("prompt_tokens"),
                        "completion_tokens": engine.session_tokens.get(
                            "completion_tokens"
                        ),
                        "total_tokens": engine.session_tokens.get("total_tokens"),
                    }
                )
                record["engine"]["session_dir"] = str(
                    getattr(engine, "_session_path", "") or ""
                )
                record["engine"]["policy"] = "allow_all_disposable_workspace"
                record["tool_calls"] = [
                    {
                        "name": rec.get("name"),
                        "ok": rec.get("status") in ("succeeded", "completed"),
                        "duration_ms": rec.get("duration_ms"),
                        "brief": str(rec.get("args", {}).get("command", ""))[:80],
                    }
                    for rec in (engine._tool_records or {}).values()
                ]
        append_record(self.runs_path, record)
        return record

    async def run(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for task, profile, index in self.build_schedule():
            records.append(await self._run_attempt(task, profile, index))
        return records

    # -- verdicts & cleanup --------------------------------------------------

    def verify_all(self, records: list[dict[str, Any]]) -> None:
        task_by_id = {t.id: t for t in self.suite.tasks}
        for record in records:
            if record.get("verdict") is not None:
                continue
            task = task_by_id[record["task_id"]]
            verdict = run_verifier(
                task.verifier_command,
                Path(record["workspace"]),
                trusted_cwd=self.suite.path.parent,
                timeout_s=task.verifier_timeout_s,
            )
            update_verdict(
                self.runs_path, record["run_id"], verdict.verdict, verdict.evidence
            )
            record["verdict"] = verdict.verdict
            record["verdict_evidence"] = verdict.evidence

    def cleanup_workspaces(self, records: list[dict[str, Any]]) -> None:
        import shutil

        for record in records:
            workspace = Path(record["workspace"])
            if workspace.exists() and workspace.is_dir():
                shutil.rmtree(workspace, ignore_errors=True)

    async def run_and_verify(self) -> list[dict[str, Any]]:
        records = await self.run()
        self.verify_all(records)
        self.cleanup_workspaces(records)
        return records

    def run_and_verify_sync(self) -> list[dict[str, Any]]:
        """Synchronous convenience wrapper (scripts, tests)."""
        return asyncio.run(self.run_and_verify())


def run_suite(
    suite: Suite, profiles: list[Profile], **kwargs: Any
) -> list[dict[str, Any]]:
    """Synchronous convenience entry point."""
    return asyncio.run(SuiteRunner(suite, profiles, **kwargs).run_and_verify())
