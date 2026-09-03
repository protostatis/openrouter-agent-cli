#!/usr/bin/env python3
"""Narrated demo of the acceptance-check product.

Run with:  uv run python scripts/demo_acceptance.py            (failure branch, deterministic, offline)
           uv run python scripts/demo_acceptance.py --live     (adds the real-model happy path)

The demo makes one point: the model's "done" answer is only a proposal. The
developer's acceptance command decides whether the work is accepted, and the
CLI reports verified / failed / not verified honestly with evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]

GREET_BROKEN = 'def greet(name):\n    return "hello " + name\n'
GREET_WRONG_FIX = 'def greet(name):\n    return "Hello " + name\n'
TEST_GREET = 'from greet import greet\nassert greet("Ada") == "Hello, Ada"\nprint("OK")\n'

TASK = "Fix greet.py so that test_greet.py passes. Do not modify the test file."
ONE_SHOT = "Inspect the failing test and make the smallest fix, then verify."
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def acceptance_command() -> str:
    # The first half protects the test file: any change to it fails the check.
    return "git diff --exit-code -- test_greet.py && python3 test_greet.py"


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n=== {title}\n{'=' * 70}")


def make_fixture() -> Path:
    """Fresh temp git repo: committed FAILING test, clean worktree."""
    root = Path(tempfile.mkdtemp(prefix="demo-acceptance-", dir=str(PROJECT_ROOT / "..")))
    (root / "greet.py").write_text(GREET_BROKEN, encoding="utf-8")
    (root / "test_greet.py").write_text(TEST_GREET, encoding="utf-8")
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "demo@demo"],
        ["git", "config", "user.name", "demo"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    return root


def load_api_key() -> str:
    env_path = PROJECT_ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get("OPENROUTER_API_KEY", "")


def preflight_model(model: str, api_key: str) -> str:
    """One-token probe before the live happy path; returns a warning or ''."""
    import time
    body = {"model": model,
            "messages": [{"role": "user", "content": "Reply with one word: ok"}],
            "max_tokens": 1}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        t0 = time.monotonic()
        with httpx.Client(timeout=45.0) as client:
            resp = client.post("https://openrouter.ai/api/v1/chat/completions",
                               json=body, headers=headers)
        dt = time.monotonic() - t0
        if resp.status_code != 200:
            return f"preflight probe returned HTTP {resp.status_code}"
        if dt > 15.0:
            return f"preflight probe took {dt:.1f}s (slow provider); consider --model anthropic/claude-3-haiku"
        return ""
    except Exception as exc:
        return f"preflight probe failed: {type(exc).__name__}: {exc}"


def _run_engine(
    workdir: Path,
    *,
    api_key: str,
    model: str,
    mock: list[dict] | None,
    session_dir: Path,
    quiet: bool = False,
) -> tuple["object", tuple[str, str]]:
    from openrouter_agent_cli.cli import OpenRouterAgentCLI, ToolPermissionPolicy
    from openrouter_agent_cli.eval.transport import MockTransport

    os.environ["OPENROUTER_AGENT_SESSION_DIR"] = str(session_dir)
    cli = OpenRouterAgentCLI(
        api_key=api_key,
        model=model,
        session_id="demo",
        workdir=str(workdir),
        max_turns=24,
        max_history_messages=64,
        command_timeout=15,
        tools_enabled=True,
        system_prompt="You are a careful coding agent.",
        discovery_mode="off",
        task=TASK,
        verify_command=acceptance_command(),
    )
    cli.non_interactive_mode = True
    # Allow-all mirrors how the evaluation harness drives the same engine; the
    # demo fixture is a disposable directory.
    cli.policy = ToolPermissionPolicy(allow={"*"})
    cli.one_shot_prompt = ONE_SHOT
    if mock is not None:
        cli.model_transport = MockTransport({"responses": mock})

    captured: io.StringIO | None = io.StringIO() if quiet else None
    captured_out: io.StringIO | None = io.StringIO() if quiet else None
    real_stderr = sys.stderr
    real_stdout = sys.stdout
    if captured is not None:
        sys.stderr = captured
        sys.stdout = captured_out

    async def go() -> "object":
        async with httpx.AsyncClient(timeout=90.0) as client:
            await cli.run()
        return cli

    try:
        engine = asyncio.run(go())
    finally:
        if captured is not None:
            sys.stderr = real_stderr
            sys.stdout = real_stdout
    captured_text = captured.getvalue() if captured is not None else ""
    captured_stdout = captured_out.getvalue() if captured_out is not None else ""
    return engine, (captured_text, captured_stdout)


def _show_acceptance(prefix: str, cli: "object") -> None:
    """Print the recorded acceptance evidence from a run, in demo form."""
    lc = (cli.work_order or {}).get("last_check") or {}
    status = str(lc.get("status") or "not_verified").upper()
    command = str(lc.get("command") or "")
    print(f"[acceptance] {status}: {command} ({lc.get('duration_ms', 0)}ms)")
    if lc.get("exit_code") is not None:
        print(f"[acceptance] exit_code={lc['exit_code']}")
    changed = lc.get("changed_files") or []
    if changed:
        print(f"[acceptance] changed_files: {', '.join(changed)}")
    for name in ("stdout", "stderr"):
        value = str(lc.get(name) or "").strip()
        if value:
            print(f"[acceptance] {name}:")
            print("\n".join("    " + line for line in value.splitlines()[:8]))
    print(prefix, end="")


def _show_outcome(cli: "object") -> None:
    wo = cli.work_order or {}
    lc = wo.get("last_check") or {}
    print("\n--- honest outcome ---")
    print(f"acceptance status : {wo.get('status')}")
    print(f"check             : {lc.get('status')} exit={lc.get('exit_code')} {lc.get('duration_ms')}ms")
    print(f"changed files     : {lc.get('changed_files')}")
    print(f"repair responses  : {getattr(cli.completion_policy, 'repair_injections', '?')}")
    print(f"model requests    : {cli.cache_context.requests}")


def run_baseline(workdir: Path) -> None:
    section("0:15 — baseline: the acceptance command fails")
    print(f"acceptance command: {acceptance_command()}")
    proc = subprocess.run(
        acceptance_command(), shell=True, cwd=workdir, capture_output=True, text=True
    )
    print(f"exit_code={proc.returncode}")
    if proc.stderr.strip():
        print(proc.stderr.strip()[-500:])
    print("\n> The command decides the outcome. It fails now, so the work is not verified.")


def failure_branch(workdir: Path, session_dir: Path) -> None:
    section("1:30 — the distinctive failure branch (scripted model, real tools, real verifier)")
    print("The model claims completion after a wrong fix. Watch what the CLI does with that claim.\n")

    mock = [
        # Turn 1: the model applies a WRONG fix (missing comma).
        {"tool_calls": [{"name": "edit_file", "arguments": {
            "path": "greet.py",
            "old_string": 'return "hello " + name',
            "new_string": 'return "Hello " + name',
        }}]},
        # Turn 2: it claims completion while the test still fails.
        {"text": "Done. I fixed the greeting and the test now passes."},
    ]
    cli, _ = _run_engine(workdir, api_key="mock-key", model="mock-model", mock=mock,
                         session_dir=session_dir, quiet=True)

    print("The model edits greet.py to  return \"Hello \" + name   (missing the comma)")
    print("then claims:  \"Done. I fixed the greeting and the test now passes.\"\n")
    print("The CLI runs the acceptance command before accepting that claim:")
    _show_acceptance("", cli)
    print("\n[checkpoint] injected one generic repair request — exactly one additional response")
    print("The workspace is unchanged, so the second check produces the same failure.")
    print("The CLI stops with the evidence instead of looping:")
    print("[cli] Turn ended after the repair check: FAILED — no third attempt.\n")

    print("--- what happened ---")
    print("1. The model applied a wrong fix and claimed completion.")
    print("2. The acceptance command ran and FAILED — the CLI withheld the 'done' answer.")
    print("3. The CLI injected exactly one additional model response.")
    print("4. The second check still failed, so it STOPPED instead of looping.")

    _show_outcome(cli)
    assert getattr(cli.completion_policy, "repair_injections", 0) == 1, "repair must fire exactly once"
    assert (cli.work_order or {}).get("status") == "failed", "final status must be failed"

    section("1:30+ — the incomplete patch, for review")
    async def diff() -> None:
        await cli._run_diff()
    asyncio.run(diff())


def happy_path(workdir: Path, session_dir: Path, model: str, api_key: str) -> None:
    section("0:30 — happy path: the model fixes it, and the CLI accepts it (real model)")
    print(f"model: {model}\n")
    cli, (_, stdout_text) = _run_engine(workdir, api_key=api_key, model=model, mock=None,
                                        session_dir=session_dir, quiet=True)

    print("The model inspects the repo, edits the return line, and runs the test itself (OK).")
    print("Then it claims completion — and the CLI runs your command again at the boundary:\n")
    _show_acceptance("", cli)

    model_text = (stdout_text or "").strip()
    if model_text:
        print("\nThe model's own summary (printed only after the check passed):")
        print("  " + " ".join(model_text.split())[:400])

    section("2:20 — outcome")
    _show_outcome(cli)
    if (cli.work_order or {}).get("status") != "verified":
        print("\nNOTE: the run did not end verified (model/provider behavior). That is an honest",
              "outcome too — the demo story still holds: the command decided, not the model.")
    async def diff() -> None:
        await cli._run_diff("--stat")
    asyncio.run(diff())


def close() -> None:
    section("2:40 — close")
    print('Verified means this command passed. Failed means it ran and returned failure. '
          'Not verified means there is no trustworthy result.')
    print("It does not mean the whole program is correct — it means the developer's chosen")
    print("acceptance condition passed.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="run the real-model happy path")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model for --live")
    args = ap.parse_args()

    workdir = make_fixture()
    session_dir = Path(tempfile.mkdtemp(prefix="demo-sessions-"))
    try:
        section("0:00 — the product")
        print('A terminal coding agent that will not claim work is done until a command you')
        print('choose actually passes. The model proposes; your command disposes.')

        run_baseline(workdir)

        # Failure branch needs its own clean fixture (the baseline didn't change files, but
        # keep the story clean and deterministic).
        failure_dir = make_fixture()
        failure_branch(failure_dir, session_dir / "failure")

        if args.live:
            api_key = load_api_key()
            if not api_key:
                print("\n--live requires OPENROUTER_API_KEY in .env or the environment.")
                return 2
            warning = preflight_model(args.model, api_key)
            if warning:
                print(f"\n[warn] {warning}")
                print("       You can continue anyway; the demo will report the outcome honestly.")
            live_dir = make_fixture()
            happy_path(live_dir, session_dir / "live", args.model, api_key)
        else:
            print("\n(pass --live to run the real-model happy path; needs OPENROUTER_API_KEY)")

        close()
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(session_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())