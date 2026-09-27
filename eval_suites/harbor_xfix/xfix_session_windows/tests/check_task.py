import json
import os
import subprocess
import sys
import tempfile


EXPECTED = [
    {"user": "alice", "start": "2026-01-01T00:15:00Z", "end": "2026-01-01T00:45:01Z", "events": 4},
    {"user": "alice", "start": "2026-01-01T01:16:02Z", "end": "2026-01-01T01:20:00Z", "events": 2},
    {"user": "bob", "start": "2026-01-02T08:00:00Z", "end": "2026-01-02T08:30:00Z", "events": 2},
    {"user": "bob", "start": "2026-01-02T09:01:00Z", "end": "2026-01-02T09:01:00Z", "events": 1},
]


def run(path):
    return subprocess.run(
        ["python3", "run_sessions.py", path],
        cwd="/app",
        capture_output=True,
        text=True,
    )


proc = run("events.jsonl")
if proc.returncode != 0:
    print("crashed:", proc.stderr.strip()[-200:])
    sys.exit(2)
try:
    output = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
except json.JSONDecodeError as exc:
    print("invalid JSON output:", exc)
    sys.exit(2)
if output != EXPECTED:
    print("wrong sessions:", output)
    sys.exit(2)

alternate = """\
{"user":"zed","ts":"2026-03-01T09:01:01Z"}
{"user":"amy","ts":"2026-03-01T08:30:00Z"}
{"user":"zed","ts":"2026-03-01T08:30:00Z"}
{"user":"amy","ts":"2026-03-01T10:00:00+02:00"}
{"user":"zed","ts":"2026-03-01T08:00:00Z"}
{"user":"amy","ts":"2026-03-01T09:01:00Z"}
"""
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write(alternate)
    alternate_path = fh.name
try:
    proc = run(alternate_path)
finally:
    os.unlink(alternate_path)
if proc.returncode != 0:
    print("alternate crashed:", proc.stderr.strip()[-200:])
    sys.exit(2)
alternate_output = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
alternate_expected = [
    {"user": "amy", "start": "2026-03-01T08:00:00Z", "end": "2026-03-01T08:30:00Z", "events": 2},
    {"user": "amy", "start": "2026-03-01T09:01:00Z", "end": "2026-03-01T09:01:00Z", "events": 1},
    {"user": "zed", "start": "2026-03-01T08:00:00Z", "end": "2026-03-01T08:30:00Z", "events": 2},
    {"user": "zed", "start": "2026-03-01T09:01:01Z", "end": "2026-03-01T09:01:01Z", "events": 1},
]
if alternate_output != alternate_expected:
    print("wrong alternate sessions:", alternate_output)
    sys.exit(2)
print("verified")
