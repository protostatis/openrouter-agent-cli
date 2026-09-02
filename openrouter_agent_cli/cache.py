"""Provider-agnostic context observations for long-running sessions.

The CLI cannot force a KV cache through every OpenRouter provider. This module
therefore measures the stable serialized message prefix that the client sends
and records provider cache fields only when they are explicitly present.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _message_hash(message: dict[str, Any]) -> str:
    payload = json.dumps(message, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _message_tokens(message: dict[str, Any]) -> int:
    content = message.get("content")
    chars = len(content) if isinstance(content, str) else len(json.dumps(content or "", ensure_ascii=False))
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function", {}) or {}
        chars += len(str(function.get("name", "")))
        chars += len(str(function.get("arguments", "")))
    return max(1, chars // 4)


def _cached_tokens(usage: dict[str, Any]) -> int | None:
    """Extract an explicit provider cache counter without treating missing as zero."""
    details = usage.get("prompt_tokens_details")
    candidates: list[Any] = []
    if isinstance(details, dict):
        candidates.extend(
            details.get(name)
            for name in ("cached_tokens", "cache_read_input_tokens", "cache_read_tokens")
        )
    candidates.extend(
        usage.get(name)
        for name in ("cached_tokens", "cache_read_input_tokens", "cache_read_tokens")
    )
    for value in candidates:
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


@dataclass
class CacheAwareContext:
    """Track stable-prefix and explicit provider-cache observations."""

    mode: str = "auto"
    requests: int = 0
    compactions: int = 0
    stable_prefix_tokens: int = 0
    stable_prefix_messages: int = 0
    last_cached_tokens: int | None = None
    observed_cached_tokens: int = 0
    provider_cache_observations: int = 0
    prefix_fingerprint: str | None = None
    _previous_hashes: list[str] = field(default_factory=list, repr=False)

    def observe_request(
        self, messages: list[dict[str, Any]], usage: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        current_hashes = [_message_hash(message) for message in messages]
        common = 0
        for previous, current in zip(self._previous_hashes, current_hashes):
            if previous != current:
                break
            common += 1
        self.stable_prefix_messages = common
        self.stable_prefix_tokens = sum(_message_tokens(message) for message in messages[:common])
        prefix_bytes = "".join(current_hashes[:common]).encode("ascii")
        self.prefix_fingerprint = hashlib.sha256(prefix_bytes).hexdigest()[:16] if common else None
        self.requests += 1
        usage = usage or {}
        cached = _cached_tokens(usage)
        self.last_cached_tokens = cached
        if cached is not None:
            self.provider_cache_observations += 1
            self.observed_cached_tokens += cached
        self._previous_hashes = current_hashes
        return self.snapshot()

    def note_compaction(self) -> None:
        self.compactions += 1
        # The summary intentionally changes the serialized prefix. The next
        # request reports the new stable prefix instead of claiming reuse.
        self._previous_hashes = []
        self.stable_prefix_messages = 0
        self.stable_prefix_tokens = 0
        self.prefix_fingerprint = None

    def reset_transient(self) -> None:
        """Drop the pairwise prefix baseline without counting a compaction.

        Used when the conversation identity changes (session switch / new
        session / history clear), where the next request starts a fresh prefix
        instead of claiming continuity with the old conversation.
        """
        self._previous_hashes = []
        self.stable_prefix_messages = 0
        self.stable_prefix_tokens = 0
        self.prefix_fingerprint = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "requests": self.requests,
            "compactions": self.compactions,
            "stable_prefix_messages": self.stable_prefix_messages,
            "stable_prefix_tokens": self.stable_prefix_tokens,
            "prefix_fingerprint": self.prefix_fingerprint,
            "last_cached_tokens": self.last_cached_tokens,
            "observed_cached_tokens": self.observed_cached_tokens,
            "provider_cache_observations": self.provider_cache_observations,
            "provider_cache_status": (
                "observed" if self.provider_cache_observations else "not observable"
            ),
        }
