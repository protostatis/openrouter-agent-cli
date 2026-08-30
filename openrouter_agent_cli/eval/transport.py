"""Scripted mock transport at the engine's model-call seam.

``MockTransport`` plays the role of the model: the engine hands it the exact
request the real OpenRouter API would receive (messages, tools, tool_choice),
and it returns responses in the same wire format. Tool calls it emits are
executed FOR REAL by the engine (real bash, real files) — a mock brain with
real hands. This lets the entire run->record->verify loop be exercised with
zero network calls and zero tokens.

Script format (JSON)::

    {
      "responses": [
        {"tool_calls": [{"name": "run_bash", "arguments": {"command": "ls"}}]},
        {"text": "Done."}
      ]
    }

Responses are consumed in order; the LAST response repeats if the script runs
dry (so an agent that keeps asking still terminates with a final answer).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MockTransport:
    def __init__(self, script: dict[str, Any] | list[dict[str, Any]]):
        if isinstance(script, list):
            script = {"responses": script}
        responses = script.get("responses") or []
        if not responses:
            raise ValueError("mock transport script has no responses")
        self._responses: list[dict[str, Any]] = list(responses)
        self._pos = 0
        self._calls = 0
        self.requests: list[dict[str, Any]] = []

    @classmethod
    def from_file(cls, path: str | Path) -> "MockTransport":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _next(self) -> dict[str, Any]:
        if self._pos < len(self._responses):
            response = self._responses[self._pos]
            self._pos += 1
        else:
            response = self._responses[-1]
        return response

    def _wire_tool_calls(self, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Wire-format tool calls with IDs unique for this transport's lifetime
        (the engine keys its tool records by call id)."""
        calls = []
        for spec in specs:
            fn_name = str(spec.get("name") or "run_bash")
            args = spec.get("arguments")
            if args is None and "command" in spec:
                args = {"command": spec["command"]}
            self._calls += 1
            calls.append(
                {
                    "id": f"mock-call-{self._calls:04d}",
                    "type": "function",
                    "function": {"name": fn_name, "arguments": json.dumps(args or {})},
                }
            )
        return calls

    async def __call__(
        self,
        client: Any,
        *,
        call_openrouter: Any = None,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.requests.append(
            {"messages": messages or [], "tools": tools, "tool_choice": tool_choice}
        )
        spec = self._next()
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        if "tool_calls" in spec and spec["tool_calls"]:
            tool_calls = self._wire_tool_calls(list(spec["tool_calls"]))
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": spec.get("text"),
                            "tool_calls": tool_calls,
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": usage,
            }
        text = str(spec.get("text") or "Done.")
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }
