import json
import os
import subprocess
import sys
import tempfile


def run(jobs):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(jobs, fh)
        path = fh.name
    try:
        return subprocess.run(
            ["python3", "run_plan.py", path],
            cwd="/app",
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(path)


def expect_valid(jobs, expected):
    proc = run(jobs)
    if proc.returncode != 0 or json.loads(proc.stdout) != expected:
        print("wrong valid result:", proc.returncode, proc.stdout, "expected:", expected)
        sys.exit(2)


def expect_error(jobs, expected):
    proc = run(jobs)
    if proc.returncode != 2 or json.loads(proc.stdout) != {"error": expected}:
        print("wrong error result:", proc.returncode, proc.stdout, "expected:", expected)
        sys.exit(2)


expect_valid(
    [
        {"name": "a", "depends_on": []},
        {"name": "b", "depends_on": []},
        {"name": "c", "depends_on": ["a"]},
        {"name": "d", "depends_on": ["b"]},
    ],
    ["a", "b", "c", "d"],
)
expect_valid(
    [
        {"name": "zeta", "depends_on": []},
        {"name": "alpha", "depends_on": []},
        {"name": "middle", "depends_on": ["alpha", "zeta"]},
    ],
    ["alpha", "zeta", "middle"],
)
expect_valid(
    [
        {"name": "root", "depends_on": []},
        {"name": "other", "depends_on": []},
        {"name": "child", "depends_on": ["root"]},
        {"name": "leaf", "depends_on": ["child"]},
    ],
    ["other", "root", "child", "leaf"],
)
expect_error(
    [{"name": "a", "depends_on": ["not-present"]}],
    "missing_dependency",
)
expect_error(
    [
        {"name": "ready", "depends_on": []},
        {"name": "left", "depends_on": ["right"]},
        {"name": "right", "depends_on": ["left"]},
    ],
    "cycle",
)
print("verified")
