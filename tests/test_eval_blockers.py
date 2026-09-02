"""Regression tests for the advisor-identified merge blockers."""
from __future__ import annotations

from pathlib import Path

import pytest

from openrouter_agent_cli.eval.records import make_record, append_record
from openrouter_agent_cli.eval import sandbox
from openrouter_agent_cli.eval.uncertainty import paired_bootstrap, render_uncertainty
from openrouter_agent_cli.eval.runner import Profile, SuiteRunner
from openrouter_agent_cli.eval.suite import load_suite


def _rec(task, profile, verdict, run_id):
    r = make_record(run_id=run_id, suite_id="s", task_id=task, cluster_id=task,
                    profile_name=profile, profile_prompt="P", model="m",
                    transport="mock:script", workdir="/tmp/x", scheduled_index=0)
    r["verdict"] = verdict
    return r


def test_packaging_includes_eval_subpackage():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text()
    assert "openrouter_agent_cli.eval" in text, "eval subpackage missing from wheels"


def test_two_replicates_are_aggregated_not_overwritten():
    # t1: worker passes round1, fails round2 -> aggregate 0.5 (NOT overwritten
    # by the round-2 failure). t2: both pass (tie, contributes 0).
    records = [
        _rec("t1", "worker", "pass", "w1"),
        _rec("t1", "worker", "task_fail", "w2"),
        _rec("t1", "lazy", "task_fail", "l1"),
        _rec("t1", "lazy", "task_fail", "l2"),
        _rec("t2", "worker", "pass", "w3"),
        _rec("t2", "worker", "pass", "w4"),
        _rec("t2", "lazy", "pass", "l3"),
        _rec("t2", "lazy", "pass", "l4"),
    ]
    result = paired_bootstrap(records, seed=0)
    assert result["n_tasks"] == 2 and not result["insufficient"]
    entry = result["pairs"]["lazy|worker"]
    # diff = lazy - worker; t1 contributes -0.5, t2 contributes 0
    assert entry["mean_diff"] == pytest.approx(-0.25, abs=0.01)
    assert entry["ci"][0] == pytest.approx(-0.5)
    assert entry["ci"][1] == pytest.approx(0.0)


def test_real_model_attempt_fails_closed_without_acknowledgement(tmp_path, monkeypatch):
    suite = load_suite(Path(__file__).resolve().parents[1] / "eval_suites" / "coding_smoke_v1" / "suite.json")
    monkeypatch.delenv("AGENT_EVAL_ALLOW_HOST_EXECUTION", raising=False)
    monkeypatch.delenv("AGENT_EVAL_SANDBOX", raising=False)
    if sandbox.sandbox_available():
        runner = SuiteRunner(
            suite, [Profile(name="real", prompt="P")], eval_dir=tmp_path / "e"
        )
        assert runner._sandboxed is True
    else:
        with pytest.raises(ValueError, match="AGENT_EVAL_ALLOW_HOST_EXECUTION"):
            SuiteRunner(suite, [Profile(name="real", prompt="P")], eval_dir=tmp_path / "e")


def test_verdict_is_immutable_even_for_identical_verdict(tmp_path):
    from openrouter_agent_cli.eval.records import new_run_id, update_verdict, load_records
    path = tmp_path / "runs.jsonl"
    rec = make_record(run_id=new_run_id(), suite_id="s", task_id="t", cluster_id=None,
                      profile_name="p", profile_prompt="P", model="m",
                      transport="mock:script", workdir="/tmp/x", scheduled_index=0)
    append_record(path, rec)
    update_verdict(path, rec["run_id"], "pass", "first evidence")
    with pytest.raises(ValueError):
        update_verdict(path, rec["run_id"], "pass", "tampered evidence")
    assert load_records(path)[0]["verdict_evidence"] == "first evidence"


def test_p_value_orientation_reported_for_each_profile():
    records = [
        _rec("t1", "alpha", "pass", "a1"),
        _rec("t1", "zeta", "task_fail", "z1"),
        _rec("t2", "alpha", "pass", "a2"),
        _rec("t2", "zeta", "task_fail", "z2"),
    ]
    text = "\n".join(render_uncertainty(records))
    # alpha is alphabetically first; diff = alpha - zeta = +1 -> P(alpha beats zeta)=1
    line = next(l for l in text.splitlines() if "alpha vs zeta" in l)
    assert "P(alpha beats zeta)=1.00" in line


def test_leaderboard_probability_orientation_in_rendered_report():
    """The leaderboard (not just the uncertainty renderer) must label P(name
    beats leader) correctly for BOTH alphabetical orders, in the
    non-significant branch where the original bug lived."""
    from openrouter_agent_cli.eval.compare import render_report
    records = [
        _rec("t1", "alpha", "pass", "a1"),
        _rec("t1", "zeta", "pass", "z1"),
        _rec("t2", "alpha", "task_fail", "a2"),
        _rec("t2", "zeta", "task_fail", "z2"),
        _rec("t3", "alpha", "pass", "a3"),
        _rec("t3", "zeta", "task_fail", "z3"),
        _rec("t4", "alpha", "task_fail", "a4"),
        _rec("t4", "zeta", "pass", "z4"),
    ]
    report = render_report(records)
    zline = next(l for l in report.splitlines() if l.strip().startswith("2. zeta"))
    assert "P(zeta beats alpha)=0.63" in zline, zline
