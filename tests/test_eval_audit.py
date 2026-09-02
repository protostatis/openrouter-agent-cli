"""Structural audits for completed evaluation campaigns."""
from __future__ import annotations

from typing import Any

from openrouter_agent_cli.eval.audit import audit_records
from openrouter_agent_cli.eval.records import (
    TREATMENT_MODEL_ALONE,
    TREATMENT_MODEL_PLUS_POLICY,
    make_record,
)


def _record(
    *, task: str, profile: str, treatment: str, index: int, run_id: str
) -> dict[str, Any]:
    record = make_record(
        run_id=run_id,
        suite_id="suite",
        task_id=task,
        cluster_id=None,
        profile_name=profile,
        profile_prompt=profile,
        model="model",
        transport="openrouter",
        workdir=f"/tmp/{run_id}",
        scheduled_index=index,
        treatment=treatment,
    )
    record["engine"].update(
        {"sandbox": "bubblewrap", "session_dir": f"session-{run_id}"}
    )
    record["verdict"] = "pass"
    if treatment == TREATMENT_MODEL_PLUS_POLICY:
        record["policy"] = {"contained": True}
    return record


def test_complete_paired_campaign_passes_audit() -> None:
    records = []
    index = 0
    for repeat in range(2):
        for task in ("task-a", "task-b"):
            for profile, treatment in (
                ("baseline", TREATMENT_MODEL_ALONE),
                ("assisted", TREATMENT_MODEL_PLUS_POLICY),
            ):
                records.append(
                    _record(
                        task=task,
                        profile=profile,
                        treatment=treatment,
                        index=index,
                        run_id=f"run-{index}",
                    )
                )
                index += 1

    assert audit_records(
        records,
        expected_task_ids=("task-a", "task-b"),
        expected_profile_names=("baseline", "assisted"),
        expected_repeats=2,
        require_containment=True,
    ) == []


def test_audit_rejects_duplicates_missing_pairs_and_policy_leak() -> None:
    records = [
        _record(
            task="task-a",
            profile="baseline",
            treatment=TREATMENT_MODEL_ALONE,
            index=0,
            run_id="same",
        ),
        _record(
            task="task-a",
            profile="assisted",
            treatment=TREATMENT_MODEL_PLUS_POLICY,
            index=0,
            run_id="same",
        ),
    ]
    records[0]["policy"] = {"contained": True}

    issues = audit_records(
        records,
        expected_task_ids=("task-a", "task-b"),
        expected_profile_names=("baseline", "assisted"),
        expected_repeats=1,
        require_containment=True,
    )

    assert any("expected 4 records" in issue for issue in issues)
    assert any("duplicate run_id" in issue for issue in issues)
    assert any("duplicate scheduled_index" in issue for issue in issues)
    assert any("policy receipt" in issue for issue in issues)
    assert any("pair 'task-b'" in issue for issue in issues)
