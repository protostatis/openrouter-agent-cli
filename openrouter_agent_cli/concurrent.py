"""Concurrent tool-call executor for batched discovery.

Mirrors unbrowser_batch_demo/batch_demo/executor.py but generic: runs any
async tool handler concurrently behind a semaphore, dispatching blocking work
via asyncio.to_thread so browser I/O overlaps on wall clock.

The harness uses this when a single LLM response contains multiple tool_calls
(e.g. 5x discover in parallel) – wall time collapses from sum(latency) to
max(latency).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


async def run_concurrent(
    calls: list[tuple[str, dict[str, Any], str]],
    handler: Callable[[str, dict[str, Any]], Awaitable[str]],
    max_concurrency: int = 5,
    handler_with_id: Callable[[str, dict[str, Any], str], Awaitable[str]] | None = None,
) -> list[str]:
    """Run `handler(tool_name, args)` for each call concurrently.

    `calls` is list of (tool_name, args, tool_call_id) – id kept for ordering only.
    Returns list of result strings in input order (asyncio.gather preserves order).
    Uses semaphore to cap browser concurrency (SmartClient is 1 page/session per instance).

    `handler_with_id` is an optional form for callers that need the stable call ID
    while executing and inspecting work.
    """
    if not calls:
        return []
    if max_concurrency < 1:
        max_concurrency = 1
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(tool_name: str, args: dict[str, Any], tool_call_id: str) -> str:
        async with sem:
            try:
                if handler_with_id is not None:
                    return await handler_with_id(tool_name, args, tool_call_id)
                return await handler(tool_name, args)
            except Exception as e:
                return f"Tool error ({tool_name}): {e}"

    # handler may be sync via to_thread; normalize by awaiting
    tasks = [_one(name, args, call_id) for name, args, call_id in calls]
    return await asyncio.gather(*tasks)
