# Long-Running Coding Session Product Target

**Status:** implementation target; local product use, not a benchmark claim.

## Product promise

OpenRouter Agent CLI helps a developer work on one repository for hours without
losing the thread. The developer gives the agent a bounded coding task and an
optional acceptance command. The session preserves useful context, keeps risky
actions visible, reports cache information only when it is observable, and ends
with a reviewable change plus one of three honest states:

- **verified** — the acceptance command passed;
- **failed** — the acceptance command ran and did not pass; or
- **not verified** — no trustworthy acceptance result is available.

The product never treats the model's confidence as proof of completion.

## First user flow

```text
$ openrouter-agent --workdir ./my-repo \
    --task "Fix the failing login test" \
    --verify-command "pytest tests/test_auth.py"

you> inspect the failure and make the smallest fix
... agent works under the normal permission policy ...
... context is compacted only at a recoverable boundary ...
... the acceptance command is run before completion is accepted ...

VERIFIED
Changed files: ...
Check: pytest tests/test_auth.py — passed
Actions: /export, /undo, /task, /check
```

The same contract can be configured during an interactive session:
`/task <description>`, `/verify <command>`, and `/check`. `/task clear` and
`/verify off` remove the corresponding contract. Resuming the session restores
the task, the last acceptance state, and the cache observations.

When the check fails, the session gives the agent exactly one additional model
response. If that response's check still fails, the session stops with the
failure evidence for the developer instead of looping indefinitely.

## KV-cache-aware behavior

The first implementation optimizes what the product can control:

- keep the system prompt and tool schemas stable during a session;
- preserve an append-only message prefix between model requests;
- avoid unnecessary prompt reordering or injected state;
- compact only when needed and keep an undo snapshot;
- estimate stable-prefix tokens and report provider cache fields separately;
- show `not observable` rather than inventing a cache hit; and
- keep model-cache optimization separate from filesystem and browser state.

`--cache-mode off` disables the client-side observations when a provider or
experiment requires an untouched request path.

OpenRouter does not guarantee that every provider exposes or honors KV-cache
telemetry. The CLI therefore reports provider cache usage only when the response
contains an explicit cache field. Native KV save/restore and branch search are
later experiments, not part of this first product.

## Safety boundary

The current interactive `run_bash` tool executes on the host and is not a
general-purpose sandbox. Permission prompts, workdir-jail file tools, explicit
task scope, and the user-owned acceptance command improve control but do not
make host shell execution safe for untrusted tasks. A containerized execution
profile is required before making stronger isolation claims.

## First release boundary

Included: local repositories, small bug fixes, test repairs, bounded feature
changes, persistent sessions, context status, acceptance checks, diff review,
undo, and transparent failure states.

Excluded: automatic commits or pushes, deployment, production credentials,
autonomous merge, general browser workflows, multi-user orchestration, native
KV persistence, and automatic routing.
