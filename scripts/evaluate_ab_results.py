#!/usr/bin/env python3
"""Evaluate A/B prompt run outputs for groundedness and quality."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

from openrouter_agent_cli.cli import DEFAULT_MODEL, OPENROUTER_URL

REF_RE = re.compile(r"(?P<path>[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+):(?P<line>\d{1,6})")


def _load_results(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in paths:
        data = json.loads(p.read_text())
        if not isinstance(data, list):
            raise ValueError(f"Expected list in {p}, got {type(data).__name__}")
        for row in data:
            row["_results_path"] = str(p)
            rows.append(row)
    if not rows:
        raise ValueError("No rows found in provided results files.")
    return rows


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _extract_refs(answer: str, repo_root: Path, max_refs: int) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for m in REF_RE.finditer(answer or ""):
        raw_path = m.group("path")
        line = int(m.group("line"))
        key = (raw_path, line)
        if key in seen:
            continue
        seen.add(key)
        if len(refs) >= max_refs:
            break

        if raw_path.startswith("/"):
            path = Path(raw_path).expanduser()
        else:
            path = (repo_root / raw_path).expanduser()
        exists = path.exists() and path.is_file()
        line_ok = False
        line_text = ""
        if exists:
            try:
                lines = path.read_text(errors="replace").splitlines()
                if 1 <= line <= len(lines):
                    line_ok = True
                    line_text = lines[line - 1].strip()
            except Exception:
                pass

        refs.append(
            {
                "raw_path": raw_path,
                "line": line,
                "exists": exists,
                "line_ok": line_ok,
                "line_text": line_text[:220],
                "resolved_path": str(path),
            }
        )
    return refs


def _ref_summary(refs: list[dict[str, Any]], repo_root: Path) -> str:
    if not refs:
        return "No file:line references found in answer."
    lines = []
    for ref in refs:
        status = "valid" if ref["line_ok"] else "invalid"
        rel = _safe_rel(Path(ref["resolved_path"]), repo_root)
        snippet = ref["line_text"] or "(no readable line)"
        lines.append(f"- {status}: {rel}:{ref['line']} | {snippet}")
    return "\n".join(lines)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        chunk = text[start : end + 1]
        try:
            obj = json.loads(chunk)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return {}
    return {}


async def _judge_one(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    task: str,
    answer: str,
    ref_report: str,
    max_answer_chars: int,
) -> dict[str, Any]:
    system = (
        "You are a strict evaluator for coding-agent answers. "
        "Score grounding and correctness conservatively. "
        "Return JSON only."
    )
    user = (
        "Evaluate this answer.\n\n"
        f"TASK:\n{task}\n\n"
        f"ANSWER:\n{(answer or '')[:max_answer_chars]}\n\n"
        f"REFERENCE_CHECK:\n{ref_report}\n\n"
        "Rubric:\n"
        "- groundedness: 1-5 (are claims supported by references/evidence?)\n"
        "- correctness: 1-5 (technical correctness)\n"
        "- specificity: 1-5 (actionable and concrete)\n"
        "- hallucination_risk: low|medium|high\n"
        "- notes: short explanation\n\n"
        'Return JSON object with keys: groundedness, correctness, specificity, hallucination_risk, notes'
    )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 450,
        "tool_choice": "none",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get(
            "OPENROUTER_AGENT_REFERER", "https://github.com/local/openrouter-agent-cli"
        ),
        "X-Title": os.environ.get("OPENROUTER_AGENT_TITLE", "OpenRouter AB Evaluator"),
    }
    resp = await client.post(OPENROUTER_URL, json=body, headers=headers)
    if not resp.is_success:
        resp.raise_for_status()
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = (msg.get("content") or msg.get("reasoning") or "").strip()
    parsed = _parse_json_object(text)
    return {
        "raw_text": text,
        "parsed": parsed,
        "usage": data.get("usage") or {},
    }


def _coerce_score(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return min(5.0, max(0.0, f))


def _risk_value(value: str) -> str:
    v = str(value or "").strip().lower()
    if v in {"low", "medium", "high"}:
        return v
    return "unknown"


def _write_outputs(
    evaluated: list[dict[str, Any]],
    output_dir: Path,
    source_paths: list[Path],
    judge_model: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation.json").write_text(json.dumps(evaluated, indent=2))

    fieldnames = [
        "prompt_variant",
        "task_id",
        "repeat",
        "ok",
        "finish_reason",
        "tool_calls",
        "total_tokens",
        "latency_seconds",
        "ref_mentions",
        "valid_refs",
        "invalid_refs",
        "valid_ref_ratio",
        "groundedness",
        "correctness",
        "specificity",
        "hallucination_risk",
        "overall_score",
        "overall_adjusted",
        "judge_notes",
        "error",
        "source_results",
    ]
    with (output_dir / "evaluation.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in evaluated:
            w.writerow({k: row.get(k, "") for k in fieldnames})

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evaluated:
        grouped[str(row.get("prompt_variant", "unknown"))].append(row)

    lines = [
        "# A/B Evaluation Leaderboard",
        "",
        f"- judge_model: `{judge_model}`",
        f"- source_results: {', '.join(str(p) for p in source_paths)}",
        "",
        "| prompt_variant | cases | avg_overall_adj | avg_groundedness | avg_correctness | avg_specificity | avg_valid_ref_ratio | avg_tokens | avg_latency_s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    ranking = []
    for variant, rows in grouped.items():
        avg_overall_adj = mean(float(r.get("overall_adjusted", 0.0)) for r in rows)
        ranking.append((avg_overall_adj, variant, rows))
    ranking.sort(reverse=True, key=lambda t: t[0])

    for avg_overall_adj, variant, rows in ranking:
        avg_ground = mean(float(r.get("groundedness", 0.0)) for r in rows)
        avg_corr = mean(float(r.get("correctness", 0.0)) for r in rows)
        avg_spec = mean(float(r.get("specificity", 0.0)) for r in rows)
        avg_valid = mean(float(r.get("valid_ref_ratio", 0.0)) for r in rows)
        avg_tokens = mean(float(r.get("total_tokens", 0.0)) for r in rows)
        avg_latency = mean(float(r.get("latency_seconds", 0.0)) for r in rows)
        lines.append(
            f"| {variant} | {len(rows)} | {avg_overall_adj:.3f} | {avg_ground:.3f} | "
            f"{avg_corr:.3f} | {avg_spec:.3f} | {avg_valid:.3f} | {avg_tokens:.1f} | {avg_latency:.3f} |"
        )

    lines.append("")
    lines.append("## Notes")
    lines.append("- `overall_score` = 0.5*groundedness + 0.3*correctness + 0.2*specificity")
    lines.append("- `overall_adjusted` = 0.85*overall_score + 0.15*(valid_ref_ratio*5)")
    lines.append("- `valid_ref_ratio` is based on `path:line` references that resolve in local files.")
    (output_dir / "leaderboard.md").write_text("\n".join(lines) + "\n")


async def _main_async(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    source_paths = [Path(p).expanduser().resolve() for p in args.results]
    rows = _load_results(source_paths)
    output_dir = Path(args.output_dir).expanduser()

    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not args.skip_judge and not api_key:
        raise RuntimeError("Missing API key for judge. Set OPENROUTER_API_KEY or use --skip-judge.")

    evaluated: list[dict[str, Any]] = []
    timeout = httpx.Timeout(args.request_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        total = len(rows)
        for idx, row in enumerate(rows, start=1):
            answer = str(row.get("final_text", "") or "")
            refs = _extract_refs(answer, repo_root=repo_root, max_refs=args.max_refs)
            valid_refs = sum(1 for r in refs if r["line_ok"])
            invalid_refs = max(0, len(refs) - valid_refs)
            valid_ref_ratio = (valid_refs / len(refs)) if refs else 0.0
            ref_report = _ref_summary(refs, repo_root=repo_root)

            judge_out = {
                "groundedness": 0.0,
                "correctness": 0.0,
                "specificity": 0.0,
                "hallucination_risk": "unknown",
                "notes": "",
                "judge_raw": "",
                "judge_usage": {},
            }
            error = str(row.get("error", "") or "")

            print(
                f"[{idx}/{total}] evaluate prompt={row.get('prompt_variant')} task={row.get('task_id')} repeat={row.get('repeat', 1)}"
            )
            if not args.skip_judge:
                try:
                    judged = await _judge_one(
                        client,
                        api_key=api_key,
                        model=args.judge_model,
                        task=str(row.get("task", "")),
                        answer=answer,
                        ref_report=ref_report,
                        max_answer_chars=args.max_answer_chars,
                    )
                    parsed = judged["parsed"]
                    judge_out["groundedness"] = _coerce_score(parsed.get("groundedness"), 0.0)
                    judge_out["correctness"] = _coerce_score(parsed.get("correctness"), 0.0)
                    judge_out["specificity"] = _coerce_score(parsed.get("specificity"), 0.0)
                    judge_out["hallucination_risk"] = _risk_value(parsed.get("hallucination_risk"))
                    judge_out["notes"] = str(parsed.get("notes", ""))[:500]
                    judge_out["judge_raw"] = str(judged.get("raw_text", ""))[:2000]
                    judge_out["judge_usage"] = judged.get("usage", {})
                except Exception as exc:
                    err = f"judge_failed: {exc}"
                    error = f"{error}; {err}" if error else err

            overall_score = (
                0.5 * judge_out["groundedness"]
                + 0.3 * judge_out["correctness"]
                + 0.2 * judge_out["specificity"]
            )
            overall_adjusted = 0.85 * overall_score + 0.15 * (valid_ref_ratio * 5.0)

            evaluated.append(
                {
                    "prompt_variant": row.get("prompt_variant"),
                    "task_id": row.get("task_id"),
                    "repeat": row.get("repeat", 1),
                    "ok": row.get("ok"),
                    "finish_reason": row.get("finish_reason"),
                    "tool_calls": row.get("tool_calls"),
                    "total_tokens": row.get("total_tokens"),
                    "latency_seconds": row.get("latency_seconds"),
                    "ref_mentions": len(refs),
                    "valid_refs": valid_refs,
                    "invalid_refs": invalid_refs,
                    "valid_ref_ratio": round(valid_ref_ratio, 4),
                    "groundedness": round(float(judge_out["groundedness"]), 3),
                    "correctness": round(float(judge_out["correctness"]), 3),
                    "specificity": round(float(judge_out["specificity"]), 3),
                    "hallucination_risk": judge_out["hallucination_risk"],
                    "overall_score": round(overall_score, 4),
                    "overall_adjusted": round(overall_adjusted, 4),
                    "judge_notes": judge_out["notes"],
                    "judge_raw": judge_out["judge_raw"],
                    "judge_usage": judge_out["judge_usage"],
                    "refs": refs,
                    "error": error,
                    "source_results": row.get("_results_path"),
                }
            )

    _write_outputs(evaluated, output_dir=output_dir, source_paths=source_paths, judge_model=args.judge_model)
    print(f"Wrote: {output_dir / 'evaluation.json'}")
    print(f"Wrote: {output_dir / 'evaluation.csv'}")
    print(f"Wrote: {output_dir / 'leaderboard.md'}")
    return 0


def parse_args() -> argparse.Namespace:
    default_out = f"ab_tests/results/eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    parser = argparse.ArgumentParser(description="Evaluate A/B prompt run outputs.")
    parser.add_argument(
        "--results",
        action="append",
        required=True,
        help="Path to one results.json file from ab_test_system_prompts.py. Repeat for multiple files.",
    )
    parser.add_argument("--repo-root", default=".", help="Repo root for validating file:line references.")
    parser.add_argument("--api-key", help="OpenRouter API key. Defaults to OPENROUTER_API_KEY.")
    parser.add_argument(
        "--judge-model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        help=f"Judge model id (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument("--skip-judge", action="store_true", help="Only run local heuristic evaluation.")
    parser.add_argument("--max-refs", type=int, default=12, help="Max references to validate per answer.")
    parser.add_argument("--max-answer-chars", type=int, default=7000, help="Max answer chars sent to judge.")
    parser.add_argument("--request-timeout", type=float, default=60.0, help="Judge request timeout seconds.")
    parser.add_argument("--output-dir", default=default_out, help="Output directory for evaluation artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
