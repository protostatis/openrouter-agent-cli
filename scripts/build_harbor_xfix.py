#!/usr/bin/env python3
"""Generate Harbor-format task dirs for the 3 fixed xfix tasks.

Each task: instruction.md, task.toml, environment/Dockerfile (bakes the
broken fixture into /app), tests/check_task.py + tests/test.sh (verifier,
writes reward 1/0 to /logs/verifier/reward.txt).

Run: uv run python scripts/build_harbor_xfix.py
Output: eval_suites/harbor_xfix/<task_id>/
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "eval_suites" / "harbor_xfix"

TASKS = {
    "xfix12_silent_case": {
        "files": {"emails.txt": "Ann@x.com\nann@x.com\nBob@x.com\ncal@x.com\n",
                  "domains.py": 'lines = open("emails.txt").read().splitlines()\nprint("UNIQUE:", len(set(lines)))\n'},
        "script": "domains.py",
        "expected": "UNIQUE: 3",
        "instruction": (
            "domains.py counts how many unique email addresses are in emails.txt. "
            "It currently prints UNIQUE: 4, but the correct output is UNIQUE: 3. "
            "Fix domains.py so it prints the correct output. Do not modify emails.txt."
        ),
    },
    "xfix01_indexerror": {
        "files": {"pairs.json": '{"pairs_count": 3}',
                  "chain.py": 'import json\nrows = json.load(open("pairs.json"))\nrows = rows["pairs_count"]\nfor i in range(rows):\n    print(i, "->", i + 1)\n'},
        "script": "chain.py",
        "expected": "0 -> 1\n1 -> 2\n2 -> 0",
        "instruction": (
            "chain.py prints number pairs. It currently prints 0 -> 1, 1 -> 2, 2 -> 3, "
            "but the correct output is 0 -> 1, 1 -> 2, 2 -> 0 (the last pair wraps "
            "around to the first). Fix chain.py so it prints the correct output. "
            "Do not modify pairs.json."
        ),
    },
    "xfix09_silent_whitespace": {
        "files": {"signups.txt": "a@x.com \na@x.com\nb@x.com\nc@x.com\n",
                  "uniq.py": 'lines = open("signups.txt").read().splitlines()\nprint("UNIQUE:", len(set(lines)))\n'},
        "script": "uniq.py",
        "expected": "UNIQUE: 3",
        "instruction": (
            "uniq.py counts how many unique lines are in signups.txt. It currently "
            "prints UNIQUE: 4, but the correct output is UNIQUE: 3. Fix uniq.py so it "
            "prints the correct output. Do not modify signups.txt."
        ),
    },
}

TASK_TOML = """version = "1.0"

[task]
name = "{name}"
authors = [{{ name = "openrouter-agent-cli" }}]
keywords = ["terminal", "coding", "silent-bug"]
description = "{desc}"

[verifier]
timeout_sec = 60.0

[agent]
timeout_sec = 900.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true
mcp_servers = []
"""

DOCKERFILE = """FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app/ /app/
"""

CHECK_TASK_PY = """import subprocess
import sys

expected = {expected!r}
script = {script!r}
proc = subprocess.run(["python3", script], cwd="/app", capture_output=True, text=True)
out = proc.stdout.rstrip("\\n")
expected = expected.rstrip("\\n")
if proc.returncode != 0:
    print(f"script crashed: {{proc.stderr.strip()}}")
    sys.exit(2)
if out != expected:
    print(f"wrong output: {{out!r}}, expected {{expected!r}}")
    sys.exit(2)
print("verified")
"""

TEST_SH = """#!/bin/bash
python3 /tests/check_task.py
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
"""

# The user-owned acceptance check lives in the workspace (/app) so the agent
# can see it — that is the product's honest design: the acceptance command is
# a visible check the developer wrote, not a hidden oracle.
ACCEPTANCE_PY = """import subprocess
import sys

expected = {expected!r}
script = {script!r}
proc = subprocess.run(["python3", script], cwd="/app", capture_output=True, text=True)
sys.exit(0 if proc.stdout.rstrip("\\n") == expected.rstrip("\\n") else 1)
"""


def build() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    for tid, spec in TASKS.items():
        task_dir = OUT / tid
        task_dir.mkdir(parents=True)
        (task_dir / "instruction.md").write_text(spec["instruction"] + "\n", encoding="utf-8")
        (task_dir / "task.toml").write_text(
            TASK_TOML.format(name=f"xfix/{tid}", desc=f"{tid}: fix the silent bug"),
            encoding="utf-8",
        )
        app = task_dir / "environment" / "app"
        app.mkdir(parents=True)
        for fname, content in spec["files"].items():
            (app / fname).write_text(content, encoding="utf-8")
        (app / "acceptance.py").write_text(
            ACCEPTANCE_PY.format(expected=spec["expected"], script=spec["script"]),
            encoding="utf-8",
        )
        (task_dir / "environment" / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        tests = task_dir / "tests"
        tests.mkdir(parents=True)
        (tests / "check_task.py").write_text(
            CHECK_TASK_PY.format(expected=spec["expected"], script=spec["script"]),
            encoding="utf-8",
        )
        (tests / "test.sh").write_text(TEST_SH, encoding="utf-8")
        print(f"built {tid}")


if __name__ == "__main__":
    build()