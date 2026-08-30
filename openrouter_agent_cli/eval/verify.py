"""Host-side verifier execution.

The verifier command is defined by the suite manifest and runs HOST-side with
its working directory set to a trusted directory (never the agent workspace).
The agent workspace path is passed as ``argv[1]`` so the verifier can inspect
results without any of its code living where the agent could edit it.

Exit-code contract:
  0   -> pass
  2   -> task_fail (the agent finished but the work is wrong/incomplete)
  else / timeout / crash -> infrastructure_error (harness problem, not the agent's)
"""
from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

VERDICT_PASS = "pass"
VERDICT_TASK_FAIL = "task_fail"
VERDICT_INFRA_ERROR = "infrastructure_error"


@dataclass
class Verdict:
    verdict: str
    evidence: str


def run_verifier(
    command: str, workspace: Path, trusted_cwd: Path, timeout_s: int = 30
) -> Verdict:
    """Run one verifier. Never raises; all failures become verdicts."""
    try:
        argv = shlex.split(command)
        if not argv:
            return Verdict(VERDICT_INFRA_ERROR, "verifier command is empty")
        proc = subprocess.run(
            [*argv, str(workspace)],
            shell=False,
            cwd=str(trusted_cwd),
            timeout=max(1, timeout_s),
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return Verdict(VERDICT_INFRA_ERROR, f"verifier timed out after {timeout_s}s")
    except OSError as exc:
        return Verdict(VERDICT_INFRA_ERROR, f"verifier failed to start: {exc}")
    evidence = (proc.stdout or "").strip().splitlines()
    evidence = evidence[-1][:500] if evidence else ""
    if not evidence and proc.stderr:
        evidence = (proc.stderr or "").strip().splitlines()[-1][:500]
    if proc.returncode == 0:
        return Verdict(VERDICT_PASS, evidence or "verifier exit 0")
    if proc.returncode == 2:
        return Verdict(VERDICT_TASK_FAIL, evidence or "verifier exit 2")
    return Verdict(
        VERDICT_INFRA_ERROR,
        evidence or f"verifier exit {proc.returncode} (expected 0 or 2)",
    )
