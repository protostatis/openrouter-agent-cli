"""Small tests for helpers in openrouter_agent_cli/utils.py.

Accepted dogfood patch (2026-09-07), lightly cleaned during review: plain
imports instead of __import__, no unused imports, trailing newline added.
"""

from __future__ import annotations

import json

from openrouter_agent_cli.utils import _decode_tool_arguments, format_shell_result


def test_decode_tool_arguments_none():
    """None should return an empty dict."""
    assert _decode_tool_arguments(None) == {}


def test_decode_tool_arguments_dict():
    """A dict should be returned as-is."""
    result = _decode_tool_arguments({"key": "value", "num": 42})
    assert result == {"key": "value", "num": 42}


def test_decode_tool_arguments_valid_json_string():
    """A valid JSON string should be parsed and returned as a dict."""
    raw = '{"name": "test", "n": 1}'
    result = _decode_tool_arguments(raw)
    assert result == {"name": "test", "n": 1}


def test_decode_tool_arguments_invalid_string():
    """An invalid JSON string should return an empty dict."""
    result = _decode_tool_arguments("not valid json{{{")
    assert result == {}


def test_decode_tool_arguments_empty_string():
    """An empty string (after stripping) should return an empty dict."""
    result = _decode_tool_arguments("")
    assert result == {}


def test_decode_tool_arguments_non_dict_json():
    """A JSON string that parses to a non-dict type should return an empty dict."""
    result = _decode_tool_arguments('["a", "b"]')
    assert result == {}


def test_format_shell_result_preserves_keys():
    """format_shell_result should return a JSON string preserving all payload keys."""
    payload = {
        "ok": True,
        "exit_code": 0,
        "stdout": "hello",
        "stderr": "",
        "duration_ms": 10,
    }
    result = format_shell_result(payload)
    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed == payload


def test_format_shell_result_minimal():
    """format_shell_result with a minimal payload."""
    payload = {"ok": False, "exit_code": 1, "stderr": "error message"}
    parsed = json.loads(format_shell_result(payload))
    assert parsed == payload


def test_format_shell_result_empty():
    """format_shell_result with an empty dict."""
    assert json.loads(format_shell_result({})) == {}
