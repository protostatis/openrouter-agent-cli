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
from .audit import assert_audited
from .records import (
    append_record,
    default_runs_dir,
    make_record,
    new_run_id,
    TREATMENT_MODEL_ALONE,
    TREATMENT_MODEL_PLUS_POLICY,
    update_verdict,
)
from .policy import VerifierAssistedPolicy, finalize_snapshot
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
    treatment: str = TREATMENT_MODEL_ALONE
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.treatment not in {TREATMENT_MODEL_ALONE, TREATMENT_MODEL_PLUS_POLICY}:
            raise ValueError(
                f"unknown treatment {self.treatment!r}; expected "
                f"{TREATMENT_MODEL_ALONE!r} or {TREATMENT_MODEL_PLUS_POLICY!r}"
            )

    @property
    def uses_mock(self) -> bool:
        return self.mock_script is not None


_HOST_EXEC_ACK_ENV = "AGENT_EVAL_ALLOW_HOST_EXECUTION"
_SANDBOX_ENV = "AGENT_EVAL_SANDBOX"  # "1"=require, "0"=never, unset=auto (linux+bwrap)

def _sandbox_mode() -> str:
    value = os.environ.get(_SANDBOX_ENV, "").strip().lower()
    return value if value in ("1", "0") else "auto"

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
        repeats: int = 1,
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
        self.repeats = max(1, repeats)
        # Execution-containment gate (runs after field init).
        self._sandboxed = False
        uses_real = any(not p.uses_mock for p in profiles)
        if not uses_real:
            return
        if not os.environ.get("OPENROUTER_API_KEY", ""):
            raise ValueError(
                "real-model profiles require OPENROUTER_API_KEY in the "
                "environment (or use a mock profile for offline runs)"
            )
        from .sandbox import sandbox_available

        mode = _sandbox_mode()
        available = sandbox_available()
        if mode == "1":
            # Explicit requirement: containment is mandatory; fail if absent.
            if not available:
                raise ValueError(
                    "AGENT_EVAL_SANDBOX=1 requested but the Bubblewrap sandbox is "
                    "unavailable (Linux + bwrap + systemd-user required)."
                )
            self._sandboxed = True
            return
        if mode == "auto" and available:
            self._sandboxed = True
            return  # contained: no host-execution acknowledgement required
        if os.environ.get(_HOST_EXEC_ACK_ENV) == "1":
            return  # explicit operator acknowledgement of host-level execution
        raise ValueError(
            "Real-model attempts execute bash with host permissions in a "
            "disposable workspace and no sandbox is available (Linux + bwrap + "
            "systemd-user required). Set AGENT_EVAL_ALLOW_HOST_EXECUTION=1 to "
            "accept host-level execution, or AGENT_EVAL_SANDBOX=1 to require "
            "containment (fails if unavailable)."
        )

    # -- schedule -----------------------------------------------------------

    def build_schedule(self) -> list[tuple[Task, Profile, int]]:
        """Paired schedule: task-major, profile order rotated per task."""
        schedule: list[tuple[Task, Profile, int]] = []
        index = 0
        for repeat in range(self.repeats):
            for t_idx, task in enumerate(self.suite.tasks):
                for offset, profile in enumerate(self.profiles):
                    chosen = self.profiles[
                        (t_idx + repeat + offset) % len(self.profiles)
                    ]
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
            treatment=profile.treatment,
        )
        started = time.time()
        record["timing"]["started_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)
        )
        engine: OpenRouterAgentCLI | None = None
        policy: VerifierAssistedPolicy | None = None
        try:
            if profile.treatment == TREATMENT_MODEL_PLUS_POLICY:
                policy = VerifierAssistedPolicy(
                    verifier_command=task.verifier_command,
                    workspace=workspace,
                    trusted_cwd=self.suite.path.parent,
                    timeout_s=task.verifier_timeout_s,
                    contained=self._sandboxed,
                )
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
            if getattr(self, "_sandboxed", False) and not profile.uses_mock:
                from .sandbox import BubblewrapBashRunner

                engine.bash_runner = BubblewrapBashRunner(str(workspace))
                record["engine"]["sandbox"] = "bubblewrap"
            if policy is not None:
                engine.checkpoint_hook = policy
            if profile.uses_mock:
                script = profile.mock_script
                if isinstance(script, (str, Path)):
                    engine.model_transport = MockTransport.from_file(script)
                else:
                    engine.model_transport = MockTransport(script)
            await engine.run()
            if getattr(engine, "terminal_status", "ok") != "ok":
                record["engine"]["error"] = (
                    f"engine terminal_status={engine.terminal_status}"
                )
            else:
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
            if policy is not None:
                if engine is not None:
                    policy.finish_engine(engine.session_tokens["total_tokens"])
                record["policy"] = policy.snapshot()
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
            engine_error = (record.get("engine") or {}).get("error")
            if engine_error:
                # Provider/engine failures are infrastructure errors, not
                # incomplete task work: never grade a broken attempt as a
                # model task failure.
                evidence = f"engine error: {engine_error}"
                update_verdict(
                    self.runs_path,
                    record["run_id"],
                    "infrastructure_error",
                    evidence,
                )
                record["verdict"] = "infrastructure_error"
                record["verdict_evidence"] = evidence
                continue
            task = task_by_id[record["task_id"]]
            verdict = run_verifier(
                task.verifier_command,
                Path(record["workspace"]),
                trusted_cwd=self.suite.path.parent,
                timeout_s=task.verifier_timeout_s,
                contained=self._sandboxed,
            )
            extra_fields: dict[str, Any] = {}
            if record.get("treatment") == TREATMENT_MODEL_PLUS_POLICY:
                policy_snapshot = record.get("policy")
                if isinstance(policy_snapshot, dict):
                    policy_snapshot = finalize_snapshot(policy_snapshot, verdict.verdict)
                    record["policy"] = policy_snapshot
                    extra_fields["policy"] = policy_snapshot
            update_verdict(
                self.runs_path,
                record["run_id"],
                verdict.verdict,
                verdict.evidence,
                extra_fields=extra_fields,
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
        try:
            self.verify_all(records)
            assert_audited(
                records,
                expected_task_ids=[task.id for task in self.suite.tasks],
                expected_profile_names=[profile.name for profile in self.profiles],
                expected_repeats=self.repeats,
                require_containment=any(not profile.uses_mock for profile in self.profiles),
            )
        finally:
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
