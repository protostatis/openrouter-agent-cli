#!/usr/bin/env python3
"""Check that each Harbor task fails broken and passes known-good fixtures.

This is a verifier contract check, not an agent evaluation. It builds each
task environment, runs the real verifier against the broken fixture, then
mounts a small known-good patch and runs the same verifier again.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = ROOT / "eval_suites" / "harbor_xfix"

KNOWN_GOOD: dict[str, dict[str, str]] = {
    "hard_crashing_script": {
        "report.py": '''import json

with open("sales.json") as fh:
    sales = json.load(fh)

total = sum(float(row["amount"]) for row in sales)
print(f"TOTAL: {total:.2f}")
''',
    },
    "hard_ledger_refunds": {
        "final_balances.json": '{"x": 30, "y": 80}\n',
    },
    "invoice_totals": {
        "pricing.py": '''def price_with_discount(base_price, quantity):
    discount = 0.10 if quantity >= 10 else (0.05 if quantity >= 5 else 0.0)
    return round(base_price * quantity * (1 - discount), 2)
''',
        "invoices.py": '''import json
from pricing import price_with_discount


def build_invoice(items_json):
    items = json.loads(items_json)
    lines = []
    for it in items:
        if it["quantity"] <= 0:
            continue
        unit = price_with_discount(it["unit_price"], it["quantity"])
        lines.append({"name": it["name"], "total": unit})
    subtotal = round(sum(line["total"] for line in lines), 2)
    tax = round(subtotal * 0.08, 2)
    return {"lines": lines, "subtotal": subtotal, "tax": tax,
            "total": round(subtotal + tax, 2)}
''',
    },
    "report_pipeline": {
        "transform.py": '''def process(records, config):
    eligible = [
        r for r in records
        if r["status"] != config.exclude and r["amount"] >= config.threshold
    ]
    groups = {}
    for record in eligible:
        key = record[config.group]
        groups.setdefault(key, []).append(record)
    return groups
''',
        "formatter.py": '''def format_report(records, groups):
    lines = []
    for key in sorted(groups):
        total = round(sum(r["amount"] for r in groups[key]), 2)
        count = len(groups[key])
        lines.append(f"{key},{total:.2f},{count}")
    return "\\n".join(lines)
''',
    },
    "xfix01_indexerror": {
        "chain.py": '''import json

rows = json.load(open("pairs.json"))["pairs_count"]
for i in range(rows):
    print(i, "->", (i + 1) % rows)
''',
    },
    "xfix05_zerodiv_empty": {
        "avgshare.py": '''import json

d = json.load(open("share.json"))
for k in sorted(d):
    if d[k]:
        print(k, sum(d[k]) / len(d[k]))
''',
    },
    "xfix09_silent_whitespace": {
        "uniq.py": '''lines = open("signups.txt").read().splitlines()
print("UNIQUE:", len({line.strip() for line in lines}))
''',
    },
    "xfix11_typeerror_items": {
        "pairs.py": '''import json

for k, v in json.load(open("routes.json")):
    print(k, v)
''',
    },
    "xfix12_silent_case": {
        "domains.py": '''lines = open("emails.txt").read().splitlines()
print("UNIQUE:", len({line.lower() for line in lines}))
''',
    },
    "xfix_session_windows": {
        "event_parser.py": '''import json
from datetime import datetime, timezone


def _parse_timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def load_events(path):
    events = []
    with open(path) as fh:
        for line in fh:
            row = json.loads(line)
            events.append({"user": row["user"], "at": _parse_timestamp(row["ts"])})
    return events
''',
        "sessionizer.py": '''from datetime import timedelta


def _format(when):
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize(events):
    grouped = {}
    for event in events:
        grouped.setdefault(event["user"], []).append(event)

    sessions = []
    for user, user_events in grouped.items():
        ordered = sorted(user_events, key=lambda event: event["at"])
        current = None
        for event in ordered:
            if current is None or event["at"] - current["last"] > timedelta(minutes=30):
                current = {"user": user, "start": event["at"], "end": event["at"],
                           "events": 1, "last": event["at"]}
                sessions.append(current)
            else:
                current["end"] = event["at"]
                current["last"] = event["at"]
                current["events"] += 1

    output = []
    for session in sessions:
        output.append({"user": session["user"], "start": _format(session["start"]),
                       "end": _format(session["end"]), "events": session["events"]})
    return sorted(output, key=lambda session: (session["user"], session["start"]))
''',
    },
    "xfix_config_precedence": {
        "cli.py": '''def parse_cli(argv):
    values = {}
    for arg in argv:
        if not arg.startswith("--") or "=" not in arg:
            raise ValueError("invalid flag")
        name, value = arg[2:].split("=", 1)
        if name not in {"endpoint", "workers", "debug", "retries"}:
            raise ValueError("unknown flag")
        values[name] = value
    return values
''',
        "config_loader.py": '''import json
import os

from cli import parse_cli


DEFAULTS = json.load(open("defaults.json"))


def _coerce(name, value):
    if name == "endpoint":
        value = str(value)
        if not value:
            raise ValueError("endpoint must be non-empty")
        return value
    if name in {"workers", "retries"}:
        number = int(value)
        lower, upper = (1, 64) if name == "workers" else (0, 10)
        if not lower <= number <= upper:
            raise ValueError(f"invalid {name}")
        return number
    if name == "debug":
        if isinstance(value, bool):
            return value
        normalized = str(value).lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        raise ValueError("invalid debug")
    raise ValueError("unknown key")


def load_config(argv=None):
    result = dict(DEFAULTS)
    result.update(json.load(open("config.json")))
    env_values = {}
    for name in result:
        env_name = "APP_" + name.upper()
        if env_name in os.environ:
            env_values[name] = os.environ[env_name]
    cli_values = parse_cli(argv or [])
    for source in (env_values, cli_values):
        for name, value in source.items():
            result[name] = _coerce(name, value)
    return {name: _coerce(name, value) for name, value in result.items()}
        ''',
    },
    "xfix_atomic_reservations": {
        "reservation_engine.py": '''def process_orders(orders, inventory):
    stock = dict(inventory)
    accepted = []
    rejected = []
    seen = set()
    for order in orders:
        order_id = order["id"]
        if order_id in seen:
            continue
        seen.add(order_id)
        needed = {}
        for line in order["lines"]:
            sku = line["sku"]
            needed[sku] = needed.get(sku, 0) + line["quantity"]
        if any(sku not in stock or stock[sku] < quantity for sku, quantity in needed.items()):
            rejected.append(order_id)
            continue
        for sku, quantity in needed.items():
            stock[sku] -= quantity
        accepted.append(order_id)
    return {"accepted": accepted, "rejected": rejected, "inventory": stock}
''',
    },
    "xfix_dependency_plan": {
        "planner.py": '''def plan(jobs):
    names = {job["name"] for job in jobs}
    remaining = {job["name"]: set(job["depends_on"]) for job in jobs}
    if any(dependency not in names for dependencies in remaining.values() for dependency in dependencies):
        raise ValueError("missing_dependency")
    ready = {name for name, dependencies in remaining.items() if not dependencies}
    output = []
    while ready:
        name = min(ready)
        ready.remove(name)
        output.append(name)
        for other, dependencies in remaining.items():
            if name in dependencies:
                dependencies.remove(name)
                if not dependencies:
                    ready.add(other)
    if len(output) != len(names):
        raise ValueError("cycle")
    return output
        ''',
    },
    "xfix_safe_archive_extract": {
        "archive_policy.py": '''import posixpath
import stat


def _normalized(info):
    name = info.filename
    if name.startswith("/"):
        raise ValueError("absolute_path")
    if any(part == ".." for part in name.split("/")):
        raise ValueError("path_traversal")
    mode = (info.external_attr >> 16) & 0o170000
    if mode == stat.S_IFLNK:
        raise ValueError("symlink")
    if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError("unsupported_type")
    normalized = posixpath.normpath(name)
    if normalized in {"", "."}:
        raise ValueError("unsupported_type")
    return normalized, info.is_dir() or name.endswith("/")


def validate_members(infos):
    entries = {}
    for info in infos:
        normalized, is_dir = _normalized(info)
        kind = "dir" if is_dir else "file"
        if normalized in entries:
            if entries[normalized] != kind:
                raise ValueError("path_conflict")
            raise ValueError("duplicate_path")
        for existing, existing_kind in entries.items():
            if normalized.startswith(existing + "/") and existing_kind == "file":
                raise ValueError("path_conflict")
            if existing.startswith(normalized + "/") and kind == "file":
                raise ValueError("path_conflict")
        entries[normalized] = kind
''',
        "extract_archive.py": '''from pathlib import Path
import zipfile

from archive_policy import validate_members


def extract(archive_path, destination):
    destination = Path(destination)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        validate_members(infos)
        destination.mkdir()
        count = 0
        for info in infos:
            target = destination / info.filename
            normalized = Path(*info.filename.split("/"))
            target = destination / normalized
            if info.is_dir() or info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                output.write(source.read())
            count += 1
        return count
''',
    },
}


def _run_verifier(
    image: str, verifier: Path, overrides: dict[str, str], temp_dir: Path
) -> subprocess.CompletedProcess[str]:
    mounts = [
        "-v",
        f"{verifier}:/tests/check_task.py:ro",
    ]
    for relative_path, content in overrides.items():
        host_path = temp_dir / relative_path
        host_path.parent.mkdir(parents=True, exist_ok=True)
        host_path.write_text(content, encoding="utf-8")
        mounts.extend(["-v", f"{host_path}:/app/{relative_path}:ro"])
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python3",
            *mounts,
            image,
            "/tests/check_task.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def check_task(task_dir: Path) -> dict:
    name = task_dir.name
    image = f"ora-contract-{name.replace('_', '-') }"
    environment = task_dir / "environment"
    verifier = task_dir / "tests" / "check_task.py"
    result = {"task": name, "broken": None, "known_good": None, "error": None}
    try:
        build = subprocess.run(
            ["docker", "build", "--quiet", "-t", image, str(environment)],
            capture_output=True,
            text=True,
            check=False,
        )
        if build.returncode != 0:
            result["error"] = f"docker build failed: {build.stderr.strip()[-500:]}"
            return result
        with tempfile.TemporaryDirectory(prefix=f"contract-{name}-") as temp:
            broken = _run_verifier(image, verifier, {}, Path(temp) / "broken")
            good = _run_verifier(
                image,
                verifier,
                KNOWN_GOOD[name],
                Path(temp) / "known-good",
            )
        result["broken"] = {
            "return_code": broken.returncode,
            "output": (broken.stdout or broken.stderr).strip()[-500:],
            "expected_return_code": 2,
        }
        result["known_good"] = {
            "return_code": good.returncode,
            "output": (good.stdout or good.stderr).strip()[-500:],
            "expected_return_code": 0,
        }
    finally:
        subprocess.run(
            ["docker", "image", "rm", "-f", image],
            capture_output=True,
            text=True,
            check=False,
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", help="Task directory name; repeatable.")
    args = parser.parse_args()
    names = args.task or sorted(KNOWN_GOOD)
    unknown = sorted(set(names) - set(KNOWN_GOOD))
    if unknown:
        parser.error(f"unknown task(s): {', '.join(unknown)}")

    results = [check_task(TASK_ROOT / name) for name in names]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if all(
        result["error"] is None
        and result["broken"]["return_code"] == 2
        and result["known_good"]["return_code"] == 0
        for result in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
