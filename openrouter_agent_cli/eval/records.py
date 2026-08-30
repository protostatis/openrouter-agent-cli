"""Versioned, append-only run records.

One JSONL file per suite campaign under ``.agent-eval/runs/``. Each line is a
self-contained factual record of one attempt. Records state ONLY facts the
harness observed; the ``verdict`` field is filled exclusively by a verifier
(see ``verify.py``) and stays ``null`` until then. Interactive sessions are
never labeled successful or unsuccessful by this layer.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

RECORDS_SCHEMA_VERSION = "agent-eval-run-record-v1"


def default_runs_dir() -> Path:
    root = os.environ.get("AGENT_EVAL_DIR")
    base = Path(root).expanduser() if root else Path.cwd() / ".agent-eval"
    return base / "runs"


def fingerprint_prompt(text: str) -> str:
    """Stable short fingerprint of a prompt/profile so records stay comparable
    across runs even if the prompt file moves."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def new_run_id() -> str:
    return f"run-{int(time.time() * 1000)}-{os.getpid():d}"


def make_record(
    *,
    run_id: str,
    suite_id: str,
    task_id: str,
    cluster_id: str | None,
    profile_name: str,
    profile_prompt: str,
    model: str,
    transport: str,
    workdir: str,
    scheduled_index: int,
) -> dict[str, Any]:
    """Build the initial record for one scheduled attempt (verdict pending)."""
    return {
        "schema_version": RECORDS_SCHEMA_VERSION,
        "run_id": run_id,
        "suite_id": suite_id,
        "task_id": task_id,
        "cluster_id": cluster_id,
        "profile": {
            "name": profile_name,
            "prompt_sha256_16": fingerprint_prompt(profile_prompt),
        },
        "model": model,
        "transport": transport,  # "openrouter" | "mock:<script>"
        "workspace": workdir,
        "scheduled_index": scheduled_index,
        "engine": {"session_dir": None, "finish_reason": None, "error": None},
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "timing": {"started_at": None, "ended_at": None, "latency_seconds": None},
        "tool_calls": [],  # [{name, ok, duration_ms, brief}]
        "verdict": None,  # filled only by verify.py: pass|task_fail|infrastructure_error
        "verdict_evidence": None,
    }


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def load_records(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def update_verdict(
    path: Path, run_id: str, verdict: str, evidence: str
) -> dict[str, Any]:
    """Fill the verdict on an existing record. Rewrite-in-place is safe because
    verdict assignment is idempotent per run_id and the file is campaign-local.
    Raises if the run_id is unknown or already has a different verdict."""
    rows = load_records(path)
    hits = [r for r in rows if r.get("run_id") == run_id]
    if not hits:
        raise KeyError(f"unknown run_id: {run_id}")
    rec = hits[-1]
    if rec.get("verdict") not in (None, verdict):
        raise ValueError(
            f"run {run_id} already has verdict {rec['verdict']!r}; refusing to change to {verdict!r}"
        )
    rec["verdict"] = verdict
    rec["verdict_evidence"] = evidence
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return rec
