"""Uncertainty layer tests: Wilson intervals, paired cluster bootstrap.

The key statistical property under test: the bootstrap resamples TASKS (the
paired clusters), not runs — so correlated outcomes within a task stay glued
together and the resulting intervals do not overstate precision.
"""
from __future__ import annotations

import pytest

from openrouter_agent_cli.eval.compare import render_report
from openrouter_agent_cli.eval.records import make_record
from openrouter_agent_cli.eval.uncertainty import (
    paired_bootstrap,
    render_uncertainty,
    wilson_interval,
)


def _record(run_id: str, task_id: str, profile: str, verdict: str) -> dict:
    rec = make_record(
        run_id=run_id, suite_id="s", task_id=task_id, cluster_id=task_id,
        profile_name=profile, profile_prompt="P", model="m",
        transport="mock:script", workdir="/tmp/x", scheduled_index=0,
    )
    rec["verdict"] = verdict
    return rec


def test_wilson_interval_is_wide_for_tiny_n() -> None:
    # 1/2 passes must NOT produce a tight 50% estimate:
    lo, hi = wilson_interval(1, 2)
    assert lo < 0.2 and hi > 0.8
    # 0/0 is undefined:
    assert wilson_interval(0, 0) is None
    # Large n converges near the point estimate:
    lo, hi = wilson_interval(600, 1000)
    assert 0.56 < lo < 0.60 and 0.62 < hi < 0.67


def test_bootstrap_dominance_is_decisive() -> None:
    # worker passes both tasks, lazy fails both -> P(worker beats lazy) = 1
    records = []
    for i, task in enumerate(("t1", "t2")):
        records.append(_record(f"w{i}", task, "worker", "pass"))
        records.append(_record(f"l{i}", task, "lazy", "task_fail"))
    result = paired_bootstrap(records, seed=0)
    assert not result["insufficient"] and result["n_tasks"] == 2
    # pairs are named alphabetically: "lazy|worker" diff = lazy - worker
    entry = result["pairs"]["lazy|worker"]
    assert entry["p_a_gt_b"] == 0.0            # lazy never beats worker
    assert entry["ci"] == [-1.0, -1.0]         # every draw: worker +1, lazy 0
    assert entry["mean_diff"] == -1.0


def test_bootstrap_50_50_split_is_inconclusive() -> None:
    # Each profile passes 2 and fails 2, on the SAME tasks -> no reliable
    # difference; the CI must include 0 and P roughly coin-flip.
    outcomes = {"t1": ("pass", "task_fail"), "t2": ("task_fail", "pass")}
    records = []
    for i, (task, (a, b)) in enumerate(outcomes.items()):
        records.append(_record(f"a{i}", task, "alpha", a))
        records.append(_record(f"b{i}", task, "beta", b))
    result = paired_bootstrap(records, seed=7)
    entry = result["pairs"]["alpha|beta"]
    assert entry["ci"][0] <= 0 <= entry["ci"][1]
    # Ties (both pass or both fail on a draw) count as non-wins, so with two
    # mirrored tasks P(alpha>beta) ~ P(both draws land on t1) ~ 0.25:
    assert 0.15 < entry["p_a_gt_b"] < 0.35


def test_incomplete_pairs_are_excluded_not_dropped_silently() -> None:
    # t2 has no verdict for beta; only t1 is fully verified -> n_tasks == 1
    # -> flagged insufficient (needs >= 2 paired tasks).
    records = [
        _record("a1", "t1", "alpha", "pass"),
        _record("b1", "t1", "beta", "task_fail"),
        _record("a2", "t2", "alpha", "pass"),
        # beta's t2 attempt not verified yet
    ]
    result = paired_bootstrap(records, seed=0)
    assert result["insufficient"] is True and result["n_tasks"] == 1


def test_render_includes_recommendation_language(tmp_path) -> None:
    records = []
    for i, task in enumerate(("t1", "t2", "t3")):
        records.append(_record(f"w{i}", task, "worker", "pass"))
        records.append(_record(f"l{i}", task, "lazy", "task_fail"))
    report = render_report(records)
    assert "Wilson 95%" in report
    assert "excludes 0" in report
    assert "worker is better on this suite" in report
    assert "no reliable difference yet" not in report


def test_report_of_unverified_data_says_so(tmp_path) -> None:
    records = [_record("a1", "t1", "alpha", "task_fail")]  # single unpaired verdict
    lines = render_uncertainty(records)
    assert any("unavailable" in line for line in lines)
