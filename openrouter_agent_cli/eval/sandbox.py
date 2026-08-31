"""Bubblewrap sandbox runner for evaluation bash execution.

Ports the proven sandbox pattern from the research harness
(pyreplab_harness.sandbox.BubblewrapSandbox) into the CLI's evaluation
layer. The agent's bash commands run under ``systemd-run --user ... bwrap``
with:

- network, mount, PID and UTS namespaces unshared (no network, no host mount
  access),
- the runtime paths bound read-only and the attempt workspace bound as
  ``/workspace`` (the only writable bind),
- a fresh tmpfs ``/tmp``, cleared environment (HOME=/tmp, allowlisted PATH; non-login
  shell so /etc/profile cannot override them),
- memory / task / CPU / wall-clock limits enforced by systemd.

Only engages on Linux with ``bwrap`` + systemd-user available; everywhere
else the availability checks return False and the runner stays on the host
bash path (with the existing fail-closed acknowledgement gate).
"""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

_MAX_OUTPUT_CHARS = 64 * 1024
_RUNTIME_PATHS = ("/usr", "/bin", "/lib", "/lib64")


@dataclass(frozen=True)
class SandboxLimits:
    max_timeout_seconds: int = 60
    memory_max: str = "2G"
    tasks_max: int = 64
    cpu_quota: str = "200%"


def _clamp_timeout(requested: int, limits: SandboxLimits) -> int:
    return max(1, min(int(requested), limits.max_timeout_seconds))


def bwrap_available() -> bool:
    """True when bwrap exists AND can create an isolated sandbox."""
    if sys.platform != "linux":
        return False
    if shutil.which("bwrap") is None:
        return False
    probe = [
        "bwrap",
        "--unshare-all",
        "--ro-bind", "/", "/",
        "--tmpfs", "/tmp",
        "--chdir", "/tmp",
        "--clearenv",
        "/bin/true",
    ]
    try:
        result = subprocess.run(probe, capture_output=True, timeout=10)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def systemd_user_available() -> bool:
    if sys.platform != "linux":
        return False
    if shutil.which("systemd-run") is None:
        return False
    try:
        result = subprocess.run(
            ["systemd-run", "--user", "--quiet", "--wait", "--collect", "--pipe", "/bin/true"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sandbox_available() -> bool:
    """Full stack usable: Linux + bwrap + systemd user session."""
    return bwrap_available() and systemd_user_available()


def _build_bwrap_argv(command: str, workspace: str, timeout: int, limits: SandboxLimits) -> list[str]:
    bwrap = [
        "bwrap",
        "--unshare-all",
        "--new-session",
        "--die-with-parent",
        "--clearenv",
    ]
    for path in _RUNTIME_PATHS:
        if os.path.exists(path):
            bwrap.extend(["--ro-bind", path, path])
    bwrap.extend(
        [
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--dir", "/workspace",
            "--bind", os.path.abspath(workspace), "/workspace",
            "--chdir", "/workspace",
            "--setenv", "HOME", "/tmp",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "PYTHONNOUSERSITE", "1",
            "/bin/bash", "--noprofile", "--norc", "-c", command,
        ]
    )
    return [
        "systemd-run", "--user", "--quiet", "--wait", "--collect", "--pipe",
        "--setenv=HOME=/tmp",
        "--setenv=PATH=/usr/local/bin:/usr/bin:/bin",
        "--setenv=PYTHONNOUSERSITE=1",
        f"--property=MemoryMax={limits.memory_max}",
        f"--property=TasksMax={limits.tasks_max}",
        f"--property=CPUQuota={limits.cpu_quota}",
        f"--property=RuntimeMaxSec={timeout + 2}s",
        *bwrap,
    ]


def _build_verifier_argv(
    command: str,
    workspace: str,
    trusted_cwd: str,
    timeout: int,
    limits: SandboxLimits,
) -> list[str]:
    """Build a read-only verifier sandbox command.

    The verifier is trusted code, but it may execute files the agent produced.
    Keeping that subprocess in the same namespace boundary prevents a
    malicious or accidental task output from turning verification into host
    execution.  The suite directory is mounted read-only at ``/trusted`` and
    the attempt workspace is mounted read-only at ``/workspace``.
    """
    verifier_argv = shlex.split(command)
    if not verifier_argv:
        raise ValueError("verifier command is empty")
    bwrap = [
        "bwrap",
        "--unshare-all",
        "--new-session",
        "--die-with-parent",
        "--clearenv",
    ]
    for path in _RUNTIME_PATHS:
        if os.path.exists(path):
            bwrap.extend(["--ro-bind", path, path])
    bwrap.extend(
        [
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--ro-bind", os.path.abspath(trusted_cwd), "/trusted",
            "--ro-bind", os.path.abspath(workspace), "/workspace",
            "--chdir", "/trusted",
            "--setenv", "HOME", "/tmp",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "PYTHONNOUSERSITE", "1",
            *verifier_argv,
            "/workspace",
        ]
    )
    return [
        "systemd-run", "--user", "--quiet", "--wait", "--collect", "--pipe",
        "--setenv=HOME=/tmp",
        "--setenv=PATH=/usr/local/bin:/usr/bin:/bin",
        "--setenv=PYTHONNOUSERSITE=1",
        f"--property=MemoryMax={limits.memory_max}",
        f"--property=TasksMax={limits.tasks_max}",
        f"--property=CPUQuota={limits.cpu_quota}",
        f"--property=RuntimeMaxSec={timeout + 2}s",
        *bwrap,
    ]


def run_contained_verifier(
    command: str,
    workspace: str,
    trusted_cwd: str,
    timeout_s: int,
    limits: SandboxLimits | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a suite verifier with its workspace mounted read-only."""
    active_limits = limits or SandboxLimits()
    timeout = _clamp_timeout(timeout_s, active_limits)
    argv = _build_verifier_argv(
        command, workspace, trusted_cwd, timeout, active_limits
    )
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )


class BubblewrapBashRunner:
    """Drop-in replacement for the engine's bash tool: same structured
    contract, executed inside the Bubblewrap sandbox instead of the host
    shell."""

    def __init__(self, workspace: str, limits: SandboxLimits | None = None) -> None:
        self.workspace = os.path.abspath(workspace)
        self.limits = limits or SandboxLimits()

    async def __call__(self, command: str, timeout_seconds: int) -> str:
        started = time.monotonic()
        timeout = _clamp_timeout(timeout_seconds, self.limits)
        argv = _build_bwrap_argv(command, self.workspace, timeout, self.limits)

        def _run() -> dict[str, Any]:
            try:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 5,
                )
                return {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout or "",
                    "stderr": proc.stderr or "",
                    "timed_out": False,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "truncated": False,
                    "cwd": self.workspace,
                    "command": command,
                }
            except subprocess.TimeoutExpired:
                return {
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "timed_out": True,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "truncated": False,
                    "cwd": self.workspace,
                    "command": command,
                }

        result = await asyncio.to_thread(_run)
        if result["timed_out"]:
            result["stderr"] = result.get("stderr", "") + (
                f"\n[sandbox] command timed out after {timeout}s"
            )
        # Bound output like the host path does.
        for key in ("stdout", "stderr"):
            if len(result[key]) > _MAX_OUTPUT_CHARS:
                result[key] = result[key][:_MAX_OUTPUT_CHARS]
                result["truncated"] = True
        return _structured_result(result)


def _structured_result(body: dict[str, Any]) -> str:
    """Match the engine's expected structured JSON contract."""
    import json

    return json.dumps(body)
