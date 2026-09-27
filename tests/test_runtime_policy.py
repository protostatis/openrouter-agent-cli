from __future__ import annotations

import httpx
import pytest

from openrouter_agent_cli import cli as cli_module
from openrouter_agent_cli.cli import DEFAULT_SYSTEM_PROMPT, OpenRouterAgentCLI, ToolPermissionPolicy
from openrouter_agent_cli.eval.transport import MockTransport
from openrouter_agent_cli.runtime_policy import RuntimePolicyConfig
from openrouter_agent_cli.utils import call_openrouter


def test_runtime_policy_defaults_and_bounds() -> None:
    assert RuntimePolicyConfig() == RuntimePolicyConfig(60.0, 3, 1)
    assert RuntimePolicyConfig(0.5, -2, 99) == RuntimePolicyConfig(1.0, 0, 3)
    with pytest.raises(ValueError, match="finite"):
        RuntimePolicyConfig(float("inf"))


class _Response:
    def __init__(self, status_code: int, data: dict | None = None) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.text = "temporary failure"
        self._data = data or {}
        self.is_success = 200 <= status_code < 300

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls = 0

    async def post(self, *args, **kwargs) -> _Response:
        response = self.responses[self.calls]
        self.calls += 1
        return response


@pytest.mark.asyncio
async def test_provider_retry_limit_controls_retry_count(monkeypatch) -> None:
    client = _Client(
        [
            _Response(503),
            _Response(200, {"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    retries: list[tuple[int, int, int]] = []

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("openrouter_agent_cli.utils.asyncio.sleep", no_wait)
    result = await call_openrouter(
        client,
        api_key="test",
        model="test-model",
        messages=[],
        max_retries=1,
        on_retry=lambda attempt, total, wait, status: retries.append(
            (attempt, total, status)
        ),
    )

    assert result["choices"]
    assert client.calls == 2
    assert retries == [(1, 1, 503)]


@pytest.mark.asyncio
async def test_zero_provider_retries_fails_immediately() -> None:
    client = _Client([_Response(503)])

    with pytest.raises(RuntimeError, match="HTTP 503"):
        await call_openrouter(
            client,
            api_key="test",
            model="test-model",
            messages=[],
            max_retries=0,
        )

    assert client.calls == 1


@pytest.mark.asyncio
async def test_mock_transport_can_reproduce_provider_failure() -> None:
    agent = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="runtime-policy-provider-failure",
        workdir=".",
        max_turns=1,
        max_history_messages=20,
        command_timeout=5,
        tools_enabled=False,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
    )
    transport = MockTransport({"responses": [{"error": "synthetic outage"}]})
    agent.model_transport = transport

    async with httpx.AsyncClient() as client:
        result = await agent._run_user_turn(client, "hello")

    assert result == ""
    assert agent.terminal_status == "provider_error"
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_retry_reuses_failed_user_message_without_duplicate(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    agent = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="runtime-policy-explicit-retry",
        workdir=".",
        max_turns=1,
        max_history_messages=20,
        command_timeout=5,
        tools_enabled=False,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
    )
    agent.non_interactive_mode = True
    transport = MockTransport(
        {"responses": [{"error": "synthetic provider outage"}, {"text": "recovered"}]}
    )
    agent.model_transport = transport

    async with httpx.AsyncClient() as client:
        first = await agent._run_user_turn(client, "hello")
        assert first == ""
        assert agent.terminal_status == "provider_error"

        await agent._handle_command(client, "/retry")

    assert agent.terminal_status == "ok"
    assert len(transport.requests) == 2
    assert [m["role"] for m in agent.messages if m["role"] != "system"] == [
        "user",
        "assistant",
    ]
    assert agent._last_failed_prompt is None


@pytest.mark.asyncio
async def test_request_timeout_policy_reaches_http_client(monkeypatch, tmp_path) -> None:
    seen: list[float] = []

    class _Client:
        def __init__(self, *, timeout) -> None:
            seen.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

    agent = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="runtime-policy-timeout",
        workdir=str(tmp_path),
        max_turns=1,
        max_history_messages=20,
        command_timeout=5,
        tools_enabled=False,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
        runtime_policy=RuntimePolicyConfig(request_timeout_seconds=7.5),
    )
    agent.one_shot_prompt = "hello"

    async def no_model_call(client, prompt):
        return ""

    agent._run_user_turn = no_model_call
    monkeypatch.setattr(cli_module.httpx, "AsyncClient", _Client)

    await agent._run_loop()

    assert seen == [7.5]


@pytest.mark.asyncio
async def test_repeated_tool_policy_can_allow_an_extra_batch(tmp_path) -> None:
    agent = OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="runtime-policy-repeat",
        workdir=str(tmp_path),
        max_turns=4,
        max_history_messages=20,
        command_timeout=5,
        tools_enabled=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        discovery_mode="off",
        runtime_policy=RuntimePolicyConfig(repeated_tool_call_limit=2),
    )
    agent.non_interactive_mode = True
    agent.policy = ToolPermissionPolicy(allow={"*"})
    repeated = {"name": "run_bash", "arguments": {"command": "true"}}
    transport = MockTransport(
        {
            "responses": [
                {"tool_calls": [repeated]},
                {"tool_calls": [repeated]},
                {"text": "done"},
            ]
        }
    )
    agent.model_transport = transport

    async with httpx.AsyncClient() as client:
        result = await agent._run_user_turn(client, "Do the work.")

    assert result == "done"
    assert len(transport.requests) == 3
    assert all(request["tool_choice"] == "auto" for request in transport.requests)
