"""Tests for task contracts, acceptance checks, and cache observations."""

from __future__ import annotations

import shlex
import sys

import pytest

from openrouter_agent_cli.cache import CacheAwareContext
from openrouter_agent_cli.cli import (
    DEFAULT_SYSTEM_PROMPT,
    CheckpointDecision,
    OpenRouterAgentCLI,
    RuntimeCheckpoint,
)
from openrouter_agent_cli.completion import UserCompletionPolicy


def _checkpoint() -> RuntimeCheckpoint:
    return RuntimeCheckpoint(
        sequence=1,
        kind="final_answer",
        turn=1,
        tool_names=(),
        observed_at=0.0,
        total_tokens=0,
    )


def test_cache_context_distinguishes_prefix_and_provider_observation():
    context = CacheAwareContext()
    messages = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "first"},
    ]

    first = context.observe_request(messages)
    assert first["stable_prefix_messages"] == 0
    assert first["provider_cache_status"] == "not observable"

    second = context.observe_request(
        messages + [{"role": "assistant", "content": "answer"}],
        {"prompt_tokens_details": {"cached_tokens": 12}},
    )
    assert second["stable_prefix_messages"] == 2
    assert second["stable_prefix_tokens"] > 0
    assert second["last_cached_tokens"] == 12
    assert second["provider_cache_status"] == "observed"

    context.note_compaction()
    assert context.snapshot()["stable_prefix_messages"] == 0


@pytest.mark.asyncio
async def test_acceptance_policy_repairs_once_then_stops(tmp_path):
    command = f"{shlex.quote(sys.executable)} -c 'import sys; sys.exit(1)'"
    policy = UserCompletionPolicy(command=command, workdir=str(tmp_path))

    first = await policy(_checkpoint())
    second = await policy(_checkpoint())

    assert isinstance(first, CheckpointDecision)
    assert first.action == "repair"
    assert second.action == "continue"
    assert policy.repair_injections == 1
    assert policy.last_result["status"] == "failed"


@pytest.mark.asyncio
async def test_acceptance_policy_marks_passing_check_verified(tmp_path):
    command = f"{shlex.quote(sys.executable)} -c 'print(\"pass\")'"
    policy = UserCompletionPolicy(command=command, workdir=str(tmp_path))

    decision = await policy(_checkpoint())

    assert decision.action == "stop"
    assert policy.last_result["status"] == "verified"


def test_work_order_persists_across_resume(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "session_id": "long-session",
        "workdir": str(tmp_path),
        "max_turns": 2,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    }
    first = OpenRouterAgentCLI(**kwargs, task="Fix the login test", verify_command="pytest -q")
    first._save_session()

    resumed = OpenRouterAgentCLI(**kwargs)
    assert resumed.work_order["objective"] == "Fix the login test"
    assert resumed.work_order["verify_command"] == "pytest -q"
    assert "Fix the login test" in resumed._work_order_message("continue")
