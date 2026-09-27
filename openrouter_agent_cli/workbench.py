"""Bounded internal workbench primitives.

The workbench runs one repository task in one disposable Git worktree, asks the
existing CLI to do the work, runs the trusted acceptance command independently,
and leaves a reviewable patch and evidence record. It never merges or pushes.
"""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import time
import tokenize
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ACCEPTANCE_RE = re.compile(r"\[acceptance\]\s+(VERIFIED|FAILED|NOT_VERIFIED)")
PROVIDER_ERROR_RE = re.compile(r"terminal_status=provider_error|\[openrouter\].*request failed")
DEFAULT_WORKER_PROMPT = (
    "Work carefully on the bounded repository task. Inspect before editing, "
    "use targeted inspection rather than rereading whole files, make the "
    "smallest correct change, run the acceptance command, and stop "
    "only after verifying the result. Do not commit, merge, push, deploy, or "
    "modify files outside the assigned worktree."
)


@dataclass(frozen=True)
class InternalTask:
    """A bounded task a worker can execute and a verifier can check."""

    task_id: str
    task: str
    verify_command: str
    prompt: str = DEFAULT_WORKER_PROMPT
    depends_on: tuple[str, ...] = ()
    require_changes: bool = True
    allowed_paths: tuple[str, ...] = ()
    # Optional structural requirement for "add a test" tasks, e.g.
    # {"minimum_new_nodes": 1, "allow_removals": false}. When set, the
    # workbench collects pytest node IDs before the agent runs and verifies
    # after the patch that genuinely NEW, passing test nodes were added in
    # changed files — a comment that only looks like a test cannot pass.
    test_growth: dict[str, Any] | None = None
    # Waiver for the escaped-newline structural scan (a worker failure mode
    # where code is written on one line with literal backslash-n sequences).
    allow_escaped_newlines: bool = False


@dataclass
class AttemptResult:
    task_id: str
    status: str
    source_ref: str
    source_commit: str | None
    worktree: str | None
    results_dir: str
    agent_returncode: int | None = None
    agent_timed_out: bool = False
    acceptance_status: str | None = None
    verifier_returncode: int | None = None
    verifier_timed_out: bool = False
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
    test_growth: dict[str, Any] | None = None
    structural_findings: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    error: str | None = None

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")


def _run_git(repo: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )


def _append_event(path: Path, event: str, **fields: Any) -> None:
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows is not the primary workbench host.
            process.kill()
    except (ProcessLookupError, OSError):
        pass


def _run_process(
    command: Sequence[str] | str,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    shell: bool = False,
) -> tuple[int | None, str, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name == "posix"),
        shell=shell,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        stdout, stderr = process.communicate()
        partial_stdout = stdout or (exc.stdout or "")
        partial_stderr = stderr or (exc.stderr or "")
        return process.returncode, partial_stdout, partial_stderr, True


def _changed_files(worktree: Path) -> list[str]:
    result = _run_git(worktree, ["status", "--porcelain=v1", "--untracked-files=all", "-z"])
    entries = [entry for entry in result.stdout.split("\0") if entry]
    paths: list[str] = []
    for entry in entries:
        # Normal entries have two status bytes followed by a space. With -z,
        # a rename has the second path as a separate token with no status.
        value = entry[3:] if len(entry) >= 3 and entry[2] == " " else entry
        if value not in paths:
            paths.append(value)
    return paths


def _unexpected_paths(changed_files: Sequence[str], allowed_paths: Sequence[str]) -> list[str]:
    """Return changed paths that do not match the task's optional allowlist."""
    if not allowed_paths:
        return []
    return [
        path
        for path in changed_files
        if not any(fnmatch.fnmatchcase(path, pattern) for pattern in allowed_paths)
    ]


def _collect_pytest_nodes(
    worktree: Path, timeout: float, env: dict[str, str] | None = None
) -> tuple[bool, list[str], str]:
    """Collect pytest node IDs in the worktree. (ok, node_ids, error_tail)."""
    returncode, stdout, stderr, timed_out = _run_process(
        ["uv", "run", "python", "-m", "pytest", "--collect-only", "-q"],
        cwd=worktree,
        env=env if env is not None else os.environ.copy(),
        timeout=timeout,
    )
    if timed_out or returncode != 0:
        return False, [], (stderr or stdout or "")[-500:]
    nodes = [
        line.strip()
        for line in stdout.splitlines()
        if "::" in line and not line.strip().startswith("=")
    ]
    return True, nodes, ""


def _run_new_nodes(
    worktree: Path, node_ids: list[str], timeout: float, env: dict[str, str]
) -> tuple[bool, str]:
    """Run specific test node IDs as argv (never through a shell)."""
    returncode, _stdout, stderr, timed_out = _run_process(
        ["uv", "run", "python", "-m", "pytest", "-q", *node_ids],
        cwd=worktree,
        env=env,
        timeout=timeout,
    )
    if timed_out:
        return False, "new-node test run timed out"
    if returncode != 0:
        return False, (stderr or _stdout or "")[-500:]
    return True, ""


def _verify_test_growth(
    task: "InternalTask",
    worktree: Path,
    changed_files: Sequence[str],
    results_dir: Path,
    verify_env: dict[str, str],
    verify_timeout: float,
) -> dict[str, Any]:
    """Verify a declared test-growth requirement against node-ID sets.

    Compares pytest node IDs collected from the clean baseline (saved before
    the agent ran) with a fresh collection after the patch. Requires new,
    passing nodes in changed files; a deleted-and-replaced pair cannot hide
    behind an unchanged total count, and a comment that only looks like a
    test produces no node at all.
    """
    config = task.test_growth or {}
    minimum = max(1, int(config.get("minimum_new_nodes", 1)))
    allow_removals = bool(config.get("allow_removals", False))
    summary: dict[str, Any] = {
        "required_new_nodes": minimum,
        "ok": False,
        "reason": None,
        "new_node_ids": [],
        "removed_node_ids": [],
    }

    baseline_path = results_dir / "test-growth-baseline.json"
    if not baseline_path.is_file():
        summary["reason"] = "baseline test collection is missing"
        return summary
    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not baseline_data.get("ok"):
        summary["reason"] = (
            "baseline test collection failed before the attempt: "
            + str(baseline_data.get("error") or "")[-300:]
        )
        return summary
    baseline_ids = set(baseline_data.get("node_ids") or [])

    after_ok, after_ids, collect_error = _collect_pytest_nodes(
        worktree, verify_timeout, env=verify_env
    )
    if not after_ok:
        # Collection can fail for import or environment reasons; that is
        # "not verified", never proof of a phantom test.
        summary["reason"] = "post-patch test collection failed: " + collect_error[-300:]
        return summary

    baseline_set, after_set = set(baseline_ids), set(after_ids)
    new_ids = sorted(after_set - baseline_set)
    removed_ids = sorted(baseline_set - after_set)
    summary["new_node_ids"] = new_ids
    summary["removed_node_ids"] = removed_ids

    if removed_ids and not allow_removals:
        summary["reason"] = f"baseline tests were removed: {removed_ids[:5]}"
        return summary
    if len(new_ids) < minimum:
        summary["reason"] = (
            f"required {minimum} new test node(s) but found {len(new_ids)}: "
            f"{new_ids[:5]}"
        )
        return summary
    changed_set = set(changed_files)
    foreign = [
        node for node in new_ids if node.split("::")[0] not in changed_set
    ]
    if foreign:
        summary["reason"] = f"new tests outside changed files: {foreign[:5]}"
        return summary
    run_ok, run_error = _run_new_nodes(
        worktree, new_ids, verify_timeout, verify_env
    )
    if not run_ok:
        summary["reason"] = "new tests did not pass: " + run_error[-300:]
        return summary
    summary["ok"] = True
    return summary


_ESCAPED_NEWLINE_RE = re.compile(r"\\n")
_CODE_AFTER_ESCAPE_RE = re.compile(
    r"\\n\s*(?:class|def|async|@|from|import|assert)\b"
)
_STRING_TOKEN_TYPES = {"STRING"}
for _name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    _token_type = getattr(tokenize, _name, None)
    if _token_type is not None:
        _STRING_TOKEN_TYPES.add(_token_type)


def _escaped_newline_lines(source: str) -> set[int]:
    """Line numbers (1-based) where literal backslash-n appears OUTSIDE
    string tokens, with at least two occurrences or code following the
    escape. This is the structural marker of the known failure where a
    multi-line block is emitted as one physical line."""
    try:
        tokens = list(
            tokenize.generate_tokens(io.StringIO(source).readline)
        )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A file that cannot tokenize is broken anyway; the acceptance
        # command and test collection will catch it. Nothing to add here.
        return set()
    lines = source.splitlines()
    masked: dict[int, list[str]] = {
        row: list(line) for row, line in enumerate(lines, 1)
    }
    for tok in tokens:
        if tok.type not in _STRING_TOKEN_TYPES and tok.type != tokenize.STRING:
            continue
        (start_row, start_col), (end_row, end_col) = tok.start, tok.end
        for row in range(start_row, end_row + 1):
            if row not in masked:
                continue
            begin = start_col if row == start_row else 0
            end = end_col if row == end_row else len(lines[row - 1])
            for col in range(begin, min(end, len(masked[row]))):
                masked[row][col] = " "
    flagged: set[int] = set()
    for row in sorted(masked):
        rest = "".join(masked[row])
        if _CODE_AFTER_ESCAPE_RE.search(rest) or rest.count("\\n") >= 2:
            flagged.add(row)
    return flagged


def _added_lines_per_file(
    worktree: Path, source_commit: str, changed_files: Sequence[str]
) -> dict[str, set[int]]:
    """1-based line numbers ADDED by the patch, per changed .py file."""
    result: dict[str, set[int]] = {}
    for path in changed_files:
        if not path.endswith(".py"):
            continue
        current_path = worktree / path
        try:
            current = current_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        show = subprocess.run(
            ["git", "show", f"{source_commit}:{path}"],
            cwd=worktree,
            text=True,
            capture_output=True,
            check=False,
        )
        baseline = show.stdout if show.returncode == 0 else ""
        matcher = difflib.SequenceMatcher(
            a=baseline.splitlines(), b=current.splitlines(), autojunk=False
        )
        added: set[int] = set()
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag in ("insert", "replace"):
                added.update(range(j1 + 1, j2 + 1))
        result[path] = added
    return result


def _structural_findings(
    worktree: Path,
    source_commit: str,
    changed_files: Sequence[str],
) -> list[dict[str, Any]]:
    """Escaped-newline findings on ADDED lines of changed Python files."""
    findings: list[dict[str, Any]] = []
    for path, added_rows in _added_lines_per_file(
        worktree, source_commit, changed_files
    ).items():
        try:
            source = (worktree / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        flagged = _escaped_newline_lines(source)
        for row in sorted(added_rows & flagged):
            findings.append({"path": path, "line": row})
    return findings


def _write_patch(worktree: Path, source_commit: str, results_dir: Path) -> None:
    with (results_dir / "changes.patch").open("w", encoding="utf-8") as handle:
        subprocess.run(
            ["git", "diff", "--binary", source_commit, "--"],
            cwd=worktree,
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=worktree,
            text=True,
            capture_output=True,
            check=False,
        ).stdout.split("\0")
        for path in (item for item in untracked if item):
            diff = subprocess.run(
                ["git", "diff", "--no-index", "--binary", "--", "/dev/null", path],
                cwd=worktree,
                text=True,
                capture_output=True,
                check=False,
            )
            handle.write(diff.stdout)


def _agent_command(
    task: InternalTask,
    *,
    worktree: Path,
    run_id: str,
    max_turns: int,
    request_timeout: float,
    provider_retries: int,
    repeat_tool_call_limit: int,
    tool_profile: str,
    env_file: Path | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "openrouter_agent_cli.cli",
        "--allow-tools",
        "--discovery",
        "off",
        "--workdir",
        str(worktree),
        "--task",
        task.task,
        "--verify-command",
        task.verify_command,
        "--prompt",
        task.prompt,
        "--max-turns",
        str(max_turns),
        "--request-timeout",
        str(request_timeout),
        "--provider-retries",
        str(provider_retries),
        "--repeat-tool-call-limit",
        str(repeat_tool_call_limit),
        "--tool-profile",
        tool_profile,
        "--run-id",
        run_id,
    ]
    if task.require_changes:
        # The no-progress guard watches the actual worktree content and
        # stops inspection-only runs; interactive sessions leave it off.
        command.append("--require-repo-change")
    if env_file is not None:
        command.extend(["--env-file", str(env_file)])
    return command


def run_internal_task(
    task: InternalTask,
    *,
    repo: Path,
    results_root: Path,
    source_ref: str = "HEAD",
    max_turns: int = 32,
    request_timeout: float = 60.0,
    provider_retries: int = 3,
    repeat_tool_call_limit: int = 1,
    tool_profile: str = "core4",
    task_timeout: float = 1800.0,
    verify_timeout: float = 120.0,
    keep_worktree: bool = True,
    env_file: Path | None = None,
    attempt_id: str | None = None,
    env: dict[str, str] | None = None,
) -> AttemptResult:
    """Run one task and return a reviewable, independently verified result."""
    repo = Path(repo).expanduser().resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", task.task_id):
        raise ValueError("task_id must contain only letters, numbers, '.', '_' or '-'")
    attempt_name = attempt_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results_dir = (
        Path(results_root).expanduser().resolve() / task.task_id / attempt_name
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    source_commit: str | None = None
    worktree: Path | None = None
    result = AttemptResult(
        task_id=task.task_id,
        status="infrastructure_error",
        source_ref=source_ref,
        source_commit=None,
        worktree=None,
        results_dir=str(results_dir),
        started_at=started_at,
        runtime_policy={
            "max_turns": max_turns,
            "request_timeout_seconds": request_timeout,
            "provider_retry_limit": provider_retries,
            "repeated_tool_call_limit": repeat_tool_call_limit,
            "tool_profile": tool_profile,
            "task_timeout_seconds": task_timeout,
            "verify_timeout_seconds": verify_timeout,
        },
    )
    (results_dir / "task.json").write_text(
        json.dumps(asdict(task), indent=2) + "\n", encoding="utf-8"
    )
    events_path = results_dir / "events.jsonl"
    _append_event(events_path, "attempt_started", task_id=task.task_id, source_ref=source_ref)

    try:
        root = Path(_run_git(repo, ["rev-parse", "--show-toplevel"]).stdout.strip())
        source_commit = _run_git(root, ["rev-parse", source_ref]).stdout.strip()
        result.source_commit = source_commit
        worktree = results_dir / "worktree"
        _run_git(root, ["worktree", "add", "--detach", str(worktree), source_commit])
        result.worktree = str(worktree)
        _append_event(
            events_path,
            "worktree_ready",
            source_commit=source_commit,
            worktree=str(worktree),
        )

        # For declared test-growth tasks, snapshot pytest node IDs from the
        # CLEAN baseline before the agent can touch anything. The file lives
        # in the results directory, outside the model-writable worktree.
        if task.test_growth:
            baseline_env = {
                key: value
                for key, value in os.environ.items()
                if key
                not in {"OPENROUTER_API_KEY", "BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"}
            }
            baseline_ok, baseline_nodes, baseline_error = _collect_pytest_nodes(
                worktree, verify_timeout, env=baseline_env
            )
            (results_dir / "test-growth-baseline.json").write_text(
                json.dumps(
                    {
                        "ok": baseline_ok,
                        "node_ids": baseline_nodes,
                        "error": baseline_error or None,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            _append_event(
                events_path,
                "test_growth_baseline_collected",
                ok=baseline_ok,
                node_count=len(baseline_nodes),
            )

        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        child_env["PYTHONPATH"] = os.pathsep.join(
            [str(root), child_env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        run_id = f"workbench-{task.task_id}-{int(time.time())}"
        command = _agent_command(
            task,
            worktree=worktree,
            run_id=run_id,
            max_turns=max_turns,
            request_timeout=request_timeout,
            provider_retries=provider_retries,
            repeat_tool_call_limit=repeat_tool_call_limit,
            tool_profile=tool_profile,
            env_file=env_file,
        )
        returncode, stdout, stderr, timed_out = _run_process(
            command,
            cwd=root,
            env=child_env,
            timeout=task_timeout,
        )
        (results_dir / "agent.stdout").write_text(stdout, encoding="utf-8")
        (results_dir / "agent.stderr").write_text(stderr, encoding="utf-8")
        result.agent_returncode = returncode
        result.agent_timed_out = timed_out
        _append_event(
            events_path,
            "agent_finished",
            returncode=returncode,
            timed_out=timed_out,
        )
        matches = ACCEPTANCE_RE.findall(stderr)
        result.acceptance_status = matches[-1].lower() if matches else None

        changed = _changed_files(worktree)
        result.changed_files = changed
        (results_dir / "changed_files.json").write_text(
            json.dumps(changed, indent=2) + "\n", encoding="utf-8"
        )
        _write_patch(worktree, source_commit, results_dir)
        _append_event(events_path, "changes_collected", changed_files=changed)

        result.policy_violations = _unexpected_paths(changed, task.allowed_paths)
        if result.policy_violations:
            result.status = "policy_violation"
            result.error = (
                "worker changed paths outside the allowlist: "
                + ", ".join(result.policy_violations)
            )
            _append_event(
                events_path,
                "policy_violation",
                paths=result.policy_violations,
            )
        elif timed_out or PROVIDER_ERROR_RE.search(stderr):
            result.status = "provider_error" if PROVIDER_ERROR_RE.search(stderr) else "not_verified"
            result.error = "agent process timed out" if timed_out else "provider request failed"
        else:
            verify_env = {
                key: value
                for key, value in child_env.items()
                if key
                not in {"OPENROUTER_API_KEY", "BRAVE_API_KEY", "BRAVE_SEARCH_API_KEY"}
            }
            verify_code, verify_stdout, verify_stderr, verify_timed_out = _run_process(
                task.verify_command,
                cwd=worktree,
                env=verify_env,
                timeout=verify_timeout,
                shell=True,
            )
            (results_dir / "verifier.stdout").write_text(verify_stdout, encoding="utf-8")
            (results_dir / "verifier.stderr").write_text(verify_stderr, encoding="utf-8")
            result.verifier_returncode = verify_code
            result.verifier_timed_out = verify_timed_out
            _append_event(
                events_path,
                "verifier_finished",
                returncode=verify_code,
                timed_out=verify_timed_out,
            )
            if verify_timed_out or verify_code is None:
                result.status = "not_verified"
                result.error = "verifier timed out"
            elif verify_code == 0 and returncode == 0 and (
                not task.require_changes or bool(changed)
            ):
                # The acceptance command passed; structural checks must also
                # pass before the attempt counts as verified.
                findings = _structural_findings(
                    worktree, source_commit, changed
                )
                result.structural_findings = findings
                if findings and not task.allow_escaped_newlines:
                    result.status = "structural_violation"
                    result.error = (
                        "added Python lines contain literal escaped-newline "
                        "sequences outside strings (known worker failure mode): "
                        + ", ".join(
                            f"{item['path']}:{item['line']}"
                            for item in findings[:5]
                        )
                    )
                    _append_event(
                        events_path,
                        "structural_violation",
                        findings=findings[:20],
                    )
                elif task.test_growth:
                    growth = _verify_test_growth(
                        task,
                        worktree,
                        changed,
                        results_dir,
                        verify_env,
                        verify_timeout,
                    )
                    result.test_growth = growth
                    (results_dir / "test-growth.json").write_text(
                        json.dumps(growth, indent=2) + "\n", encoding="utf-8"
                    )
                    _append_event(
                        events_path,
                        "test_growth_checked",
                        ok=growth.get("ok"),
                        reason=growth.get("reason"),
                    )
                    if growth.get("ok"):
                        result.status = "verified"
                    else:
                        result.status = "not_verified"
                        result.error = f"test-growth requirement not met: {growth.get('reason')}"
                else:
                    result.status = "verified"
            elif verify_code == 0 and returncode == 0:
                result.status = "not_verified"
                result.error = "worker produced no repository changes"
            elif verify_code == 0 and returncode != 0:
                result.status = "not_verified"
                result.error = "agent did not finish normally although the verifier passed"
            else:
                result.status = "failed"
    except subprocess.CalledProcessError as exc:
        result.error = (exc.stderr or str(exc)).strip()[-1000:]
    except Exception as exc:  # pragma: no cover - defensive boundary for CLI use.
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if worktree is not None and not keep_worktree:
            try:
                root = Path(_run_git(repo, ["rev-parse", "--show-toplevel"]).stdout.strip())
                _run_git(root, ["worktree", "remove", "--force", str(worktree)])
                result.worktree = None
            except Exception as exc:
                result.error = result.error or f"worktree cleanup failed: {exc}"
        result.finished_at = datetime.now(timezone.utc).isoformat()
        result.duration_seconds = round(time.monotonic() - started, 3)
        _append_event(
            events_path,
            "attempt_finished",
            status=result.status,
            error=result.error,
            duration_seconds=result.duration_seconds,
        )
        result.write(results_dir / "result.json")
    return result


def _blocked_result(task: InternalTask, results_root: Path, reason: str) -> AttemptResult:
    """Create a durable result for work that was intentionally not started."""
    results_dir = Path(results_root).expanduser().resolve() / task.task_id / "blocked"
    results_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    result = AttemptResult(
        task_id=task.task_id,
        status="blocked",
        source_ref="",
        source_commit=None,
        worktree=None,
        results_dir=str(results_dir),
        started_at=now,
        finished_at=now,
        error=reason,
    )
    result.write(results_dir / "result.json")
    return result


def run_workbench(
    tasks: Sequence[InternalTask],
    *,
    repo: Path,
    results_root: Path,
    source_ref: str = "HEAD",
    max_concurrency: int = 1,
    max_turns: int = 32,
    request_timeout: float = 60.0,
    provider_retries: int = 3,
    repeat_tool_call_limit: int = 1,
    tool_profile: str = "core4",
    task_timeout: float = 1800.0,
    verify_timeout: float = 120.0,
    keep_worktree: bool = True,
    env_file: Path | None = None,
    runner: Any = run_internal_task,
) -> list[AttemptResult]:
    """Run dependency-aware tasks without merging their worktrees."""
    if not tasks:
        return []
    if not 1 <= max_concurrency <= 4:
        raise ValueError("max_concurrency must be between 1 and 4")
    task_map = {task.task_id: task for task in tasks}
    if len(task_map) != len(tasks):
        raise ValueError("task IDs must be unique")
    for task in tasks:
        missing = [dep for dep in task.depends_on if dep not in task_map]
        if missing:
            raise ValueError(f"{task.task_id} has unknown dependencies: {', '.join(missing)}")

    pending = set(task_map)
    finished: dict[str, AttemptResult] = {}
    batch_id = datetime.now(timezone.utc).strftime("batch-%Y%m%dT%H%M%SZ")

    while pending:
        blocked = []
        ready = []
        for task_id in sorted(pending):
            task = task_map[task_id]
            dependency_results = [finished.get(dep) for dep in task.depends_on]
            if any(result is not None and result.status != "verified" for result in dependency_results):
                blocked.append(task)
            elif all(result is not None for result in dependency_results):
                ready.append(task)
        for task in blocked:
            result = _blocked_result(
                task,
                Path(results_root),
                "dependency did not finish with verified status",
            )
            finished[task.task_id] = result
            pending.remove(task.task_id)
        if not ready:
            if blocked:
                continue
            if pending:
                cycle = ", ".join(sorted(pending))
                raise ValueError(f"dependency cycle prevents progress: {cycle}")
            break

        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            futures = {
                executor.submit(
                    runner,
                    task,
                    repo=repo,
                    results_root=results_root,
                    source_ref=source_ref,
                    max_turns=max_turns,
                    request_timeout=request_timeout,
                    provider_retries=provider_retries,
                    repeat_tool_call_limit=repeat_tool_call_limit,
                    tool_profile=tool_profile,
                    task_timeout=task_timeout,
                    verify_timeout=verify_timeout,
                    keep_worktree=keep_worktree,
                    env_file=env_file,
                    attempt_id=f"{batch_id}-{task.task_id}",
                ): task
                for task in ready
            }
            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensive boundary.
                    result = _blocked_result(task, Path(results_root), f"worker crashed: {exc}")
                    result.status = "infrastructure_error"
                    result.write(Path(result.results_dir) / "result.json")
                finished[task.task_id] = result
                pending.remove(task.task_id)

    ordered = [finished[task.task_id] for task in tasks]
    Path(results_root).expanduser().resolve().mkdir(parents=True, exist_ok=True)
    (Path(results_root).expanduser().resolve() / "workbench.json").write_text(
        json.dumps(
            {
                "source_ref": source_ref,
                "max_concurrency": max_concurrency,
                "tasks": [asdict(result) for result in ordered],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return ordered


def build_review_queue(results_root: Path) -> dict[str, Any]:
    """Classify durable workbench results for human review.

    A passing verifier is evidence, not approval. Changed patches are placed in
    a review queue; provider failures, policy violations, and failed checks are
    placed in an attention queue instead.
    """
    root = Path(results_root).expanduser().resolve()
    summary_path = root / "workbench.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or not isinstance(summary.get("tasks"), list):
        raise ValueError("workbench.json must contain a tasks list")

    review_candidates: list[dict[str, Any]] = []
    completed_without_changes: list[dict[str, Any]] = []
    needs_attention: list[dict[str, Any]] = []
    for item in summary["tasks"]:
        if not isinstance(item, dict):
            needs_attention.append({"error": "invalid task result"})
            continue
        task_id = str(item.get("task_id") or "unknown")
        status = str(item.get("status") or "unknown")
        changed_files = list(item.get("changed_files") or [])
        base = {
            "task_id": task_id,
            "status": status,
            "results_dir": str(item.get("results_dir") or root),
            "changed_files": changed_files,
            "error": item.get("error"),
        }
        if status != "verified":
            needs_attention.append(base)
            continue
        if not changed_files:
            completed_without_changes.append(base)
            continue
        patch_path = Path(base["results_dir"]) / "changes.patch"
        if not patch_path.exists() or patch_path.stat().st_size == 0:
            base["error"] = "verified changes have no reviewable patch"
            needs_attention.append(base)
            continue
        base["human_review_required"] = True
        review_candidates.append(base)

    return {
        "source_ref": summary.get("source_ref", ""),
        "review_candidates": review_candidates,
        "completed_without_changes": completed_without_changes,
        "needs_attention": needs_attention,
    }
