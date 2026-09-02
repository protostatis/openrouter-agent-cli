"""No-network end-to-end self-test for the local coding workflow."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import httpx

from openrouter_agent_cli.cli import DEFAULT_SYSTEM_PROMPT, OpenRouterAgentCLI
from openrouter_agent_cli.eval.transport import MockTransport


async def _run() -> None:
    with tempfile.TemporaryDirectory(prefix="openrouter-agent-selftest-") as raw_dir:
        root = Path(raw_dir)
        session_dir = root / "sessions"
        previous_session_dir = os.environ.get("OPENROUTER_AGENT_SESSION_DIR")
        os.environ["OPENROUTER_AGENT_SESSION_DIR"] = str(session_dir)
        try:
            cli = OpenRouterAgentCLI(
                api_key="self-test-key",
                model="self-test-model",
                session_id="self-test",
                workdir=str(root),
                max_turns=3,
                max_history_messages=60,
                command_timeout=10,
                tools_enabled=True,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                discovery_mode="off",
                task="Create marker.txt and verify it",
                verify_command="test -f marker.txt",
            )
            cli.non_interactive_mode = True
            cli.policy.allow.add("write_file")
            cli.model_transport = MockTransport(
                [
                    {
                        "tool_calls": [
                            {
                                "name": "write_file",
                                "arguments": {"path": "marker.txt", "content": "ok\n"},
                            }
                        ]
                    },
                    {"text": "Created and verified marker.txt."},
                ]
            )
            async with httpx.AsyncClient() as client:
                response = await cli._run_user_turn(client, "Do the work.")
            marker = root / "marker.txt"
            if response != "Created and verified marker.txt.":
                raise AssertionError(f"unexpected response: {response!r}")
            if marker.read_text(encoding="utf-8") != "ok\n":
                raise AssertionError("self-test marker was not written")
            if not cli.work_order or cli.work_order.get("status") != "verified":
                raise AssertionError(f"acceptance was not verified: {cli.work_order!r}")
            if cli.cache_context.requests < 2:
                raise AssertionError("model request cache observations were not recorded")
            if not cli._session_path.is_file():
                raise AssertionError("session checkpoint was not persisted")
        finally:
            if previous_session_dir is None:
                os.environ.pop("OPENROUTER_AGENT_SESSION_DIR", None)
            else:
                os.environ["OPENROUTER_AGENT_SESSION_DIR"] = previous_session_dir


def main() -> int:
    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"SELF-TEST FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("SELF-TEST PASSED: task contract, real file tool, acceptance check, session save, and cache accounting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
