#!/usr/bin/env python3
"""A/B test harness for comparing system prompts against OpenRouter models."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from openrouter_agent_cli.cli import DEFAULT_MODEL, TOOLS
from openrouter_agent_cli.utils import call_openrouter, run_bash, _decode_tool_arguments


@dataclass
class PromptVariant:
    name: str
    path: Path
    text: str


@dataclass
class TaskCase:
    id: str
    prompt: str


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "item"


async def _run_bash(command: str, cwd: str, timeout_seconds: int) -> str:
    return await run_bash(command, cwd, timeout_seconds)


async def _call_openrouter(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    tool_mode: str,
) -> dict[str, Any]:
    tools = TOOLS if tool_mode != "none" else None
    tool_choice = "auto" if tool_mode != "none" else "none"
    return await call_openrouter(
        client,
        api_key=api_key,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        tool_choice=tool_choice,
        tools=tools,
    )


def _load_prompt(path: Path) -> PromptVariant:
    return PromptVariant(
        name=_safe_name(path.stem), path=path, text=path.read_text().strip()
    )


def _load_tasks(tasks_file: Path | None, inline_tasks: list[str]) -> list[TaskCase]:
    tasks: list[TaskCase] = []
    if tasks_file:
        if tasks_file.exists():
            lines = tasks_file.read_text().splitlines()
            for idx, line in enumerate(lines, start=1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                tasks.append(TaskCase(id=f"task_{idx:02d}", prompt=text))
        elif not inline_tasks:
            raise ValueError(f"Tasks file not found: {tasks_file}")
    for idx, text in enumerate(inline_tasks, start=1):
        prompt = text.strip()
        if prompt:
            tasks.append(TaskCase(id=f"inline_{idx:02d}", prompt=prompt))
    if not tasks:
        raise ValueError("No tasks loaded. Provide --tasks-file and/or --task.")
    return tasks


async def _run_case(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: PromptVariant,
    task: TaskCase,
    tool_mode: str,
    max_turns: int,
    max_tokens: int,
    command_timeout: int,
    workdir: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt.text},
        {"role": "user", "content": task.prompt},
    ]
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    total_tool_calls = 0
    steps = 0
    last_tool_signature: str | None = None
    repeated_count = 0

    try:
        for _ in range(max_turns):
            steps += 1
            resp = await _call_openrouter(
                client=client,
                api_key=api_key,
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                tool_mode=tool_mode,
            )
            usage = resp.get("usage") or {}
            total_prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            total_completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            total_tokens += int(usage.get("total_tokens", 0) or 0)

            choice = (resp.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            finish_reason = str(choice.get("finish_reason", ""))
            messages.append(message)
            tool_calls = message.get("tool_calls") or []
            total_tool_calls += len(tool_calls)

            if not tool_calls or tool_mode != "execute":
                text = (
                    message.get("content") or message.get("reasoning") or ""
                ).strip()
                elapsed = time.perf_counter() - started
                return {
                    "ok": True,
                    "error": "",
                    "prompt_variant": prompt.name,
                    "prompt_path": str(prompt.path),
                    "task_id": task.id,
                    "task": task.prompt,
                    "finish_reason": finish_reason,
                    "steps": steps,
                    "tool_calls": total_tool_calls,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_seconds": round(elapsed, 3),
                    "final_text": text,
                    "messages": messages,
                }

            signature = json.dumps(
                [
                    {
                        "name": tc.get("function", {}).get("name"),
                        "args": tc.get("function", {}).get("arguments"),
                    }
                    for tc in tool_calls
                ],
                sort_keys=True,
            )
            if signature == last_tool_signature:
                repeated_count += 1
            else:
                repeated_count = 0
                last_tool_signature = signature

            if repeated_count >= 1:
                nudge = (
                    "STOP. You repeated the same tool call without progress. "
                    "Do not call additional tools. Reply with a concise final answer."
                )
                for tc in tool_calls:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", "loop"),
                            "content": nudge,
                        }
                    )
                forced = await _call_openrouter(
                    client=client,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    tool_mode="none",
                )
                forced_usage = forced.get("usage") or {}
                total_prompt_tokens += int(forced_usage.get("prompt_tokens", 0) or 0)
                total_completion_tokens += int(
                    forced_usage.get("completion_tokens", 0) or 0
                )
                total_tokens += int(forced_usage.get("total_tokens", 0) or 0)
                forced_choice = (forced.get("choices") or [{}])[0]
                forced_message = forced_choice.get("message") or {}
                forced_finish_reason = str(forced_choice.get("finish_reason", ""))
                forced_text = (
                    forced_message.get("content")
                    or forced_message.get("reasoning")
                    or ""
                ).strip()
                messages.append(forced_message)
                elapsed = time.perf_counter() - started
                return {
                    "ok": True,
                    "error": "",
                    "prompt_variant": prompt.name,
                    "prompt_path": str(prompt.path),
                    "task_id": task.id,
                    "task": task.prompt,
                    "finish_reason": forced_finish_reason or "loop_break",
                    "steps": steps,
                    "tool_calls": total_tool_calls,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_seconds": round(elapsed, 3),
                    "final_text": forced_text,
                    "messages": messages,
                }

            tool_results: list[dict[str, Any]] = []
            for idx, tc in enumerate(tool_calls):
                fn = tc.get("function") or {}
                tool_name = str(fn.get("name", "")).strip()
                tool_args = _decode_tool_arguments(fn.get("arguments"))
                call_id = tc.get("id") or f"tc-{steps}-{idx + 1}"

                if tool_name != "run_bash":
                    result = f"Unknown tool: {tool_name}"
                else:
                    command = str(tool_args.get("command", "")).strip()
                    timeout_seconds = tool_args.get("timeout_seconds", command_timeout)
                    try:
                        timeout_seconds = int(timeout_seconds)
                    except (TypeError, ValueError):
                        timeout_seconds = command_timeout
                    timeout_seconds = min(max(1, timeout_seconds), 600)
                    if not command:
                        result = "run_bash error: 'command' is required."
                    else:
                        result = await _run_bash(
                            command, cwd=workdir, timeout_seconds=timeout_seconds
                        )

                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": str(result)[:8000],
                    }
                )

            messages.extend(tool_results)

        # If we hit max turns while still seeing tool calls, force a final text-only answer.
        forced_prompt = "Stop using tools. Provide your final answer now using the gathered context."
        messages.append({"role": "user", "content": forced_prompt})
        forced = await _call_openrouter(
            client=client,
            api_key=api_key,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            tool_mode="none",
        )
        forced_usage = forced.get("usage") or {}
        total_prompt_tokens += int(forced_usage.get("prompt_tokens", 0) or 0)
        total_completion_tokens += int(forced_usage.get("completion_tokens", 0) or 0)
        total_tokens += int(forced_usage.get("total_tokens", 0) or 0)
        forced_choice = (forced.get("choices") or [{}])[0]
        forced_message = forced_choice.get("message") or {}
        forced_finish_reason = str(forced_choice.get("finish_reason", ""))
        forced_text = (
            forced_message.get("content") or forced_message.get("reasoning") or ""
        ).strip()
        messages.append(forced_message)
        elapsed = time.perf_counter() - started
        return {
            "ok": True,
            "error": "",
            "prompt_variant": prompt.name,
            "prompt_path": str(prompt.path),
            "task_id": task.id,
            "task": task.prompt,
            "finish_reason": forced_finish_reason or "forced_final",
            "steps": steps,
            "tool_calls": total_tool_calls,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "latency_seconds": round(elapsed, 3),
            "final_text": forced_text,
            "messages": messages,
        }
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return {
            "ok": False,
            "error": str(exc),
            "prompt_variant": prompt.name,
            "prompt_path": str(prompt.path),
            "task_id": task.id,
            "task": task.prompt,
            "finish_reason": "error",
            "steps": steps,
            "tool_calls": total_tool_calls,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "latency_seconds": round(elapsed, 3),
            "final_text": "",
            "messages": messages,
        }


def _write_outputs(results: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = output_dir / "results.json"
    raw_path.write_text(json.dumps(results, indent=2))

    summary_rows = []
    for row in results:
        summary_rows.append(
            {
                "prompt_variant": row["prompt_variant"],
                "task_id": row["task_id"],
                "ok": row["ok"],
                "finish_reason": row["finish_reason"],
                "steps": row["steps"],
                "tool_calls": row["tool_calls"],
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "total_tokens": row["total_tokens"],
                "latency_seconds": row["latency_seconds"],
                "final_text_preview": (row["final_text"] or "")[:160].replace(
                    "\n", " "
                ),
                "error": row["error"],
            }
        )

    csv_path = output_dir / "summary.csv"
    with csv_path.open("w", newline="") as f:
        fieldnames = list(summary_rows[0].keys()) if summary_rows else []
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    lines = [
        "# Prompt A/B Test Summary",
        "",
        "| prompt_variant | task_id | ok | finish_reason | tool_calls | total_tokens | latency_seconds |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["prompt_variant"]),
                    str(row["task_id"]),
                    str(row["ok"]),
                    str(row["finish_reason"]),
                    str(row["tool_calls"]),
                    str(row["total_tokens"]),
                    str(row["latency_seconds"]),
                ]
            )
            + " |"
        )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n")


async def _main_async(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing API key. Set OPENROUTER_API_KEY or pass --api-key.")

    prompts = [_load_prompt(Path(p).expanduser()) for p in args.prompt]
    tasks = _load_tasks(
        Path(args.tasks_file).expanduser() if args.tasks_file else None, args.task
    )
    output_dir = Path(args.output_dir).expanduser()

    print(f"Model: {args.model}")
    print(f"Tool mode: {args.tool_mode}")
    print(f"Prompts: {', '.join(p.name for p in prompts)}")
    print(f"Tasks: {len(tasks)}")
    print(f"Workdir for tool execution: {args.workdir}")
    print()

    results: list[dict[str, Any]] = []
    timeout = httpx.Timeout(args.request_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        total_cases = len(prompts) * len(tasks) * args.repeats
        case_num = 0
        for repeat_idx in range(args.repeats):
            for prompt in prompts:
                for task in tasks:
                    case_num += 1
                    print(
                        f"[{case_num}/{total_cases}] prompt={prompt.name} task={task.id} repeat={repeat_idx + 1}"
                    )
                    result = await _run_case(
                        client,
                        api_key=api_key,
                        model=args.model,
                        prompt=prompt,
                        task=task,
                        tool_mode=args.tool_mode,
                        max_turns=args.max_turns,
                        max_tokens=args.max_tokens,
                        command_timeout=args.command_timeout,
                        workdir=args.workdir,
                    )
                    result["repeat"] = repeat_idx + 1
                    results.append(result)

    _write_outputs(results, output_dir)
    print()
    print(f"Wrote: {output_dir / 'results.json'}")
    print(f"Wrote: {output_dir / 'summary.csv'}")
    print(f"Wrote: {output_dir / 'summary.md'}")
    return 0


def parse_args() -> argparse.Namespace:
    default_output = f"ab_tests/results/{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    parser = argparse.ArgumentParser(description="Run OpenRouter prompt A/B tests.")
    parser.add_argument(
        "--api-key", help="OpenRouter API key. Defaults to OPENROUTER_API_KEY."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        help=f"Model id to test (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=[
            "prompts/system_prompt_control.md",
            "prompts/system_prompt_agentic_v1.md",
        ],
        help=(
            "Path to prompt file. Repeat flag for multiple variants. "
            "Defaults to control and agentic prompts."
        ),
    )
    parser.add_argument(
        "--tasks-file",
        default="ab_tests/tasks_sample.txt",
        help="Text file with one task prompt per line.",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Inline task prompt. Repeat flag to add multiple tasks.",
    )
    parser.add_argument(
        "--tool-mode",
        choices=["none", "inspect", "execute"],
        default="none",
        help=(
            "'none': disable tools, "
            "'inspect': include tools but do not execute returned tool calls, "
            "'execute': include tools and execute run_bash tool calls."
        ),
    )
    parser.add_argument(
        "--workdir",
        default=os.getcwd(),
        help="Working directory for tool execution in execute mode.",
    )
    parser.add_argument(
        "--max-turns", type=int, default=6, help="Max model/tool loop turns per case."
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1200,
        help="Max completion tokens per model call.",
    )
    parser.add_argument(
        "--command-timeout", type=int, default=30, help="run_bash timeout seconds."
    )
    parser.add_argument(
        "--request-timeout", type=float, default=90.0, help="HTTP timeout seconds."
    )
    parser.add_argument(
        "--repeats", type=int, default=1, help="Runs each prompt/task pair N times."
    )
    parser.add_argument(
        "--output-dir", default=default_output, help="Directory for test artifacts."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
