"""Descriptive paired-comparison report.

v1 deliberately reports DESCRIPTIONS, not statistical significance: with the
small task counts a local suite carries, confidence intervals would imply a
rigor the data cannot support. Each table answers one plain question:

  outcome counts per profile  -> "who passed what?"
  outcome matrix per task     -> "where do the profiles differ?"
  cost/latency per profile    -> "what does each choice cost?"
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .records import load_records


def _outcome_counts(records: list[dict[str, Any]]) -> dict[str, Counter]:
    by_profile: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        by_profile[r["profile"]["name"]][r.get("verdict") or "not_verified"] += 1
    return by_profile


def paired_matrix(records: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """task_id -> {profile_name: verdict} for tasks covered by all profiles."""
    by_task: dict[str, dict[str, str]] = defaultdict(dict)
    for r in records:
        by_task[r["task_id"]][r["profile"]["name"]] = r.get("verdict") or "not_verified"
    return dict(by_task)


def paired_tally(records: list[dict[str, Any]]) -> dict[tuple[str, str], Counter]:
    """For each ordered profile pair (a, b) on shared tasks: how often a passed
    while b failed, b passed while a failed, both, neither."""
    matrix = paired_matrix(records)
    profiles = sorted({r["profile"]["name"] for r in records})
    tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for outcomes in matrix.values():
        if len(outcomes) < 2 or any(v == "not_verified" for v in outcomes.values()):
            continue
        for a in profiles:
            for b in profiles:
                if a >= b:
                    continue
                a_pass = outcomes.get(a) == "pass"
                b_pass = outcomes.get(b) == "pass"
                if a_pass and b_pass:
                    tally[(a, b)]["both_pass"] += 1
                elif a_pass:
                    tally[(a, b)]["a_only_pass"] += 1
                elif b_pass:
                    tally[(a, b)]["b_only_pass"] += 1
                else:
                    tally[(a, b)]["neither_pass"] += 1
    return dict(tally)


def cost_table(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_profile[r["profile"]["name"]].append(r)
    table: dict[str, dict[str, Any]] = {}
    for name, rows in by_profile.items():
        latencies = [r["timing"].get("latency_seconds") or 0 for r in rows]
        tokens = [
            (r["usage"] or {}).get("total_tokens") or 0
            for r in rows
        ]
        table[name] = {
            "attempts": len(rows),
            "total_tokens": sum(tokens),
            "median_latency_s": sorted(latencies)[len(latencies) // 2] if latencies else None,
        }
    return table


def render_report(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    counts = _outcome_counts(records)
    lines.append("## Outcome counts per profile")
    lines.append("(rows: profiles; columns: pass / task_fail / infrastructure_error / not_verified)")
    for name, counter in sorted(counts.items()):
        lines.append(
            f"  {name}: pass={counter['pass']} task_fail={counter['task_fail']} "
            f"infra={counter['infrastructure_error']} unverified={counter['not_verified']}"
        )
    tally = paired_tally(records)
    if tally:
        lines.append("")
        lines.append("## Paired outcomes (shared tasks, both verified)")
        lines.append("(each line: [a-only-pass | b-only-pass | both | neither] for profiles a vs b)")
        for (a, b), counter in sorted(tally.items()):
            lines.append(
                f"  {a} vs {b}: a_only={counter['a_only_pass']} "
                f"b_only={counter['b_only_pass']} both={counter['both_pass']} "
                f"neither={counter['neither_pass']}"
            )
    costs = cost_table(records)
    lines.append("")
    lines.append("## Cost and latency per profile")
    for name, entry in sorted(costs.items()):
        lines.append(
            f"  {name}: attempts={entry['attempts']} tokens={entry['total_tokens']} "
            f"median_latency={entry['median_latency_s']}s"
        )
    lines.append("")
    lines.append(
        "Note: descriptive summary of THIS suite run only; it is not a general "
        "ranking of the profiles."
    )
    from .uncertainty import render_uncertainty

    lines.append("")
    lines.extend(render_uncertainty(records))
    return "\n".join(lines)


def report_from_file(path: Path) -> str:
    return render_report(load_records(path))
