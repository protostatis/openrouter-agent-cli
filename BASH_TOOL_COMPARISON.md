# Bash Tool Invocation Comparison

As of February 21, 2026.

## Summary table

| Area | OpenRouter Agent CLI (this repo) | Claude Code | GitHub Copilot CLI |
|---|---|---|---|
| How shell is exposed to model | Explicit JSON function tool (`run_bash`) defined in app code | Built-in `Bash` tool | Built-in shell tool permissions (`shell(...)`) |
| Execution path | `tool_calls` -> policy check -> `create_subprocess_shell(...)` | Tool runtime managed by Claude Code | Tool runtime managed by Copilot CLI |
| Direct shell bypass | Not implemented | `!` runs shell directly | `!` runs shell directly |
| Permission model | `allow`/`deny`/`ask` by tool name | Rich permission modes + rules/patterns | Per-tool allow/deny flags and session approvals |
| Context handling | Session history + compaction | `/context`, `/compact`, memory system | `/context`, `/compact`, history compression |
| Sandboxing | No built-in sandbox | Documented sandbox mode | Trust and approval controls (no equivalent documented OS sandbox page) |

## OpenRouter Agent CLI implementation (this repo)

### Tool schema sent to the model

Declared in `openrouter_agent_cli/cli.py`:

```json
{
  "type": "function",
  "function": {
    "name": "run_bash",
    "description": "Run a shell command in the current working directory and return stdout/stderr.",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {
          "type": "string",
          "description": "Shell command to execute."
        },
        "timeout_seconds": {
          "type": "integer",
          "description": "Execution timeout in seconds (1-600).",
          "default": 30
        }
      },
      "required": ["command"]
    }
  }
}
```

Key code references:
- tool registration: `openrouter_agent_cli/cli.py:31`
- request attaches tools: `openrouter_agent_cli/cli.py:357`
- tool disabled path (`tool_choice=none`): `openrouter_agent_cli/cli.py:354`
- permission gate: `openrouter_agent_cli/cli.py:487`
- shell execution: `openrouter_agent_cli/cli.py:455`
- timeout + kill: `openrouter_agent_cli/cli.py:462`
- tool result appended to messages: `openrouter_agent_cli/cli.py:600`

### Invocation flow

1. Model returns assistant `tool_calls`.
2. CLI decodes `function.arguments`.
3. CLI applies policy (`deny`, `allow`, or interactive ask).
4. If allowed, CLI runs `asyncio.create_subprocess_shell(command, cwd=self.workdir, ...)`.
5. CLI returns formatted stdout/stderr/exit text as a `role=tool` message.

Note: despite the name `run_bash`, execution uses system shell via `create_subprocess_shell`, not explicitly `bash` unless the command itself calls `bash`.

## Claude Code vs Copilot CLI notes

- Claude Code emphasizes a policy system and sandboxing controls around tool execution.
- Copilot CLI emphasizes permission flags, trust model, and session-level approvals around tool execution.
- Both provide direct shell prefix usage (`!`) in interactive mode.

## Licensing and open-source status caveat

- `anthropics/claude-code` is public source, but license terms are not standard OSI open-source terms.
- `github/copilot-cli` is public source, with a restrictive license.
- Older `github/gh-copilot` is archived/deprecated.

## Sources

- OpenRouter CLI code:
  - `openrouter_agent_cli/cli.py:31`
  - `openrouter_agent_cli/cli.py:354`
  - `openrouter_agent_cli/cli.py:357`
  - `openrouter_agent_cli/cli.py:455`
  - `openrouter_agent_cli/cli.py:487`
  - `openrouter_agent_cli/cli.py:600`
- Claude Code docs:
  - https://code.claude.com/docs/en/permissions
  - https://code.claude.com/docs/en/settings
  - https://code.claude.com/docs/en/interactive-mode
  - https://code.claude.com/docs/en/memory
  - https://code.claude.com/docs/en/sandboxing
- Claude repo/license:
  - https://github.com/anthropics/claude-code
  - https://raw.githubusercontent.com/anthropics/claude-code/main/LICENSE.md
- Copilot CLI docs:
  - https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli
  - https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli
  - https://docs.github.com/en/copilot/reference/cli-command-reference
- Copilot repo/license:
  - https://github.com/github/copilot-cli
  - https://raw.githubusercontent.com/github/copilot-cli/main/LICENSE.md
- Archived old extension:
  - https://github.com/github/gh-copilot
