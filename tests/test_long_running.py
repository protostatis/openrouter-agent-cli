"""Tests for task contracts, acceptance checks, and cache observations."""

from __future__ import annotations

import asyncio
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


@pytest.mark.asyncio
async def test_acceptance_policy_times_out_records_not_verified(tmp_path):
    """A timed-out acceptance check never claims that work was verified."""
    command = f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(10)'"
    policy = UserCompletionPolicy(command=command, workdir=str(tmp_path), timeout_seconds=1)

    decision = await policy(_checkpoint())

    assert policy.last_result["status"] == "not_verified"
    assert policy.last_result["timed_out"] is True
    assert decision.action != "stop"

    # A timeout does not poison the contract; a later check is still recorded
    # as not_verified rather than incorrectly reusing an earlier status.
    second = await policy(_checkpoint())
    assert second.action != "stop"
    assert policy.last_result["status"] == "not_verified"


@pytest.mark.asyncio
async def test_acceptance_policy_checks_turn_limit_and_repairs(tmp_path, monkeypatch):
    """A policy-enabled run can rescue work left unfinished at the turn limit."""
    engine = _engine_with_task(
        tmp_path,
        monkeypatch,
        task="Create marker.txt",
        verify_command="test -f marker.txt",
        responses=[
            {
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {"path": "partial.txt", "content": "x\n"},
                    }
                ]
            },
            {
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {"path": "marker.txt", "content": "ok\n"},
                    }
                ]
            },
        ],
    )
    engine.max_turns = 1

    async with httpx.AsyncClient() as client:
        result = await engine._run_user_turn(client, "Do the work.")

    assert result == ""
    assert (Path(engine.workdir) / "marker.txt").is_file()
    assert engine.completion_policy.last_result["status"] == "verified"
    assert engine.completion_policy.repair_injections == 1
    assert len(engine.model_transport.requests) == 2


def _git(workdir: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_changed_files_excludes_python_bytecode(tmp_path):
    """__pycache__ noise in a fresh repository must not be listed as changed
    files: only source changes prove real work, and bytecode artifacts make
    every session look like it changed something."""
    _git(tmp_path, "init")
    (tmp_path / "app.py").write_text("print('hi')\n")
    _git(tmp_path, "add", "app.py")
    _git(
        tmp_path,
        "-c", "user.email=t@example.com",
        "-c", "user.name=t",
        "commit", "-m", "init",
    )
    # Source edit + a new source file + bytecode artifacts.
    (tmp_path / "app.py").write_text("print('bye')\n")
    (tmp_path / "helper.py").write_text("x = 1\n")
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "app.cpython-314.pyc").write_bytes(b"\x00")
    (tmp_path / "loose.pyc").write_bytes(b"\x00")

    policy = UserCompletionPolicy(command="true", workdir=str(tmp_path))
    changed = await policy._changed_files()

    assert set(changed) == {"app.py", "helper.py"}
    assert not any(path.endswith((".pyc", ".pyo")) for path in changed)
    assert not any("__pycache__" in path for path in changed)


def test_generated_path_filter():
    from openrouter_agent_cli.completion import _is_generated_path

    assert _is_generated_path("__pycache__/app.cpython-314.pyc")
    assert _is_generated_path("pkg/__pycache__/mod.cpython-314.pyc")
    assert _is_generated_path("app.pyc")
    assert _is_generated_path("app.pyo")
    assert not _is_generated_path("app.py")
    assert not _is_generated_path("src/cache.py")


@pytest.mark.asyncio
async def test_approval_wait_is_not_counted_as_tool_runtime(
    tmp_path, monkeypatch
):
    """The time a developer spends reading the permission prompt must not be
    reported as tool execution time — a millisecond file edit used to show as
    tens of seconds in the [tool-result] line."""
    engine = _engine_with_task(
        tmp_path,
        monkeypatch,
        task="List the directory",
        verify_command="true",
        responses=[{"text": "done"}],
    )
    monkeypatch.setattr(
        engine, "_effective_policy_decision", lambda name: "ask"
    )

    async def slow_confirm(tool_name, args):
        await asyncio.sleep(0.15)
        return True

    monkeypatch.setattr(engine, "_confirm_tool_call", slow_confirm)
    await engine._run_tool_call("list_dir", {"path": "."}, "tc-approval")

    record = engine._tool_records["tc-approval"]
    assert record["status"] == "succeeded"
    assert record["approval_wait_ms"] >= 100
    # Duration covers execution only; the approval pause is excluded.
    assert record["duration_ms"] < 100
    assert record["duration_ms"] < record["approval_wait_ms"]


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


def test_startup_hints_flag_resumed_sessions_and_unstarted_tasks(
    tmp_path, monkeypatch
):
    """Resuming an old session and loading a task without starting it must
    both be stated plainly under the startup status, where the lines stay
    visible even when the top banner scrolls away."""
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "session_id": "hints-session",
        "workdir": str(tmp_path),
        "max_turns": 2,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "discovery_mode": "off",
    }

    # Fresh run with a task: only the not-yet-started hint.
    fresh = OpenRouterAgentCLI(**kwargs, task="Do the thing")
    fresh_hints = fresh._startup_hints()
    assert any("Task attached but not started" in h for h in fresh_hints)
    assert not any("Resumed session" in h for h in fresh_hints)

    # Resumed before any assistant reply: both hints.
    fresh.messages.append({"role": "user", "content": "hello"})
    fresh._save_session()
    resumed = OpenRouterAgentCLI(**kwargs)
    resumed_hints = resumed._startup_hints()
    assert any("Resumed session" in h for h in resumed_hints)
    assert any("Task attached but not started" in h for h in resumed_hints)

    # Resumed mid-work: the resume hint only, never the not-started hint.
    fresh.messages.append({"role": "assistant", "content": "working on it"})
    fresh._save_session()
    resumed_mid = OpenRouterAgentCLI(**kwargs)
    mid_hints = resumed_mid._startup_hints()
    assert any("Resumed session" in h for h in mid_hints)
    assert not any("Task attached but not started" in h for h in mid_hints)


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
async def test_read_only_repair_rounds_allow_inspect_then_edit(
    tmp_path, monkeypatch
):
    """A repair response that only inspected files may continue, so an
    inspect-then-edit model gets to act on what it learned: the read-only
    reply is followed by a real edit, the check passes, and the turn ends
    verified instead of stopping at the inspection."""
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
    # write + final-answer + read-only round + marker write; the 5th scripted
    # response must not be consumed.
    assert len(engine.model_transport.requests) == 4


@pytest.mark.asyncio
async def test_read_only_repair_rounds_are_bounded(
    tmp_path, monkeypatch, capsys
):
    """Read-only inspection during a repair is bounded: after the allowed
    rounds the turn re-runs the acceptance check once and stops with that
    fresh evidence instead of looping on pure reads."""
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
            {"tool_calls": [{"name": "read_file", "arguments": {"path": "tmp.txt"}}]},
            {"tool_calls": [{"name": "list_dir", "arguments": {"path": "."}}]},
            {"text": "must not be requested"},
        ],
    )
    async with httpx.AsyncClient() as client:
        result = await engine._run_user_turn(client, "Do the work.")

    assert result == ""
    # write, final-answer, two allowed read-only rounds, then one more
    # read-only reply that trips the bound and ends the turn; the 6th
    # scripted response must not be consumed.
    assert len(engine.model_transport.requests) == 5
    assert engine.completion_policy.last_result["status"] == "failed"
    assert engine.work_order["status"] == "failed"
    captured = capsys.readouterr()
    assert (
        "[cli] Turn ended after the repair check: FAILED"
        in captured.out + captured.err
    )


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
async def test_provider_failure_sets_terminal_status(tmp_path, monkeypatch, capsys):
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
    # The failure line names the error, not just "Request failed:".
    captured = capsys.readouterr()
    assert (
        "[openrouter] Request failed: RuntimeError: provider unreachable"
        in captured.err + captured.out
    )
    # Non-interactive runs do not print the interactive /retry hint.
    assert "/retry" not in captured.err + captured.out


@pytest.mark.asyncio
async def test_provider_failure_with_empty_message_still_says_why(
    tmp_path, monkeypatch, capsys
):
    """Transport failures like TimeoutError() stringify to an empty message;
    the failure line must still name the error type instead of ending at a
    bare colon."""
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    cli = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="provider-timeout-test",
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

    class TimeoutTransport:
        async def __call__(self, client, **kwargs):
            raise TimeoutError()

    cli.model_transport = TimeoutTransport()
    async with httpx.AsyncClient() as client:
        await cli._run_user_turn(client, "hi")
    assert cli.terminal_status == "provider_error"
    captured = capsys.readouterr()
    failure_line = captured.err + captured.out
    assert "[openrouter] Request failed: TimeoutError" in failure_line
    assert "no detail" in failure_line


@pytest.mark.asyncio
async def test_provider_failure_hint_offered_interactively(
    tmp_path, monkeypatch, capsys
):
    """Interactive runs are told how to resume the failed request."""
    session_dir = tmp_path / "sessions"
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(session_dir))
    cli = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="provider-interactive-test",
        workdir=str(tmp_path),
        max_turns=2,
        max_history_messages=60,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
    )
    cli.policy = ToolPermissionPolicy(allow={"*"})

    class BoomTransport:
        async def __call__(self, client, **kwargs):
            raise RuntimeError("provider unreachable")

    cli.model_transport = BoomTransport()
    async with httpx.AsyncClient() as client:
        await cli._run_user_turn(client, "hi")
    captured = capsys.readouterr()
    assert "type /retry to try again" in captured.err + captured.out
    assert cli._last_failed_prompt == "hi"


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
    # A loop-breaker failure stays retryable like any other provider failure.
    assert cli._last_failed_prompt == "do it"
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
