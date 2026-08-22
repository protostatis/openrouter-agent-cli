"""Standalone OpenRouter agent CLI with basic actions and context management."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from openrouter_agent_cli.utils import (
    OPENROUTER_URL,
    _decode_tool_arguments,
    call_openrouter,
    run_bash,
)

try:
    from openrouter_agent_cli.concurrent import run_concurrent
except ImportError:  # pragma: no cover
    run_concurrent = None  # type: ignore

try:
    from openrouter_agent_cli.discovery import run_discover
except ImportError:  # pragma: no cover
    run_discover = None  # type: ignore

# Default to a free-tier model so first-run usage does not consume paid credits.
DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning:free"
DEFAULT_SESSION_ID = "default"
DEFAULT_MAX_TURNS = 24
DEFAULT_MAX_HISTORY_MESSAGES = 60
DEFAULT_COMMAND_TIMEOUT = 30
CONTEXT_KEEP_TAIL = 10

DEFAULT_SYSTEM_PROMPT = """You are a pragmatic coding assistant in a terminal.
Use tools only when needed. Explain outputs clearly and stay concise.
When unsure, ask for clarification before destructive operations.

Tool use:
- read_file/write_file/edit_file: workdir-jail file ops (preferred for files — they enforce workdir jail). Use these over shell for file reads/writes.
- run_bash: local shell with cwd=workdir (not jailed; can run any command). Use for git, tests, builds, and when file tools are insufficient.
- discover: web search/navigate via browser (https only, private addresses blocked). This is a normal tool_call like run_bash.
  Agent fills it: discover(kind="search", query="...", goal="...") or discover(kind="navigate", url="...", goal="...").
  You fill query/url/goal yourself from the user task — no human prompt needed.
  AGENT-DEFINED LIMITS (you decide, within caps):
  - Per-batch discover calls: 1 to max_discover (default cap 5, you choose 2-5 based on task). For purchase/decision tasks, use diverse template: [search review] [navigate rtings/spec] [search vs comparison] [navigate wiki/history] [search complaints] — all in ONE parallel response.
  - Rounds: 1 to max_rounds (default cap 2). If first batch is shallow or needs verification, emit a 2nd batch that deepens SAME topic (verify claims, official specs, contradictions) before final synthesis. You decide 1 vs 2 rounds from context and prior results.
  - Concurrency cap: max_concurrency (default 5) limits parallel execution; shell/file tools always serialize even if mixed.
  You invoke your own LLM again next turn to synthesize results. The discover tool can invoke LLM extraction internally (navigate_auto with goal) — you don't need to fetch manually.
"""

DISCOVER_TOOL = {
    "type": "function",
    "function": {
        "name": "discover",
        "description": (
            "Web discovery via pyunbrowser smart client (agent fills this tool_call itself, defines its own limits). "
            "Use kind='search' for a query (Brave search) or kind='navigate' for a specific URL (fetch + auto-discover with LLM extraction on goal). "
            "Agent must fill query/url/goal from user task. For research, agent defines batch size 1..max_discover (cap 5) and emits that many IN THE SAME RESPONSE (parallel tool calls) to cover different angles — diverse template: search review, navigate specs, search vs, navigate wiki, search complaints. "
            "Agent also defines rounds 1..max_rounds (cap 2): if shallow, emit 2nd batch deepening same topic before synth. "
            "Each discover in a batch runs concurrently (cap max_concurrency). The tool can invoke LLM internally; outer agent invokes its own LLM next turn to synthesize. "
            "Prefer discover for web, run_bash for local; can mix both but mixed batches serialize."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["search", "navigate"], "description": "search=query, navigate=URL"},
                "query": {"type": "string", "description": "Search query (for kind=search)."},
                "url": {"type": "string", "description": "URL to fetch + auto-discover (for kind=navigate)."},
                "goal": {"type": "string", "description": "What this objective should surface / why it matters."},
            },
            "required": ["kind", "goal"],
        },
    },
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": (
                "Run a shell command in the current working directory and return stdout/stderr."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Execution timeout in seconds (1-600).",
                        "default": DEFAULT_COMMAND_TIMEOUT,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file and return it as text. "
                "Supports optional line range for large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file (relative to working directory or absolute).",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Start line (1-indexed). Default: 1.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "End line (1-indexed, inclusive). Default: last line.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file, creating or overwriting it. "
                "Creates parent directories if they do not exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file (relative to working directory or absolute).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Edit an existing file by replacing a specific text block. "
                "The old_string must match exactly (including whitespace). "
                "Use read_file first to see the current content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file (relative to working directory or absolute).",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Exact text block to replace (must match uniquely in the file).",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement text block.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    DISCOVER_TOOL,
]


def _sanitize_session_id(session_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", session_id)
    return safe or DEFAULT_SESSION_ID


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _message_content_as_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False)


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    chars = 0
    for msg in messages:
        chars += len(_message_content_as_text(msg))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            chars += len(str(fn.get("name", "")))
            chars += len(str(fn.get("arguments", "")))
    return max(1, chars // 4)


@dataclass
class ToolPermissionPolicy:
    allow: set[str] = field(default_factory=set)
    deny: set[str] = field(default_factory=set)

    def decision(self, tool_name: str) -> str:
        if "*" in self.deny or tool_name in self.deny:
            return "deny"
        if "*" in self.allow or tool_name in self.allow:
            return "allow"
        return "ask"


class OpenRouterAgentCLI:
    def __init__(
        self,
        api_key: str,
        model: str,
        session_id: str,
        workdir: str,
        max_turns: int,
        max_history_messages: int,
        command_timeout: int,
        tools_enabled: bool,
        system_prompt: str,
        discovery_mode: str = "auto",
        max_concurrency: int = 5,
        max_discover: int = 5,
        max_rounds: int = 2,
    ):
        self.api_key = api_key
        self.model = model
        self.session_id = _sanitize_session_id(session_id)
        self.workdir = os.path.abspath(workdir)
        self.max_turns = max(1, max_turns)
        self.max_history_messages = max(8, max_history_messages)
        self.command_timeout = min(max(1, command_timeout), 600)
        self.tools_enabled = tools_enabled
        self.system_prompt = system_prompt
        self.discovery_mode = discovery_mode  # auto|mock|real|off
        self.max_concurrency = max(1, min(16, max_concurrency))
        self.max_discover = max(1, min(10, max_discover))
        self.max_rounds = max(1, min(5, max_rounds))
        self.non_interactive_mode = False
        self.policy = ToolPermissionPolicy()
        self.one_shot_prompt: str | None = None
        self.session_tokens: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        self.session_root = Path(
            os.environ.get(
                "OPENROUTER_AGENT_SESSION_DIR", "~/.openrouter-agent-cli/sessions"
            )
        ).expanduser()
        self.session_root.mkdir(parents=True, exist_ok=True)
        self._policy_path = self.session_root.parent / "policy.json"
        self._load_policy()
        self.messages = self._load_session()

    def _log(self, message: str, *, end: str = "\n") -> None:
        target = sys.stderr if self.non_interactive_mode else sys.stdout
        print(message, file=target, end=end)

    def _output_response(self, text: str) -> str:
        if self.non_interactive_mode:
            print(text)
        else:
            print(f"\nassistant> {text}\n")
        return text

    @property
    def _session_path(self) -> Path:
        return self.session_root / f"{self.session_id}.json"

    def _load_session(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._session_path.read_text())
            stored = data.get("messages", [])
            if isinstance(stored, list):
                stored_prompt = data.get("system_prompt", "")
                if stored_prompt and stored_prompt != self.system_prompt:
                    print(
                        "[session] System prompt changed since last session. "
                        "Old conversation context may reference the previous prompt.",
                        file=sys.stderr,
                    )
                return [{"role": "system", "content": self.system_prompt}] + stored
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[session] Failed to load session: {e}")
        return [{"role": "system", "content": self.system_prompt}]

    def _save_session(self):
        non_system = [m for m in self.messages if m.get("role") != "system"]
        if len(non_system) > self.max_history_messages:
            non_system = non_system[-self.max_history_messages :]
        payload = {"messages": non_system, "system_prompt": self.system_prompt}
        try:
            self._session_path.write_text(json.dumps(payload))
        except Exception as e:
            print(f"[session] Failed to save session: {e}")

    def _load_policy(self) -> None:
        try:
            data = json.loads(self._policy_path.read_text())
            allow = data.get("allow", [])
            deny = data.get("deny", [])
            if isinstance(allow, list):
                self.policy.allow = set(str(x) for x in allow if isinstance(x, str))
            if isinstance(deny, list):
                self.policy.deny = set(str(x) for x in deny if isinstance(x, str))
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[policy] Failed to load policy: {e}", file=sys.stderr)

    def _save_policy(self) -> None:
        try:
            payload = {"allow": sorted(self.policy.allow), "deny": sorted(self.policy.deny)}
            self._policy_path.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            print(f"[policy] Failed to save policy: {e}", file=sys.stderr)

    def _tool_names(self) -> list[str]:
        names: list[str] = []
        for tool in TOOLS:
            fn = tool.get("function", {})
            name = fn.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return sorted(names)

    async def run(self):
        if not self.non_interactive_mode:
            print("OpenRouter Agent CLI")
            print(f"Model      : {self.model}")
            print(f"Session    : {self.session_id}")
            print(f"Working dir: {self.workdir}")
            print(f"Discovery  : {self.discovery_mode} (max_discover={self.max_discover}, max_rounds={self.max_rounds}, max_concurrency={self.max_concurrency}) [agent-defined within caps]")
            print("Type /help for commands. Type /exit to quit.")
            print()

        async with httpx.AsyncClient(timeout=60.0) as client:
            if self.one_shot_prompt:
                await self._run_user_turn(client, self.one_shot_prompt)
                return

            while True:
                try:
                    user_text = await asyncio.to_thread(input, "you> ")
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting.")
                    break

                user_text = user_text.strip()
                if not user_text:
                    continue

                if user_text.startswith("/"):
                    keep_running = await self._handle_command(client, user_text)
                    if not keep_running:
                        break
                    continue

                await self._run_user_turn(client, user_text)

    async def _handle_command(
        self, client: httpx.AsyncClient, command_line: str
    ) -> bool:
        parts = command_line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            return False

        if cmd == "/help":
            print("Commands:")
            print("  /help                 Show help")
            print("  /exit                 Exit")
            print("  /new [id]             New session (fresh history, like every harness)")
            print("  /model [id]           Show or set model")
            print("  /usage                Show message count + rough token estimate")
            print("  /context [n]          Show last n messages (default 8)")
            print("  /compact              Force conversation compaction")
            print("  /clear                Clear session history (same id)")
            print("  /tools                Show tools + permission policy")
            print("  /tools on|off         Enable or disable tool calling")
            print("  /allow <tool|*>       Always allow tool")
            print("  /deny <tool|*>        Always deny tool")
            print("  /unallow <tool|*>     Remove allow rule")
            print("  /undeny <tool|*>      Remove deny rule")
            print("  /cwd [path]           Show or set working directory")
            print("  /discovery [auto|mock|real|off]  Show or set discovery mode")
            print("  /concurrency [n]      Show or set max concurrent tool calls (1-16)")
            print("  /max-discover [n]     Show or set cap for discover per batch (1-10, agent defines within)")
            print("  /max-rounds [n]       Show or set cap for discover rounds (1-5, agent defines within)")
            return True

        if cmd == "/model":
            if not arg:
                print(f"Current model: {self.model}")
            else:
                self.model = arg
                print(f"Model set to: {self.model}")
            return True

        if cmd == "/usage":
            msg_count = len([m for m in self.messages if m.get("role") != "system"])
            token_est = _estimate_tokens(self.messages)
            actual = self.session_tokens
            print(f"Messages (non-system) : {msg_count}")
            print(f"Estimated tokens      : ~{token_est}")
            print(f"Actual session tokens : {actual['total_tokens']}")
            print(f"  prompt_tokens       : {actual['prompt_tokens']}")
            print(f"  completion_tokens   : {actual['completion_tokens']}")
            print(f"History limit         : {self.max_history_messages}")
            return True

        if cmd == "/context":
            n = 8
            if arg:
                try:
                    n = max(1, int(arg))
                except ValueError:
                    print("Usage: /context [n]")
                    return True
            context = self.messages[-n:]
            print(f"Last {len(context)} messages:")
            for i, msg in enumerate(context, 1):
                role = msg.get("role", "unknown")
                text = _truncate(_message_content_as_text(msg).replace("\n", " "), 180)
                print(f"  {i:>2}. {role}: {text}")
            return True

        if cmd == "/compact":
            compacted = await self._compact_history(client, force=True)
            print("Context compacted." if compacted else "Nothing to compact.")
            return True

        if cmd == "/clear":
            self.messages = [{"role": "system", "content": self.system_prompt}]
            self._save_session()
            print("Session history cleared.")
            return True

        if cmd == "/new":
            new_id = arg.strip() or f"session-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
            old_id = self.session_id
            self.session_id = _sanitize_session_id(new_id)
            self.messages = [{"role": "system", "content": self.system_prompt}]
            # keep allow/deny policy? /new starts fresh but keeps it; uncomment to reset:
            # self.policy = ToolPermissionPolicy()
            self._save_session()
            print(f"New session: {self.session_id} (was {old_id}) — history reset")
            return True

        if cmd == "/tools":
            lowered = arg.lower()
            if lowered in ("on", "off"):
                self.tools_enabled = lowered == "on"
                print(f"Tools {'enabled' if self.tools_enabled else 'disabled'}.")
                return True
            print(f"Tools enabled: {self.tools_enabled}")
            print(f"Available tools: {', '.join(self._tool_names())}")
            print(
                f"Allow list: {sorted(self.policy.allow) if self.policy.allow else '[]'}"
            )
            print(
                f"Deny list : {sorted(self.policy.deny) if self.policy.deny else '[]'}"
            )
            return True

        if cmd == "/allow":
            if not arg:
                print("Usage: /allow <tool_name|*>")
                return True
            self.policy.allow.add(arg)
            self.policy.deny.discard(arg)
            self._save_policy()
            print(f"Always allow: {arg} (cached across sessions)")
            return True

        if cmd == "/deny":
            if not arg:
                print("Usage: /deny <tool_name|*>")
                return True
            self.policy.deny.add(arg)
            self.policy.allow.discard(arg)
            self._save_policy()
            print(f"Always deny: {arg} (cached across sessions)")
            return True

        if cmd == "/unallow":
            if not arg:
                print("Usage: /unallow <tool_name|*>")
                return True
            self.policy.allow.discard(arg)
            self._save_policy()
            print(f"Removed allow rule: {arg}")
            return True

        if cmd == "/undeny":
            if not arg:
                print("Usage: /undeny <tool_name|*>")
                return True
            self.policy.deny.discard(arg)
            self._save_policy()
            print(f"Removed deny rule: {arg}")
            return True

        if cmd == "/cwd":
            if not arg:
                print(f"Current working directory: {self.workdir}")
                return True
            candidate = os.path.abspath(os.path.expanduser(arg))
            if not os.path.isdir(candidate):
                print(f"Directory not found: {candidate}")
                return True
            self.workdir = candidate
            print(f"Working directory set to: {self.workdir}")
            return True

        if cmd == "/discovery":
            if not arg:
                print(f"Discovery mode: {self.discovery_mode}")
                return True
            if arg not in ("auto", "mock", "real", "off"):
                print("Usage: /discovery [auto|mock|real|off]")
                return True
            self.discovery_mode = arg
            print(f"Discovery mode set to: {self.discovery_mode}")
            return True

        if cmd == "/concurrency":
            if not arg:
                print(f"Max concurrency: {self.max_concurrency} (agent-defined within cap)")
                return True
            try:
                n = int(arg)
                self.max_concurrency = max(1, min(16, n))
                print(f"Max concurrency set to: {self.max_concurrency}")
            except ValueError:
                print("Usage: /concurrency [n]  (1-16)")
            return True

        if cmd == "/max-discover":
            if not arg:
                print(f"Max discover per batch: {self.max_discover} (agent defines 1..cap)")
                return True
            try:
                n = int(arg)
                self.max_discover = max(1, min(10, n))
                print(f"Max discover per batch set to: {self.max_discover}")
            except ValueError:
                print("Usage: /max-discover [n]  (1-10)")
            return True

        if cmd == "/max-rounds":
            if not arg:
                print(f"Max rounds: {self.max_rounds} (agent defines 1..cap)")
                return True
            try:
                n = int(arg)
                self.max_rounds = max(1, min(5, n))
                print(f"Max rounds set to: {self.max_rounds}")
            except ValueError:
                print("Usage: /max-rounds [n]  (1-5)")
            return True

        print(f"Unknown command: {cmd}. Use /help.")
        return True

    async def _call_openrouter(
        self,
        client: httpx.AsyncClient,
        messages: list[dict[str, Any]],
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        if self.discovery_mode == "off":
            tools = [t for t in TOOLS if t["function"]["name"] != "discover"] if self.tools_enabled and tool_choice != "none" else None
        else:
            tools = TOOLS if self.tools_enabled and tool_choice != "none" else None
        effective_tool_choice = (
            "none" if tool_choice == "none" or not self.tools_enabled else "auto"
        )
        # Enable parallel tool calls when discovery batching is available
        parallel = True if (self.discovery_mode != "off" and self.tools_enabled and tool_choice != "none") else None
        data = await call_openrouter(
            client,
            api_key=self.api_key,
            model=self.model,
            messages=messages,
            max_tokens=4096,
            tool_choice=effective_tool_choice,
            tools=tools,
            parallel_tool_calls=parallel,
        )

        usage = data.get("usage") or {}
        if usage:
            self.session_tokens["prompt_tokens"] += int(usage.get("prompt_tokens", 0))
            self.session_tokens["completion_tokens"] += int(
                usage.get("completion_tokens", 0)
            )
            self.session_tokens["total_tokens"] += int(usage.get("total_tokens", 0))

        return data

    async def _compact_history(
        self, client: httpx.AsyncClient, force: bool = False
    ) -> bool:
        non_system = [m for m in self.messages if m.get("role") != "system"]
        if not force and len(non_system) <= self.max_history_messages:
            return False
        if len(non_system) <= CONTEXT_KEEP_TAIL + 2:
            return False

        older = non_system[:-CONTEXT_KEEP_TAIL]
        tail = non_system[-CONTEXT_KEEP_TAIL:]

        transcript_lines = []
        for msg in older[-80:]:
            role = msg.get("role", "unknown")
            text = _truncate(_message_content_as_text(msg).replace("\n", " "), 500)
            transcript_lines.append(f"{role}: {text}")
        transcript = "\n".join(transcript_lines) or "No prior messages."

        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "Summarize prior conversation for continuation. "
                    "Return short bullets: goals, decisions, facts, TODOs, constraints. "
                    "Keep below 180 words."
                ),
            },
            {"role": "user", "content": transcript},
        ]

        summary = ""
        try:
            summary_resp = await self._call_openrouter(
                client, summary_prompt, tool_choice="none"
            )
            summary_msg = summary_resp["choices"][0]["message"]
            summary = (
                summary_msg.get("content") or summary_msg.get("reasoning") or ""
            ).strip()
        except Exception as e:
            summary = f"Compaction summary failed: {e}"

        if not summary:
            summary = "No significant prior context."

        summary_entry = {
            "role": "assistant",
            "content": f"[Context summary]\n{summary}",
        }
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            summary_entry,
            *tail,
        ]
        self._save_session()
        return True

    async def _confirm_tool_call(self, tool_name: str, args: dict[str, Any]) -> bool:
        if self.non_interactive_mode:
            self._log(
                f"[permission] Tool '{tool_name}' denied in non-interactive mode."
            )
            return False
        preview = _truncate(json.dumps(args, ensure_ascii=False), 220)
        question = (
            f"[permission] Allow tool '{tool_name}' args={preview}? "
            "[y]es/[n]o/[a]lways allow/[d]eny always: "
        )
        choice = (await asyncio.to_thread(input, question)).strip().lower()
        if choice == "a":
            self.policy.allow.add(tool_name)
            self.policy.deny.discard(tool_name)
            self._save_policy()
            return True
        if choice == "d":
            self.policy.deny.add(tool_name)
            self.policy.allow.discard(tool_name)
            self._save_policy()
            return False
        return choice in ("y", "yes")

    def _resolve_file_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.workdir) / p
        return p.resolve()

    def _validate_path_in_workdir(self, path: Path) -> str | None:
        try:
            path.resolve().relative_to(Path(self.workdir).resolve())
            return None
        except ValueError:
            return f"Path outside working directory: {path}"

    async def _read_file(
        self, path: str, start_line: int | None, end_line: int | None
    ) -> str:
        try:
            file_path = self._resolve_file_path(path)
        except Exception as e:
            return f"read_file error: invalid path '{path}': {e}"

        err = self._validate_path_in_workdir(file_path)
        if err:
            return f"read_file error: {err}"

        if not file_path.is_file():
            return f"read_file error: file not found: {file_path}"

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"read_file error: {e}"

        lines = content.splitlines()
        total = len(lines)
        start = max(1, start_line or 1) - 1
        end = end_line or total
        end = min(end, total)

        if start >= total:
            return f"read_file error: start_line {start_line} exceeds file length ({total} lines)"

        selected = lines[start:end]
        header = f"File: {file_path} (lines {start + 1}-{end} of {total})\n"
        return header + "\n".join(selected)

    async def _write_file(self, path: str, content: str) -> str:
        try:
            file_path = self._resolve_file_path(path)
        except Exception as e:
            return f"write_file error: invalid path '{path}': {e}"

        err = self._validate_path_in_workdir(file_path)
        if err:
            return f"write_file error: {err}"

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"write_file ok: wrote {len(content)} bytes to {file_path}"
        except Exception as e:
            return f"write_file error: {e}"

    async def _edit_file(self, path: str, old_string: str, new_string: str) -> str:
        try:
            file_path = self._resolve_file_path(path)
        except Exception as e:
            return f"edit_file error: invalid path '{path}': {e}"

        err = self._validate_path_in_workdir(file_path)
        if err:
            return f"edit_file error: {err}"

        if not file_path.is_file():
            return f"edit_file error: file not found: {file_path}"

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"edit_file error: {e}"

        occurrences = content.count(old_string)
        if occurrences == 0:
            return f"edit_file error: old_string not found in {file_path}"
        if occurrences > 1:
            return (
                f"edit_file error: old_string found {occurrences} times, must be unique"
            )

        new_content = content.replace(old_string, new_string, 1)
        try:
            file_path.write_text(new_content, encoding="utf-8")
            return f"edit_file ok: replaced 1 occurrence in {file_path}"
        except Exception as e:
            return f"edit_file error: {e}"

    async def _run_bash(self, command: str, timeout_seconds: int) -> str:
        return await run_bash(command, self.workdir, timeout_seconds)

    async def _discover(self, args: dict[str, Any]) -> str:
        if self.discovery_mode == "off":
            return "discover error: discovery is disabled (use --discovery auto|mock|real)"
        if run_discover is None:
            return "discover error: discovery module not available"
        # run_discover is blocking (may do time.sleep or SmartClient I/O) -> thread with timeout
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    run_discover,
                    str(args.get("kind", "search")),
                    str(args.get("query", "")),
                    str(args.get("url", "")),
                    str(args.get("goal", "")),
                    discovery_mode=self.discovery_mode,
                    brave_api_key=os.environ.get("BRAVE_API_KEY"),
                    binary=os.environ.get("UNBROWSER_BINARY"),
                ),
                timeout=30,
            )
        except asyncio.TimeoutError:
            return "discover error: timed out after 30s"

    async def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        if not self.tools_enabled:
            return f"Tool blocked: tools are disabled. Requested '{tool_name}'."

        decision = self.policy.decision(tool_name)
        if decision == "deny":
            return f"Tool blocked by deny policy: {tool_name}"
        if decision == "ask":
            allowed = await self._confirm_tool_call(tool_name, args)
            if not allowed:
                return f"Tool call denied by user: {tool_name}"

        if tool_name == "run_bash":
            command = str(args.get("command", "")).strip()
            if not command:
                return "run_bash error: 'command' is required."

            timeout_seconds = args.get("timeout_seconds", self.command_timeout)
            try:
                timeout_seconds = int(timeout_seconds)
            except (TypeError, ValueError):
                timeout_seconds = self.command_timeout
            timeout_seconds = min(max(1, timeout_seconds), 600)

            return await self._run_bash(command, timeout_seconds)

        if tool_name == "read_file":
            file_path = str(args.get("path", "")).strip()
            if not file_path:
                return "read_file error: 'path' is required."
            start_line = args.get("start_line")
            end_line = args.get("end_line")
            try:
                start_line = int(start_line) if start_line is not None else None
            except (TypeError, ValueError):
                start_line = None
            try:
                end_line = int(end_line) if end_line is not None else None
            except (TypeError, ValueError):
                end_line = None
            return await self._read_file(file_path, start_line, end_line)

        if tool_name == "write_file":
            file_path = str(args.get("path", "")).strip()
            content = str(args.get("content", ""))
            if not file_path:
                return "write_file error: 'path' is required."
            return await self._write_file(file_path, content)

        if tool_name == "edit_file":
            file_path = str(args.get("path", "")).strip()
            old_str = args.get("old_string", "")
            new_str = args.get("new_string", "")
            if not file_path:
                return "edit_file error: 'path' is required."
            if not old_str:
                return "edit_file error: 'old_string' is required."
            return await self._edit_file(file_path, old_str, new_str)

        if tool_name == "discover":
            kind = str(args.get("kind", "")).strip()
            goal = str(args.get("goal", "")).strip()
            if not kind:
                return "discover error: 'kind' is required (search|navigate)"
            if not goal:
                return "discover error: 'goal' is required"
            if kind == "search" and not str(args.get("query", "")).strip() and not goal:
                return "discover error: 'query' is required for kind=search"
            if kind == "navigate" and not str(args.get("url", "")).strip():
                return "discover error: 'url' is required for kind=navigate"
            return await self._discover(args)

        return f"Unknown tool: {tool_name}"

    async def _run_user_turn(self, client: httpx.AsyncClient, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        last_tool_signature: str | None = None
        repeated_count = 0

        for turn in range(self.max_turns):
            try:
                if await self._compact_history(client):
                    self._log("[context] Auto-compacted old history.")
                response = await self._call_openrouter(client, self.messages)
            except httpx.HTTPStatusError as e:
                detail = _truncate(e.response.text, 300)
                self._log(f"[openrouter] HTTP {e.response.status_code}: {detail}")
                self._save_session()
                return ""
            except Exception as e:
                self._log(f"[openrouter] Request failed: {e}")
                self._save_session()
                return ""

            choice = response["choices"][0]
            message = choice["message"]
            finish_reason = choice.get("finish_reason", "")
            tool_calls = message.get("tool_calls") or []
            self.messages.append(message)

            if not tool_calls:
                text = message.get("content") or message.get("reasoning") or ""
                if not text:
                    text = f"[empty response, finish_reason={finish_reason}]"
                self._output_response(text)
                self._save_session()
                return text

            signature = json.dumps(
                [
                    {
                        "name": tc.get("function", {}).get("name"),
                        "args": tc.get("function", {}).get("arguments"),
                    }
                    for tc in tool_calls
                ],
                sort_keys=True,
            )
            if signature == last_tool_signature:
                repeated_count += 1
            else:
                repeated_count = 0
                last_tool_signature = signature

            if repeated_count >= 1:
                nudge = (
                    "STOP. You repeated the same tool call without progress. "
                    "Do not call additional tools. Reply with a concise final answer."
                )
                for tc in tool_calls:
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id", "loop"),
                            "content": nudge,
                        }
                    )
                try:
                    forced = await self._call_openrouter(
                        client, self.messages, tool_choice="none"
                    )
                    forced_message = forced["choices"][0]["message"]
                    text = (
                        forced_message.get("content")
                        or forced_message.get("reasoning")
                        or ""
                    )
                    self.messages.append(forced_message)
                except Exception:
                    text = ""
                if not text:
                    text = "I got stuck in a tool loop and could not make progress."
                self._output_response(text)
                self._save_session()
                return text

            # Decode args first (preserve canonical JSON for log/replay)
            parsed_calls: list[tuple[str, dict[str, Any], str, dict]] = []
            for idx, tc in enumerate(tool_calls):
                fn = tc.get("function", {}) or {}
                tool_name = str(fn.get("name", "")).strip()
                tool_args = _decode_tool_arguments(fn.get("arguments"))
                fn["arguments"] = json.dumps(tool_args, separators=(",", ":"))
                tool_call_id = tc.get("id") or f"tc-{turn + 1}-{idx + 1}"
                parsed_calls.append((tool_name, tool_args, tool_call_id, tc))

            # Decide execution strategy: concurrent only for pure discover batches (P1)
            can_concurrent = False
            if len(parsed_calls) > 1 and all(n == "discover" for n, _, _, _ in parsed_calls):
                # Check permission without prompting
                ask_needed = False
                for tname, _, _, _ in parsed_calls:
                    dec = self.policy.decision(tname)
                    if dec == "ask" and not self.non_interactive_mode:
                        ask_needed = True
                        break
                if not ask_needed or self.non_interactive_mode:
                    can_concurrent = True

            tool_results = []
            if can_concurrent and self.max_concurrency > 1:
                for tname, targs, _, _ in parsed_calls:
                    self._log(f"[tool] {tname}({_truncate(json.dumps(targs), 140)})")
                self._log(f"[executor] dispatching {len(parsed_calls)} call(s) concurrently (cap={self.max_concurrency})")

                if run_concurrent is not None:
                    # Use shared helper with exception isolation
                    calls = [(n, a, cid) for n, a, cid, _ in parsed_calls]

                    async def _handler(name: str, args: dict[str, Any]) -> str:
                        return await self._execute_tool(name, args)

                    results = await run_concurrent(calls, _handler, max_concurrency=self.max_concurrency)
                else:
                    # Fallback inline with isolation
                    sem = asyncio.Semaphore(self.max_concurrency)

                    async def _handler(name: str, args: dict[str, Any]) -> str:
                        return await self._execute_tool(name, args)

                    async def _gated(name: str, args: dict[str, Any]) -> str:
                        async with sem:
                            try:
                                return await _handler(name, args)
                            except Exception as e:
                                return f"Tool error ({name}): {e}"

                    results = await asyncio.gather(*[_gated(n, a) for n, a, _, _ in parsed_calls])

                for (_, _, tcid, _), res in zip(parsed_calls, results):
                    preview = _truncate(res.replace("\n", " "), 220)
                    self._log(f"[tool-result] {preview}")
                    tool_results.append({"role": "tool", "tool_call_id": tcid, "content": res[:8000]})
            else:
                for tname, targs, tcid, _ in parsed_calls:
                    self._log(f"[tool] {tname}({_truncate(json.dumps(targs), 140)})")
                    res = await self._execute_tool(tname, targs)
                    preview = _truncate(res.replace("\n", " "), 220)
                    self._log(f"[tool-result] {preview}")
                    tool_results.append({"role": "tool", "tool_call_id": tcid, "content": res[:8000]})

            self.messages.extend(tool_results)

        self._log("[agent] Reached max turns for this user message.")
        self._save_session()
        return ""


_ENV_ALLOWLIST = {
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_AGENT_DISCOVERY",
    "OPENROUTER_AGENT_MAX_CONCURRENCY",
    "OPENROUTER_AGENT_MAX_DISCOVER",
    "OPENROUTER_AGENT_MAX_ROUNDS",
    "OPENROUTER_AGENT_REFERER",
    "OPENROUTER_AGENT_TITLE",
    "OPENROUTER_AGENT_SESSION_DIR",
    "BRAVE_API_KEY",
    "UNBROWSER_BINARY",
}


def _load_dotenv(env_file: str | None = None) -> None:
    """Load .env from explicit file or cwd/repo root, allowlisted keys only."""
    # Explicit --env-file takes precedence
    candidates: list[Path] = []
    if env_file:
        candidates.append(Path(env_file).expanduser())
    else:
        candidates.extend([Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"])

    # Prefer python-dotenv if installed, but filter to allowlist
    try:
        from dotenv import dotenv_values  # type: ignore

        for p in candidates:
            if not p.is_file():
                continue
            try:
                for k, v in dotenv_values(p).items():
                    if k in _ENV_ALLOWLIST and k not in os.environ and v is not None:
                        os.environ[k] = v
            except Exception:
                continue
        return
    except ImportError:
        pass
    # Minimal fallback
    for env_path in candidates:
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                # handle optional leading "export "
                if line.startswith("export "):
                    line = line[7:].strip()
                k, v = line.split("=", 1)
                k = k.strip()
                if k not in _ENV_ALLOWLIST or k in os.environ:
                    continue
                v = v.strip().strip('"').strip("'")
                os.environ[k] = v
        except Exception:
            continue


def _load_system_prompt(path: str | None) -> str:
    if not path:
        return DEFAULT_SYSTEM_PROMPT
    p = Path(path).expanduser()
    try:
        return p.read_text()
    except Exception as e:
        raise RuntimeError(f"Failed to read system prompt file {p}: {e}") from e


def main() -> None:
    # Pre-load default .env (allowlisted) so OPENROUTER_API_KEY/MODEL are available for defaults
    _load_dotenv()
    # Early peek for explicit --env-file without consuming args
    _explicit_env = None
    for i, a in enumerate(sys.argv):
        if a == "--env-file" and i + 1 < len(sys.argv):
            _explicit_env = sys.argv[i + 1]
        elif a.startswith("--env-file="):
            _explicit_env = a.split("=", 1)[1]
    if _explicit_env:
        _load_dotenv(_explicit_env)

    parser = argparse.ArgumentParser(
        description="Standalone OpenRouter terminal agent with tool actions and context management."
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENROUTER_API_KEY", ""),
        help="OpenRouter API key (defaults to OPENROUTER_API_KEY env var).",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL),
        help=f"OpenRouter model ID (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--session-id",
        default=DEFAULT_SESSION_ID,
        help=f"Session ID for persisted history (default: {DEFAULT_SESSION_ID}).",
    )
    parser.add_argument(
        "--workdir",
        default=os.getcwd(),
        help="Working directory for run_bash tool (default: current directory).",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=DEFAULT_MAX_TURNS,
        help=f"Max model/tool iterations per user turn (default: {DEFAULT_MAX_TURNS}).",
    )
    parser.add_argument(
        "--max-history-messages",
        type=int,
        default=DEFAULT_MAX_HISTORY_MESSAGES,
        help=f"Compaction threshold in non-system messages (default: {DEFAULT_MAX_HISTORY_MESSAGES}).",
    )
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=DEFAULT_COMMAND_TIMEOUT,
        help=f"Default timeout in seconds for run_bash (default: {DEFAULT_COMMAND_TIMEOUT}).",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Disable all tool calling.",
    )
    parser.add_argument(
        "--system-prompt-file",
        help="Path to a custom system prompt file.",
    )
    parser.add_argument(
        "--prompt",
        "-p",
        help="Run a single prompt, emit the assistant reply on stdout, and exit.",
    )
    parser.add_argument(
        "--discovery",
        choices=["auto", "mock", "real", "off"],
        default=os.environ.get("OPENROUTER_AGENT_DISCOVERY", "auto"),
        help="Web discovery mode for `discover` tool: auto (real if pyunbrowser installed else mock), mock (no network), real (requires pyunbrowser), off (disable tool) (default: auto).",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.environ.get("OPENROUTER_AGENT_MAX_CONCURRENCY", "5")),
        help="Max concurrent discover when agent batches (cap, agent defines within 1..cap, default 5, max 16).",
    )
    parser.add_argument(
        "--max-discover",
        type=int,
        default=int(os.environ.get("OPENROUTER_AGENT_MAX_DISCOVER", "5")),
        help="Cap for discover calls per batch (agent defines 1..cap, default 5, max 10).",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=int(os.environ.get("OPENROUTER_AGENT_MAX_ROUNDS", "2")),
        help="Cap for discover rounds (agent defines 1..cap, default 2, max 5).",
    )
    parser.add_argument(
        "--allow-discovery",
        action="store_true",
        help="Shortcut to auto-allow `discover` tool (equivalent to /allow discover).",
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env file to load (allowlisted keys only, no override).",
    )
    args = parser.parse_args()
    # If --env-file was passed and not already loaded via early peek (e.g. quoted), ensure loaded
    if args.env_file and args.env_file != _explicit_env:
        _load_dotenv(args.env_file)

    if not args.api_key:
        print(
            "ERROR: missing OpenRouter API key. Set OPENROUTER_API_KEY or pass --api-key.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        system_prompt = _load_system_prompt(args.system_prompt_file)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)

    # Default to fresh session for -p (one-shot) when --session-id not explicitly given
    # Prevents crypto-contamination via shared default.json (50-msg pollution)
    _session_explicit = any(a.startswith("--session-id") for a in sys.argv)
    if args.prompt is not None and not _session_explicit and args.session_id == DEFAULT_SESSION_ID:
        args.session_id = f"ephemeral-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        print(f"[session] one-shot fresh session: {args.session_id} (use --session-id to persist)", file=sys.stderr)

    # Inject agent-defined caps into prompt so model sees actual limits (not just defaults)
    if "AGENT-DEFINED LIMITS" in system_prompt:
        system_prompt += f"\n[Caps for this session: max_discover={args.max_discover} per batch, max_rounds={args.max_rounds}, max_concurrency={args.max_concurrency} — you define within caps]\n"

    cli = OpenRouterAgentCLI(
        api_key=args.api_key,
        model=args.model,
        session_id=args.session_id,
        workdir=args.workdir,
        max_turns=args.max_turns,
        max_history_messages=args.max_history_messages,
        command_timeout=args.command_timeout,
        tools_enabled=not args.no_tools,
        system_prompt=system_prompt,
        discovery_mode=args.discovery,
        max_concurrency=args.max_concurrency,
        max_discover=args.max_discover,
        max_rounds=args.max_rounds,
    )
    if args.allow_discovery:
        cli.policy.allow.add("discover")
        cli.policy.deny.discard("discover")
        cli._save_policy()

    if args.prompt is not None:
        cli.one_shot_prompt = args.prompt
        cli.non_interactive_mode = True

    try:
        asyncio.run(cli.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
