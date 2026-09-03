#!/usr/bin/env python3
"""A sixty-second narrated demo of the acceptance-check product.

Run with:  uv run python scripts/demo_acceptance.py            (the core story, offline, ~10s)
           uv run python scripts/demo_acceptance.py --live     (+ real-model happy path)

The story, in one line: an agent that is not allowed to say "I'm done" until
a check YOU wrote passes. The agent proposes the work; the check disposes of
the claim.
"""
from __future__ import annotations

import argparse
import asyncio
import io
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
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def say(text: str) -> None:
    print(text)


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
) -> tuple["object", tuple[str, str]]:
    """Drive the real engine silently; return (cli, (captured_stderr, captured_stdout))."""
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
    cli.policy = ToolPermissionPolicy(allow={"*"})
    cli.one_shot_prompt = ONE_SHOT
    if mock is not None:
        cli.model_transport = MockTransport({"responses": mock})

    captured_err = io.StringIO()
    captured_out = io.StringIO()
    real_stderr, real_stdout = sys.stderr, sys.stdout
    sys.stderr, sys.stdout = captured_err, captured_out
    try:
        async def go() -> "object":
            async with httpx.AsyncClient(timeout=90.0) as client:
                await cli.run()
            return cli
        engine = asyncio.run(go())
    finally:
        sys.stderr, sys.stdout = real_stderr, real_stdout
    return engine, (captured_err.getvalue(), captured_out.getvalue())


def _test_output(cli: "object") -> str:
    lc = (cli.work_order or {}).get("last_check") or {}
    return str(lc.get("stderr") or lc.get("stdout") or "").strip()


def _show_claim(cli: "object", stdout_text: str, expected: str) -> None:
    """Show the model's claim (the captured final text, deduplicated)."""
    text = " ".join((stdout_text or "").split()).strip()
    if text and text != expected:
        say(f'       "{text}"')
    else:
        say(f'       "{expected}"')


def catch_story(workdir: Path, session_dir: Path) -> None:
    """The core beat: the agent claims done, and it is wrong."""
    mock = [
        {"tool_calls": [{"name": "edit_file", "arguments": {
            "path": "greet.py",
            "old_string": 'return "hello " + name',
            "new_string": 'return "Hello " + name',  # missing the comma
        }}]},
        {"text": "Done. I fixed the greeting and the test now passes."},
    ]
    cli, (_, stdout_text) = _run_engine(workdir, api_key="mock-key", model="mock-model",
                                        mock=mock, session_dir=session_dir)

    section("The catch — the agent claims done, and it is wrong")
    say("The agent makes a small mistake (it forgets a comma) and then says:")
    _show_claim(cli, stdout_text, "Done. I fixed the greeting and the test now passes.")
    say("")
    say("In a normal transcript, that sentence is the end. You would trust it.")
    say("Here, the tool runs your rule before accepting the claim. The rule fails:")
    say("")
    say("       $ python3 test_greet.py")
    for line in _test_output(cli).splitlines()[:6]:
        say(f"       {line}")
    say("")
    say("So the tool withholds \"done\" and gives the agent exactly one more response.")
    say("The second attempt is still wrong. The tool stops.")
    say("It does not loop, and it does not fake success. It leaves you the")
    say("failure evidence and the unfinished patch to review:")
    say("")
    async def diff() -> None:
        await cli._run_diff()
    asyncio.run(diff())

    say("")
    say("--- for the curious: the recorded outcome ---")
    lc = (cli.work_order or {}).get("last_check") or {}
    say(f"state: {cli.work_order.get('status')} | repair responses: "
        f"{getattr(cli.completion_policy, 'repair_injections', '?')} | "
        f"model requests: {cli.cache_context.requests} | changed: {lc.get('changed_files')}")

    assert getattr(cli.completion_policy, "repair_injections", 0) == 1, "repair must fire once"
    assert (cli.work_order or {}).get("status") == "failed", "final status must be failed"


def happy_story(workdir: Path, session_dir: Path, model: str, api_key: str) -> None:
    """When the agent is right: the same rule passes and the claim is accepted."""
    section("When the agent is right")
    say(f"(real model: {model})")
    say("The same task, the same rule. This time the agent fixes it correctly,")
    say("then claims completion. The tool runs your rule again at the boundary:")
    say("")
    cli, (_, stdout_text) = _run_engine(workdir, api_key=api_key, model=model,
                                        mock=None, session_dir=session_dir)
    lc = (cli.work_order or {}).get("last_check") or {}
    state = str(cli.work_order.get("status") or "not_verified")
    say(f"       rule: {lc.get('command') or acceptance_command()}")
    say(f"       result: {state.upper()} (exit {lc.get('exit_code')})")
    if state == "verified":
        say(f"       changed: {lc.get('changed_files')}")
        model_text = " ".join((stdout_text or "").split()).strip()
        if model_text:
            say("")
            say("The agent's own summary (only printed after the rule passed):")
            say(f"       {model_text[:300]}")
    else:
        say("")
        say("(The run did not end verified — provider behavior. That is an honest")
        say("outcome too: the rule decided, not the model.)")


def close_story() -> None:
    section("The three states")
    say("verified     — your rule passed.")
    say("failed       — your rule ran and failed.")
    say("not verified — no trustworthy result (e.g. the check itself could not run).")
    say("")
    say("The agent never gets the last word on whether it is done. You do.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="add the real-model happy path")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="model for --live")
    args = ap.parse_args()

    session_dir = Path(tempfile.mkdtemp(prefix="demo-sessions-"))
    try:
        section("What you are about to see")
        say("An agent that is not allowed to say \"I'm done\" until a check YOU wrote")
        say("passes. The agent proposes the work; the check disposes of the claim.")

        section("The setup")
        say(f"task: {TASK}")
        say(f"rule: before \"done\" counts, this must pass:  {acceptance_command()}")

        catch_dir = make_fixture()
        catch_story(catch_dir, session_dir / "catch")

        if args.live:
            api_key = load_api_key()
            if not api_key:
                print("\n--live requires OPENROUTER_API_KEY in .env or the environment.")
                return 2
            warning = preflight_model(args.model, api_key)
            if warning:
                print(f"\n[warn] {warning}")
                print("       Continuing anyway; the demo reports the outcome honestly.")
            happy_dir = make_fixture()
            happy_story(happy_dir, session_dir / "happy", args.model, api_key)
        else:
            say("")
            say("(pass --live to add the real-model happy path; needs OPENROUTER_API_KEY)")

        close_story()
        return 0
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())