"""Web discovery tool backed by pyunbrowser (with mock fallback).

Exposes the same semantics as `unbrowser_batch_demo/batch_demo/tools.py` but
as a standalone harness tool: `discover(kind, query, url, goal)`.

- kind=search  -> Brave search via SmartClient.search(query)
- kind=navigate -> SmartClient.navigate_auto(url, goal)

Direct ``run_discover`` calls create one SmartClient per call.  The CLI can
instead pass a ``DiscoverySession`` so one research task keeps cookies and
navigation state across calls.  Session-backed calls are serialized because
the underlying JSON-RPC client uses one request/response pipe.

If pyunbrowser is not installed, returns a clear error with install hint
instead of crashing.
"""

from __future__ import annotations

import ipaddress
import json
import os
import random
import threading
import time
import urllib.parse
from typing import Any


_BRAVE_ENV_LOCK = threading.RLock()


def _new_smart_client(binary: str | None = None) -> Any:
    """Construct a SmartClient without passing unsupported provider kwargs."""
    from unbrowser.smart import SmartClient  # type: ignore

    kwargs: dict[str, Any] = {}
    if binary:
        kwargs["binary"] = binary
    return SmartClient(**kwargs)


def _search_with_key(
    client: Any, query: str, brave_api_key: str | None = None
) -> Any:
    """Search while honoring an explicitly supplied Brave key.

    SmartClient reads Brave credentials from the environment.  Keep the
    explicit ``run_discover`` argument working without leaking it into the
    SmartClient constructor, which does not accept provider-specific kwargs.
    """
    if (
        not brave_api_key
        or os.environ.get("BRAVE_API_KEY")
        or os.environ.get("BRAVE_SEARCH_API_KEY")
    ):
        return client.search(query, engine="brave")

    with _BRAVE_ENV_LOCK:
        previous = os.environ.get("BRAVE_API_KEY")
        os.environ["BRAVE_API_KEY"] = brave_api_key
        try:
            return client.search(query, engine="brave")
        finally:
            if previous is None:
                os.environ.pop("BRAVE_API_KEY", None)
            else:
                os.environ["BRAVE_API_KEY"] = previous


_NAVIGATION_KEYS = (
    "url",
    "status",
    "blockmap",
    "headers",
    "challenge",
    "scripts",
    "extract",
    "raw",
)


def _navigation_view(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return the legacy ``navigate`` view from current or old bundle shapes."""
    legacy = bundle.get("navigate")
    if isinstance(legacy, dict):
        return legacy
    return {key: bundle[key] for key in _NAVIGATION_KEYS if key in bundle}


def _real_payload(
    client: Any,
    kind: str,
    query: str,
    url: str,
    goal: str,
    brave_api_key: str | None = None,
) -> dict[str, Any]:
    """Run one real operation and preserve SmartClient's full bundle."""
    if kind == "navigate" and url:
        bundle = client.navigate_auto(url, goal=goal or None)
        data = dict(bundle)
        # Keep the historical key for callers while exposing the current
        # SmartClient fields at the top level as the canonical shape.
        data["navigate"] = _navigation_view(bundle)
        return data

    q = query or goal
    return {"hits": _search_with_key(client, q, brave_api_key)}


class DiscoverySession:
    """Own one SmartClient for the lifetime of a research task.

    SmartClient's native client is synchronous and matches responses by pipe
    position, so concurrent calls on one instance are unsafe.  The lock keeps
    parallel agent tool calls from interleaving while preserving cookies and
    the current URL for subsequent calls in the same task.
    """

    def __init__(
        self,
        *,
        binary: str | None = None,
        brave_api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._binary = binary
        self._brave_api_key = brave_api_key
        self._client = client
        self._lock = threading.RLock()
        self._closed = False

    def _ensure_client(self) -> Any:
        if self._closed:
            raise RuntimeError("discovery session is closed")
        if self._client is None:
            self._client = _new_smart_client(self._binary)
        return self._client

    def execute(
        self,
        kind: str,
        query: str = "",
        url: str = "",
        goal: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            return _real_payload(
                self._ensure_client(),
                kind,
                query,
                url,
                goal,
                self._brave_api_key,
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            self._client = None
            if client is not None:
                client.close()


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
    session: DiscoverySession | None = None,
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

    # SSRF-safe validation for navigate
    if kind == "navigate" and url:
        try:
            parsed = urllib.parse.urlparse(url.strip())
            if parsed.scheme != "https":
                return json.dumps({"error": f"discover error: navigate url must be https, got {parsed.scheme!r}"})
            host = parsed.hostname or ""
            # block localhost/private/link-local
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return json.dumps({"error": f"discover error: navigate to private address blocked: {host}"})
            except ValueError:
                # hostname, not IP — block obvious local names
                if host.lower() in ("localhost", "metadata.google.internal") or host.endswith(".internal"):
                    return json.dumps({"error": f"discover error: navigate to {host} blocked"})
        except Exception as e:
            return json.dumps({"error": f"discover error: invalid url {url!r}: {e}"})

    # mock mode: deterministic, no network/binary
    if discovery_mode == "mock":
        data = _mock_result(kind, url or query, goal)
        return json.dumps(data, ensure_ascii=False)

    # auto / real: try real browser; auto no longer silently mocks (P1)
    if discovery_mode in ("auto", "real"):
        try:
            if session is not None:
                data = session.execute(kind, query=query, url=url, goal=goal)
            else:
                with _new_smart_client(binary) as client:
                    data = _real_payload(
                        client,
                        kind,
                        query,
                        url,
                        goal,
                        brave_api_key,
                    )
            return json.dumps(
                {"target": target, "goal": goal, "mode": "real", **data},
                ensure_ascii=False,
            )
        except ImportError as e:
            return json.dumps({
                "error": f"discover error: pyunbrowser not installed ({e}). Install with `pip install \"openrouter-agent-cli[unbrowser]\"` or use --discovery mock for synthetic results",
            })
        except Exception as e:
            return json.dumps({"error": f"discover error (real): {e}"})

    return json.dumps({"error": f"discover error: unknown discovery_mode {discovery_mode!r}"})
