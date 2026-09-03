# openrouter-agent-cli

A terminal coding agent for OpenRouter models where a command you control
determines whether completion is recorded as **verified, failed, or not
verified**. Give it a bounded task and an acceptance command; the agent works,
and before its answer is accepted the command runs. A failing check earns
exactly one additional model response, then it stops with the evidence.

Coding agents are everywhere — opencode, pi, Claude Code. They all run tools,
keep sessions, and can run your tests. The difference here is not more models,
lower cost, or more polish: completion is a checked state, recorded honestly,
and the same engine doubles as an experiment harness — contained, audited,
treatment-separated — so claims about whether the completion policy helps are
measured, not asserted.

It is for developers who want to try several OpenRouter models on bounded
repository tasks while keeping explicit acceptance evidence — a command that
must pass before the agent's answer is accepted.

What it does:

- bounded task contracts (`--task` / `/task`) with a user-owned acceptance
  command (`--verify-command` / `/verify` / `/check`);
- honest completion states: verified / failed / not verified;
- exactly one additional model response on a failed check, then it stops;
- tool actions (`run_bash`, `list_dir`/`search_text`/`read_file`/`write_file`/`edit_file`, `discover` web search/navigate);
- interactive permission gating (`allow` / `deny` / `ask`);
- session persistence and context visibility with honest cache accounting
  (provider cache counters are reported only when the provider exposes them);
- diff review (`/diff`) and undo that only claims what the tool itself tracked;
- an experiment harness on the same engine: preregistered runs, a
  verifier-assisted policy kept separate from ordinary results, a campaign
  audit, and contained real-model execution.

## Install

```bash
pip install openrouter-agent-cli          # from PyPI
pipx install openrouter-agent-cli         # or isolated CLI install
```

Or from a source checkout:

```bash
cd openrouter-agent-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                    # core includes pyunbrowser (real web discovery)
pip install -e ".[viz]"             # + png gantt (matplotlib)
pip install -e ".[full]"            # all extras (openai, dotenv, viz)
```

Note: real web discovery depends on `pyunbrowser`, which currently ships
Linux/macOS wheels — on Windows the rest of the CLI works, but `discover`
may be unavailable.

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

For a bounded coding task, give the session an objective and a developer-owned
acceptance command:

```bash
openrouter-agent --workdir ./my-repo \
  --task "Fix the failing login test" \
  --verify-command "pytest tests/test_auth.py"
```

The command runs at the completion boundary (once initially, and once more
after the single permitted repair response when the first check fails). A
failed command earns exactly one additional model response; a timeout or
execution error is reported as `not_verified` rather than treated as success.
The workflow can be exercised without credentials or network access with
`openrouter-agent-self-test` (or `openrouter-agent --self-test`).

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

Debug logging:

```bash
openrouter-agent --debug  # timestamps + idle instrumentation on stderr
```

## Slash commands

- `/help`
- `/exit`
- `/new [id]` (fresh session — history reset, isolates crypto contamination)
- `/model [id]`
- `/usage`
- `/status`
- `/task [description]`
- `/verify [command]` (use `off` to clear it)
- `/check` (run the acceptance command immediately)
- `/diff [path]` (review working-tree changes; `--stat` for a summary)
- `/context [n]`
- `/compact [--preview]`
- `/undo` (last file-tool edit or compaction — shell changes are never rolled back)
- `/clear` (same id)
- `/tools`
- `/tools on|off`
- `/allow <tool|*>` (cached across sessions → `~/.openrouter-agent-cli/policy.json`)
- `/deny <tool|*>` (cached)
- `/unallow <tool|*>`
- `/undeny <tool|*>`
- `/cwd [path]`
- `/discovery [auto|mock|real|off]`
- `/concurrency [n]` (1-16, cap for parallel `discover`)
- `/inspect <call-id>`
- `/sessions`
- `/resume <id>`
- `/policy`
- `/export [path]`

## Context management

- history is saved in `~/.openrouter-agent-cli/sessions/<session_id>.json`
- `/usage` shows a rough token estimate and process-only API counters
- `/usage` also shows the stable context-prefix estimate and whether the
  provider exposed explicit cache counters; `not observable` is a real state,
  not a zero-cache claim
- `/status` shows the active model, session, cwd, tool policy, context estimate, and
  current lifecycle state
- `/compact` forces summarization; `/compact --preview` shows what would be summarized
- automatic compaction triggers around 12k estimated tokens; `--max-history-messages`
  also controls persisted-history trimming when both message and token thresholds are high
- `/undo` restores the last compaction snapshot or the last file write/edit;
  failed summarization does not replace the original history

## Security notes

- `run_bash` executes shell commands on your machine in `--workdir` (cwd only, not jailed — unlike `list_dir`/`search_text`/`read_file`/`write_file`/`edit_file` which enforce workdir jail). It returns structured JSON, runs in a separate process group, has bounded output, kills descendants on timeout, and does not pass OpenRouter/Brave API keys to the child environment.
- `discover` fetches web content (`https` only, private/loopback/link-local/metadata blocked after hostname resolution and on observed final URLs; browser subrequests still depend on the underlying browser boundary). All web content is untrusted — model may be prompt-injected via page content; keep allow/deny gated.
- `BRAVE_API_KEY` used for `discover(search)`, `UNBROWSER_BINARY` can select browser binary — both allowlisted from `.env`; `auto` no longer silently mocks (requires `--discovery mock` for synthetic `example.com/mock`).
- independent `discover` batches use stateless clients for real concurrency (`max_concurrency`, default 5); stateful calls outside a batch reuse one session and are queued. `run_bash`/file ops serialize in mixed batches. Each `discover` has a configurable `1-120s` timeout (30s default).
- Model outputs (tool calls) are reflected literally in `run_bash` + URLs in `discover`, so treat every allowed tool call as untrusted input and keep the allow/deny policy enforced unless you deliberately want to run everything.
- default policy is `ask` for every tool call; approvals can be once, batch, turn,
  session, or explicitly persistent
- use `/deny *` for a fully no-tools session; `/allow discover` is persistent while
  `--allow-discovery` is scoped to the current process
- default model is free-tier (`nvidia/nemotron-3.5-lightning:free`); override with `--model` or `OPENROUTER_MODEL`

## Tool schema seen by the model

When tools are enabled, each OpenRouter request includes these tool definitions (filtered when `--discovery off`):

```json
[
  {
    "type": "function",
    "function": {
      "name": "run_bash",
      "description": "Run a host shell command; returns structured JSON (ok/exit_code/stdout/stderr/timed_out).",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {"type": "string"},
          "timeout_seconds": {"type": "integer", "default": 30}
        },
        "required": ["command"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_dir",
      "description": "List directory entries inside the workdir jail.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "max_entries": {"type": "integer"}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "search_text",
      "description": "Literal text search under a workdir path.",
      "parameters": {
        "type": "object",
        "properties": {
          "pattern": {"type": "string"},
          "path": {"type": "string"},
          "max_matches": {"type": "integer"},
          "max_file_bytes": {"type": "integer"}
        },
        "required": ["pattern"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": "Read file (workdir-jail) with line range, max_lines paging, and next_cursor.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "start_line": {"type": "integer"},
          "end_line": {"type": "integer"},
          "max_lines": {"type": "integer"},
          "max_bytes": {"type": "integer"},
          "cursor": {"type": "string"}
        },
        "required": ["path"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "write_file",
      "description": "Atomic write (workdir-jail) with optional expected_sha256 and dry_run.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "content": {"type": "string"},
          "expected_sha256": {"type": "string"},
          "dry_run": {"type": "boolean"}
        },
        "required": ["path", "content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "edit_file",
      "description": "Atomic unique string replace (workdir-jail) with optional expected_sha256 and dry_run.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string"},
          "old_string": {"type": "string"},
          "new_string": {"type": "string"},
          "expected_sha256": {"type": "string"},
          "dry_run": {"type": "boolean"}
        },
        "required": ["path", "old_string", "new_string"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "discover",
      "description": "Web discovery via pyunbrowser. Use search with query or navigate with an https URL; independent calls may run stateless and concurrently.",
      "parameters": {
        "type": "object",
        "properties": {
          "kind": {"type": "string", "enum": ["search", "navigate"]},
          "query": {"type": "string"},
          "url": {"type": "string"},
          "goal": {"type": "string"},
          "timeout_seconds": {"type": "integer"}
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
   - otherwise prompt user with once/batch/turn/session/persistent scopes.
4. For `run_bash`, CLI executes:
   - `asyncio.create_subprocess_shell(command, cwd=<workdir>, stdout=PIPE, stderr=PIPE)` in a separate process group with sensitive API keys removed from the child environment
   - waits with `asyncio.wait_for(..., timeout_seconds)`
   - kills process on timeout
    - concurrent batches: independent pure `discover` calls use stateless clients and run concurrent (`max_concurrency`, semaphore); any `run_bash`/file ops in batch force serialization
5. For `discover`, CLI executes (blocking → `to_thread`, configurable `1-120s` timeout, 30s default):
   - `kind=search`: `SmartClient.search(query, engine=brave)` (needs `BRAVE_API_KEY`)
   - `kind=navigate`: `SmartClient.navigate_auto(url, goal=goal)` (LLM extraction)
   - `mock` mode: synthetic `example.com/mock` hits (explicit `--discovery mock` only)
6. CLI records each call with a stable ID, formats a bounded result, and appends exactly one `role:tool` message per `tool_call_id`; structured discovery truncation remains valid JSON. Use `/inspect <call-id>` to inspect a recent full result.

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

## Offline evaluation workflow

The repository includes a small evaluation workflow that runs the real CLI
engine, real tool layer, and real task verifiers. The mock profile is
provider-offline: it makes no provider calls (mock-generated commands are host
shell commands, so they are not a network guarantee). Suite manifests and mock
scripts are trusted operator-provided input: their commands execute on the host
inside a disposable working directory, so review them like test code before
running.

After installing the source checkout with `pip install -e .`:

```bash
openrouter-agent-eval \
  --suite eval_suites/coding_smoke_v1/suite.json \
  --profile worker=eval_suites/mock_worker.json
```

The command writes append-only attempt records under `.agent-eval/runs/` and
prints a paired report with pass counts, shared-task outcomes, token/latency
accounting, uncertainty intervals, and the suite-specific leaderboard. To
re-render an existing run without executing attempts:

```bash
openrouter-agent-eval \
  --suite eval_suites/coding_smoke_v1/suite.json \
  --eval-dir .agent-eval \
  --report-only
```

To exercise both ordinary and verifier-assisted treatments fully offline,
provide the mock profile twice and mark one profile as assisted:

```bash
openrouter-agent-eval \
  --suite eval_suites/coding_smoke_v1/suite.json \
  --profile baseline=eval_suites/mock_worker.json \
  --profile assisted=eval_suites/mock_worker.json \
  --assisted-profile assisted \
  --repeats 2
```

The assisted rows are reported separately and are excluded from the ordinary
model leaderboard. Prompt-file profiles make real OpenRouter calls and must
only be used with an explicitly approved model budget and the documented
execution-containment settings.

## Findings and release docs

- benchmark findings: `docs/AB_FINDINGS_2026-02-21.md`
- public release checklist: `docs/PUBLIC_RELEASE_CHECKLIST.md`
- security policy: `SECURITY.md`
- env template: `.env.example`
