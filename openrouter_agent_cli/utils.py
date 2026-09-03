"""Shared utilities used by the CLI and A/B test scripts."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from collections.abc import Callable
from typing import Any

import httpx

OPENROUTER_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
) + "/chat/completions"


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


MAX_SHELL_OUTPUT_CHARS = 20_000


async def _read_limited(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    captured = 0
    total = 0
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if captured < limit:
            remaining = limit - captured
            chunks.append(chunk[:remaining])
            captured += min(len(chunk), remaining)
    return b"".join(chunks), total > limit


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass


def format_shell_result(payload: dict[str, Any]) -> str:
    """Render a structured shell result as stable text for tools and tests."""
    return json.dumps(payload, ensure_ascii=False)


async def run_bash(
    command: str,
    cwd: str,
    timeout_seconds: int,
    *,
    max_output_chars: int = MAX_SHELL_OUTPUT_CHARS,
    structured: bool = False,
) -> str:
    """Run a host shell command and return a bounded result.

    The command still intentionally uses the host shell for compatibility, but
    starts a separate process group on POSIX so timeout/cancellation can stop
    descendants too. API credentials are not inherited by the child process.
    Set ``structured=True`` for the typed JSON result used by the CLI; the
    default keeps the legacy plain-text return format for direct callers.
    """
    started = time.monotonic()
    proc: asyncio.subprocess.Process | None = None
    stdout_task: asyncio.Task | None = None
    stderr_task: asyncio.Task | None = None
    env = os.environ.copy()
    for secret_name in ("OPENROUTER_API_KEY", "BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"):
        env.pop(secret_name, None)

    def _payload(**fields: Any) -> str:
        body = {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "truncated": False,
            "cwd": cwd,
            "command": command,
            **fields,
        }
        if not structured:
            # Legacy plain-text path kept for scripts that still expect it.
            if body.get("error"):
                return str(body["error"])
            if body.get("timed_out"):
                note = "\n[output truncated]" if body.get("truncated") else ""
                return f"Command timed out after {timeout_seconds}s.{note}"
            out = body.get("stdout") or ""
            err = body.get("stderr") or ""
            code = body.get("exit_code")
            note = "\n[output truncated]" if body.get("truncated") else ""
            if code == 0:
                return (out or "(command succeeded with no output)") + note
            if out and err:
                return f"exit={code}\nstdout:\n{out}\nstderr:\n{err}{note}"
            if err:
                return f"exit={code}\nstderr:\n{err}{note}"
            if out:
                return f"exit={code}\nstdout:\n{out}{note}"
            return f"exit={code} (no output){note}"
        return format_shell_result(body)

    try:
        kwargs: dict[str, Any] = {
            "cwd": cwd,
            "env": env,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_shell(
            command,
            **kwargs,
        )
        assert proc.stdout is not None and proc.stderr is not None
        stdout_task = asyncio.create_task(_read_limited(proc.stdout, max_output_chars))
        stderr_task = asyncio.create_task(_read_limited(proc.stderr, max_output_chars))
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_process_tree(proc)
            await proc.wait()
        stdout_result, stderr_result = await asyncio.gather(stdout_task, stderr_task)
        stdout, stdout_truncated = stdout_result
        stderr, stderr_truncated = stderr_result
    except asyncio.CancelledError:
        if proc is not None:
            _kill_process_tree(proc)
            try:
                await proc.wait()
            except Exception:
                pass
        for task in (stdout_task, stderr_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (stdout_task, stderr_task) if task is not None),
            return_exceptions=True,
        )
        raise
    except Exception as exc:
        if proc is not None and proc.returncode is None:
            _kill_process_tree(proc)
            try:
                await proc.wait()
            except Exception:
                pass
        for task in (stdout_task, stderr_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (stdout_task, stderr_task) if task is not None),
            return_exceptions=True,
        )
        return _payload(error=f"Command failed to start: {exc}", ok=False)

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    truncated = bool(stdout_truncated or stderr_truncated)
    if timed_out:
        return _payload(
            ok=False,
            exit_code=proc.returncode,
            stdout=out,
            stderr=err,
            timed_out=True,
            truncated=truncated,
            message=f"Command timed out after {timeout_seconds}s.",
        )
    return _payload(
        ok=proc.returncode == 0,
        exit_code=proc.returncode,
        stdout=out,
        stderr=err,
        timed_out=False,
        truncated=truncated,
        message=(
            out
            if proc.returncode == 0 and out
            else (
                "(command succeeded with no output)"
                if proc.returncode == 0
                else f"exit={proc.returncode}"
            )
        ),
    )


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
    on_retry: Callable[[int, int, float, int], None] | None = None,
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
                try:
                    retry_after = int(resp.headers.get("retry-after", 0))
                except (TypeError, ValueError):
                    retry_after = 0
                wait = max(retry_after, 2**attempt)
            else:
                wait = 2**attempt
            if on_retry is not None:
                on_retry(attempt, 3, wait, resp.status_code)
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
