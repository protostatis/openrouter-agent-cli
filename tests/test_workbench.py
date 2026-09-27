from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from openrouter_agent_cli.workbench import (
    AttemptResult,
    InternalTask,
    build_review_queue,
    run_workbench,
)
import openrouter_agent_cli.workbench as workbench_module


def _result(task_id: str, status: str) -> AttemptResult:
    return AttemptResult(
        task_id=task_id,
        status=status,
        source_ref="HEAD",
        source_commit="abc123",
        worktree=None,
        results_dir="",
    )


def test_workbench_runs_ready_tasks_and_blocks_failed_dependencies(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_runner(task: InternalTask, **kwargs) -> AttemptResult:
        calls.append(task.task_id)
        return _result(task.task_id, "failed" if task.task_id == "first" else "verified")

    tasks = [
        InternalTask("first", "first", "true"),
        InternalTask("dependent", "dependent", "true", depends_on=("first",)),
        InternalTask("independent", "independent", "true"),
    ]
    results = run_workbench(
        tasks,
        repo=tmp_path,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert calls == ["first", "independent"]
    assert [result.status for result in results] == ["failed", "blocked", "verified"]
    summary = json.loads((tmp_path / "results" / "workbench.json").read_text())
    assert [item["task_id"] for item in summary["tasks"]] == [
        "first",
        "dependent",
        "independent",
    ]


def test_workbench_rejects_unknown_dependency(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown dependencies"):
        run_workbench(
            [InternalTask("task", "task", "true", depends_on=("missing",))],
            repo=tmp_path,
            results_root=tmp_path / "results",
        )


def test_workbench_rejects_dependency_cycle(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dependency cycle"):
        run_workbench(
            [
                InternalTask("a", "a", "true", depends_on=("b",)),
                InternalTask("b", "b", "true", depends_on=("a",)),
            ],
            repo=tmp_path,
            results_root=tmp_path / "results",
            runner=lambda task, **kwargs: _result(task.task_id, "verified"),
        )


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "Workbench Test"],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True, text=True)
    (repo / "target.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "initial"], cwd=repo, check=True
    )
    return repo


def _python_command(source: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


def test_internal_task_isolates_changes_and_records_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)

    def fake_agent_command(task, *, worktree, **kwargs):
        source = (
            "from pathlib import Path; "
            f"Path({str(worktree)!r}, 'target.txt').write_text('after\\n'); "
            f"Path({str(worktree)!r}, 'new.txt').write_text('new\\n')"
        )
        return [sys.executable, "-c", source]

    monkeypatch.setattr(workbench_module, "_agent_command", fake_agent_command)
    verify = _python_command(
        "from pathlib import Path; "
        "assert Path('target.txt').read_text() == 'after\\n'"
    )
    result = workbench_module.run_internal_task(
        InternalTask("isolated", "change target", verify),
        repo=repo,
        results_root=tmp_path / "results",
        request_timeout=7.5,
        provider_retries=0,
        repeat_tool_call_limit=2,
        task_timeout=10,
        verify_timeout=10,
    )

    assert result.status == "verified"
    assert set(result.changed_files) == {"target.txt", "new.txt"}
    assert (repo / "target.txt").read_text() == "before\n"
    assert Path(result.worktree, "target.txt").read_text() == "after\n"
    patch = (Path(result.results_dir) / "changes.patch").read_text()
    assert "+after" in patch
    assert "+new" in patch
    evidence = json.loads((Path(result.results_dir) / "result.json").read_text())
    assert evidence["runtime_policy"]["request_timeout_seconds"] == 7.5
    assert (Path(result.results_dir) / "task.json").exists()
    events = [
        json.loads(line)
        for line in (Path(result.results_dir) / "events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == [
        "attempt_started",
        "worktree_ready",
        "agent_finished",
        "changes_collected",
        "verifier_finished",
        "attempt_finished",
    ]


def test_provider_failure_is_recorded_without_running_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)

    def fake_agent_command(task, **kwargs):
        source = "import sys; sys.stderr.write('[openrouter] request failed\\n'); raise SystemExit(1)"
        return [sys.executable, "-c", source]

    monkeypatch.setattr(workbench_module, "_agent_command", fake_agent_command)
    result = workbench_module.run_internal_task(
        InternalTask("provider-failure", "fail", "false"),
        repo=repo,
        results_root=tmp_path / "results",
        task_timeout=10,
        verify_timeout=10,
    )

    assert result.status == "provider_error"
    assert result.verifier_returncode is None
    assert result.error == "provider request failed"


def test_no_change_is_not_verified_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    monkeypatch.setattr(
        workbench_module,
        "_agent_command",
        lambda task, **kwargs: [sys.executable, "-c", "pass"],
    )
    result = workbench_module.run_internal_task(
        InternalTask("no-change", "do nothing", "true"),
        repo=repo,
        results_root=tmp_path / "results",
        task_timeout=10,
        verify_timeout=10,
    )

    assert result.status == "not_verified"
    assert result.error == "worker produced no repository changes"


def test_path_allowlist_blocks_out_of_scope_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)

    def fake_agent_command(task, *, worktree, **kwargs):
        source = f"from pathlib import Path; Path({str(worktree)!r}, 'target.txt').write_text('after\\n')"
        return [sys.executable, "-c", source]

    monkeypatch.setattr(workbench_module, "_agent_command", fake_agent_command)
    result = workbench_module.run_internal_task(
        InternalTask(
            "scope-check",
            "change only the allowed file",
            "true",
            allowed_paths=("tests/**",),
        ),
        repo=repo,
        results_root=tmp_path / "results",
        task_timeout=10,
        verify_timeout=10,
    )

    assert result.status == "policy_violation"
    assert result.policy_violations == ["target.txt"]
    assert result.verifier_returncode is None


def test_review_queue_separates_patches_from_attention_items(tmp_path: Path) -> None:
    root = tmp_path / "results"
    candidate_dir = root / "candidate"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "changes.patch").write_text("diff --git a/a b/a\n", encoding="utf-8")
    summary = {
        "source_ref": "HEAD",
        "tasks": [
            {
                "task_id": "candidate",
                "status": "verified",
                "results_dir": str(candidate_dir),
                "changed_files": ["a"],
            },
            {
                "task_id": "provider",
                "status": "provider_error",
                "results_dir": str(root / "provider"),
                "changed_files": [],
                "error": "provider request failed",
            },
            {
                "task_id": "review-only",
                "status": "verified",
                "results_dir": str(root / "review-only"),
                "changed_files": [],
            },
        ],
    }
    root.mkdir(exist_ok=True)
    (root / "workbench.json").write_text(json.dumps(summary), encoding="utf-8")

    queue = build_review_queue(root)

    assert [item["task_id"] for item in queue["review_candidates"]] == ["candidate"]
    assert [item["task_id"] for item in queue["completed_without_changes"]] == [
        "review-only"
    ]
    assert [item["task_id"] for item in queue["needs_attention"]] == ["provider"]


def test_verifier_does_not_receive_provider_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)

    def fake_agent_command(task, **kwargs):
        return [sys.executable, "-c", "pass"]

    monkeypatch.setattr(workbench_module, "_agent_command", fake_agent_command)
    verify = _python_command(
        "import os; from pathlib import Path; "
        "Path('secret_seen.txt').write_text(os.environ.get('OPENROUTER_API_KEY', 'missing'))"
    )
    result = workbench_module.run_internal_task(
        InternalTask("secret-boundary", "check", verify, require_changes=False),
        repo=repo,
        results_root=tmp_path / "results",
        task_timeout=10,
        verify_timeout=10,
        env={"OPENROUTER_API_KEY": "do-not-leak"},
    )

    assert result.status == "verified"
    assert Path(result.worktree, "secret_seen.txt").read_text() == "missing"
