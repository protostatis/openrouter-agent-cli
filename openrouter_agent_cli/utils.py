"""Shared utilities used by the CLI and A/B test scripts."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _decode_tool_arguments(raw_args: Any) -> dict[str, Any]:
    """Decode tool call arguments from JSON string or dict."""
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        value = raw_args.strip()
        if not value:
            return {}
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


async def run_bash(command: str, cwd: str, timeout_seconds: int) -> str:
    """Run a shell command and return stdout/stderr."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"Command timed out after {timeout_seconds}s."
    except Exception as exc:
        return f"Command failed to start: {exc}"

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode == 0:
        return out or "(command succeeded with no output)"
    if out and err:
        return f"exit={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
    if err:
        return f"exit={proc.returncode}\nstderr:\n{err}"
    if out:
        return f"exit={proc.returncode}\nstdout:\n{out}"
    return f"exit={proc.returncode} (no output)"


async def call_openrouter(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 4096,
    tool_choice: str = "auto",
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0,
    parallel_tool_calls: bool | None = None,
) -> dict[str, Any]:
    """Make a request to the OpenRouter API."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tool_choice == "none" or tools is None:
        body["tool_choice"] = "none"
    else:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
        if parallel_tool_calls is not None:
            body["parallel_tool_calls"] = parallel_tool_calls

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get(
            "OPENROUTER_AGENT_REFERER", "https://github.com/local/openrouter-agent-cli"
        ),
        "X-Title": os.environ.get("OPENROUTER_AGENT_TITLE", "OpenRouter Agent CLI"),
    }

    resp = await client.post(OPENROUTER_URL, json=body, headers=headers)

    retryable = {429, 500, 502, 503, 504}
    if resp.status_code in retryable:
        for attempt in range(1, 4):
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("retry-after", 0))
                wait = max(retry_after, 2**attempt)
            else:
                wait = 2**attempt
            await asyncio.sleep(wait)
            resp = await client.post(OPENROUTER_URL, json=body, headers=headers)
            if resp.status_code not in retryable:
                break

    if not resp.is_success:
        resp.raise_for_status()

    data = resp.json()
    if "choices" not in data:
        err = data.get("error", {})
        if isinstance(err, dict):
            err = err.get("message", str(data))
        raise RuntimeError(f"OpenRouter error: {err}")
    return data
