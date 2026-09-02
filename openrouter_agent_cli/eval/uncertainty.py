"""Uncertainty for suite results: per-profile intervals + paired differences.

Two layers, stdlib-only, each honest about what it assumes:

1. **Per-profile Wilson score intervals** on pass rate. Closed-form, always
   valid, and notably wider than the naive "passes/n" when attempts are few —
   which is the point.

2. **Paired task-level cluster bootstrap** for profile differences and
   P(A beats B). Tasks — not runs — are resampled with replacement, because
   outcomes on the same task are correlated (the paired design exists for
   that reason); resampling runs would overstate precision. Each draw
   recomputes the paired difference, so the interval and P(A>B) reflect
   exactly the comparison an optimizer would act on.

Both are suite-specific statements. They say nothing about performance on
tasks outside the suite.
"""
from __future__ import annotations

import random
from collections import defaultdict
from statistics import NormalDist
from typing import Any

from .records import model_alone_records

_Z_95 = NormalDist().inv_cdf(0.975)


def wilson_interval(successes: int, n: int) -> tuple[float, float] | None:
    """95% Wilson score interval for a binomial proportion.

    center = (p + z^2/(2n)) / (1 + z^2/n)
    half   = z / (1 + z^2/n) * sqrt(p(1-p)/n + z^2/(4n^2))
    """
    if n <= 0:
        return None
    p = successes / n
    z = _Z_95
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * (p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5
    return max(0.0, center - half), min(1.0, center + half)


def _paired_task_table(records: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """task_id -> {profile: mean pass fraction}; keeps only tasks verified for
    ALL profiles. Replicate attempts (same task+profile, e.g. multiple rounds)
    are AGGREGATED (averaged), never overwritten."""
    records = model_alone_records(records)
    per_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in records:
        verdict = r.get("verdict")
        if verdict not in ("pass", "task_fail"):
            continue
        per_pair[(r["task_id"], r["profile"]["name"])].append(1 if verdict == "pass" else 0)
    profile_count = len({r["profile"]["name"] for r in records})
    raw: dict[str, dict[str, float]] = defaultdict(dict)
    for (task_id, profile), vals in per_pair.items():
        raw[task_id][profile] = sum(vals) / len(vals)
    complete: dict[str, dict[str, float]] = {}
    for task_id, outcomes in raw.items():
        if len(outcomes) == profile_count:
            complete[task_id] = outcomes
    return complete


def paired_bootstrap(
    records: list[dict[str, Any]],
    *,
    n_draws: int = 10_000,
    seed: int = 0,
) -> dict[str, Any]:
    """Cluster-bootstrap intervals and P(A>B) for every profile pair.

    Returns {"n_tasks": int, "pairs": {"a|b": {"diff": float, "ci": [lo, hi],
    "p_a_gt_b": float}}}. Deterministic for a fixed seed.
    """
    table = _paired_task_table(records)
    if len(table) < 2:
        return {"n_tasks": len(table), "pairs": {}, "insufficient": True}
    profiles = sorted({p for outcomes in table.values() for p in outcomes})
    task_ids = sorted(table)
    draws: dict[str, list[float]] = {f"{a}|{b}": [] for i, a in enumerate(profiles) for b in profiles[i + 1:]}
    rng = random.Random(seed)
    for _ in range(n_draws):
        sample = [table[rng.choice(task_ids)] for _ in range(len(task_ids))]
        for key in draws:
            a, b = key.split("|")
            diff = sum(o.get(a, 0) - o.get(b, 0) for o in sample) / len(sample)
            draws[key].append(diff)
    pairs: dict[str, dict[str, Any]] = {}
    for key, values in draws.items():
        values.sort()
        lo, hi = values[int(0.025 * n_draws)], values[min(n_draws - 1, int(0.975 * n_draws))]
        mean = sum(values) / n_draws
        p_gt = sum(1 for v in values if v > 0) / n_draws
        pairs[key] = {
            "mean_diff": round(mean, 4),
            "ci": [round(lo, 4), round(hi, 4)],
            "p_a_gt_b": round(p_gt, 4),
            "tied": bool(lo == 0.0 and hi == 0.0),
        }
    return {"n_tasks": len(table), "pairs": pairs, "insufficient": False}


def render_uncertainty(records: list[dict[str, Any]]) -> list[str]:
    records = model_alone_records(records)
    lines: list[str] = []
    # Per-profile Wilson intervals over all verified attempts.
    per_profile: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in records:
        verdict = r.get("verdict")
        if verdict in ("pass", "task_fail"):
            bucket = per_profile[r["profile"]["name"]]
            bucket[0] += verdict == "pass"
            bucket[1] += 1
    if per_profile:
        lines.append("## Uncertainty — per profile (Wilson 95% on pass rate)")
        for name in sorted(per_profile):
            passes, n = per_profile[name]
            interval = wilson_interval(passes, n)
            if interval is None:
                continue
            lines.append(
                f"  {name}: {passes}/{n} pass -> 95% CI [{interval[0]:.2f}, {interval[1]:.2f}]"
            )
    boot = paired_bootstrap(records)
    if boot.get("insufficient"):
        lines.append("")
        lines.append(
            "## Uncertainty — paired differences: unavailable "
            f"(only {boot['n_tasks']} fully-verified paired tasks; need >= 2)"
        )
        return lines
    lines.append("")
    lines.append("## Uncertainty — paired differences (task-level bootstrap, 95% CI + P(beats))")
    for key in sorted(boot["pairs"]):
        entry = boot["pairs"][key]
        a, b = key.split("|")
        if entry.get("tied"):
            lines.append(
                f"  {a} vs {b}: identical outcomes on every paired task (tied — "
                f"add harder or more varied tasks to separate them)"
            )
            continue
        significant = entry["ci"][0] > 0 or entry["ci"][1] < 0
        if significant:
            winner = a if entry["mean_diff"] > 0 else b
            lines.append(
                f"  {a} vs {b}: diff={entry['mean_diff']:+.2f} CI "
                f"[{entry['ci'][0]:+.2f}, {entry['ci'][1]:+.2f}] excludes 0 -> "
                f"{winner} is better on this suite (P({a} beats {b})={entry['p_a_gt_b']:.2f})"
            )
        else:
            lines.append(
                f"  {a} vs {b}: diff={entry['mean_diff']:+.2f} CI "
                f"[{entry['ci'][0]:+.2f}, {entry['ci'][1]:+.2f}] includes 0 -> "
                f"no reliable difference yet; add tasks (P({a} beats {b})={entry['p_a_gt_b']:.2f})"
            )
    lines.append(
        f"  (bootstrap over {boot['n_tasks']} fully-verified paired tasks, 10,000 draws)"
    )
    return lines
