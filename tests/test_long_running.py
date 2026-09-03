"""Tests for task contracts, acceptance checks, and cache observations."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from openrouter_agent_cli.cache import CacheAwareContext
from openrouter_agent_cli.cli import (
    DEFAULT_SYSTEM_PROMPT,
    CheckpointDecision,
    OpenRouterAgentCLI,
    RuntimeCheckpoint,
    ToolPermissionPolicy,
)
from openrouter_agent_cli.completion import UserCompletionPolicy
from openrouter_agent_cli.eval.transport import MockTransport


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


def _engine_with_task(
    tmp_path,
    monkeypatch,
    *,
    task: str,
    verify_command: str,
    responses: list[dict],
    workdir=None,
) -> OpenRouterAgentCLI:
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    engine = OpenRouterAgentCLI(
        api_key="not-a-real-key",
        model="mock-model",
        session_id="product-test",
        workdir=str(workdir or tmp_path),
        max_turns=10,
        max_history_messages=64,
        command_timeout=30,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
        task=task,
        verify_command=verify_command,
    )
    engine.non_interactive_mode = True
    engine.policy = ToolPermissionPolicy(allow={"*"})
    engine.model_transport = MockTransport({"responses": responses})
    return engine


@pytest.mark.asyncio
async def test_tool_using_repair_is_reverified(tmp_path, monkeypatch):
    """A repair response that used mutating tools must re-run the acceptance
    check at that boundary and stop with fresh evidence (not end silently)."""
    engine = _engine_with_task(
        tmp_path,
        monkeypatch,
        task="Create marker.txt",
        verify_command="test -f marker.txt",
        responses=[
            {"tool_calls": [
                {"name": "write_file",
                 "arguments": {"path": "tmp.txt", "content": "x\n"}}
            ]},
            {"text": "I wrote tmp.txt, marker is next"},
            {"tool_calls": [
                {"name": "write_file",
                 "arguments": {"path": "marker.txt", "content": "ok\n"}}
            ]},
            {"text": "must not be requested"},
        ],
    )
    async with httpx.AsyncClient() as client:
        result = await engine._run_user_turn(client, "Do the work.")

    assert result == ""
    assert engine.work_order["status"] == "verified"
    assert (Path(engine.workdir) / "marker.txt").is_file()
    assert engine.completion_policy.last_result["status"] == "verified"
    # The 4th scripted response must not be consumed.
    assert len(engine.model_transport.requests) == 3


@pytest.mark.asyncio
async def test_read_only_repair_response_is_reverified(tmp_path, monkeypatch):
    """A repair response using only read-only tools still re-runs the
    acceptance check before the turn stops. A read-only repair cannot change
    the workspace, so the second check honestly reports failed and the turn
    ends with that evidence instead of silently."""
    engine = _engine_with_task(
        tmp_path,
        monkeypatch,
        task="Create marker.txt",
        verify_command="test -f marker.txt",
        responses=[
            {"tool_calls": [
                {"name": "write_file",
                 "arguments": {"path": "tmp.txt", "content": "x\n"}}
            ]},
            {"text": "checking the workspace"},
            {"tool_calls": [{"name": "list_dir", "arguments": {"path": "."}}]},
            {"text": "must not be requested"},
        ],
    )
    async with httpx.AsyncClient() as client:
        result = await engine._run_user_turn(client, "Do the work.")

    assert result == ""
    # The second acceptance check ran at the read-only boundary (and failed,
    # because a read-only repair could not create marker.txt).
    assert engine.completion_policy.last_result["status"] == "failed"
    assert engine.work_order["status"] == "failed"
    assert len(engine.model_transport.requests) == 3


@pytest.mark.asyncio
async def test_resume_rebinds_the_resumed_sessions_contract(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    base = {
        "api_key": "test-key",
        "model": "test-model",
        "max_turns": 2,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "discovery_mode": "off",
    }
    session_a = OpenRouterAgentCLI(
        **base,
        session_id="session-a",
        workdir=str(tmp_path),
        task="Task A",
        verify_command="test -f a.txt",
    )
    session_a._save_session()

    session_b = OpenRouterAgentCLI(
        **base,
        session_id="session-b",
        workdir=str(tmp_path),
        task="Task B",
        verify_command="test -f b.txt",
    )
    assert session_b.completion_policy.command == "test -f b.txt"

    # Resuming A must bind A's command, not carry B's policy forward.
    await session_b._handle_command(None, "/resume session-a")
    assert session_b.work_order["objective"] == "Task A"
    assert session_b.completion_policy.command == "test -f a.txt"

    # Resuming a contractless session must clear the contract entirely.
    session_c = OpenRouterAgentCLI(
        **base, session_id="session-c", workdir=str(tmp_path)
    )
    session_c._save_session()
    await session_b._handle_command(None, "/resume session-c")
    assert session_b.work_order is None
    assert session_b.completion_policy is None


@pytest.mark.asyncio
async def test_cwd_rescopes_the_acceptance_contract(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    other = tmp_path / "other-project"
    other.mkdir()
    cli = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="cwd-test",
        workdir=str(tmp_path),
        max_turns=2,
        max_history_messages=60,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
        task="Task X",
        verify_command="pytest -q",
    )
    assert cli.completion_policy.workdir == os.path.abspath(str(tmp_path))

    await cli._handle_command(None, f"/cwd {other}")
    assert cli.completion_policy.workdir == os.path.abspath(str(other))
    assert cli.work_order["status"] == "not_verified"
    assert cli.work_order["last_check"] is None


@pytest.mark.asyncio
async def test_provider_failure_sets_terminal_status(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    cli = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="provider-test",
        workdir=str(tmp_path),
        max_turns=2,
        max_history_messages=60,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
    )
    cli.non_interactive_mode = True
    cli.policy = ToolPermissionPolicy(allow={"*"})

    class BoomTransport:
        async def __call__(self, client, **kwargs):
            raise RuntimeError("provider unreachable")

    cli.model_transport = BoomTransport()
    async with httpx.AsyncClient() as client:
        await cli._run_user_turn(client, "hi")
    assert cli.terminal_status == "provider_error"


@pytest.mark.asyncio
async def test_loop_breaker_failure_is_provider_error(tmp_path, monkeypatch):
    """A failed forced loop-breaker call must be recorded as a provider error
    and terminate, not fabricate a normal answer."""
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    cli = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="loop-break-test",
        workdir=str(tmp_path),
        max_turns=10,
        max_history_messages=60,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
    )
    cli.non_interactive_mode = True
    cli.policy = ToolPermissionPolicy(allow={"*"})
    repeated = {"name": "run_bash", "arguments": {"command": "true"}}

    class FailingLoopBreaker:
        def __init__(self):
            self.requests = 0

        async def __call__(self, client, **kwargs):
            self.requests += 1
            if kwargs.get("tool_choice") == "none":
                raise RuntimeError("loop-breaker provider failure")
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"tc-{self.requests}",
                                    "type": "function",
                                    "function": {
                                        "name": "run_bash",
                                        "arguments": '{"command": "true"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }

    transport = FailingLoopBreaker()
    cli.model_transport = transport
    async with httpx.AsyncClient() as client:
        result = await cli._run_user_turn(client, "do it")
    assert result == ""
    assert cli.terminal_status == "provider_error"
    # The repeated tool call was nudged; the forced request failed once.
    assert transport.requests == 3


@pytest.mark.asyncio
async def test_tool_repair_emits_completion_notice(
    tmp_path, monkeypatch, capsys
):
    """The tool-using repair path must print a deterministic completion notice
    so one-shot mode is not left with an empty stdout."""
    engine = _engine_with_task(
        tmp_path,
        monkeypatch,
        task="Create marker.txt",
        verify_command="test -f marker.txt",
        responses=[
            {"tool_calls": [
                {"name": "write_file",
                 "arguments": {"path": "tmp.txt", "content": "x\n"}}
            ]},
            {"text": "I wrote tmp.txt, marker is next"},
            {"tool_calls": [
                {"name": "write_file",
                 "arguments": {"path": "marker.txt", "content": "ok\n"}}
            ]},
            {"text": "must not be requested"},
        ],
    )
    async with httpx.AsyncClient() as client:
        await engine._run_user_turn(client, "Do the work.")
    out = capsys.readouterr().out
    assert "Turn ended after the repair check: VERIFIED" in out


def test_cached_prefix_is_not_restored_on_resume(tmp_path, monkeypatch):
    """Session loading restores cumulative counters but never transient
    stable-prefix state (there are no stored request hashes to back it)."""
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "workdir": str(tmp_path),
        "max_turns": 2,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "discovery_mode": "off",
    }
    first = OpenRouterAgentCLI(**kwargs, session_id="cache-resume")
    prefix = [
        {"role": "system", "content": "stable-system"},
        {"role": "user", "content": "hello"},
    ]
    first.cache_context.observe_request(prefix)
    first.cache_context.observe_request(prefix + [{"role": "assistant", "content": "hi"}])
    assert first.cache_context.stable_prefix_tokens > 0
    first._save_session()

    resumed = OpenRouterAgentCLI(**kwargs, session_id="cache-resume")
    assert resumed.cache_context.stable_prefix_tokens == 0
    assert resumed.cache_context.stable_prefix_messages == 0
    # Cumulative observations survive.
    assert resumed.cache_context.requests == 2


def test_workdir_mismatch_invalidates_acceptance(tmp_path, monkeypatch):
    """An acceptance result from another directory must never be shown as
    verified after resuming in a different workdir."""
    session_dir = tmp_path / "sessions"
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "max_turns": 2,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "discovery_mode": "off",
    }
    first = OpenRouterAgentCLI(
        **kwargs, session_id="workdir-switch", workdir=str(tmp_path),
        task="Task X", verify_command="pytest -q",
    )
    first.work_order["status"] = "verified"
    first._save_session()

    resumed = OpenRouterAgentCLI(
        **kwargs, session_id="workdir-switch", workdir=str(other)
    )
    assert resumed.work_order["objective"] == "Task X"
    assert resumed.work_order["status"] == "not_verified"
    assert resumed.work_order["last_check"] is None


@pytest.mark.asyncio
async def test_cwd_change_persists_contract_reset(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    other = tmp_path / "other-project"
    other.mkdir()
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    cli = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="cwd-persist",
        workdir=str(tmp_path),
        max_turns=2,
        max_history_messages=60,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
        task="Task X",
        verify_command="pytest -q",
    )
    cli.work_order["status"] = "verified"
    await cli._handle_command(None, f"/cwd {other}")

    persisted = json.loads(cli._session_path.read_text())
    assert persisted["work_order"]["status"] == "not_verified"
    assert persisted["work_order"]["verify_command"] == "pytest -q"


def _git_repo(tmp_path, monkeypatch, session_id="diff-test") -> Path:
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _plain_cli(tmp_path, workdir, session_id="diff-test") -> OpenRouterAgentCLI:
    return OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id=session_id,
        workdir=str(workdir),
        max_turns=2,
        max_history_messages=60,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
    )


@pytest.mark.asyncio
async def test_diff_shows_tracked_and_untracked(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path, monkeypatch)
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")

    cli = _plain_cli(tmp_path, repo)
    await cli._run_diff()
    out = capsys.readouterr().out
    assert "-one" in out and "+two" in out
    assert "new.txt" in out  # untracked files listed separately


@pytest.mark.asyncio
async def test_diff_stat_and_path_filter(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path, monkeypatch)
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "b.txt").write_text("new\n", encoding="utf-8")

    cli = _plain_cli(tmp_path, repo)
    await cli._run_diff("--stat")
    out = capsys.readouterr().out
    assert "1 file changed" in out

    await cli._run_diff("a.txt")
    out = capsys.readouterr().out
    assert "-one" in out and "+two" in out
    assert "b.txt" not in out.split("Untracked files")[0]


@pytest.mark.asyncio
async def test_diff_non_git_directory_is_honest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    cli = _plain_cli(tmp_path, tmp_path)
    await cli._run_diff()
    out = capsys.readouterr().out
    assert "not inside a git repository" in out
    assert "/export" in out


@pytest.mark.asyncio
async def test_changed_files_handles_renames_with_spaces(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path, monkeypatch, session_id="rename-test")
    (repo / "a.txt").rename(repo / "renamed file.txt")

    policy = UserCompletionPolicy(command="true", workdir=str(repo))
    changed = await policy._changed_files()
    assert "renamed file.txt" in changed
