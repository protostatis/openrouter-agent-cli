"""User-owned acceptance checks for long-running coding sessions.

This is intentionally separate from the hidden evaluation policy. A developer
may opt in with an explicit check command; the command's output is shown to the
developer, while the model receives only a generic repair instruction. The
check runs at a final-answer boundary and once more when a policy-enabled turn
reaches its iteration limit without producing a final answer.
"""
from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Callable

from .utils import run_bash

if TYPE_CHECKING:
    from .cli import CheckpointDecision, RuntimeCheckpoint

_REPAIR_MESSAGE = (
    "The acceptance check did not pass. Inspect your changes and tests, make any "
    "necessary repairs, and reply when the task is complete."
)


def _preview(value: Any, limit: int = 800) -> str:
    text = str(value or "").replace("\x00", "")
    return text if len(text) <= limit else text[:limit] + "..."


class UserCompletionPolicy:
    """Run a user-supplied acceptance command before accepting final text."""

    def __init__(
        self,
        *,
        command: str,
        workdir: str,
        timeout_seconds: int = 120,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not command.strip():
            raise ValueError("acceptance command must not be empty")
        self.command = command.strip()
        self.workdir = workdir
        self.timeout_seconds = max(1, min(int(timeout_seconds), 600))
        self.on_result = on_result
        self.repair_injections = 0
        self.last_result: dict[str, Any] | None = None

    def begin_turn(self) -> None:
        """Reset the bounded repair allowance for a new developer request."""
        self.repair_injections = 0
        self.last_result = None

    async def check(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            raw = await run_bash(
                self.command,
                self.workdir,
                self.timeout_seconds,
                structured=True,
            )
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("acceptance command returned a non-object result")
            exit_code = payload.get("exit_code")
            timed_out = bool(payload.get("timed_out"))
            if timed_out or payload.get("error"):
                status = "not_verified"
            elif exit_code == 0:
                status = "verified"
            else:
                status = "failed"
            result = {
                "status": status,
                "command": self.command,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "duration_ms": payload.get("duration_ms")
                or round((time.monotonic() - started) * 1000),
                "stdout": _preview(payload.get("stdout")),
                "stderr": _preview(payload.get("stderr")),
                "error": _preview(payload.get("error")),
            }
        except Exception as exc:
            result = {
                "status": "not_verified",
                "command": self.command,
                "exit_code": None,
                "timed_out": False,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "stdout": "",
                "stderr": "",
                "error": f"{type(exc).__name__}: {exc}",
            }
        result["changed_files"] = await self._changed_files()
        self.last_result = result
        if self.on_result is not None:
            self.on_result(result)
        return result

    async def _changed_files(self) -> list[str]:
        """Return a bounded git worktree list for the developer-facing result.

        Uses NUL-delimited name-only output (rename-safe, no short-status
        parsing) and degrades gracefully for repositories without commits or
        for non-git directories.
        """
        files: list[str] = []
        for command in (
            "git diff --name-only -z HEAD",
            "git ls-files --others --exclude-standard -z",
        ):
            try:
                raw = await run_bash(command, self.workdir, 30, structured=True)
                payload = json.loads(raw)
                if not isinstance(payload, dict) or payload.get("exit_code") != 0:
                    continue
                files.extend(
                    path
                    for path in str(payload.get("stdout") or "").split("\0")
                    if path
                )
            except Exception:
                continue
        seen: set[str] = set()
        deduped: list[str] = []
        for path in files:
            if path not in seen:
                seen.add(path)
                deduped.append(path)
        return deduped[:100]

    def _decide(self, result: dict[str, Any]) -> CheckpointDecision:
        from .cli import CheckpointDecision

        status = result["status"]
        if status == "verified":
            return CheckpointDecision(action="stop")
        if status == "failed" and self.repair_injections == 0:
            self.repair_injections += 1
            return CheckpointDecision(action="repair", message=_REPAIR_MESSAGE)
        # failed / not_verified after the single permitted repair: the engine
        # shows the second check evidence and ends the turn without looping.
        return CheckpointDecision()

    async def __call__(self, event: RuntimeCheckpoint) -> CheckpointDecision:
        from .cli import CheckpointDecision

        if event.kind in {"final_answer", "turn_limit"}:
            return self._decide(await self.check())
        if event.kind == "mutating_batch" and self.repair_injections > 0:
            # The repair response used mutating tools and the work has now
            # executed. Re-run the acceptance check once at this boundary and
            # stop with the fresh evidence instead of ending silently.
            await self.check()
            return CheckpointDecision(action="stop")
        # Mutating batches before any repair do not end a user turn; the check
        # runs at the actual completion boundary to avoid interrupting useful
        # multi-step work.
        return CheckpointDecision()

    def snapshot(self) -> dict[str, Any]:
        result = self.last_result or {}
        return {
            "name": "user-acceptance-check",
            "command": self.command,
            "timeout_seconds": self.timeout_seconds,
            "repair_injections": self.repair_injections,
            "last_status": result.get("status"),
            "last_exit_code": result.get("exit_code"),
            "last_duration_ms": result.get("duration_ms"),
            "last_changed_file_count": len(result.get("changed_files") or []),
        }


def copy_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a detached result for UI use without sharing policy state."""
    return deepcopy(result) if result is not None else None
