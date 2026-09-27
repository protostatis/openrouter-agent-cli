"""Run the frozen tool-profile comparison bank (core4 vs full7).

The comparison is defined by ``eval_suites/tool_profile_bank_v1/bank.json``:
40 distinct tasks, one matched pair per task, identical prompt bytes, model,
turn budget, and verifier for both arms. The only intended difference is the
tool surface the engine exposes (seven tools vs the four coding-loop tools).

Features:
- Validates the bank manifest against the suite files before anything runs.
- Deterministic seeded task order (recorded in the bank), so provider drift
  over time affects both arms equally.
- Resume-safe: completed pairs are detected from prior records and skipped,
  so an interrupted batch can continue without duplicating attempts.
- Writes one summary JSON with the paired outcome and the frozen decision
  rules applied.

Dry-run mode validates everything and prints the schedule without any model
calls::

    uv run python scripts/run_tool_profile_bank.py --dry-run

Real run (explicit host-execution acknowledgement is required on macOS)::

    AGENT_EVAL_ALLOW_HOST_EXECUTION=1 uv run python \
        scripts/run_tool_profile_bank.py --pairs 40
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from openrouter_agent_cli.cli import _load_dotenv  # noqa: E402

_load_dotenv(None)

from openrouter_agent_cli.eval.records import load_records  # noqa: E402
from openrouter_agent_cli.eval.runner import Profile, SuiteRunner  # noqa: E402
from openrouter_agent_cli.eval.suite import Suite, load_suite  # noqa: E402

BANK_DEFAULT = REPO_ROOT / "eval_suites" / "tool_profile_bank_v1" / "bank.json"
ARM_A = "full7"
ARM_B = "core4"


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_bank(path: Path) -> dict:
    bank = json.loads(path.read_text(encoding="utf-8"))
    if bank.get("schema_version") != "tool-profile-bank-v1":
        _fail(f"{path} is not a tool-profile-bank-v1 manifest")
    return bank


def validate_bank(bank: dict, repo_root: Path) -> dict[str, Suite]:
    """Load every referenced suite and confirm the bank's task list matches."""
    suites: dict[str, Suite] = {}
    total = 0
    for suite_name, task_ids in bank["tasks"].items():
        suite_path = repo_root / "eval_suites" / suite_name / "suite.json"
        if not suite_path.is_file():
            _fail(f"bank references missing suite: {suite_path}")
        suite = load_suite(suite_path)
        available = {t.id for t in suite.tasks}
        missing = [tid for tid in task_ids if tid not in available]
        if missing:
            _fail(f"suite {suite_name} is missing bank tasks: {missing}")
        suites[suite_name] = suite
        total += len(task_ids)
    expected = int(bank.get("pairs", 0))
    if total != expected:
        _fail(f"bank lists {total} tasks but declares pairs={expected}")
    # Prompt freeze: the exact prompt bytes are part of the comparison.
    prompt_path = repo_root / bank["controls"]["prompt_file"]
    digest = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if digest != bank["controls"]["prompt_sha256"]:
        _fail(
            "control prompt changed since the bank was frozen "
            f"(expected {bank['controls']['prompt_sha256']}, found {digest})"
        )
    return suites


def seeded_order(bank: dict) -> list[tuple[str, str]]:
    """Deterministic global task order: (suite_name, task_id) pairs."""
    entries = [
        (suite_name, task_id)
        for suite_name, task_ids in bank["tasks"].items()
        for task_id in task_ids
    ]
    random.Random(int(bank["seed"])).shuffle(entries)
    return entries


def existing_bank_records(eval_dir: Path, bank_task_ids: set[str]) -> dict[str, dict]:
    """Collect already-recorded attempts for bank tasks (resume support)."""
    found: dict[str, dict] = {}
    runs_dir = eval_dir / "runs"
    if not runs_dir.is_dir():
        return found
    for runs_file in sorted(runs_dir.glob("*.jsonl")):
        try:
            records = load_records(runs_file)
        except Exception:
            continue
        for record in records:
            task_id = str(record.get("task_id") or "")
            if task_id in bank_task_ids and record.get("verdict"):
                # Keep the first completed verdict per (task, arm).
                arm = str((record.get("profile") or {}).get("name") or "")
                found.setdefault(f"{task_id}::{arm}", record)
    return found


def run_batch(
    bank: dict,
    suites: dict[str, Suite],
    order: list[tuple[str, str]],
    pairs: int,
    eval_dir: Path,
) -> list[dict]:
    """Run the next incomplete pairs in seeded order; return new records."""
    controls = bank["controls"]
    prompt_path = REPO_ROOT / controls["prompt_file"]
    prompt = prompt_path.read_text(encoding="utf-8")
    model = controls["model"]
    profiles = [
        Profile(name=ARM_A, prompt=prompt, model=model,
                tool_profile=controls.get("arm_a_profile", ARM_A)),
        Profile(name=ARM_B, prompt=prompt, model=model,
                tool_profile=controls.get("arm_b_profile", ARM_B)),
    ]

    bank_task_ids = {tid for _, tid in order}
    done = existing_bank_records(eval_dir, bank_task_ids)
    needed: list[tuple[str, str]] = []
    for suite_name, task_id in order:
        if f"{task_id}::{ARM_A}" in done and f"{task_id}::{ARM_B}" in done:
            continue
        needed.append((suite_name, task_id))
        if len(needed) >= pairs:
            break
    if not needed:
        print("All requested pairs are already complete; nothing to run.")
        return []

    # Interleave arms task-major (SuiteRunner pairs per task) and process
    # suites in the global seeded order of their first needed task.
    by_suite: dict[str, list[tuple[int, str]]] = {}
    global_index = {entry: i for i, entry in enumerate(order)}
    for suite_name, task_id in needed:
        by_suite.setdefault(suite_name, []).append(
            (global_index[(suite_name, task_id)], task_id)
        )
    suite_order = sorted(by_suite, key=lambda s: min(i for i, _ in by_suite[s]))

    all_records: list[dict] = []
    for suite_name in suite_order:
        chunk = [tid for _, tid in sorted(by_suite[suite_name])]
        source = suites[suite_name]
        selected = Suite(
            suite_id=source.suite_id,
            path=source.path,
            tasks=[t for t in source.tasks if t.id in set(chunk)],
        )
        # Preserve the global seeded order inside the chunk.
        selected.tasks.sort(key=lambda t: chunk.index(t.id))
        runner = SuiteRunner(
            selected,
            profiles,
            eval_dir=eval_dir,
            max_turns=int(controls["max_turns"]),
            command_timeout=int(controls["command_timeout_s"]),
            repeats=int(controls.get("repeats", 1)),
        )
        print(
            f"[bank] suite {suite_name}: running {len(chunk)} pair(s): "
            f"{', '.join(chunk)}"
        )
        all_records.extend(asyncio.run(runner.run_and_verify()))
    return all_records


def summarize(
    bank: dict,
    eval_dir: Path,
    order: list[tuple[str, str]],
) -> dict:
    """Merge every bank record on disk, apply the frozen decision rules."""
    bank_task_ids = {tid for _, tid in order}
    done = existing_bank_records(eval_dir, bank_task_ids)
    per_task: dict[str, dict[str, str]] = {}
    arm_stats: dict[str, dict] = {
        ARM_A: {"pass": 0, "fail": 0, "infra": 0, "tokens": 0,
                "requests": 0, "latencies": []},
        ARM_B: {"pass": 0, "fail": 0, "infra": 0, "tokens": 0,
                "requests": 0, "latencies": []},
    }
    for key, record in done.items():
        task_id, arm = key.split("::", 1)
        verdict = str(record.get("verdict"))
        per_task.setdefault(task_id, {})[arm] = verdict
        stats = arm_stats[arm]
        usage = record.get("usage") or {}
        stats["tokens"] += int(usage.get("total_tokens") or 0)
        stats["requests"] += int(usage.get("model_requests") or 0)
        latency = (record.get("timing") or {}).get("latency_seconds")
        if isinstance(latency, (int, float)):
            stats["latencies"].append(latency)
        if verdict == "pass":
            stats["pass"] += 1
        elif verdict == "infrastructure_error":
            stats["infra"] += 1
            stats["fail"] += 1  # counts as a failure for the primary metric
        else:
            stats["fail"] += 1

    complete_pairs = [
        tid for tid in {tid for _, tid in order}
        if ARM_A in per_task.get(tid, {}) and ARM_B in per_task.get(tid, {})
    ]
    pairs_done = len(complete_pairs)
    a_pass = arm_stats[ARM_A]["pass"]
    b_pass = arm_stats[ARM_B]["pass"]
    diff_pp = round((a_pass - b_pass) / pairs_done * 100, 1) if pairs_done else None
    b_only = sum(
        1 for tid in complete_pairs
        if per_task[tid].get(ARM_B) == "pass" and per_task[tid].get(ARM_A) != "pass"
    )
    a_only = sum(
        1 for tid in complete_pairs
        if per_task[tid].get(ARM_A) == "pass" and per_task[tid].get(ARM_B) != "pass"
    )

    rules = bank["decision_rules"]
    if pairs_done < int(bank["pairs"]):
        interim_lead = abs(a_pass - b_pass)
        decision = (
            "interim-stop threshold reached"
            if interim_lead >= 7 and pairs_done >= 20
            else "interim: continue to the full 40 pairs"
        )
    elif diff_pp is None:
        decision = "no complete pairs"
    elif abs(diff_pp) >= 25:
        decision = (
            f"{ARM_A} wins by {-diff_pp} points; change the default tool profile"
            if diff_pp < 0
            else f"{ARM_A} wins by {diff_pp} points; keep full7 as default"
        )
    elif abs(diff_pp) >= 10:
        decision = "trend only: keep the current default, change nothing"
    else:
        decision = "no meaningful difference: treat the profiles as equivalent"

    summary = {
        "bank_id": bank["bank_id"],
        "seed": bank["seed"],
        "model": bank["controls"]["model"],
        "prompt_sha256": bank["controls"]["prompt_sha256"],
        "pairs_completed": pairs_done,
        "pairs_planned": int(bank["pairs"]),
        "per_arm": {
            arm: {
                "pass": s["pass"],
                "fail": s["fail"],
                "infrastructure_errors": s["infra"],
                "total_tokens": s["tokens"],
                "model_requests": s["requests"],
                "median_latency_seconds": (
                    round(statistics.median(s["latencies"]), 1)
                    if s["latencies"] else None
                ),
            }
            for arm, s in arm_stats.items()
        },
        "paired_outcomes": {
            "both_pass": sum(
                1 for tid in complete_pairs
                if per_task[tid][ARM_A] == "pass" and per_task[tid][ARM_B] == "pass"
            ),
            "both_fail": sum(
                1 for tid in complete_pairs
                if per_task[tid][ARM_A] != "pass" and per_task[tid][ARM_B] != "pass"
            ),
            f"{ARM_A}_only_pass": a_only,
            f"{ARM_B}_only_pass": b_only,
        },
        "pass_rate_difference_points": diff_pp,
        "decision": decision,
        "per_task": {tid: per_task[tid] for tid in sorted(complete_pairs)},
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", default=str(BANK_DEFAULT))
    parser.add_argument("--eval-dir", default=str(REPO_ROOT / ".agent-eval" / "tool-profile-bank-v1"))
    parser.add_argument("--pairs", type=int, default=None,
                        help="run at most this many incomplete pairs (default: all 40)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the bank and print the schedule; no model calls")
    args = parser.parse_args(argv)

    bank = load_bank(Path(args.bank))
    suites = validate_bank(bank, REPO_ROOT)
    order = seeded_order(bank)
    eval_dir = Path(args.eval_dir)

    if args.dry_run:
        print(f"Bank {bank['bank_id']}: {len(order)} tasks validated.")
        print(f"Seed {bank['seed']} | model {bank['controls']['model']} | "
              f"max_turns {bank['controls']['max_turns']}")
        for i, (suite_name, task_id) in enumerate(order, 1):
            print(f"  {i:2d}. {task_id} ({suite_name})")
        print("Dry run OK: no attempts were made.")
        return 0

    import os

    if not os.environ.get("AGENT_EVAL_ALLOW_HOST_EXECUTION") == "1":
        _fail(
            "Real attempts execute bash on this host in disposable workspaces. "
            "Set AGENT_EVAL_ALLOW_HOST_EXECUTION=1 to accept, or use --dry-run."
        )
    if not os.environ.get("OPENROUTER_API_KEY"):
        _fail("OPENROUTER_API_KEY is not set; real profiles require it.")

    limit = args.pairs if args.pairs is not None else int(bank["pairs"])
    run_batch(bank, suites, order, limit, eval_dir)
    summary = summarize(bank, eval_dir, order)
    summary_path = eval_dir / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n[{summary['pairs_completed']}/{summary['pairs_planned']} pairs complete]")
    for arm, stats in summary["per_arm"].items():
        print(
            f"  {arm}: pass={stats['pass']} fail={stats['fail']} "
            f"(infra={stats['infrastructure_errors']}) tokens={stats['total_tokens']:,} "
            f"requests={stats['model_requests']} "
            f"median={stats['median_latency_seconds']}s"
        )
    print(f"  paired: {summary['paired_outcomes']}")
    print(f"  pass-rate difference: {summary['pass_rate_difference_points']} points")
    print(f"  decision: {summary['decision']}")
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
