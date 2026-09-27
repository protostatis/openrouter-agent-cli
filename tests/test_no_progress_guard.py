"""Offline tests for the required-change no-progress guard.

The guard watches ACTUAL worktree content (git status), not tool names. A
scripted MockTransport plays the model; the engine executes the tool calls
for real inside a temporary git repository. No network, no tokens.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from openrouter_agent_cli.cli import (
    DEFAULT_SYSTEM_PROMPT,
    NO_PROGRESS_NUDGE_TURNS,
    OpenRouterAgentCLI,
    _NO_PROGRESS_NUDGE_MESSAGE,
    _NO_PROGRESS_STOP_MESSAGE,
)
from openrouter_agent_cli.eval.transport import MockTransport


def _tool(name: str, **arguments) -> dict:
    """One scripted model response that calls exactly one tool."""
    return {"tool_calls": [{"name": name, "arguments": arguments}]}


def _readonly(i: int = 0) -> dict:
    # Unique per call: identical repeated batches would trigger the
    # loop-breaker nudge, which is a different mechanism under test.
    return _tool("run_bash", command=f"echo inspect-{i}")


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _make_agent(workdir: Path, **overrides) -> OpenRouterAgentCLI:
    import os
    import uuid

    kwargs = dict(
        api_key="test-key",
        model="test-model",
        session_id=f"no-progress-guard-{uuid.uuid4().hex[:8]}",
        workdir=str(workdir),
        max_turns=24,
        max_history_messages=40,
        command_timeout=10,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
        require_repo_change=True,
    )
    kwargs.update(overrides)
    # Session state lives under the test's own directory so tests never
    # resume each other's saved sessions.
    os.environ["OPENROUTER_AGENT_SESSION_DIR"] = str(workdir / "sessions")
    agent = OpenRouterAgentCLI(**kwargs)
    agent.policy.allow.add("*")
    agent.non_interactive_mode = True
    return agent


def _run_turn(agent: OpenRouterAgentCLI, prompt: str = "work") -> str:
    async def _run():
        import httpx

        async with httpx.AsyncClient() as client:
            return await agent._run_user_turn(client, prompt)

    return asyncio.run(_run())


def _nudge_request_index(transport: MockTransport) -> int | None:
    """Index of the first model request whose messages contain the nudge."""
    for i, request in enumerate(transport.requests):
        for message in request["messages"]:
            if message.get("content") == _NO_PROGRESS_NUDGE_MESSAGE:
                return i
    return None


def test_readonly_turns_trigger_one_nudge_then_recover(tmp_path, git_repo):
    """Six read-only turns nudge once; the next write succeeds and the run ends ok."""
    transport = MockTransport(
        {"responses": [_readonly(i) for i in range(NO_PROGRESS_NUDGE_TURNS)]
         + [_tool("write_file", path="out.txt", content="done"), {"text": "done"}]}
    )
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    assert result == "done"
    nudge_at = _nudge_request_index(transport)
    assert nudge_at is not None
    # The nudge arrives after the configured number of unchanged turns and
    # exactly one nudge message was ever appended to the conversation (the
    # message then persists in later request snapshots, which is expected):
    assert nudge_at >= NO_PROGRESS_NUDGE_TURNS
    assert (
        sum(
            1
            for message in agent.messages
            if message.get("content") == _NO_PROGRESS_NUDGE_MESSAGE
        )
        == 1
    )
    assert (tmp_path / "out.txt").read_text() == "done"


def test_premature_final_answer_is_suppressed_and_nudged(tmp_path, git_repo):
    """A final answer on an unchanged worktree is suppressed; the run continues."""
    transport = MockTransport(
        {"responses": [{"text": "I'm done!"},
                       _tool("write_file", path="out.txt", content="real work"),
                       {"text": "now done"}]}
    )
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    assert result == "now done"
    assert _nudge_request_index(transport) == 1
    assert (tmp_path / "out.txt").read_text() == "real work"


def test_post_nudge_unchanged_final_stops_with_message(tmp_path, git_repo):
    """After the nudge, a second unchanged final answer ends the turn with the stop message."""
    transport = MockTransport(
        {"responses": [{"text": "finished"}, {"text": "still nothing"}]}
    )
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    assert result == _NO_PROGRESS_STOP_MESSAGE
    assert len(transport.requests) == 2


def test_failed_edit_and_readonly_bash_do_not_count_as_progress(tmp_path, git_repo):
    """A failed edit_file and read-only run_bash both keep the counter rising."""
    failed_edit = _tool(
        "edit_file", path="out.txt", content="x", expected_sha256="0" * 64
    )
    transport = MockTransport(
        {"responses": [failed_edit]
         + [_readonly(i) for i in range(4)]
         + [{"text": "give up"}, {"text": "still nothing"}]}
    )
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    # The premature final answer after five unchanged turns is suppressed and
    # nudged (a final-answer gate may fire before six turns), then the next
    # unchanged final answer stops:
    assert result == _NO_PROGRESS_STOP_MESSAGE
    assert _nudge_request_index(transport) is not None
    assert (
        sum(
            1
            for message in agent.messages
            if message.get("content") == _NO_PROGRESS_NUDGE_MESSAGE
        )
        == 1
    )


def test_real_content_change_resets_and_no_nudge(tmp_path, git_repo):
    """Real content changes reset the counter; no nudge is ever injected."""
    responses = [
        _tool("run_bash", command=f"printf 'x{i}' >> out.txt") for i in range(3)
    ] + [{"text": "done"}]
    transport = MockTransport({"responses": responses})
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    assert result == "done"
    assert _nudge_request_index(transport) is None
    assert "x" in (tmp_path / "out.txt").read_text()


def test_guard_inactive_without_git_repository(tmp_path):
    """Outside a git repository the guard stays silent (no nudge, no stop)."""
    transport = MockTransport(
        {"responses": [_readonly(i) for i in range(NO_PROGRESS_NUDGE_TURNS + 2)]
         + [{"text": "done"}]}
    )
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    assert result == "done"
    assert _nudge_request_index(transport) is None


def test_first_turn_edit_then_final_is_accepted(tmp_path, git_repo):
    """An edit made on the very first turn counts as progress, not as the baseline.

    Regression: the baseline used to be captured only AFTER the first turn's
    tools had run, so a turn-1 edit silently became the baseline and the
    correct final answer on turn 2 was suppressed, then stopped as 'no
    changes made'. The baseline must be captured before any model action.
    """
    transport = MockTransport(
        {"responses": [
            _tool("write_file", path="out.txt", content="real work"),
            {"text": "done"},
        ]}
    )
    agent = _make_agent(tmp_path)
    agent.model_transport = transport

    result = _run_turn(agent)

    assert result == "done"
    assert _nudge_request_index(transport) is None
    assert (tmp_path / "out.txt").read_text() == "real work"
