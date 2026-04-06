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

## Non-interactive prompt

`--prompt` (short `-p`) lets another process run the CLI with a single user message, emit only the assistant reply to `stdout`, and exit immediately. Operation logs, tool call summaries, and permission notices are written to `stderr`, and tool calls are automatically denied unless you disable tools with `--no-tools`.

Example:

```bash
openrouter-agent --prompt "Explain tail recursion" --no-tools
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

- `run_bash` executes shell commands on your machine in `--workdir`.
- Model outputs (tool calls) are reflected literally in `run_bash`, so treat every allowed tool call as untrusted input and keep the allow/deny policy enforced unless you deliberately want to run everything.
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

## Prompt A/B testing

This repo includes a small harness for comparing system prompts:

- script: `scripts/ab_test_system_prompts.py`
- prompt variants:
  - `prompts/system_prompt_control.md`
  - `prompts/system_prompt_agentic_v1.md`
- sample tasks: `ab_tests/tasks_sample.txt`

Run prompt-only comparison (no tools):

```bash
export OPENROUTER_API_KEY=sk-or-...
python scripts/ab_test_system_prompts.py \
  --tool-mode none \
  --model arcee-ai/trinity-large-preview:free
```

Run with tool execution enabled (use cautiously):

```bash
export OPENROUTER_API_KEY=sk-or-...
python scripts/ab_test_system_prompts.py \
  --tool-mode execute \
  --workdir "$(pwd)" \
  --model arcee-ai/trinity-large-preview:free
```

Artifacts are written to `ab_tests/results/<timestamp>/`:

- `results.json` full transcripts and metadata
- `summary.csv` flat comparison table
- `summary.md` quick markdown summary

Run a harder repeated suite (2 prompts x 6 tasks x 3 repeats):

```bash
export OPENROUTER_API_KEY=sk-or-...
python scripts/ab_test_system_prompts.py \
  --tool-mode execute \
  --tasks-file ab_tests/tasks_hard_suite_v1.txt \
  --repeats 3 \
  --max-turns 3 \
  --max-tokens 1000 \
  --request-timeout 40 \
  --command-timeout 20 \
  --workdir "$(pwd)" \
  --model arcee-ai/trinity-large-preview:free \
  --output-dir ab_tests/results/hard_suite_v1_r3
```

Evaluate quality and groundedness from a run:

```bash
export OPENROUTER_API_KEY=sk-or-...
python scripts/evaluate_ab_results.py \
  --results ab_tests/results/hard_suite_v1_r3/results.json \
  --judge-model arcee-ai/trinity-large-preview:free \
  --output-dir ab_tests/results/hard_suite_v1_r3/eval
```

Evaluator artifacts:

- `evaluation.json` per-case raw evaluation details
- `evaluation.csv` tabular scores
- `leaderboard.md` aggregated per-prompt ranking

## Findings and release docs

- benchmark findings: `docs/AB_FINDINGS_2026-02-21.md`
- public release checklist: `docs/PUBLIC_RELEASE_CHECKLIST.md`
- security policy: `SECURITY.md`
- env template: `.env.example`
