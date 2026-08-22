"""Web discovery tool backed by pyunbrowser (with mock fallback).

Exposes the same semantics as `unbrowser_batch_demo/batch_demo/tools.py` but
as a standalone harness tool: `discover(kind, query, url, goal)`.

- kind=search  -> Brave search via SmartClient.search(query)
- kind=navigate -> SmartClient.navigate_auto(url, goal)

SmartClient is created per call (1 page/session per instance) so concurrent
`discover` calls run in independent browser sessions (via asyncio.to_thread
in the executor).  If pyunbrowser is not installed, returns a clear error
with install hint instead of crashing.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any


def _mock_result(kind: str, target: str, goal: str, latency: float = 0.2) -> dict:
    # Small jittered sleep to simulate I/O for tests / no-browser mode
    sleep_for = max(0.02, latency + random.uniform(-0.05, 0.05))
    time.sleep(sleep_for)
    return {
        "target": target,
        "goal": goal,
        "mode": "mock",
        "hits": [
            {
                "title": f"Result {i} for {target}",
                "url": f"https://example.com/mock/{i}",
                "snippet": f"Mock discovery hit {i} relevant to: {goal}",
            }
            for i in range(1, 4)
        ],
        "discovered_at": time.time(),
    }


def run_discover(
    kind: str = "search",
    query: str = "",
    url: str = "",
    goal: str = "",
    *,
    discovery_mode: str = "auto",
    brave_api_key: str | None = None,
    binary: str | None = None,
) -> str:
    """Execute one discover objective and return JSON string for tool result.

    Returns a JSON string (capped by caller) – kept as string so CLI can truncate.
    On failure returns JSON with {"error": ...}.
    """
    kind = (kind or "search").strip().lower()
    if kind not in ("search", "navigate"):
        return json.dumps({"error": f"discover error: kind must be 'search' or 'navigate', got {kind!r}"})

    target = (url or query or goal).strip()
    if not target:
        return json.dumps({"error": "discover error: provide query (for search) or url (for navigate) or goal"})

    # mock mode: deterministic, no network/binary
    if discovery_mode == "mock":
        data = _mock_result(kind, url or query, goal)
        return json.dumps(data, ensure_ascii=False)

    # auto / real: try real browser, fall back to mock with hint if not installed
    if discovery_mode in ("auto", "real"):
        try:
            from unbrowser.smart import SmartClient  # type: ignore
        except ImportError as e:
            if discovery_mode == "real":
                return json.dumps({
                    "error": f"discover error: pyunbrowser not installed ({e}). Install with `pip install \"openrouter-agent-cli[unbrowser]\"` or use discovery_mode=mock",
                })
            # auto -> mock fallback
            data = _mock_result(kind, url or query, goal)
            data["_note"] = "mock fallback: pyunbrowser not installed"
            return json.dumps(data, ensure_ascii=False)

        # real execution
        try:
            kwargs: dict[str, Any] = {}
            if binary:
                kwargs["binary"] = binary
            # brave key passed via env by SmartClient; explicit kw only if provided
            if brave_api_key:
                kwargs["brave_api_key"] = brave_api_key  # type: ignore

            with SmartClient(**kwargs) as client:  # type: ignore
                if kind == "navigate" and url:
                    bundle = client.navigate_auto(url, goal=goal or None)
                    data = {
                        "target": url,
                        "goal": goal,
                        "mode": "real",
                        "navigate": bundle.get("navigate"),
                        "discover": bundle.get("discover"),
                        "cards": bundle.get("cards"),
                    }
                    return json.dumps(data, ensure_ascii=False)
                else:
                    q = query or goal
                    hits = client.search(q, engine="brave")
                    data = {"target": q, "goal": goal, "mode": "real", "hits": hits}
                    return json.dumps(data, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": f"discover error (real): {e}"})

    return json.dumps({"error": f"discover error: unknown discovery_mode {discovery_mode!r}"})
