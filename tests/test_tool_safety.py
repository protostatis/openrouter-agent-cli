"""Regression tests for tool safety, lifecycle metadata, and transcript invariants."""

from __future__ import annotations

import copy
import hashlib
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from openrouter_agent_cli import cli as cli_module
from openrouter_agent_cli.cli import DEFAULT_SYSTEM_PROMPT, OpenRouterAgentCLI, _strip_control_chars
from openrouter_agent_cli.utils import run_bash


def _make_cli(tmp_path, **overrides):
    kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "session_id": f"safety-test-{hashlib.sha1(str(tmp_path).encode()).hexdigest()[:10]}",
        "workdir": str(tmp_path),
        "max_turns": 2,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "discovery_mode": "mock",
        "max_concurrency": 3,
        "max_discover": 2,
        "max_rounds": 2,
    }
    kwargs.update(overrides)
    return OpenRouterAgentCLI(**kwargs)


def _tool_response(calls):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": calls,
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _final_response(text="done"):
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ]
    }


def _discover_call(call_id: str, query: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "discover",
            "arguments": json.dumps(
                {"kind": "search", "query": query, "goal": "find evidence"}
            ),
        },
    }


@pytest.mark.asyncio
async def test_mixed_batch_preserves_every_tool_call_id(tmp_path):
    agent = _make_cli(tmp_path, max_discover=1)
    agent.policy.allow.add("*")
    calls = [
        {
            "id": "shell-1",
            "type": "function",
            "function": {"name": "run_bash", "arguments": '{"command":"echo ok"}'},
        },
        _discover_call("web-1", "one"),
        _discover_call("web-2", "two"),
        _discover_call("web-3", "three"),
    ]
    fake_openrouter = AsyncMock(side_effect=[_tool_response(calls), _final_response()])

    with patch.object(cli_module, "call_openrouter", fake_openrouter):
        await agent._run_user_turn(httpx.AsyncClient(), "inspect")

    tool_messages = [m for m in agent.messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == [
        "shell-1",
        "web-1",
        "web-2",
        "web-3",
    ]
    assert "ok" in tool_messages[0]["content"]
    assert "max_discover" in tool_messages[2]["content"]
    assert "max_discover" in tool_messages[3]["content"]


@pytest.mark.asyncio
async def test_compaction_failure_keeps_history(tmp_path):
    agent = _make_cli(tmp_path)
    agent.messages.extend(
        {"role": "user", "content": f"message {i}"} for i in range(20)
    )
    before = copy.deepcopy(agent.messages)
    agent._call_openrouter = AsyncMock(side_effect=RuntimeError("summary unavailable"))

    compacted = await agent._compact_history(httpx.AsyncClient(), force=True)

    assert compacted is False
    assert agent.messages == before


@pytest.mark.asyncio
async def test_shell_does_not_inherit_api_key_and_bounds_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-value")
    hidden = json.loads(
        await run_bash(
            "printf '%s' \"$OPENROUTER_API_KEY\"",
            str(tmp_path),
            5,
            structured=True,
        )
    )
    assert "secret-value" not in hidden.get("stdout", "")
    assert hidden["ok"] is True

    output = json.loads(
        await run_bash(
            "printf '%*s' 30000 ''",
            str(tmp_path),
            5,
            structured=True,
        )
    )
    assert output["truncated"] is True
    assert len(output.get("stdout", "")) <= 20_000


@pytest.mark.asyncio
async def test_shell_default_remains_legacy_plain_text(tmp_path):
    assert await run_bash("printf ok", str(tmp_path), 5) == "ok"


@pytest.mark.asyncio
async def test_read_file_handles_empty_and_invalid_paged_reads(tmp_path):
    agent = _make_cli(tmp_path)
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")

    empty = json.loads(await agent._read_file("empty.txt", None, None))
    assert empty["ok"] is True
    assert empty["content"] == ""

    invalid = json.loads(
        await agent._read_file("empty.txt", None, None, cursor="not-a-cursor")
    )
    assert invalid["ok"] is False
    assert "invalid cursor" in invalid["error"]


def test_terminal_sanitizer_removes_csi_and_osc_sequences():
    value = "safe\x1b[31mred\x1b[0m\x1b]8;;https://evil.test\x1b\\click\x07"
    assert _strip_control_chars(value) == "saferedclick"


@pytest.mark.asyncio
async def test_file_write_supports_hash_precondition_and_dry_run(tmp_path):
    agent = _make_cli(tmp_path)
    path = tmp_path / "file.txt"
    path.write_text("old", encoding="utf-8")
    digest = hashlib.sha256(b"old").hexdigest()

    preview = await agent._write_file("file.txt", "new", digest, True)
    assert "dry-run" in preview
    assert path.read_text(encoding="utf-8") == "old"

    stale = await agent._write_file("file.txt", "new", "0" * 64)
    assert "stale file" in stale
