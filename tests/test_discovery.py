"""Tests for the pyunbrowser discovery adapter and task sessions."""

from __future__ import annotations

import json

import pytest

from openrouter_agent_cli import cli as cli_module
from openrouter_agent_cli.discovery import DiscoverySession, run_discover


class FakeSmartClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def navigate_auto(self, url: str, goal: str | None = None) -> dict:
        self.calls.append(("navigate", url))
        return {
            "url": url,
            "status": 200,
            "blockmap": {"title": "Example Domain"},
            "headers": {"content-type": "text/html"},
            "discover": {"summary": {"routes": 1}},
            "cards": [],
            "extract": {"strategy": "text_main", "confidence": 0.8},
            "escalation": None,
            "next_tools": [{"tool": "query_text", "confidence": 0.9}],
            "micro_hint": {"tool": "text_main"},
        }

    def search(self, query: str, engine: str = "brave") -> list[dict]:
        self.calls.append(("search", query))
        return [{"title": query, "url": "https://example.com", "snippet": "hit"}]

    def close(self) -> None:
        self.closed = True


def test_run_discover_maps_current_smartclient_bundle_shape():
    session = DiscoverySession(client=FakeSmartClient())

    result = json.loads(
        run_discover(
            kind="navigate",
            url="https://example.com",
            goal="inspect the page",
            discovery_mode="real",
            session=session,
        )
    )

    assert result["navigate"]["url"] == "https://example.com"
    assert result["navigate"]["status"] == 200
    assert result["status"] == 200
    assert result["blockmap"]["title"] == "Example Domain"
    assert result["discover"]["summary"]["routes"] == 1
    assert result["next_tools"][0]["tool"] == "query_text"
    session.close()


def test_discovery_session_reuses_client_and_closes_it():
    client = FakeSmartClient()
    session = DiscoverySession(client=client)

    session.execute("navigate", url="https://example.com", goal="open")
    session.execute("search", query="example", goal="find")
    session.close()
    session.close()

    assert client.calls == [
        ("navigate", "https://example.com"),
        ("search", "example"),
    ]
    assert client.closed is True


@pytest.mark.asyncio
async def test_cli_reuses_one_discovery_session_for_a_task(tmp_path, monkeypatch):
    sessions = []

    def fake_run_discover(*args, **kwargs):
        sessions.append(kwargs["session"])
        return json.dumps({"mode": "real"})

    monkeypatch.setattr(cli_module, "run_discover", fake_run_discover)
    agent = cli_module.OpenRouterAgentCLI(
        api_key="test-key",
        model="test-model",
        session_id="discovery-test",
        workdir=str(tmp_path),
        max_turns=1,
        max_history_messages=20,
        command_timeout=5,
        tools_enabled=True,
        system_prompt="test",
        discovery_mode="real",
    )

    await agent._discover({"kind": "search", "query": "first", "goal": "first"})
    await agent._discover({"kind": "navigate", "url": "https://example.com", "goal": "second"})

    assert len(sessions) == 2
    assert sessions[0] is sessions[1]
    agent._close_discovery_session()
