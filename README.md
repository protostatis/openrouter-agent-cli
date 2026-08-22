# openrouter-agent-cli

Standalone terminal agent for OpenRouter models with:
- tool actions (`run_bash`, `read_file`/`write_file`/`edit_file`, `discover` web search/navigate)
- interactive permission gating (`allow` / `deny` / `ask`)
- session persistence
- context visibility and compaction
- concurrent `discover` batching (parallel tool calls → `max_concurrency`)

## Install

```bash
cd openrouter-agent-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                    # core includes pyunbrowser (real web discovery)
pip install -e ".[viz]"             # + png gantt (matplotlib)
pip install -e ".[full]"            # all extras (openai, dotenv, viz)
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
  --model nvidia/nemotron-3.5-lightning:free \
  --session-id my-session \
  --workdir ~/Projects \
  --max-turns 24 \
  --max-history-messages 60 \
  --command-timeout 30 \
  --discovery auto \
  --max-concurrency 5 \
  --env-file .env

# web discovery modes: auto (real if pyunbrowser installed else error), mock (synthetic example.com), real (requires pyunbrowser), off
openrouter-agent --discovery mock --allow-discovery --prompt "what is unbrowser?"
openrouter-agent --discovery real --allow-discovery  # needs BRAVE_API_KEY for search
```

Env auto-load: `.env` in `cwd` and repo root is loaded via `python-dotenv` (or allowlisted fallback: `OPENROUTER_*, BRAVE_API_KEY, UNBROWSER_BINARY`). `--env-file` overrides.

Disable tools:

```bash
openrouter-agent --no-tools
```

## Slash commands

- `/help`
- `/exit`
- `/new [id]` (fresh session — history reset, isolates crypto contamination)
- `/model [id]`
- `/usage`
- `/context [n]`
- `/compact`
- `/clear` (same id)
- `/tools`
- `/tools on|off`
- `/allow <tool|*>`
- `/deny <tool|*>`
- `/unallow <tool|*>`
- `/undeny <tool|*>`
- `/cwd [path]`
- `/discovery [auto|mock|real|off]`
- `/concurrency [n]` (1-16, cap for parallel `discover`)

## Context management

- history is saved in `~/.openrouter-agent-cli/sessions/<session_id>.json`
- `/usage` shows rough token estimate
- `/compact` forces summarization
- automatic compaction triggers when non-system message count exceeds `--max-history-messages`

## Security notes

- `run_bash` executes shell commands on your machine in `--workdir` (cwd only, not jailed — unlike `read_file`/`write_file`/`edit_file` which enforce workdir jail).
- `discover` fetches web content (`https` only, private/loopback/link-local/metadata blocked on initial URL; redirects not yet revalidated — treat as SSRF best-effort). All web content is untrusted — model may be prompt-injected via page content; keep allow/deny gated.
- `BRAVE_API_KEY` used for `discover(search)`, `UNBROWSER_BINARY` can select browser binary — both allowlisted from `.env`; `auto` no longer silently mocks (requires `--discovery mock` for synthetic `example.com/mock`).
- `discover` batches run concurrently (`max_concurrency`, default 5, isolated per `SmartClient`); `run_bash`/file ops serialize even in mixed batches. Each `discover` has `30s` timeout (thread abandoned on timeout — not yet killable subprocess).
- Model outputs (tool calls) are reflected literally in `run_bash` + URLs in `discover`, so treat every allowed tool call as untrusted input and keep the allow/deny policy enforced unless you deliberately want to run everything.
- default policy is `ask` for every tool call
- use `/deny *` for a fully no-tools session / `/allow discover` or `--allow-discovery` to batch without prompts
- default model is free-tier (`nvidia/nemotron-3.5-lightning:free`); override with `--model` or `OPENROUTER_MODEL`

## Tool schema seen by the model

When tools are enabled, each OpenRouter request includes these tool definitions (filtered when `--discovery off`):

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
  },
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": "Read file (workdir-jail) with optional line range.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "start_line": {"type": "integer"},
          "end_line": {"type": "integer"}
        },
        "required": ["path"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "write_file",
      "description": "Write file (workdir-jail, creates dirs).",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "content": {"type": "string"}
        },
        "required": ["path", "content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "edit_file",
      "description": "Edit file by unique old_string → new_string (workdir-jail).",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "old_string": {"type": "string"},
          "new_string": {"type": "string"}
        },
        "required": ["path", "old_string", "new_string"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "discover",
      "description": "Web discovery via pyunbrowser (agent fills search|navigate). Parallel 2-5 calls per turn, concurrent (https-only, private blocked).",
      "parameters": {
        "type": "object",
        "properties": {
          "kind": {"type": "string", "enum": ["search", "navigate"]},
          "query": {"type": "string"},
          "url": {"type": "string"},
          "goal": {"type": "string"}
        },
        "required": ["kind", "goal"]
      }
    }
  }
]
```

Request body shape sent to OpenRouter (simplified):

```json
{
  "model": "nvidia/nemotron-3.5-lightning:free",
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

## How tools are invoked

Execution flow per user turn:

1. Model returns `tool_calls` in assistant message (may be 1 or parallel batch when `parallel_tool_calls=True`).
2. CLI decodes `function.arguments` JSON into a dict.
3. Permission policy is applied per tool:
   - `deny` list blocks immediately.
   - `allow` list runs immediately.
   - otherwise prompt user (`y/n/a/d`); mixed `ask` batches serialize (no concurrency).
4. For `run_bash`, CLI executes:
   - `asyncio.create_subprocess_shell(command, cwd=<workdir>, stdout=PIPE, stderr=PIPE)`
   - waits with `asyncio.wait_for(..., timeout_seconds)`
   - kills process on timeout
   - concurrent batches: only pure `discover` batches run concurrent (`max_concurrency`, semaphore); any `run_bash`/file ops in batch force serialization
5. For `discover`, CLI executes (blocking → `to_thread`, `30s` timeout):
   - `kind=search`: `SmartClient.search(query, engine=brave)` (needs `BRAVE_API_KEY`)
   - `kind=navigate`: `SmartClient.navigate_auto(url, goal=goal)` (LLM extraction)
   - `mock` mode: synthetic `example.com/mock` hits (explicit `--discovery mock` only)
6. CLI formats each result to text and appends `role:tool` messages (one per `tool_call_id`, capped 8000 chars, valid-JSON truncation not yet guaranteed)

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
  --model nvidia/nemotron-3.5-lightning:free
```

Run with tool execution enabled (use cautiously):

```bash
export OPENROUTER_API_KEY=sk-or-...
python scripts/ab_test_system_prompts.py \
  --tool-mode execute \
  --workdir "$(pwd)" \
  --model nvidia/nemotron-3.5-lightning:free
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
  --model nvidia/nemotron-3.5-lightning:free \
  --output-dir ab_tests/results/hard_suite_v1_r3
```

Evaluate quality and groundedness from a run:

```bash
export OPENROUTER_API_KEY=sk-or-...
python scripts/evaluate_ab_results.py \
  --results ab_tests/results/hard_suite_v1_r3/results.json \
  --judge-model nvidia/nemotron-3.5-lightning:free \
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
