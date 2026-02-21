"""Standalone OpenRouter agent CLI with basic actions and context management."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Default to a free-tier model so first-run usage does not consume paid credits.
DEFAULT_MODEL = "arcee-ai/trinity-large-preview:free"
DEFAULT_SESSION_ID = "default"
DEFAULT_MAX_TURNS = 24
DEFAULT_MAX_HISTORY_MESSAGES = 60
DEFAULT_COMMAND_TIMEOUT = 30
CONTEXT_KEEP_TAIL = 10

DEFAULT_SYSTEM_PROMPT = """You are a pragmatic coding assistant in a terminal.
Use tools only when needed. Explain outputs clearly and stay concise.
When unsure, ask for clarification before destructive operations."""

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
    }
]


def _sanitize_session_id(session_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", session_id)
    return safe or DEFAULT_SESSION_ID


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _decode_tool_arguments(raw_args: Any) -> dict[str, Any]:
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        value = raw_args.strip()
        if not value:
            return {}
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


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
        self.policy = ToolPermissionPolicy()

        self.session_root = (
            Path(os.environ.get("OPENROUTER_AGENT_SESSION_DIR", "~/.openrouter-agent-cli/sessions"))
            .expanduser()
        )
        self.session_root.mkdir(parents=True, exist_ok=True)
        self.messages = self._load_session()

    @property
    def _session_path(self) -> Path:
        return self.session_root / f"{self.session_id}.json"

    def _load_session(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._session_path.read_text())
            stored = data.get("messages", [])
            if isinstance(stored, list):
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
        payload = {"messages": non_system}
        try:
            self._session_path.write_text(json.dumps(payload))
        except Exception as e:
            print(f"[session] Failed to save session: {e}")

    def _tool_names(self) -> list[str]:
        names: list[str] = []
        for tool in TOOLS:
            fn = tool.get("function", {})
            name = fn.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return sorted(names)

    async def run(self):
        print("OpenRouter Agent CLI")
        print(f"Model      : {self.model}")
        print(f"Session    : {self.session_id}")
        print(f"Working dir: {self.workdir}")
        print("Type /help for commands. Type /exit to quit.")
        print()

        async with httpx.AsyncClient(timeout=60.0) as client:
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

    async def _handle_command(self, client: httpx.AsyncClient, command_line: str) -> bool:
        parts = command_line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            return False

        if cmd == "/help":
            print("Commands:")
            print("  /help                 Show help")
            print("  /exit                 Exit")
            print("  /model [id]           Show or set model")
            print("  /usage                Show message count + rough token estimate")
            print("  /context [n]          Show last n messages (default 8)")
            print("  /compact              Force conversation compaction")
            print("  /clear                Clear session history")
            print("  /tools                Show tools + permission policy")
            print("  /tools on|off         Enable or disable tool calling")
            print("  /allow <tool|*>       Always allow tool")
            print("  /deny <tool|*>        Always deny tool")
            print("  /unallow <tool|*>     Remove allow rule")
            print("  /undeny <tool|*>      Remove deny rule")
            print("  /cwd [path]           Show or set working directory")
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
            print(f"Messages (non-system): {msg_count}")
            print(f"Estimated tokens     : ~{token_est}")
            print(f"History limit        : {self.max_history_messages}")
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

        if cmd == "/tools":
            lowered = arg.lower()
            if lowered in ("on", "off"):
                self.tools_enabled = lowered == "on"
                print(f"Tools {'enabled' if self.tools_enabled else 'disabled'}.")
                return True
            print(f"Tools enabled: {self.tools_enabled}")
            print(f"Available tools: {', '.join(self._tool_names())}")
            print(f"Allow list: {sorted(self.policy.allow) if self.policy.allow else '[]'}")
            print(f"Deny list : {sorted(self.policy.deny) if self.policy.deny else '[]'}")
            return True

        if cmd == "/allow":
            if not arg:
                print("Usage: /allow <tool_name|*>")
                return True
            self.policy.allow.add(arg)
            self.policy.deny.discard(arg)
            print(f"Always allow: {arg}")
            return True

        if cmd == "/deny":
            if not arg:
                print("Usage: /deny <tool_name|*>")
                return True
            self.policy.deny.add(arg)
            self.policy.allow.discard(arg)
            print(f"Always deny: {arg}")
            return True

        if cmd == "/unallow":
            if not arg:
                print("Usage: /unallow <tool_name|*>")
                return True
            self.policy.allow.discard(arg)
            print(f"Removed allow rule: {arg}")
            return True

        if cmd == "/undeny":
            if not arg:
                print("Usage: /undeny <tool_name|*>")
                return True
            self.policy.deny.discard(arg)
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

        print(f"Unknown command: {cmd}. Use /help.")
        return True

    async def _call_openrouter(
        self,
        client: httpx.AsyncClient,
        messages: list[dict[str, Any]],
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 4096,
        }
        if tool_choice == "none" or not self.tools_enabled:
            body["tool_choice"] = "none"
        else:
            body["tools"] = TOOLS
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get(
                "OPENROUTER_AGENT_REFERER", "https://github.com/local/openrouter-agent-cli"
            ),
            "X-Title": os.environ.get("OPENROUTER_AGENT_TITLE", "OpenRouter Agent CLI"),
        }

        resp = await client.post(OPENROUTER_URL, json=body, headers=headers)
        if resp.status_code in (500, 502, 503):
            for attempt in range(1, 3):
                await asyncio.sleep(attempt * 2)
                resp = await client.post(OPENROUTER_URL, json=body, headers=headers)
                if resp.status_code not in (500, 502, 503):
                    break
        if not resp.is_success:
            resp.raise_for_status()

        data = resp.json()
        if "choices" not in data:
            err = data.get("error", {})
            if isinstance(err, dict):
                err = err.get("message", str(data))
            raise RuntimeError(f"OpenRouter error: {err}")
        return data

    async def _compact_history(self, client: httpx.AsyncClient, force: bool = False) -> bool:
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
            summary_resp = await self._call_openrouter(client, summary_prompt, tool_choice="none")
            summary_msg = summary_resp["choices"][0]["message"]
            summary = (summary_msg.get("content") or summary_msg.get("reasoning") or "").strip()
        except Exception as e:
            summary = f"Compaction summary failed: {e}"

        if not summary:
            summary = "No significant prior context."

        summary_entry = {"role": "assistant", "content": f"[Context summary]\n{summary}"}
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            summary_entry,
            *tail,
        ]
        self._save_session()
        return True

    async def _confirm_tool_call(self, tool_name: str, args: dict[str, Any]) -> bool:
        preview = _truncate(json.dumps(args, ensure_ascii=False), 220)
        question = (
            f"[permission] Allow tool '{tool_name}' args={preview}? "
            "[y]es/[n]o/[a]lways allow/[d]eny always: "
        )
        choice = (await asyncio.to_thread(input, question)).strip().lower()
        if choice == "a":
            self.policy.allow.add(tool_name)
            self.policy.deny.discard(tool_name)
            return True
        if choice == "d":
            self.policy.deny.add(tool_name)
            self.policy.allow.discard(tool_name)
            return False
        return choice in ("y", "yes")

    async def _run_bash(self, command: str, timeout_seconds: int) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=self.workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return f"Command timed out after {timeout_seconds}s."
        except Exception as e:
            return f"Command failed to start: {e}"

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0:
            return out or "(command succeeded with no output)"
        if out and err:
            return f"exit={proc.returncode}\nstdout:\n{out}\nstderr:\n{err}"
        if err:
            return f"exit={proc.returncode}\nstderr:\n{err}"
        if out:
            return f"exit={proc.returncode}\nstdout:\n{out}"
        return f"exit={proc.returncode} (no output)"

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

        if tool_name != "run_bash":
            return f"Unknown tool: {tool_name}"

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

    async def _run_user_turn(self, client: httpx.AsyncClient, user_text: str):
        self.messages.append({"role": "user", "content": user_text})
        last_tool_signature: str | None = None
        repeated_count = 0

        for turn in range(self.max_turns):
            try:
                if await self._compact_history(client):
                    print("[context] Auto-compacted old history.")
                response = await self._call_openrouter(client, self.messages)
            except httpx.HTTPStatusError as e:
                detail = _truncate(e.response.text, 300)
                print(f"[openrouter] HTTP {e.response.status_code}: {detail}")
                self._save_session()
                return
            except Exception as e:
                print(f"[openrouter] Request failed: {e}")
                self._save_session()
                return

            choice = response["choices"][0]
            message = choice["message"]
            finish_reason = choice.get("finish_reason", "")
            tool_calls = message.get("tool_calls") or []
            self.messages.append(message)

            if not tool_calls:
                text = message.get("content") or message.get("reasoning") or ""
                if not text:
                    text = f"[empty response, finish_reason={finish_reason}]"
                print(f"\nassistant> {text}\n")
                self._save_session()
                return

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
                    forced = await self._call_openrouter(client, self.messages, tool_choice="none")
                    forced_message = forced["choices"][0]["message"]
                    text = forced_message.get("content") or forced_message.get("reasoning") or ""
                    self.messages.append(forced_message)
                except Exception:
                    text = ""
                if not text:
                    text = "I got stuck in a tool loop and could not make progress."
                print(f"\nassistant> {text}\n")
                self._save_session()
                return

            tool_results = []
            for idx, tool_call in enumerate(tool_calls):
                fn = tool_call.get("function", {})
                tool_name = str(fn.get("name", "")).strip()
                tool_args = _decode_tool_arguments(fn.get("arguments"))
                fn["arguments"] = json.dumps(tool_args, separators=(",", ":"))

                print(f"[tool] {tool_name}({_truncate(json.dumps(tool_args), 140)})")
                result = await self._execute_tool(tool_name, tool_args)
                preview = _truncate(result.replace("\n", " "), 220)
                print(f"[tool-result] {preview}")

                tool_call_id = tool_call.get("id") or f"tc-{turn + 1}-{idx + 1}"
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result[:8000],
                    }
                )

            self.messages.extend(tool_results)

        print("[agent] Reached max turns for this user message.")
        self._save_session()


def _load_system_prompt(path: str | None) -> str:
    if not path:
        return DEFAULT_SYSTEM_PROMPT
    p = Path(path).expanduser()
    try:
        return p.read_text()
    except Exception as e:
        raise RuntimeError(f"Failed to read system prompt file {p}: {e}") from e


def main() -> None:
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
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: missing OpenRouter API key. Set OPENROUTER_API_KEY or pass --api-key.", file=sys.stderr)
        raise SystemExit(1)

    try:
        system_prompt = _load_system_prompt(args.system_prompt_file)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)

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
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: loop.stop())
        except NotImplementedError:
            # add_signal_handler is not available on some platforms.
            pass

    try:
        loop.run_until_complete(cli.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
