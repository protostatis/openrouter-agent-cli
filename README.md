# openrouter-agent-cli

Standalone terminal agent for OpenRouter models with:
- tool actions (`run_bash`)
- interactive permission gating (`allow` / `deny` / `ask`)
- session persistence
- context visibility and compaction

## Install

```bash
cd openrouter-agent-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
export OPENROUTER_API_KEY=sk-or-...
openrouter-agent
```

Or without installation:

```bash
export OPENROUTER_API_KEY=sk-or-...
python -m openrouter_agent_cli.cli
```

## Useful flags

```bash
openrouter-agent \
  --model arcee-ai/trinity-large-preview:free \
  --session-id my-session \
  --workdir ~/Projects \
  --max-turns 24 \
  --max-history-messages 60 \
  --command-timeout 30
```

Disable tools:

```bash
openrouter-agent --no-tools
```

## Slash commands

- `/help`
- `/exit`
- `/model [id]`
- `/usage`
- `/context [n]`
- `/compact`
- `/clear`
- `/tools`
- `/tools on|off`
- `/allow <tool|*>`
- `/deny <tool|*>`
- `/unallow <tool|*>`
- `/undeny <tool|*>`
- `/cwd [path]`

## Context management

- history is saved in `~/.openrouter-agent-cli/sessions/<session_id>.json`
- `/usage` shows rough token estimate
- `/compact` forces summarization
- automatic compaction triggers when non-system message count exceeds `--max-history-messages`

## Security notes

- `run_bash` executes shell commands on your machine in `--workdir`
- default policy is `ask` for every tool call
- use `/deny *` for a fully no-tools session
- default model is free-tier (`arcee-ai/trinity-large-preview:free`); override with `--model` or `OPENROUTER_MODEL`

## Tool schema seen by the model

When tools are enabled, each OpenRouter request includes this tool definition:

```json
[
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
]
```

Request body shape sent to OpenRouter (simplified):

```json
{
  "model": "arcee-ai/trinity-large-preview:free",
  "messages": [...],
  "temperature": 0,
  "max_tokens": 4096,
  "tools": [...],
  "tool_choice": "auto"
}
```

If tools are disabled (`--no-tools` or `/tools off`), the request sets:

```json
{
  "tool_choice": "none"
}
```

## How `run_bash` is invoked

Execution flow per user turn:

1. Model returns `tool_calls` in assistant message.
2. CLI decodes `function.arguments` JSON into a dict.
3. Permission policy is applied:
   - `deny` list blocks immediately.
   - `allow` list runs immediately.
   - otherwise prompt user (`y/n/a/d`).
4. For `run_bash`, CLI executes:
   - `asyncio.create_subprocess_shell(command, cwd=<workdir>, stdout=PIPE, stderr=PIPE)`
   - waits with `asyncio.wait_for(..., timeout_seconds)`
   - kills process on timeout
5. CLI formats stdout/stderr/exit code to text and appends a tool result message:
   - role: `tool`
   - tool_call_id: model-provided id
   - content: command output (capped to 8000 chars before being sent back to model)

Example tool call from model:

```json
{
  "id": "call_123",
  "type": "function",
  "function": {
    "name": "run_bash",
    "arguments": "{\"command\":\"ls -la\",\"timeout_seconds\":30}"
  }
}
```

Example tool result message added by CLI:

```json
{
  "role": "tool",
  "tool_call_id": "call_123",
  "content": "total 64\n-rw-r--r-- ..."
}
```

Note: despite the name `run_bash`, execution uses `create_subprocess_shell` (system shell), not an explicit `bash` binary unless the command itself invokes `bash`.
