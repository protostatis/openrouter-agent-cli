"""Tests for the workbench structural checks: test growth and escaped newlines.

These run the REAL workbench verification helpers against small real git
repositories — no model calls. The agent-facing pieces (collection, node-ID
diff, new-node run) are exercised through the same helpers run_internal_task
uses.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from openrouter_agent_cli.workbench import (
    InternalTask,
    _collect_pytest_nodes,
    _escaped_newline_lines,
    _structural_findings,
    _verify_test_growth,
)


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    # A minimal virtual project so `uv run` resolves pytest for collection.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.1"\n'
        'requires-python = ">=3.10"\ndependencies = ["pytest>=7"]\n'
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _commit_all(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


# ---------------------------------------------------------------------------
# Test growth
# ---------------------------------------------------------------------------


def _growth_task(tmp_path: Path, minimum: int = 1) -> tuple[InternalTask, Path]:
    task = InternalTask(
        task_id="growth",
        task="add a test",
        verify_command="true",
        test_growth={"minimum_new_nodes": minimum},
    )
    return task, tmp_path


def test_real_new_test_passes_growth(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_base.py").write_text("def test_base():\n    assert True\n")
    source_commit = _commit_all(repo, "base")

    task, _ = _growth_task(tmp_path)
    # Baseline collection from the clean tree:
    ok, baseline_nodes, err = _collect_pytest_nodes(repo, 120.0)
    assert ok, err
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "test-growth-baseline.json").write_text(
        json.dumps({"ok": True, "node_ids": baseline_nodes, "error": None})
    )

    # The worker adds a REAL test:
    (repo / "tests" / "test_new.py").write_text(
        "def test_new_thing():\n    assert 1 + 1 == 2\n"
    )
    growth = _verify_test_growth(
        task, repo, ["tests/test_new.py"], results_dir, dict(os.environ), 120.0
    )
    assert growth["ok"], growth["reason"]
    assert len(growth["new_node_ids"]) == 1
    assert growth["new_node_ids"][0].endswith("test_new_thing")


def test_phantom_comment_test_fails_growth(tmp_path: Path) -> None:
    """A one-line 'test' written with literal \\n escapes produces no node."""
    repo = _git_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_base.py").write_text("def test_base():\n    assert True\n")
    _commit_all(repo, "base")

    task, _ = _growth_task(tmp_path)
    ok, baseline_nodes, err = _collect_pytest_nodes(repo, 120.0)
    assert ok, err
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "test-growth-baseline.json").write_text(
        json.dumps({"ok": True, "node_ids": baseline_nodes, "error": None})
    )

    # The exact batch-1 failure mode: one physical line, literal \n escapes.
    one_line = (
        "# ---------------------------------------------------------------------------\\n"
        "# phantom test\\n"
        "# ---------------------------------------------------------------------------\\n"
        "\\n"
        "class TestPhantom:\\n"
        "    def test_phantom(self):\\n"
        "        assert True\\n"
    )
    (repo / "tests" / "test_phantom.py").write_text(one_line)
    growth = _verify_test_growth(
        task, repo, ["tests/test_phantom.py"], results_dir, dict(os.environ), 120.0
    )
    assert not growth["ok"]
    assert "required 1 new test node" in (growth["reason"] or "")


def test_deleted_plus_added_cannot_hide_behind_count(tmp_path: Path) -> None:
    """Removing an old test while adding a new one is a removal violation."""
    repo = _git_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_base.py").write_text(
        "def test_base():\n    assert True\n\n\ndef test_old():\n    assert True\n"
    )
    _commit_all(repo, "base")

    task, _ = _growth_task(tmp_path)
    ok, baseline_nodes, err = _collect_pytest_nodes(repo, 120.0)
    assert ok, err
    assert len(baseline_nodes) == 2
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "test-growth-baseline.json").write_text(
        json.dumps({"ok": True, "node_ids": baseline_nodes, "error": None})
    )

    (repo / "tests" / "test_base.py").write_text(
        "def test_base():\n    assert True\n\n\ndef test_replacement():\n    assert True\n"
    )
    growth = _verify_test_growth(
        task, repo, ["tests/test_base.py"], results_dir, dict(os.environ), 120.0
    )
    assert not growth["ok"]
    assert "removed" in (growth["reason"] or "")


def test_missing_baseline_blocks_growth(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n")
    task, _ = _growth_task(tmp_path)
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    growth = _verify_test_growth(
        task, repo, ["tests/test_new.py"], results_dir, dict(os.environ), 120.0
    )
    assert not growth["ok"]
    assert "baseline" in (growth["reason"] or "")


# ---------------------------------------------------------------------------
# Escaped-newline scan
# ---------------------------------------------------------------------------


def test_phantom_one_line_block_is_flagged() -> None:
    one_line = (
        "# --- header\\n# guard test\\n# --- footer\\n\\n"
        "class TestX:\\n    def test_x(self):\\n        assert True\\n"
    )
    flagged = _escaped_newline_lines(one_line)
    assert 1 in flagged


def test_string_literal_escaped_newline_is_not_flagged() -> None:
    source = 'VALUE = "line1\\nline2"\n\ndef main():\n    return VALUE\n'
    assert _escaped_newline_lines(source) == set()


def test_single_comment_mention_is_not_flagged() -> None:
    source = (
        "def main():\n"
        "    # joins items with \\n between them\n"
        "    return 'x'\n"
    )
    assert _escaped_newline_lines(source) == set()


def test_scan_ignores_string_content_and_flags_only_added_lines(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "mod.py").write_text('TEMPLATE = "a\\nb"\n')
    source_commit = _commit_all(repo, "base")
    # Add a flagged line (the worker failure mode) next to clean code:
    (repo / "mod.py").write_text(
        'TEMPLATE = "a\\nb"\n# --- block\\n# more\\n# --- end\\n'
    )
    findings = _structural_findings(repo, source_commit, ["mod.py"])
    assert findings == [{"path": "mod.py", "line": 2}]
