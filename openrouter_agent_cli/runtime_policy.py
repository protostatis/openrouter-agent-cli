"""Explicit, bounded controls for the agent runtime.

These settings are deliberately separate from the model-facing prompt and the
tool permission policy. They let an operator choose how the runtime handles
provider latency, provider retries, and repeated tool calls without changing
the tools themselves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimePolicyConfig:
    """Bounded runtime decisions selected for one agent attempt."""

    request_timeout_seconds: float = 60.0
    provider_retry_limit: int = 3
    repeated_tool_call_limit: int = 1

    def __post_init__(self) -> None:
        try:
            timeout = float(self.request_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("request timeout must be a number") from exc
        if not math.isfinite(timeout):
            raise ValueError("request timeout must be finite")
        try:
            retries = int(self.provider_retry_limit)
            repeats = int(self.repeated_tool_call_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime policy limits must be integers") from exc

        # Keep the policy safe and compatible with the existing hard limits.
        object.__setattr__(self, "request_timeout_seconds", min(max(1.0, timeout), 600.0))
        object.__setattr__(self, "provider_retry_limit", min(max(0, retries), 5))
        object.__setattr__(self, "repeated_tool_call_limit", min(max(1, repeats), 3))
