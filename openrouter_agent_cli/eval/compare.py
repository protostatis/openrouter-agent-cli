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

from .records import (
    load_records,
    model_alone_records,
    model_plus_policy_records,
    record_treatment,
)


def _outcome_counts(records: list[dict[str, Any]]) -> dict[str, Counter]:
    records = model_alone_records(records)
    by_profile: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        by_profile[r["profile"]["name"]][r.get("verdict") or "not_verified"] += 1
    return by_profile


def paired_matrix(records: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """task_id -> {profile_name: aggregate verdict} for shared tasks.

    Repeated attempts are aggregated rather than silently overwritten. A task
    with mixed pass/fail repeats is marked ``mixed`` and excluded from the
    integer paired tally below.
    """
    records = model_alone_records(records)
    by_task: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        by_task[r["task_id"]][r["profile"]["name"]].append(
            r.get("verdict") or "not_verified"
        )
    matrix: dict[str, dict[str, str]] = {}
    for task_id, profiles in by_task.items():
        matrix[task_id] = {}
        for profile, verdicts in profiles.items():
            if any(verdict == "not_verified" for verdict in verdicts):
                aggregate = "not_verified"
            elif all(verdict == "pass" for verdict in verdicts):
                aggregate = "pass"
            elif all(verdict == "task_fail" for verdict in verdicts):
                aggregate = "task_fail"
            else:
                aggregate = "mixed"
            matrix[task_id][profile] = aggregate
    return matrix


def paired_tally(records: list[dict[str, Any]]) -> dict[tuple[str, str], Counter]:
    """For each ordered profile pair (a, b) on shared tasks: how often a passed
    while b failed, b passed while a failed, both, neither."""
    matrix = paired_matrix(records)
    profiles = sorted({r["profile"]["name"] for r in records})
    tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for outcomes in matrix.values():
        if len(outcomes) < 2 or any(v not in {"pass", "task_fail"} for v in outcomes.values()):
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


def paired_treatment_tally(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], Counter]:
    """Compare unassisted and verifier-assisted attempts by task and repeat.

    Repeats have no separate field in the v2 record contract, so attempts are
    paired by their scheduled order within each task and treatment.  The runner
    creates exactly this order and the record audit checks its completeness.
    """
    baseline = model_alone_records(records)
    assisted = model_plus_policy_records(records)
    by_group: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in baseline + assisted:
        by_group[
            (
                record["task_id"],
                record["profile"]["name"],
                "baseline" if record_treatment(record) == "model_alone" else "assisted",
            )
        ].append(record)
    for rows in by_group.values():
        rows.sort(key=lambda record: record["scheduled_index"])

    baseline_profiles = sorted({r["profile"]["name"] for r in baseline})
    assisted_profiles = sorted({r["profile"]["name"] for r in assisted})
    task_ids = sorted({r["task_id"] for r in baseline} & {r["task_id"] for r in assisted})
    tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for baseline_profile in baseline_profiles:
        for assisted_profile in assisted_profiles:
            counter = tally[(baseline_profile, assisted_profile)]
            for task_id in task_ids:
                baseline_rows = by_group[(task_id, baseline_profile, "baseline")]
                assisted_rows = by_group[(task_id, assisted_profile, "assisted")]
                for left, right in zip(baseline_rows, assisted_rows):
                    outcomes = (left.get("verdict"), right.get("verdict"))
                    if not all(outcome in {"pass", "task_fail"} for outcome in outcomes):
                        continue
                    counter["paired_attempts"] += 1
                    if outcomes == ("pass", "pass"):
                        counter["both_pass"] += 1
                    elif outcomes == ("pass", "task_fail"):
                        counter["baseline_only_pass"] += 1
                    elif outcomes == ("task_fail", "pass"):
                        counter["assisted_only_pass"] += 1
                    else:
                        counter["neither_pass"] += 1
    return {key: value for key, value in tally.items() if value["paired_attempts"]}


def assisted_cost_table(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Resource totals for the separate verifier-assisted treatment report."""
    rows_by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in model_plus_policy_records(records):
        rows_by_profile[record["profile"]["name"]].append(record)
    table: dict[str, dict[str, Any]] = {}
    for name, rows in rows_by_profile.items():
        latencies = [(r.get("timing") or {}).get("latency_seconds") or 0 for r in rows]
        table[name] = {
            "attempts": len(rows),
            "total_tokens": sum(
                (r.get("usage") or {}).get("total_tokens") or 0 for r in rows
            ),
            "median_latency_s": sorted(latencies)[len(latencies) // 2] if latencies else None,
            "added_tokens": sum(
                int((r.get("policy") or {}).get("added_tokens") or 0) for r in rows
            ),
            "added_time_s": sum(
                float((r.get("policy") or {}).get("added_time_seconds") or 0.0)
                for r in rows
            ),
        }
    return table


def cost_table(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records = model_alone_records(records)
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


def leaderboard(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Profiles ranked by verified pass rate, with uncertainty vs the leader.

    Rows: profile, passes/n, Wilson 95% CI, P(this profile beats the current
    leader) from the paired task bootstrap. A profile "leads" only if its
    interval advantage is real on this suite; ties resolve to 'no reliable
    difference yet'. Suite-specific by construction.
    """
    from .uncertainty import paired_bootstrap, wilson_interval

    records = model_alone_records(records)
    per_profile: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in records:
        verdict = r.get("verdict")
        if verdict in ("pass", "task_fail"):
            bucket = per_profile[r["profile"]["name"]]
            bucket[0] += verdict == "pass"
            bucket[1] += 1
    if not per_profile:
        return []
    boot = paired_bootstrap(records)

    def sort_key(name: str) -> tuple[float, float]:
        passes, n = per_profile[name]
        interval = wilson_interval(passes, n) or (0.0, 0.0)
        return (-(passes / n if n else 0.0), -(interval[0] + interval[1]) / 2)

    ranked = sorted(per_profile, key=sort_key)
    leader = ranked[0]
    rows: list[dict[str, Any]] = []
    for name in ranked:
        passes, n = per_profile[name]
        interval = wilson_interval(passes, n)
        if name == leader:
            comparison = "leader (best verified pass rate on this suite)"
        else:
            key = "|".join(sorted((name, leader)))
            entry = (boot.get("pairs") or {}).get(key)
            if entry is None:
                comparison = "insufficient paired data vs leader"
            elif entry.get("tied"):
                comparison = "tied with leader on every paired task"
            else:
                significant = entry["ci"][0] > 0 or entry["ci"][1] < 0
                # entry["p_a_gt_b"] is P(first-in-key beats second-in-key).
                if name == key.split("|")[0]:
                    p_name_beats_leader = entry["p_a_gt_b"]
                else:
                    p_name_beats_leader = 1.0 - entry["p_a_gt_b"]
                if significant:
                    better = p_name_beats_leader > 0.5
                    comparison = (
                        (f"significantly AHEAD of leader (bootstrap favors {name}; "
                         f"leader is stale)" if better else
                         f"significantly behind leader (bootstrap favors {leader})")
                        + f" — P({name} beats {leader})={p_name_beats_leader:.2f}"
                    )
                else:
                    comparison = (
                        f"no reliable difference vs leader "
                        f"(P({name} beats {leader})={p_name_beats_leader:.2f}); add tasks"
                    )
        rows.append(
            {
                "profile": name,
                "passes": passes,
                "attempts": n,
                "pass_rate": round(passes / n, 3) if n else None,
                "wilson_95": interval,
                "comparison": comparison,
            }
        )
    return rows


def render_leaderboard(records: list[dict[str, Any]]) -> str:
    rows = leaderboard(records)
    if not rows:
        return "## Leaderboard: no verified attempts yet"
    lines = ["## Leaderboard (this suite only)", "(ranked by verified pass rate; uncertainty vs the leader)"]
    for i, row in enumerate(rows, 1):
        interval = row["wilson_95"]
        ci = f"[{interval[0]:.2f}, {interval[1]:.2f}]" if interval else "n/a"
        lines.append(
            f"  {i}. {row['profile']}: {row['passes']}/{row['attempts']} "
            f"(95% CI {ci}) — {row['comparison']}"
        )
    return "\n".join(lines)


def render_report(records: list[dict[str, Any]]) -> str:
    all_records = records
    assisted_records = model_plus_policy_records(all_records)
    records = model_alone_records(all_records)
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
    lines.append("")
    lines.append(render_leaderboard(records))
    if assisted_records:
        lines.append("")
        lines.append("## Verifier-assisted outcomes (not included in ordinary leaderboard)")
        lines.append(
            "(these rows measure the completion policy, not ordinary model performance)"
        )
        by_profile: dict[str, Counter] = defaultdict(Counter)
        for record in assisted_records:
            by_profile[record["profile"]["name"]][
                record.get("verdict") or "not_verified"
            ] += 1
        for name, counter in sorted(by_profile.items()):
            repairs = sum(
                int((record.get("policy") or {}).get("repair_injections") or 0)
                for record in assisted_records
                if record["profile"]["name"] == name
            )
            disagreements = sum(
                bool((record.get("policy") or {}).get("probe_final_verifier_disagreed"))
                for record in assisted_records
                if record["profile"]["name"] == name
            )
            added_tokens = sum(
                int((record.get("policy") or {}).get("added_tokens") or 0)
                for record in assisted_records
                if record["profile"]["name"] == name
            )
            added_time = sum(
                float((record.get("policy") or {}).get("added_time_seconds") or 0.0)
                for record in assisted_records
                if record["profile"]["name"] == name
            )
            lines.append(
                f"  {name}: pass={counter['pass']} task_fail={counter['task_fail']} "
                f"infra={counter['infrastructure_error']} unverified={counter['not_verified']} "
                f"repairs={repairs} added_tokens={added_tokens} "
                f"added_time={added_time:.3f}s probe_final_disagreements={disagreements}"
            )
        lines.append("")
        lines.append("## Verifier-assisted resource use")
        lines.append("(total model tokens and policy-attributable repair overhead)")
        for name, entry in sorted(assisted_cost_table(all_records).items()):
            lines.append(
                f"  {name}: attempts={entry['attempts']} tokens={entry['total_tokens']} "
                f"median_latency={entry['median_latency_s']}s "
                f"added_tokens={entry['added_tokens']} "
                f"added_time={entry['added_time_s']:.3f}s"
            )
        policy_tally = paired_treatment_tally(all_records)
        if policy_tally:
            lines.append("")
            lines.append("## Paired outcomes: unassisted baseline vs verifier-assisted policy")
            lines.append(
                "(matching task/repeat attempts; assisted rows remain outside the ordinary leaderboard)"
            )
            for (baseline, assisted), counter in sorted(policy_tally.items()):
                lines.append(
                    f"  {baseline} vs {assisted}: baseline_only={counter['baseline_only_pass']} "
                    f"assisted_only={counter['assisted_only_pass']} "
                    f"both={counter['both_pass']} neither={counter['neither_pass']}"
                )
    return "\n".join(lines)


def report_from_file(path: Path) -> str:
    return render_report(load_records(path))
