"""Tests for the bounded verifier-assisted completion policy."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openrouter_agent_cli.cli import OpenRouterAgentCLI, ToolPermissionPolicy
from openrouter_agent_cli.eval.compare import render_leaderboard, render_report
from openrouter_agent_cli.eval.policy import (
    REPAIR_MESSAGE,
    VerifierAssistedPolicy,
    finalize_snapshot,
)
from openrouter_agent_cli.eval.records import (
    TREATMENT_MODEL_PLUS_POLICY,
    make_record,
)
from openrouter_agent_cli.eval.suite import load_suite, make_fresh_workspace
from openrouter_agent_cli.eval.transport import MockTransport
from openrouter_agent_cli.eval.verify import Verdict, run_verifier


SUITE_PATH = (
    Path(__file__).resolve().parents[1]
    / "eval_suites"
    / "coding_smoke_v1"
    / "suite.json"
)


def _write_greet_calls() -> list[dict]:
    return [
        {
            "name": "run_bash",
            "arguments": {
                "command": (
                    "printf '%b' 'def greet():\\n    return \"hello from greet\"\\n' "
                    "> greet.py"
                )
            },
        },
        {
            "name": "run_bash",
            "arguments": {
                "command": (
                    "printf '%b' 'from greet import greet\\nassert greet() == "
                    "\"hello from greet\"\\n' > test_greet.py"
                )
            },
        },
    ]


def _engine_and_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    responses: list[dict],
    *,
    max_turns: int = 10,
    verifier_command: str | None = None,
) -> tuple[OpenRouterAgentCLI, MockTransport, VerifierAssistedPolicy, object]:
    suite = load_suite(SUITE_PATH)
    task = suite.tasks[0]
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir()
    workspace = make_fresh_workspace(suite, task, base_dir=workspaces)
    monkeypatch.setenv("OPENROUTER_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    engine = OpenRouterAgentCLI(
        api_key="not-a-real-key",
        model="mock-model",
        session_id="policy-test",
        workdir=str(workspace),
        max_turns=max_turns,
        max_history_messages=64,
        command_timeout=30,
        tools_enabled=True,
        system_prompt="You are a test agent.",
        discovery_mode="off",
    )
    engine.non_interactive_mode = True
    engine.policy = ToolPermissionPolicy(allow={"*"})
    engine.one_shot_prompt = task.prompt
    transport = MockTransport({"responses": responses})
    engine.model_transport = transport
    policy = VerifierAssistedPolicy(
        verifier_command=verifier_command or task.verifier_command,
        workspace=workspace,
        trusted_cwd=suite.path.parent,
        timeout_s=task.verifier_timeout_s,
    )
    engine.checkpoint_hook = policy
    return engine, transport, policy, task


def _run_engine(
    engine: OpenRouterAgentCLI, policy: VerifierAssistedPolicy
) -> None:
    asyncio.run(engine.run())
    policy.finish_engine(engine.session_tokens["total_tokens"])


def test_incomplete_final_gets_one_repair_and_preserves_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine, transport, policy, task = _engine_and_policy(
        tmp_path,
        monkeypatch,
        [
            {"text": "initial completion"},
            {"tool_calls": _write_greet_calls()},
            {"text": "this response must not be requested"},
        ],
        max_turns=1,
    )
    _run_engine(engine, policy)

    # The last configured turn still grants exactly one extra model response.
    assert len(transport.requests) == 2
    messages = engine.messages
    repair_index = next(
        i for i, message in enumerate(messages) if message.get("content") == REPAIR_MESSAGE
    )
    assert messages[repair_index - 1]["role"] == "assistant"
    assert messages[repair_index + 1]["role"] == "assistant"
    assert all(message["role"] == "tool" for message in messages[repair_index + 2 :])
    assert "initial completion" not in capsys.readouterr().out

    state = policy.snapshot()
    assert [event["kind"] for event in state["checkpoints"]] == [
        "final_answer",
        "mutating_batch",
    ]
    assert [event["action"] for event in state["checkpoints"]] == ["repair", "stop"]
    assert state["repair_injections"] == 1
    assert state["added_tokens"] == 15
    assert all("evidence" not in event for event in state["checkpoints"])

    final = run_verifier(
        task.verifier_command,
        Path(engine.workdir),
        trusted_cwd=load_suite(SUITE_PATH).path.parent,
    )
    assert final.verdict == "pass"
    finalized = finalize_snapshot(state, final.verdict)
    assert finalized["probe_final_verifier_disagreed"] is False


def test_complete_mutating_batch_stops_before_next_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, transport, policy, task = _engine_and_policy(
        tmp_path,
        monkeypatch,
        [
            {"tool_calls": _write_greet_calls()},
            {"text": "the model should not be called again"},
        ],
    )
    _run_engine(engine, policy)

    assert len(transport.requests) == 1
    state = policy.snapshot()
    assert state["checkpoints"][0]["kind"] == "mutating_batch"
    assert state["checkpoints"][0]["probe_result"] == "complete"
    assert state["checkpoints"][0]["action"] == "stop"
    final = run_verifier(
        task.verifier_command,
        Path(engine.workdir),
        trusted_cwd=load_suite(SUITE_PATH).path.parent,
    )
    assert final.verdict == "pass"


def test_infrastructure_probe_continues_without_intervention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, transport, policy, task = _engine_and_policy(
        tmp_path,
        monkeypatch,
        [{"text": "accepted despite probe infrastructure failure"}],
        verifier_command='python3 -c "import sys; sys.exit(3)"',
    )
    _run_engine(engine, policy)

    assert len(transport.requests) == 1
    state = policy.snapshot()
    assert state["checkpoints"][0]["probe_result"] == "infrastructure_error"
    assert state["checkpoints"][0]["action"] == "continue"
    assert state["repair_injections"] == 0
    assert not any(message.get("content") == REPAIR_MESSAGE for message in engine.messages)
    assert state["probe_final_verifier_disagreed"] is None
    assert task.id == "greet"


def test_repeated_tool_forced_final_still_passes_through_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repeated = {
        "name": "run_bash",
        "arguments": {"command": "true"},
    }
    engine, transport, policy, _ = _engine_and_policy(
        tmp_path,
        monkeypatch,
        [
            {"tool_calls": [repeated]},
            {"tool_calls": [repeated]},
            {"text": "forced final"},
        ],
    )
    _run_engine(engine, policy)

    # First tool batch gets a repair; the repeated-call forced answer is then
    # checked as a final answer and consumes the single extra response budget.
    assert len(transport.requests) == 3
    state = policy.snapshot()
    assert [event["kind"] for event in state["checkpoints"]] == [
        "mutating_batch",
        "final_answer",
    ]
    assert [event["action"] for event in state["checkpoints"]] == ["repair", "stop"]
    assert state["repair_injections"] == 1


def test_second_incomplete_answer_cannot_inject_another_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, transport, policy, task = _engine_and_policy(
        tmp_path,
        monkeypatch,
        [{"text": "first incomplete"}, {"text": "second incomplete"}],
        max_turns=1,
    )
    _run_engine(engine, policy)

    assert len(transport.requests) == 2
    state = policy.snapshot()
    assert [event["action"] for event in state["checkpoints"]] == ["repair", "stop"]
    assert state["repair_injections"] == 1
    final = run_verifier(
        task.verifier_command,
        Path(engine.workdir),
        trusted_cwd=load_suite(SUITE_PATH).path.parent,
    )
    assert final.verdict == "task_fail"


def test_containment_flag_reaches_hidden_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[bool] = []

    def fake_verifier(*args, **kwargs) -> Verdict:
        seen.append(bool(kwargs["contained"]))
        return Verdict("pass", "secret evidence that must be discarded")

    monkeypatch.setattr("openrouter_agent_cli.eval.policy.run_verifier", fake_verifier)
    policy = VerifierAssistedPolicy(
        verifier_command="ignored",
        workspace=tmp_path,
        trusted_cwd=tmp_path,
        contained=True,
    )
    from openrouter_agent_cli.cli import RuntimeCheckpoint

    decision = asyncio.run(
        policy(
            RuntimeCheckpoint(
                sequence=1,
                kind="final_answer",
                turn=1,
                tool_names=(),
                observed_at=0.0,
                total_tokens=10,
            )
        )
    )
    assert seen == [True]
    assert decision.action == "stop"
    assert "secret evidence" not in json.dumps(policy.snapshot())


def test_assisted_records_are_excluded_from_ordinary_leaderboard() -> None:
    baseline = make_record(
        run_id="baseline",
        suite_id="s",
        task_id="t1",
        cluster_id="t1",
        profile_name="baseline",
        profile_prompt="P",
        model="m",
        transport="mock:script",
        workdir="/tmp/x",
        scheduled_index=0,
    )
    baseline["verdict"] = "task_fail"
    assisted = make_record(
        run_id="assisted",
        suite_id="s",
        task_id="t1",
        cluster_id="t1",
        profile_name="assisted",
        profile_prompt="P",
        model="m",
        transport="mock:script",
        workdir="/tmp/x",
        scheduled_index=1,
        treatment=TREATMENT_MODEL_PLUS_POLICY,
    )
    assisted["verdict"] = "pass"
    assisted["policy"] = {
        "repair_injections": 1,
        "probe_final_verifier_disagreed": False,
    }

    leaderboard = render_leaderboard([baseline, assisted])
    report = render_report([baseline, assisted])
    ordinary = report.split("## Verifier-assisted outcomes", 1)[0]
    assert "assisted" not in leaderboard
    assert "assisted" not in ordinary
    assert "assisted" in report
    assert "not included in ordinary leaderboard" in report
