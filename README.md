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
openrouter-agent --model openrouter/auto
```

Or without installation:

```bash
export OPENROUTER_API_KEY=sk-or-...
python -m openrouter_agent_cli.cli --model openrouter/auto
```

## Useful flags

```bash
openrouter-agent \
  --model openrouter/auto \
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

