"""Integrity checks for completed evaluation records.

The audit checks campaign structure and treatment separation without inspecting
model text or private verifier evidence.  It is deliberately independent of
the comparison report so a malformed campaign cannot look healthy merely
because its summary renders successfully.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .records import (
    RECORDS_SCHEMA_VERSION,
    TREATMENT_MODEL_ALONE,
    TREATMENT_MODEL_PLUS_POLICY,
    load_records,
)

VALID_TREATMENTS = {TREATMENT_MODEL_ALONE, TREATMENT_MODEL_PLUS_POLICY}
VALID_VERDICTS = {"pass", "task_fail", "infrastructure_error"}


class RecordAuditError(ValueError):
    """Raised when a completed campaign fails a structural integrity check."""


def audit_records(
    records: list[dict[str, Any]],
    *,
    expected_task_ids: Iterable[str] | None = None,
    expected_profile_names: Iterable[str] | None = None,
    expected_repeats: int | None = None,
    require_containment: bool = False,
) -> list[str]:
    """Return human-readable integrity failures for a completed campaign.

    ``expected_task_ids`` and ``expected_profile_names`` are optional so this
    can audit an existing file without a suite object.  When both are supplied,
    ``expected_repeats`` checks the complete paired schedule.  Real OpenRouter
    rows must use Bubblewrap when ``require_containment`` is true; offline mock
    rows are not required to carry that sandbox marker.
    """
    issues: list[str] = []
    task_ids = list(expected_task_ids) if expected_task_ids is not None else None
    profile_names = (
        list(expected_profile_names) if expected_profile_names is not None else None
    )
    task_set = set(task_ids or ())
    profile_set = set(profile_names or ())

    if task_ids is not None and len(task_set) != len(task_ids):
        issues.append("expected task ids contain duplicates")
    if profile_names is not None and len(profile_set) != len(profile_names):
        issues.append("expected profile names contain duplicates")
    if expected_repeats is not None and expected_repeats < 1:
        issues.append("expected_repeats must be at least 1")

    if not records:
        issues.append("no records found")

    expected_count = None
    if task_ids is not None and profile_names is not None and expected_repeats is not None:
        expected_count = len(task_set) * len(profile_set) * expected_repeats
        if len(records) != expected_count:
            issues.append(f"expected {expected_count} records, found {len(records)}")

    run_ids: list[str] = []
    workspaces: list[str] = []
    schedule_indexes: list[int] = []
    pair_counts: Counter[tuple[str, str]] = Counter()

    for position, record in enumerate(records):
        label = f"record {position}"
        if not isinstance(record, dict):
            issues.append(f"{label} is not an object")
            continue

        if record.get("schema_version") != RECORDS_SCHEMA_VERSION:
            issues.append(f"{label} has unexpected schema_version")

        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            issues.append(f"{label} has no run_id")
        else:
            run_ids.append(run_id)

        task_id = record.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            issues.append(f"{label} has no task_id")
        elif task_set and task_id not in task_set:
            issues.append(f"{label} has unexpected task_id {task_id!r}")

        profile = record.get("profile")
        profile_name = profile.get("name") if isinstance(profile, dict) else None
        if not isinstance(profile_name, str) or not profile_name:
            issues.append(f"{label} has no profile name")
        elif profile_set and profile_name not in profile_set:
            issues.append(f"{label} has unexpected profile {profile_name!r}")

        treatment = record.get("treatment")
        if treatment not in VALID_TREATMENTS:
            issues.append(f"{label} has invalid treatment {treatment!r}")
        elif isinstance(task_id, str) and isinstance(profile_name, str):
            pair_counts[(task_id, profile_name)] += 1

        verdict = record.get("verdict")
        if verdict not in VALID_VERDICTS:
            issues.append(f"{label} is not finally verified: {verdict!r}")

        workspace = record.get("workspace")
        if not isinstance(workspace, str) or not workspace:
            issues.append(f"{label} has no workspace")
        else:
            workspaces.append(workspace)

        scheduled_index = record.get("scheduled_index")
        if not isinstance(scheduled_index, int):
            issues.append(f"{label} has no integer scheduled_index")
        else:
            schedule_indexes.append(scheduled_index)

        engine = record.get("engine")
        if not isinstance(engine, dict):
            issues.append(f"{label} has no engine receipt")
            engine = {}
        transport = record.get("transport")
        if require_containment and transport == "openrouter":
            if engine.get("sandbox") != "bubblewrap":
                issues.append(f"{label} real-model attempt was not Bubblewrap-contained")

        policy = record.get("policy")
        if treatment == TREATMENT_MODEL_PLUS_POLICY:
            if not isinstance(policy, dict):
                issues.append(f"{label} assisted treatment has no policy receipt")
            elif require_containment and transport == "openrouter":
                if policy.get("contained") is not True:
                    issues.append(f"{label} policy receipt is not marked contained")
        elif treatment == TREATMENT_MODEL_ALONE and policy is not None:
            issues.append(f"{label} unassisted treatment contains a policy receipt")

    for value, description in (
        (run_ids, "run_id"),
        (workspaces, "workspace"),
        (schedule_indexes, "scheduled_index"),
    ):
        duplicates = [item for item, count in Counter(value).items() if count > 1]
        if duplicates:
            issues.append(f"duplicate {description}: {duplicates[0]!r}")

    if task_set and profile_set and expected_repeats is not None:
        for task_id in sorted(task_set):
            for profile_name in sorted(profile_set):
                count = pair_counts[(task_id, profile_name)]
                if count != expected_repeats:
                    issues.append(
                        f"pair {task_id!r}/{profile_name!r}: expected "
                        f"{expected_repeats} records, found {count}"
                    )

    return issues


def assert_audited(records: list[dict[str, Any]], **kwargs: Any) -> None:
    """Raise ``RecordAuditError`` unless ``records`` pass ``audit_records``."""
    issues = audit_records(records, **kwargs)
    if issues:
        raise RecordAuditError("evaluation record audit failed: " + "; ".join(issues))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, help="completed JSONL record file")
    parser.add_argument("--task", action="append", dest="tasks", help="expected task id")
    parser.add_argument(
        "--profile", action="append", dest="profiles", help="expected profile name"
    )
    parser.add_argument("--repeats", type=int, default=None)
    parser.add_argument("--require-containment", action="store_true")
    args = parser.parse_args(argv)

    issues = audit_records(
        load_records(Path(args.records)),
        expected_task_ids=args.tasks,
        expected_profile_names=args.profiles,
        expected_repeats=args.repeats,
        require_containment=args.require_containment,
    )
    if issues:
        print("INVALID evaluation records:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("VALID evaluation records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
