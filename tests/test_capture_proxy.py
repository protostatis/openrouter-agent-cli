"""Tests for the proxy's non-secret experiment metadata."""

from scripts.capture_proxy import _capture_request_headers, _request_metadata


def test_capture_request_headers_excludes_credentials():
    headers = _capture_request_headers(
        {
            "Authorization": "Bearer secret",
            "X-OpenRouter-Agent-Run-ID": "trial-1",
            "X-OpenRouter-Agent-Tool-Profile": "core4",
            "X-OpenRouter-Agent-Source-Digest": "wheel-sha",
        }
    )

    assert headers == {
        "x-openrouter-agent-run-id": "trial-1",
        "x-openrouter-agent-tool-profile": "core4",
        "x-openrouter-agent-source-digest": "wheel-sha",
    }


def test_request_metadata_identifies_task_prompt_and_tool_schema():
    metadata = _request_metadata(
        {
            "x-openrouter-agent-run-id": "trial-1",
            "x-openrouter-agent-tool-profile": "core4",
        },
        {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "neutral"},
                {"role": "user", "content": "fix the task"},
            ],
            "tools": [
                {"type": "function", "function": {"name": "run_bash"}},
                {"type": "function", "function": {"name": "read_file"}},
            ],
        },
    )

    assert metadata["run_id"] == "trial-1"
    assert metadata["tool_profile"] == "core4"
    assert metadata["model"] == "test-model"
    assert metadata["tool_count"] == 2
    assert len(metadata["tool_schema_sha256"]) == 64
    assert len(metadata["system_prompt_sha256"]) == 64
    assert len(metadata["task_prompt_sha256"]) == 64
    assert len(metadata["request_sha256"]) == 64


def test_request_metadata_changes_when_tool_schema_changes():
    base = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "task"}],
        "tools": [{"type": "function", "function": {"name": "run_bash"}}],
    }
    with_extra_tool = {**base, "tools": [*base["tools"], {"type": "function", "function": {"name": "read_file"}}]}

    first = _request_metadata({}, base)
    second = _request_metadata({}, with_extra_tool)

    assert first["tool_schema_sha256"] != second["tool_schema_sha256"]
