#!/usr/bin/env python3
"""Compatibility wrapper for ``openrouter-agent-eval``."""
from openrouter_agent_cli.eval.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
