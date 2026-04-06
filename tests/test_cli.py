"""Unit tests for openrouter_agent_cli.cli."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openrouter_agent_cli.cli import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_SYSTEM_PROMPT,
    OpenRouterAgentCLI,
    TOOLS,
    ToolPermissionPolicy,
    _estimate_tokens,
    _message_content_as_text,
    _sanitize_session_id,
    _truncate,
)
from openrouter_agent_cli.utils import _decode_tool_arguments


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _make_cli(**overrides) -> "OpenRouterAgentCLI":
    """Create an OpenRouterAgentCLI instance with safe defaults."""
    tmpdir = tempfile.mkdtemp()
    kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "session_id": "test-session",
        "workdir": tmpdir,
        "max_turns": 3,
        "max_history_messages": 60,
        "command_timeout": 5,
        "tools_enabled": True,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
    }
    kwargs.update(overrides)
    return OpenRouterAgentCLI(**kwargs)


# ---------------------------------------------------------------------------
# _sanitize_session_id
# ---------------------------------------------------------------------------


class TestSanitizeSessionId:
    def test_safe_id_unchanged(self):
        assert _sanitize_session_id("my-session_1.0") == "my-session_1.0"

    def test_unsafe_chars_replaced(self):
        assert _sanitize_session_id("hello world!") == "hello_world_"

    def test_dots_are_safe(self):
        assert _sanitize_session_id("/../") == "_.._"

    def test_only_unsafe_returns_underscores(self):
        result = _sanitize_session_id("!!!")
        assert result == "___"


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_text_truncated(self):
        result = _truncate("a" * 100, 10)
        assert result == "a" * 10 + "..."

    def test_exact_length_unchanged(self):
        assert _truncate("abcde", 5) == "abcde"


# ---------------------------------------------------------------------------
# _decode_tool_arguments
# ---------------------------------------------------------------------------


class TestDecodeToolArguments:
    def test_none_returns_empty(self):
        assert _decode_tool_arguments(None) == {}

    def test_dict_passthrough(self):
        assert _decode_tool_arguments({"key": "val"}) == {"key": "val"}

    def test_valid_json_string(self):
        assert _decode_tool_arguments('{"cmd": "ls"}') == {"cmd": "ls"}

    def test_invalid_json_returns_empty(self):
        assert _decode_tool_arguments("not json") == {}

    def test_empty_string_returns_empty(self):
        assert _decode_tool_arguments("") == {}

    def test_json_array_returns_empty(self):
        assert _decode_tool_arguments("[1, 2, 3]") == {}

    def test_whitespace_string_returns_empty(self):
        assert _decode_tool_arguments("   ") == {}


# ---------------------------------------------------------------------------
# _message_content_as_text
# ---------------------------------------------------------------------------


class TestMessageContentAsText:
    def test_string_content(self):
        assert _message_content_as_text({"content": "hello"}) == "hello"

    def test_none_content(self):
        assert _message_content_as_text({"content": None}) == ""

    def test_missing_content_key(self):
        assert _message_content_as_text({}) == ""

    def test_list_content_serialized(self):
        result = _message_content_as_text({"content": [{"type": "text", "text": "hi"}]})
        assert "hi" in result


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_messages(self):
        assert _estimate_tokens([]) == 1  # max(1, ...)

    def test_simple_message(self):
        msgs = [{"role": "user", "content": "hello world"}]
        assert _estimate_tokens(msgs) > 0

    def test_tool_calls_counted(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"function": {"name": "run_bash", "arguments": '{"command":"ls"}'}}
                ],
            }
        ]
        assert _estimate_tokens(msgs) > 0


# ---------------------------------------------------------------------------
# ToolPermissionPolicy
# ---------------------------------------------------------------------------


class TestToolPermissionPolicy:
    def test_default_is_ask(self):
        policy = ToolPermissionPolicy()
        assert policy.decision("run_bash") == "ask"

    def test_allow_tool(self):
        policy = ToolPermissionPolicy(allow={"run_bash"})
        assert policy.decision("run_bash") == "allow"

    def test_deny_tool(self):
        policy = ToolPermissionPolicy(deny={"run_bash"})
        assert policy.decision("run_bash") == "deny"

    def test_wildcard_allow(self):
        policy = ToolPermissionPolicy(allow={"*"})
        assert policy.decision("anything") == "allow"

    def test_wildcard_deny(self):
        policy = ToolPermissionPolicy(deny={"*"})
        assert policy.decision("anything") == "deny"

    def test_deny_overrides_allow_specific(self):
        policy = ToolPermissionPolicy(allow={"run_bash"}, deny={"run_bash"})
        assert policy.decision("run_bash") == "deny"

    def test_allow_other_tool(self):
        policy = ToolPermissionPolicy(deny={"run_bash"})
        assert policy.decision("read_file") == "ask"


# ---------------------------------------------------------------------------
# TOOLS constant
# ---------------------------------------------------------------------------


class TestToolsConstant:
    def test_has_run_bash(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert "run_bash" in names

    def test_has_read_file(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert "read_file" in names

    def test_has_write_file(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert "write_file" in names

    def test_has_edit_file(self):
        names = [t["function"]["name"] for t in TOOLS]
        assert "edit_file" in names

    def test_all_tools_have_parameters(self):
        for tool in TOOLS:
            fn = tool["function"]
            assert "parameters" in fn
            assert "required" in fn["parameters"]


# ---------------------------------------------------------------------------
# OpenRouterAgentCLI - session management
# ---------------------------------------------------------------------------


class TestSessionManagement:
    def test_new_session_has_system_prompt(self):
        cli = _make_cli()
        assert len(cli.messages) == 1
        assert cli.messages[0]["role"] == "system"
        assert cli.messages[0]["content"] == DEFAULT_SYSTEM_PROMPT

    def test_save_and_load_session(self):
        cli = _make_cli()
        cli.messages.append({"role": "user", "content": "hello"})
        cli._save_session()

        cli2 = _make_cli(session_id="test-session")
        # System prompt is prepended on load
        assert cli2.messages[0]["role"] == "system"

    def test_session_path(self):
        cli = _make_cli(session_id="my-test")
        assert cli._session_path.name == "my-test.json"

    def test_clear_session(self):
        cli = _make_cli()
        cli.messages.append({"role": "user", "content": "hello"})
        cli.messages.append({"role": "assistant", "content": "hi"})
        cli.messages = [{"role": "system", "content": cli.system_prompt}]
        cli._save_session()
        assert len([m for m in cli.messages if m["role"] != "system"]) == 0


# ---------------------------------------------------------------------------
# OpenRouterAgentCLI - file tools
# ---------------------------------------------------------------------------


class TestFileTools:
    @pytest.fixture
    def cli(self):
        return _make_cli()

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, cli):
        result = await cli._write_file("test.txt", "hello world")
        assert "ok" in result

        result = await cli._read_file("test.txt", None, None)
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_read_file_with_range(self, cli):
        content = "line1\nline2\nline3\nline4\n"
        await cli._write_file("lines.txt", content)

        result = await cli._read_file("lines.txt", 2, 3)
        assert "line2" in result
        assert "line3" in result
        assert "line1" not in result

    @pytest.mark.asyncio
    async def test_edit_file(self, cli):
        await cli._write_file("edit.txt", "hello world")
        result = await cli._edit_file("edit.txt", "world", "universe")
        assert "ok" in result

        result = await cli._read_file("edit.txt", None, None)
        assert "hello universe" in result

    @pytest.mark.asyncio
    async def test_edit_file_non_unique_old_string(self, cli):
        await cli._write_file("dup.txt", "foo bar foo")
        result = await cli._edit_file("dup.txt", "foo", "baz")
        assert "found 2 times" in result

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, cli):
        result = await cli._read_file("nonexistent.txt", None, None)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_write_file_creates_directories(self, cli):
        result = await cli._write_file("sub/dir/file.txt", "content")
        assert "ok" in result
        assert (Path(cli.workdir) / "sub" / "dir" / "file.txt").exists()

    @pytest.mark.asyncio
    async def test_read_file_outside_workdir(self, cli):
        result = await cli._read_file("/etc/passwd", None, None)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_write_file_outside_workdir(self, cli):
        result = await cli._write_file("/tmp/evil.txt", "content")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, cli):
        result = await cli._edit_file("missing.txt", "old", "new")
        assert "error" in result


# ---------------------------------------------------------------------------
# OpenRouterAgentCLI - bash tool
# ---------------------------------------------------------------------------


class TestBashTool:
    @pytest.fixture
    def cli(self):
        return _make_cli()

    @pytest.mark.asyncio
    async def test_run_bash_success(self, cli):
        result = await cli._run_bash("echo hello", 5)
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_run_bash_failure(self, cli):
        result = await cli._run_bash("exit 1", 5)
        assert "exit=1" in result

    @pytest.mark.asyncio
    async def test_run_bash_timeout(self, cli):
        result = await cli._run_bash("sleep 10", 1)
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_run_bash_stdout_stderr(self, cli):
        result = await cli._run_bash(
            "python3 -c \"import sys; print('out'); print('err', file=sys.stderr); sys.exit(1)\"",
            5,
        )
        assert "out" in result
        assert "err" in result


# ---------------------------------------------------------------------------
# OpenRouterAgentCLI - _execute_tool routing
# ---------------------------------------------------------------------------


class TestExecuteToolRouting:
    @pytest.fixture
    def cli(self):
        cli = _make_cli()
        cli.policy.allow.add("*")
        return cli

    @pytest.mark.asyncio
    async def test_tools_disabled(self):
        cli = _make_cli(tools_enabled=False)
        result = await cli._execute_tool("run_bash", {"command": "echo hi"})
        assert "blocked" in result

    @pytest.mark.asyncio
    async def test_unknown_tool(self, cli):
        result = await cli._execute_tool("nonexistent", {})
        assert "Unknown tool" in result

    @pytest.mark.asyncio
    async def test_run_bash_via_execute_tool(self, cli):
        result = await cli._execute_tool("run_bash", {"command": "echo test"})
        assert "test" in result

    @pytest.mark.asyncio
    async def test_read_file_via_execute_tool(self, cli):
        await cli._write_file("via_tool.txt", "content")
        result = await cli._execute_tool("read_file", {"path": "via_tool.txt"})
        assert "content" in result

    @pytest.mark.asyncio
    async def test_write_file_via_execute_tool(self, cli):
        result = await cli._execute_tool(
            "write_file", {"path": "via_tool2.txt", "content": "data"}
        )
        assert "ok" in result

    @pytest.mark.asyncio
    async def test_edit_file_via_execute_tool(self, cli):
        await cli._write_file("via_tool3.txt", "old")
        result = await cli._execute_tool(
            "edit_file",
            {"path": "via_tool3.txt", "old_string": "old", "new_string": "new"},
        )
        assert "ok" in result


# ---------------------------------------------------------------------------
# OpenRouterAgentCLI - tool loop detection
# ---------------------------------------------------------------------------


class TestToolLoopDetection:
    """Tool loop detection is tested at the _run_user_turn level which
    requires HTTP mocking. We verify the signature logic here instead."""

    def test_same_tool_same_args_same_signature(self):
        tc1 = [{"function": {"name": "run_bash", "arguments": '{"command":"ls"}'}}]
        tc2 = [{"function": {"name": "run_bash", "arguments": '{"command":"ls"}'}}]
        sig1 = json.dumps(
            [
                {
                    "name": tc.get("function", {}).get("name"),
                    "args": tc.get("function", {}).get("arguments"),
                }
                for tc in tc1
            ],
            sort_keys=True,
        )
        sig2 = json.dumps(
            [
                {
                    "name": tc.get("function", {}).get("name"),
                    "args": tc.get("function", {}).get("arguments"),
                }
                for tc in tc2
            ],
            sort_keys=True,
        )
        assert sig1 == sig2

    def test_same_tool_different_args_different_signature(self):
        tc1 = [{"function": {"name": "run_bash", "arguments": '{"command":"ls"}'}}]
        tc2 = [{"function": {"name": "run_bash", "arguments": '{"command":"pwd"}'}}]
        sig1 = json.dumps(
            [
                {
                    "name": tc.get("function", {}).get("name"),
                    "args": tc.get("function", {}).get("arguments"),
                }
                for tc in tc1
            ],
            sort_keys=True,
        )
        sig2 = json.dumps(
            [
                {
                    "name": tc.get("function", {}).get("name"),
                    "args": tc.get("function", {}).get("arguments"),
                }
                for tc in tc2
            ],
            sort_keys=True,
        )
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# _load_system_prompt
# ---------------------------------------------------------------------------


class TestLoadSystemPrompt:
    def test_none_returns_default(self):
        from openrouter_agent_cli.cli import _load_system_prompt

        assert _load_system_prompt(None) == DEFAULT_SYSTEM_PROMPT

    def test_valid_file(self):
        from openrouter_agent_cli.cli import _load_system_prompt

        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("custom prompt")
            f.flush()
            assert _load_system_prompt(f.name) == "custom prompt"
        os.unlink(f.name)

    def test_missing_file_raises(self):
        from openrouter_agent_cli.cli import _load_system_prompt

        with pytest.raises(RuntimeError, match="Failed to read"):
            _load_system_prompt("/nonexistent/prompt.md")
