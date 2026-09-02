"""Verifier-assisted completion policy for feasibility experiments.

This module is deliberately a control-plane layer. It probes an attempt's
workspace without exposing verifier evidence to the model, requests at most
one generic repair cycle, and never assigns the canonical task verdict.
"""
from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..cli import CheckpointDecision, RuntimeCheckpoint
from .verify import (
    VERDICT_PASS,
    VERDICT_TASK_FAIL,
    run_verifier,
)

REPAIR_MESSAGE = (
    "The trusted completion check did not pass. Inspect your changes and tests, "
    "make any necessary repairs, and reply when the task is complete."
)


class VerifierAssistedPolicy:
    """Minimal one-injection policy from the experiment contract.

    The canonical verifier is used as a hidden probe, but its evidence is
    discarded. The runner later invokes the same verifier again to assign the
    immutable final verdict.
    """

    def __init__(
        self,
        *,
        verifier_command: str,
        workspace: Path,
        trusted_cwd: Path,
        timeout_s: int = 30,
        contained: bool = False,
    ) -> None:
        self.verifier_command = verifier_command
        self.workspace = Path(workspace)
        self.trusted_cwd = Path(trusted_cwd)
        self.timeout_s = timeout_s
        self.contained = contained
        self._repair_injected = False
        self._repair_started_tokens: int | None = None
        self._repair_started_at: float | None = None
        self._state: dict[str, Any] = {
            "name": "verify-before-completion",
            "contained": contained,
            "checkpoints": [],
            "probe_count": 0,
            "repair_injections": 0,
            "terminal_probe_result": None,
            "added_tokens": 0,
            "added_time_seconds": 0.0,
            "probe_final_verifier_disagreed": None,
        }

    @staticmethod
    def _probe_result(verdict: str) -> str:
        if verdict == VERDICT_PASS:
            return "complete"
        if verdict == VERDICT_TASK_FAIL:
            return "incomplete"
        return "infrastructure_error"

    async def __call__(self, event: RuntimeCheckpoint) -> CheckpointDecision:
        """Probe one checkpoint and return a bounded engine action."""
        started = time.monotonic()
        try:
            verdict = await asyncio.to_thread(
                run_verifier,
                self.verifier_command,
                self.workspace,
                self.trusted_cwd,
                self.timeout_s,
                contained=self.contained,
            )
            probe_result = self._probe_result(verdict.verdict)
        except Exception:
            # The policy must fail open if its own control path breaks. No raw
            # exception or verifier evidence enters the model transcript.
            probe_result = "infrastructure_error"
        duration = round(time.monotonic() - started, 3)

        if probe_result == "complete":
            action = "stop"
        elif probe_result == "incomplete" and not self._repair_injected:
            action = "repair"
            self._repair_injected = True
            self._repair_started_tokens = event.total_tokens
            self._repair_started_at = time.monotonic()
            self._state["repair_injections"] += 1
        elif probe_result == "incomplete":
            # The extra response has been consumed; never inject a second
            # repair request. The final verifier still grades the workspace.
            action = "stop"
        else:
            # Infrastructure problems are not attributed to the model and do
            # not trigger intervention.
            action = "continue"

        self._state["probe_count"] += 1
        self._state["terminal_probe_result"] = probe_result
        self._state["checkpoints"].append(
            {
                "sequence": event.sequence,
                "kind": event.kind,
                "turn": event.turn,
                "tool_names": list(event.tool_names),
                "total_tokens": event.total_tokens,
                "probe_result": probe_result,
                "action": action,
                "probe_duration_seconds": duration,
            }
        )
        return CheckpointDecision(action=action, message=REPAIR_MESSAGE)

    def finish_engine(self, total_tokens: int) -> None:
        """Capture costs attributable to the permitted repair cycle."""
        if self._repair_started_tokens is None or self._repair_started_at is None:
            return
        self._state["added_tokens"] = max(0, total_tokens - self._repair_started_tokens)
        self._state["added_time_seconds"] = round(
            max(0.0, time.monotonic() - self._repair_started_at), 3
        )

    def finish_verdict(self, verdict: str) -> None:
        """Compare only the terminal probe with the canonical final verdict."""
        probe_result = self._state.get("terminal_probe_result")
        if probe_result == "complete":
            self._state["probe_final_verifier_disagreed"] = verdict != VERDICT_PASS
        elif probe_result == "incomplete":
            self._state["probe_final_verifier_disagreed"] = verdict != VERDICT_TASK_FAIL
        else:
            self._state["probe_final_verifier_disagreed"] = None

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe policy fields for the attempt record."""
        return deepcopy(self._state)


def finalize_snapshot(snapshot: dict[str, Any], verdict: str) -> dict[str, Any]:
    """Add final probe/verifier agreement without changing the probe history."""
    result = deepcopy(snapshot)
    probe_result = result.get("terminal_probe_result")
    if probe_result == "complete":
        result["probe_final_verifier_disagreed"] = verdict != VERDICT_PASS
    elif probe_result == "incomplete":
        result["probe_final_verifier_disagreed"] = verdict != VERDICT_TASK_FAIL
    else:
        result["probe_final_verifier_disagreed"] = None
    return result
