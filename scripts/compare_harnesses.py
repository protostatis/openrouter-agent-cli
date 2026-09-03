#!/usr/bin/env python3
"""Cross-harness comparison: same tasks, same model, same verifiers.

Harnesses compared:
- ours     : this project's engine, plain (no acceptance gate) — the fair baseline
- opencode : opencode run (headless), same OpenRouter model
- pi       : pi -p (headless), same OpenRouter model

Each harness gets a fresh workspace with the task's fixture files, the task's
prompt, and its own loop. The SAME verifier grades every result. The only
difference between cells is the harness (the loop around the model).

Usage:
    uv run python scripts/compare_harnesses.py                    # 3 fixed tasks, default model
    uv run python scripts/compare_harnesses.py --tasks xfix12_silent_case,xfix01_indexerror
    uv run python scripts/compare_harnesses.py --model <openrouter-model-id> --all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = PROJECT_ROOT / "eval_suites" / "coding_smoke_v1" / "suite.json"
DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

# Captured comparison: every harness routes through the capture proxy so the
# full raw prompts AND true per-call token usage are recorded.
CAPTURE_URL = "http://localhost:8789/v1"
CAPTURE_LOG = "/tmp/capture.jsonl"
ISOLATED_OC = "/tmp/opencode-clean/config"
ISOLATED_PI = "/tmp/pi-clean"

# The three tasks whose prompts were fixed to state their expected output.
DEFAULT_TASKS = ["xfix12_silent_case", "xfix01_indexerror", "xfix09_silent_whitespace"]


def load_suite(path: str | Path | None = None) -> tuple[dict, dict]:
    suite_path = Path(path) if path else SUITE_PATH
    data = json.loads(suite_path.read_text(encoding="utf-8"))
    tasks = {t["id"]: t for t in data.get("tasks", [])}
    return data, tasks


def make_workspace(task: dict) -> Path:
    ws = Path(tempfile.mkdtemp(prefix="cmp-"))
    for step in task.get("setup") or []:
        if "write_file" in step:
            spec = step["write_file"]
            target = ws / str(spec["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(spec.get("content", "")), encoding="utf-8")
    return ws


def _load_key() -> str:
    env_path = PROJECT_ROOT / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get("OPENROUTER_API_KEY", "")


def grade(task: dict, workspace: Path, suite_dir: Path) -> dict:
    """Run the task's verifier against the workspace; return {verdict, detail}."""
    cmd = task["verifier"]["command"].split()
    proc = subprocess.run(
        [*cmd, str(workspace)],
        cwd=suite_dir,
        capture_output=True,
        text=True,
        timeout=int(task["verifier"].get("timeout_s", 30)) + 30,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode == 0:
        verdict = "pass"
    elif proc.returncode == 2:
        verdict = "task_fail"
    else:
        verdict = "infra"
    return {"verdict": verdict, "detail": out[:200], "exit": proc.returncode}


def _ensure_isolated_configs() -> None:
    """Create the isolated opencode/pi configs if missing."""
    if Path(ISOLATED_OC).is_dir() and Path(ISOLATED_PI).is_dir():
        return
    subprocess.run(
        [str(PROJECT_ROOT / "scripts" / "isolated_harnesses.sh")],
        check=True,
        capture_output=True,
        text=True,
    )


def _capture_snapshot() -> int:
    try:
        return sum(1 for _ in open(CAPTURE_LOG))
    except OSError:
        return 0


def _capture_tokens_since(start: int) -> dict:
    """Sum provider-reported usage tokens from the capture log lines added
    since ``start`` — TRUE token accounting for any harness routed through
    the capture proxy."""
    rows: list[dict] = []
    try:
        with open(CAPTURE_LOG) as fh:
            for i, line in enumerate(fh):
                if i >= start and line.strip():
                    rows.append(json.loads(line))
    except OSError:
        return {"captured_calls": 0, "captured_tokens": 0, "captured_prompt": 0, "captured_completion": 0}
    total = prompt = completion = 0
    for r in rows:
        body = r.get("response_body")
        u = r.get("usage") or (body.get("usage") if isinstance(body, dict) else None) or {}
        prompt += int(u.get("prompt_tokens", 0))
        completion += int(u.get("completion_tokens", 0))
        total += int(u.get("total_tokens", 0))
    return {
        "captured_calls": len(rows),
        "captured_tokens": total,
        "captured_prompt": prompt,
        "captured_completion": completion,
    }


# ---------------------------------------------------------------------------
# harness runners: each returns a small record
# ---------------------------------------------------------------------------

def run_ours(task: dict, workspace: Path, model: str, api_key: str) -> dict:
    from openrouter_agent_cli.cli import OpenRouterAgentCLI, ToolPermissionPolicy

    os.environ["OPENROUTER_AGENT_SESSION_DIR"] = str(workspace / ".sessions")
    cli = OpenRouterAgentCLI(
        api_key=api_key,
        model=model,
        session_id="cmp",
        workdir=str(workspace),
        max_turns=20,
        max_history_messages=64,
        command_timeout=30,
        tools_enabled=True,
        system_prompt="You are a careful coding agent.",
        discovery_mode="real" if "web_" in task["id"] else "off",
    )
    cli.non_interactive_mode = True
    cli.policy = ToolPermissionPolicy(allow={"*"})
    cli.one_shot_prompt = task["prompt"]

    async def go():
        async with httpx.AsyncClient(timeout=120.0) as client:
            await cli.run()
        return cli

    cli = asyncio.run(go())
    steps = [
        f"{r['name']}:{r['status']}" for r in (cli._tool_records or {}).values()
    ]
    return {
        "harness": "ours",
        "tool_calls": len(getattr(cli, "_tool_records", {})),
        "tokens": cli.session_tokens.get("total_tokens", 0),
        "steps": steps,
        "terminal_status": cli.terminal_status,
    }


def _shell(harness: str, cmd: list[str], workspace: Path, timeout: int = 240, env: dict | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd, cwd=workspace, capture_output=True, text=True, timeout=timeout, env=env
    )
    return proc.returncode, (proc.stdout or "")[-800:], (proc.stderr or "")[-400:]


def run_opencode(task: dict, workspace: Path, model: str, api_key: str) -> dict:
    model_spec = f"skycap/{model}"
    env = {**os.environ, "XDG_CONFIG_HOME": ISOLATED_OC}
    rc, out, err = _shell(
        "opencode",
        ["opencode", "run", "--model", model_spec, task["prompt"]],
        workspace,
        env=env,
    )
    steps = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("→")]
    return {
        "harness": "opencode",
        "exit": rc,
        "steps": steps,
        "output_tail": out,
        "error_tail": err,
    }


def run_pi(task: dict, workspace: Path, model: str, api_key: str) -> dict:
    env = {**os.environ, "HOME": ISOLATED_PI}
    rc, out, err = _shell(
        "pi",
        ["pi", "-p", "--provider", "skycap", "--model", model, task["prompt"]],
        workspace,
        env=env,
    )
    return {
        "harness": "pi",
        "exit": rc,
        "steps": [],
        "output_tail": out,
        "error_tail": err,
    }


RUNNERS = {
    "ours": run_ours,
    "opencode": run_opencode,
    "pi": run_pi,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--tasks", default=",".join(DEFAULT_TASKS))
    ap.add_argument("--all", action="store_true", help="run every suite task")
    ap.add_argument("--suite", default=str(SUITE_PATH), help="suite JSON path")
    args = ap.parse_args()

    _, tasks = load_suite(args.suite)
    suite_dir = Path(args.suite).parent
    wanted = list(tasks) if args.all else [t.strip() for t in args.tasks.split(",") if t.strip()]
    missing = [t for t in wanted if t not in tasks]
    if missing:
        print(f"unknown tasks: {missing}")
        return 2
    api_key = _load_key()
    if not api_key:
        print("need OPENROUTER_API_KEY in .env")
        return 2
    _ensure_isolated_configs()
    os.environ["OPENROUTER_BASE_URL"] = CAPTURE_URL  # ours routes through capture

    results: list[dict] = []
    for tid in wanted:
        task = tasks[tid]
        for name, runner in RUNNERS.items():
            ws = make_workspace(task)
            cell = {"task": tid, "harness": name, "model": args.model}
            cap_start = _capture_snapshot()
            try:
                extra = runner(task, ws, args.model, api_key)
                cell.update(extra)
                g = grade(task, ws, suite_dir)
                cell.update({"verdict": g["verdict"], "detail": g["detail"]})
            except Exception as exc:
                cell.update({"verdict": "infra", "detail": f"{type(exc).__name__}: {exc}"})
            finally:
                shutil.rmtree(ws, ignore_errors=True)
            cell.update(_capture_tokens_since(cap_start))
            results.append(cell)
            tok = cell.get("captured_tokens")
            print(f"{tid:<28} {name:<10} {cell['verdict']:<10} tok={tok} calls={cell.get('captured_calls')} {cell.get('detail','')[:50]}")
            steps = cell.get("steps")
            if steps:
                print(f"{'':<28} {'':<10} steps: {' -> '.join(steps)}")

    # save for later analysis
    out_dir = PROJECT_ROOT / ".agent-eval" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"harness-cmp-{stamp}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nresults -> {path}")
    print(f"{'task':<28}{'ours':<8}{'opencode':<10}{'pi':<6}")
    for tid in wanted:
        row = {r["harness"]: r["verdict"] for r in results if r["task"] == tid}
        print(f"{tid:<28}{row.get('ours','?'):<8}{row.get('opencode','?'):<10}{row.get('pi','?'):<6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())