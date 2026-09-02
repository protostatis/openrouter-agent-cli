"""End-to-end acceptance test: the REAL engine, a mock brain, real hands.

One coding task runs through ``OpenRouterAgentCLI`` (headless one-shot path,
identical to ``--prompt`` mode) with a scripted MockTransport playing the
model. The mock's tool calls are executed FOR REAL by the engine (real bash in
a disposable workspace). A host-side verifier then grades the workspace. This
is the acceptance test from docs/eval-integration.md; no network, no tokens.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openrouter_agent_cli.eval.records import load_records
from openrouter_agent_cli.eval.records import TREATMENT_MODEL_PLUS_POLICY
from openrouter_agent_cli.eval.runner import Profile, SuiteRunner
from openrouter_agent_cli.eval.suite import load_suite

# A scripted "model" that actually does the work through the real tool layer:
# write the files via run_bash heredocs, then answer. The engine executes the
# tool calls; the mock never touches the filesystem itself.
_MOCK_DOES_WORK = {
    "responses": [
        {"tool_calls": [
            {"name": "run_bash",
             "arguments": {"command":
                           "printf '%b' 'def greet():\\n    return \"hello from greet\"\\n' > greet.py"}},
        ]},
        {"tool_calls": [
            {"name": "run_bash",
             "arguments": {"command":
                           "printf '%b' 'from greet import greet\\nassert greet() == \"hello from greet\"\\n' > test_greet.py"}},
        ]},
        {"text": "Created greet.py and test_greet.py."},
    ]
}

_MOCK_LAZY = {
    "responses": [
        {"text": "I would create greet.py with a greet function. Done!"},
    ]
}


@pytest.fixture()
def suite(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[1] / "eval_suites" / "coding_smoke_v1"
    target = tmp_path / "suites" / "coding_smoke_v1"
    target.parent.mkdir(parents=True)
    import shutil
    shutil.copytree(source, target)
    return target / "suite.json"


def test_mock_brain_real_hands_end_to_end(tmp_path: Path, suite: Path) -> None:
    loaded = load_suite(suite)
    runner = SuiteRunner(
        loaded,
        [Profile(name="worker", prompt="You are a coding agent.", mock_script=dict(_MOCK_DOES_WORK))],
        eval_dir=tmp_path / "eval",
    )
    records = asyncio.run(runner.run_and_verify())

    # One profile x every suite task = one attempt per task, nothing dropped.
    assert len(records) == len(loaded.tasks)
    by_task = {r["task_id"]: r for r in records}
    record = by_task["greet"]
    # The mock brain's tool calls were executed for real by the engine:
    assert record["engine"]["error"] is None
    tool_names = [tc["name"] for tc in record["tool_calls"]]
    assert tool_names.count("run_bash") == 2
    assert all(tc["ok"] for tc in record["tool_calls"])
    # And the host-side verifier graded the real workspace:
    assert record["verdict"] == "pass"
    # The second task has no matching mock script -> the agent does nothing ->
    # task_fail (its failure), never infrastructure_error:
    assert by_task["sumlib"]["verdict"] == "task_fail"
    # Records are factual and append-only readable:
    on_disk = load_records(runner.runs_path)
    assert len(on_disk) == len(loaded.tasks)
    assert all(r["verdict"] in ("pass", "task_fail") for r in on_disk)
    # The mock saw the real request shape (system prompt + tools):
    # (transport instance is per-attempt; check the engine received tools)
    assert record["transport"] == "mock:script"


def test_lazy_agent_fails_verifier_not_infra(tmp_path: Path, suite: Path) -> None:
    """An agent that does nothing gets task_fail, never infrastructure_error."""
    loaded = load_suite(suite)
    runner = SuiteRunner(
        loaded,
        [Profile(name="lazy", prompt="You are a coding agent.", mock_script=dict(_MOCK_LAZY))],
        eval_dir=tmp_path / "eval",
    )
    records = asyncio.run(runner.run_and_verify())
    assert records[0]["verdict"] == "task_fail"
    assert records[0]["verdict_evidence"] == "missing greet.py"


def test_paired_counterbalanced_schedule_and_report(tmp_path: Path, suite: Path) -> None:
    from openrouter_agent_cli.eval.compare import paired_tally, render_report

    loaded = load_suite(suite)
    profiles = [
        Profile(name="worker", prompt="P1", mock_script=dict(_MOCK_DOES_WORK)),
        Profile(name="lazy", prompt="P2", mock_script=dict(_MOCK_LAZY)),
    ]
    runner = SuiteRunner(loaded, profiles, eval_dir=tmp_path / "eval")
    schedule = runner.build_schedule()
    # tasks x profiles, paired task-major with rotation:
    assert len(schedule) == len(loaded.tasks) * 2
    assert [p.name for _, p, _ in schedule[:2]] == ["worker", "lazy"]  # task 0
    assert [p.name for _, p, _ in schedule[2:4]] == ["lazy", "worker"]  # rotated

    records = asyncio.run(runner.run_and_verify())
    verdicts = {(r["task_id"], r["profile"]["name"]): r["verdict"] for r in records}
    assert verdicts[("greet", "worker")] == "pass"
    assert verdicts[("greet", "lazy")] == "task_fail"
    tally = paired_tally(records)
    assert tally[("lazy", "worker")]["a_only_pass"] == 0          # lazy never passes
    assert tally[("lazy", "worker")]["b_only_pass"] == 1          # worker: greet only
    # every other task defeats both profiles (the mock only knows greet):
    assert tally[("lazy", "worker")]["neither_pass"] == len(loaded.tasks) - 1
    report = render_report(records)
    assert "worker" in report and "task_fail" in report
    assert "not a general ranking" in report  # honesty disclaimer present


def test_repeated_schedule_rotates_profile_order(tmp_path: Path, suite: Path) -> None:
    loaded = load_suite(suite)
    profiles = [
        Profile(name="worker", prompt="P1", mock_script=dict(_MOCK_DOES_WORK)),
        Profile(name="lazy", prompt="P2", mock_script=dict(_MOCK_LAZY)),
    ]
    runner = SuiteRunner(loaded, profiles, eval_dir=tmp_path / "eval", repeats=2)
    schedule = runner.build_schedule()

    assert len(schedule) == len(loaded.tasks) * len(profiles) * 2
    assert [p.name for _, p, _ in schedule[:2]] == ["worker", "lazy"]
    repeat_start = len(loaded.tasks) * len(profiles)
    assert [p.name for _, p, _ in schedule[repeat_start : repeat_start + 2]] == [
        "lazy",
        "worker",
    ]


def test_duplicate_run_id_verdict_is_immutable(tmp_path: Path, suite: Path) -> None:
    from openrouter_agent_cli.eval.records import (
        append_record, load_records, make_record, new_run_id, update_verdict,
    )

    loaded = load_suite(suite)
    runner = SuiteRunner(
        loaded,
        [Profile(name="worker", prompt="P", mock_script=dict(_MOCK_DOES_WORK))],
        eval_dir=tmp_path / "eval",
    )
    runner.runs_path.parent.mkdir(parents=True, exist_ok=True)
    rid = new_run_id()
    record = make_record(
        run_id=rid, suite_id="s", task_id="t", cluster_id=None,
        profile_name="p", profile_prompt="P", model="m", transport="mock:script",
        workdir="/tmp/x", scheduled_index=0,
    )
    append_record(runner.runs_path, record)
    update_verdict(runner.runs_path, rid, "pass", "evidence")
    with pytest.raises(ValueError):
        update_verdict(runner.runs_path, rid, "task_fail", "cheating")
    assert load_records(runner.runs_path)[0]["verdict"] == "pass"


def test_run_suite_script(tmp_path: Path, suite: Path) -> None:
    """The CLI entry point runs a full mock campaign and prints a report."""
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable, str(repo / "scripts" / "run_suite.py"),
            "--suite", str(suite),
            "--profile", f"worker={repo / 'eval_suites' / 'mock_worker.json'}",
            "--eval-dir", str(tmp_path / "eval"),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "pass=2" in proc.stdout          # both tasks pass
    assert "not a general ranking" in proc.stdout


def test_verifier_assisted_runner_records_policy_and_final_agreement(
    tmp_path: Path, suite: Path
) -> None:
    loaded = load_suite(suite)
    runner = SuiteRunner(
        loaded,
        [
            Profile(
                name="assisted",
                prompt="You are a coding agent.",
                mock_script=Path(__file__).resolve().parents[1]
                / "eval_suites"
                / "mock_worker.json",
                treatment=TREATMENT_MODEL_PLUS_POLICY,
            )
        ],
        eval_dir=tmp_path / "eval",
    )
    records = asyncio.run(runner.run_and_verify())

    assert len(records) == len(loaded.tasks)
    assert all(r["treatment"] == TREATMENT_MODEL_PLUS_POLICY for r in records)
    verdicts = {r["task_id"]: r["verdict"] for r in records}
    assert verdicts["greet"] == "pass"
    assert verdicts["sumlib"] == "pass"
    assert sum(verdict == "pass" for verdict in verdicts.values()) == 2
    assert all(r["policy"]["name"] == "verify-before-completion" for r in records)
    assert all(r["policy"]["probe_final_verifier_disagreed"] is False for r in records)
    assert all(
        r["policy"]["repair_injections"] == (0 if r["verdict"] == "pass" else 1)
        for r in records
    )
    on_disk = load_records(runner.runs_path)
    assert on_disk[0]["policy"]["probe_final_verifier_disagreed"] is False


def test_eval_module_rejects_missing_profile(tmp_path: Path, suite: Path) -> None:
    """The public module entry point gives a useful offline-safe error."""
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "openrouter_agent_cli.eval.cli",
            "--suite",
            str(suite),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "at least one --profile is required" in proc.stderr


def test_engine_failure_is_graded_infrastructure_not_task_fail(
    tmp_path: Path, suite: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider/engine failure must never be graded as an ordinary model
    task failure; the workspace verifier must not even run for it."""
    from openrouter_agent_cli.eval.records import append_record, make_record, new_run_id
    from openrouter_agent_cli.eval.verify import Verdict

    loaded = load_suite(suite)
    runner = SuiteRunner(
        loaded,
        [Profile(name="worker", prompt="P", mock_script=dict(_MOCK_DOES_WORK))],
        eval_dir=tmp_path / "eval",
    )
    runner.runs_path.parent.mkdir(parents=True, exist_ok=True)
    record = make_record(
        run_id=new_run_id(), suite_id="s", task_id=loaded.tasks[0].id,
        cluster_id=loaded.tasks[0].cluster_id, profile_name="p",
        profile_prompt="P", model="m", transport="openrouter",
        workdir=str(tmp_path), scheduled_index=0,
    )
    record["engine"] = {"error": "engine terminal_status=provider_error"}
    append_record(runner.runs_path, record)

    verifier_calls: list[str] = []

    def _boom_verifier(*args, **kwargs) -> Verdict:
        verifier_calls.append("called")
        return Verdict("pass", "must not happen")

    monkeypatch.setattr("openrouter_agent_cli.eval.runner.run_verifier", _boom_verifier)
    runner.verify_all([record])

    assert verifier_calls == []
    assert record["verdict"] == "infrastructure_error"
    assert "provider_error" in record["verdict_evidence"]


def test_unknown_assisted_profile_is_rejected(tmp_path: Path, suite: Path) -> None:
    from openrouter_agent_cli.eval.cli import _parse_profiles

    with pytest.raises(SystemExit):
        _parse_profiles(
            ["worker=some/path.json"],
            None,
            assisted_profiles={"worker", "ghost"},
        )
