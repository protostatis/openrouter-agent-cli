"""Sandbox seam tests: availability detection, engine delegation, runner wiring.

On macOS (this dev host) the real Bubblewrap path cannot execute; these tests
verify the contract and the wiring logic. The live sandbox is exercised on a
Linux host with bwrap + systemd-user (see docs/verify-before-completion-
experiment.md prerequisites).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from openrouter_agent_cli.eval import sandbox
from openrouter_agent_cli.eval.runner import Profile, SuiteRunner
from openrouter_agent_cli.eval.suite import load_suite


def test_bwrap_availability_false_on_non_linux():
    if os.sys.platform != "linux":
        assert sandbox.bwrap_available() is False
        assert sandbox.sandbox_available() is False


def test_sandbox_argv_layout():
    """The bwrap/systemd argv must isolate: unshare-all, ro runtime binds,
    workspace as the only writable bind at /workspace, tmpfs /tmp, cleared env."""
    argv = sandbox._build_bwrap_argv(
        "echo hi", "/tmp/ws", 30, sandbox.SandboxLimits()
    )
    joined = " ".join(argv)
    assert "--unshare-all" in joined
    assert "--new-session" in joined
    assert "--die-with-parent" in joined
    assert "--clearenv" in joined
    assert "--tmpfs /tmp" in joined
    assert "--ro-bind /usr /usr" in joined
    assert f"--bind /tmp/ws /workspace" in joined
    assert "--chdir /workspace" in joined
    assert "RuntimeMaxSec=32s" in joined
    assert "MemoryMax=2G" in joined
    assert "TasksMax=64" in joined
    # HOME must be /tmp inside, never the host home
    assert "--setenv HOME /tmp" in joined


def test_engine_bash_runner_delegation(tmp_path):
    """When bash_runner is set on the engine, _run_bash must call it and
    return its structured JSON string."""
    from openrouter_agent_cli.cli import OpenRouterAgentCLI

    engine = OpenRouterAgentCLI(
        api_key="k", model="m", session_id="s", workdir=str(tmp_path),
        max_turns=5, max_history_messages=64, command_timeout=30,
        tools_enabled=True, system_prompt="p", discovery_mode="off",
    )
    calls: list[tuple[str, int]] = []

    async def fake_runner(command: str, timeout_seconds: int) -> str:
        calls.append((command, timeout_seconds))
        import json
        return json.dumps({"ok": True, "exit_code": 0, "stdout": "sandboxed",
                           "stderr": "", "timed_out": False, "duration_ms": 1,
                           "truncated": False, "cwd": str(tmp_path), "command": command})

    engine.bash_runner = fake_runner
    result = asyncio.run(engine._run_bash("ls", 10))
    import json
    assert json.loads(result)["stdout"] == "sandboxed"
    assert calls == [("ls", 10)]
    # and the plain engine still uses the host path (no crash on construction)
    assert engine.bash_runner is not None  # set above; default is None
    engine2 = OpenRouterAgentCLI(
        api_key="k", model="m", session_id="s", workdir=str(tmp_path),
        max_turns=5, max_history_messages=64, command_timeout=30,
        tools_enabled=True, system_prompt="p", discovery_mode="off",
    )
    assert engine2.bash_runner is None


def test_runner_gate_and_sandbox_wiring(tmp_path):
    """Mock mode: no gate, no sandbox. Real mode on non-Linux: fails closed
    unless acknowledged; with sandbox forced on + unavailable, fails closed."""
    suite = load_suite(Path(__file__).resolve().parents[1] / "eval_suites" / "coding_smoke_v1" / "suite.json")
    os.environ.pop("AGENT_EVAL_ALLOW_HOST_EXECUTION", None)
    os.environ.pop("AGENT_EVAL_SANDBOX", None)

    # mock profiles pass regardless of sandbox/gate
    runner = SuiteRunner(suite, [Profile(name="mock", prompt="P", mock_script={"responses": [{"text": "x"}]})], eval_dir=tmp_path / "e")
    assert runner._sandboxed is False

    # real profile without ack and without sandbox -> fail closed
    with pytest.raises(ValueError, match="AGENT_EVAL_ALLOW_HOST_EXECUTION"):
        SuiteRunner(suite, [Profile(name="real", prompt="P")], eval_dir=tmp_path / "e2")

    # forced sandbox with no bwrap available -> fail closed with sandbox msg
    os.environ["AGENT_EVAL_SANDBOX"] = "1"
    with pytest.raises(ValueError, match="AGENT_EVAL_SANDBOX=1 requested but the Bubblewrap"):
        SuiteRunner(suite, [Profile(name="real", prompt="P")], eval_dir=tmp_path / "e3")
    os.environ.pop("AGENT_EVAL_SANDBOX", None)
