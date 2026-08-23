"""Regression tests for assistant output rendering (markdown-formatting branch).

Covers:
- _output_response interactive path renders Markdown with "assistant>" prefix
- non-interactive path prints raw text with trailing newline
- fallback path when rich is unavailable
- untrusted-output hardening: control chars stripped, hyperlinks disabled
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from openrouter_agent_cli import cli as cli_mod
from openrouter_agent_cli.cli import OpenRouterAgentCLI, _strip_control_chars


@pytest.fixture
def make_cli():
    def _make(non_interactive: bool = False) -> OpenRouterAgentCLI:
        inst = OpenRouterAgentCLI(
            api_key="test-key",
            model="test-model",
            session_id="out-test",
            workdir=".",
            max_turns=1,
            max_history_messages=50,
            command_timeout=10,
            tools_enabled=False,
            system_prompt="s",
            discovery_mode="off",
            max_concurrency=1,
            max_discover=1,
            max_rounds=1,
        )
        inst.non_interactive_mode = non_interactive
        return inst

    return _make


MD = "# Title\n\nThis is **bold**.\n\n| a | b |\n|---|---|\n| 1 | 2 |"


def test_non_interactive_prints_raw_with_newline(make_cli, capsys):
    out = make_cli(non_interactive=True)._output_response(MD)
    captured = capsys.readouterr()
    assert out == MD
    assert captured.out == MD + "\n"


def test_interactive_renders_markdown_with_prefix(make_cli):
    # Force the rich path regardless of test-env availability.
    with (
        patch.object(cli_mod, "Console", cli_mod.Console),
        patch.object(cli_mod, "Markdown", cli_mod.Markdown),
    ):
        buf = io.StringIO()
        with patch.object(cli_mod, "sys") as fake_sys:
            fake_sys.stdout = buf
            out = make_cli()._output_response(MD)
    rendered = buf.getvalue()
    assert out == MD
    assert "assistant>" in rendered
    if cli_mod.Console is not None and cli_mod.Markdown is not None:
        assert "**bold**" not in rendered  # markdown actually rendered
        assert "| a | b |" not in rendered  # table drawn as box, not pipes


def test_fallback_without_rich_keeps_original_format(make_cli, capsys):
    saved = (cli_mod.Console, cli_mod.Markdown)
    cli_mod.Console = None
    cli_mod.Markdown = None
    try:
        out = make_cli()._output_response("hello **world**")
        captured = capsys.readouterr()
    finally:
        cli_mod.Console, cli_mod.Markdown = saved
    assert out == "hello **world**"
    assert captured.out == "\nassistant> hello **world**\n\n"


def test_strip_control_chars_removes_escapes_but_keeps_newlines():
    text = "ok\x1b[31mred\x1b[0m\nline2\x07\tend"
    cleaned = _strip_control_chars(text)
    assert "\x1b" not in cleaned
    assert "\x07" not in cleaned
    assert "\n" in cleaned and "\t" in cleaned
    assert "red" in cleaned and "line2" in cleaned


def test_interactive_passes_hyperlinks_false_and_sanitized_text(make_cli):
    if cli_mod.Console is None or cli_mod.Markdown is None:
        pytest.skip("rich not installed")
    calls: dict = {}

    class FakeMarkdown:
        def __init__(self, text, **kwargs):
            calls["text"] = text
            calls["hyperlinks"] = kwargs.get("hyperlinks")

        def __rich_console__(self, console, options):
            yield "rendered"

    nasty = "visit \x1b]8;;http://evil\x1b\\click\x07"
    with (
        patch.object(cli_mod, "Console", lambda **kw: type("C", (), {"print": staticmethod(lambda *a, **k: None)})()),
        patch.object(cli_mod, "Markdown", FakeMarkdown),
    ):
        make_cli()._output_response(nasty)
    assert calls["hyperlinks"] is False
    assert "\x1b" not in calls["text"]
    assert "\x07" not in calls["text"]
