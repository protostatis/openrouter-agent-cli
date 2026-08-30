"""Automated pin-vs-suite audit: every sha256 pin in a verifier file must
match the sha256 of the corresponding setup write_file content in the suite.
This is the regression test for the round-4 mispin false-positive."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SUITE = Path(__file__).resolve().parents[1] / "eval_suites" / "coding_smoke_v1"
VERIFIERS = SUITE / "verifiers"
PIN_RE = re.compile(r'(?:TEST|DATA|SALES)_SHA256 = "([0-9a-f]{64})"')


def _suite():
    return json.loads((SUITE / "suite.json").read_text())


def test_every_pinned_verifier_matches_its_suite_content():
    suite = _suite()
    audited = 0
    for vfile in VERIFIERS.glob("*.py"):
        pins = PIN_RE.findall(vfile.read_text())
        if not pins:
            continue
        tasks = [t for t in suite["tasks"] if vfile.name in t["verifier"]["command"]]
        assert tasks, f"{vfile.name} has pins but no task references it"
        contents = [s["write_file"]["content"] for t in tasks for s in t.get("setup") or []
                    if "write_file" in s]
        assert contents, f"{vfile.name}: task {tasks[0]['id']} has no write_file setup"
        for pin in pins:
            assert any(hashlib.sha256(c.encode()).hexdigest() == pin for c in contents), (
                f"{vfile.name}: pinned sha256 {pin[:12]} matches NO suite setup content "
                f"(the round-4 mispin false-positive pattern)"
            )
        audited += 1
    assert audited >= 5, f"expected at least 5 pinned verifiers, audited {audited}"


def test_spec_files_match_suite_too():
    suite = _suite()
    specs = SUITE / "verifiers" / "specs"
    checked = 0
    for t in suite["tasks"]:
        m = t["verifier"]["command"].split()
        for i, part in enumerate(m):
            if part.endswith(".json") and "specs" in part:
                spec = json.loads((SUITE / part.lstrip("./")).read_text())
                data = next(s["write_file"]["content"] for s in t["setup"]
                            if s["write_file"]["path"] == spec["data_name"])
                assert hashlib.sha256(data.encode()).hexdigest() == spec["data_sha256"], t["id"]
                checked += 1
    assert checked >= 12, f"expected >=12 spec audits, got {checked}"
