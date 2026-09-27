#!/usr/bin/env python3
"""Create a human-review queue from a completed internal workbench run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openrouter_agent_cli.workbench import build_review_queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    root = Path(args.results_dir).expanduser().resolve()
    try:
        queue = build_review_queue(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    (root / "review-queue.json").write_text(
        json.dumps(queue, indent=2) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(queue, indent=2))
    else:
        print(f"Review candidates: {len(queue['review_candidates'])}")
        for item in queue["review_candidates"]:
            print(f"- {item['task_id']}: {', '.join(item['changed_files'])}")
        print(f"Completed without changes: {len(queue['completed_without_changes'])}")
        print(f"Needs attention: {len(queue['needs_attention'])}")
        for item in queue["needs_attention"]:
            print(f"- {item['task_id']}: {item.get('status')} — {item.get('error') or 'no details'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
