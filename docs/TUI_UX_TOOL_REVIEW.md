# Human-Centered TUI and Tool Review

**Scope:** `openrouter_agent_cli/cli.py`, `utils.py`, `discovery.py`, the README, and the
existing tests.

**Review date:** 2026-08-29

## Executive summary

This project is currently a **line-oriented REPL**, not a full-screen TUI. It has
good foundations: bracketed multi-line paste, Markdown assistant output, persisted
sessions, explicit tool permissions, file-path jail checks, command timeouts, and
bounded discovery concurrency.

The main human problem is not visual styling. It is **trust under uncertainty**:
while the agent is working, the user cannot reliably tell what it is doing, what it
will do next, how much it costs, whether it is still alive, or how to undo/recover.
The broadest risk is that a compact tool UI hides high-impact behavior: `run_bash`
executes an unjailed local shell, while an `allow` decision is persisted across
sessions and working directories.

Recommended direction:

1. Fix tool protocol, permission scope, terminal-output safety, cancellation, and
   compaction recovery.
2. Add a compact status/lifecycle layer to the existing scrollback REPL.
3. Improve tool contracts and inspection before building a full-screen interface.
4. Build a full-screen TUI only if users need simultaneous jobs, persistent panels,
   or interactive evidence inspection.

## Current interaction model

The observable flow is approximately:

```text
startup banner
    -> you> prompt
    -> (possibly blank while the model works)
    -> [permission] raw y/n/a/d prompt
    -> [tool] one-line invocation
    -> [tool-result] one-line preview
    -> assistant> rendered Markdown
```

The implementation uses `prompt_toolkit` for input and `rich` for final Markdown,
but it does not own the terminal screen, render a persistent layout, or expose a
navigation model. That distinction matters: a scrollback-first REPL is usually
better for SSH, copy/paste, logs, accessibility, and automation; a full-screen TUI
is better for dashboards and simultaneous interactive work.

## What is already working well

- The default permission decision is `ask`, rather than silently executing tools.
- `/tools on|off`, `/allow`, `/deny`, and explicit discovery modes give users some
  control over capabilities.
- Multi-line paste is treated as one user message.
- Assistant Markdown is rendered while control characters and terminal hyperlinks
  are stripped from that particular output path.
- File tools resolve paths before checking that they remain inside `workdir`.
- Shell execution has a timeout and returns exit status/stdout/stderr information.
- Sessions and manual/automatic compaction exist, which is a useful base for a
  long-running harness.
- Pure discovery batches preserve result order in the returned list.

## Human walkthrough and friction points

| Moment | Current experience | Human cost | Improvement |
| --- | --- | --- | --- |
| First launch | Technical banner shows model, session, cwd, discovery caps; no clear `fresh`/`resumed` state | User cannot form a reliable mental model of what is active | Add `/status` and a compact status header with session state, tools, policy scope, context, and risk |
| User submits work | No visible request state until the response or a tool log appears | A 30-60 second blank terminal looks frozen | Emit immediate `requesting`, retry, queue, and elapsed-time events |
| Agent asks for a tool | Raw `input()` prompt; arguments are truncated to 220 characters | User may approve an action without seeing the important part or its scope | Use a review prompt with risk, full command/path, effect summary, and explicit approval scope |
| Agent runs tools | Plain `[tool]` and `[tool-result]` lines; no stable call IDs or duration | User cannot correlate calls and results, especially in batches | Show `call 2/5`, status, duration, exit state, and `/inspect <id>` |
| Tool returns a lot of data | Only a one-line 220-character preview is shown | Important evidence is hidden and there is no local inspection affordance | Page or save full results and make them inspectable without asking the model again |
| Discovery batch | Approval serializes an otherwise parallel batch; real session calls are lock-serialized | The product promises concurrency but the user sees repetitive prompts or queuing | Offer batch review and label stateful discovery as queued, or use independent clients for real parallelism |
| Context grows | Auto-compaction is a log line; `/usage` mixes estimates with process-only token counters | User cannot predict what context was lost or what “session tokens” means | Show context budget, compaction preview, summary snapshot, and process-vs-persisted usage |
| User changes state | `/model`, `/cwd`, `/new`, and `/clear` are terse mutations | History and permissions can silently apply to a different model/project | Confirm or warn on high-impact changes; expose active state in one place |
| Failure or cancel | Errors are plain text; Ctrl-C behavior differs between input and active work | Recovery is unclear and a stuck operation may leave background work | Make cancel a first-class state and return to a usable prompt with next actions |

## Priority 0: correctness, safety, and trust blockers

These should precede visual polish.

### 1. Make permission grants scoped and consequence-aware

`ToolPermissionPolicy` is keyed only by tool name, and `/allow` is persisted in a
global policy file. A grant can therefore outlive the session and working directory
that motivated it. `run_bash` is not jailed and inherits the process environment.

Recommended approval scopes:

- **Once**: this exact call only.
- **Batch**: calls in the current model response only.
- **Turn**: until the current user request finishes.
- **Session**: current session and working directory.
- **Persistent**: explicit, separately confirmed, and visibly marked.

The prompt should state the scope before accepting input. File writes/edits should
show a diff or a safe summary; shell calls should show the complete command, cwd,
timeout, and whether network/filesystem access is unrestricted. `/allow` and
`/deny` should validate tool names and support argument-aware rules later (for
example, read-only commands or a path prefix).

Also consider removing secrets from the child environment by default. At minimum,
the UI should clearly warn that shell commands can access local environment
variables and that tool results are sent to the remote model.

### 2. Sanitize every terminal-bound string

The final assistant path calls `_strip_control_chars`, but tool arguments, shell
stdout/stderr, discovery previews, `/context` output, and several error paths are
printed directly. Untrusted content can therefore emit ANSI/OSC sequences or
misleading terminal hyperlinks.

Create one terminal-safe rendering boundary and use it for every interactive log.
It should remove CSI/OSC escapes, BEL, C0/C1 controls, and unsafe hyperlinks while
preserving ordinary newlines, tabs, and useful Unicode. Add regression tests for
tool arguments and tool results, not only assistant output.

### 3. Preserve one tool result per tool-call ID

The `max_discover` and `max_rounds` enforcement currently operates on a mixed list
of calls. It can truncate non-discovery calls and can omit a result for a dropped
`tool_call_id`. When a batch contains both discovery and another tool, an exceeded
discovery round can also produce a discovery error for every call.

Required invariant:

```text
for every assistant tool_call ID:
    append exactly one role=tool result, in the original order
```

Count and cap discovery calls independently. If a call is over a cap, append a
structured blocked result for that ID rather than dropping it. Never silently
truncate a result in a way that destroys a structured discovery payload; use a
typed envelope with a `truncated` flag and continuation handle.

### 4. Make cancellation and compaction transactional

The current discovery timeout cancels the await on `asyncio.to_thread`, but does
not necessarily stop the underlying thread. A shared discovery session can remain
busy or hold its lock. Ctrl-C also does not have a clear “cancel active turn and
return to prompt” path.

Compaction should be a transaction:

1. Build a summary in a temporary in-memory state.
2. Validate that the summary response is usable.
3. Write a backup/undo snapshot.
4. Atomically replace the active session.

If summarization fails, retain the original history unchanged. Add a cancellation
token or genuinely cancellable subprocess boundary for browser work. Ctrl-C should
cancel the active request/tool; Ctrl-D or `/exit` should exit.

### 5. Treat redirects and network resolution as part of SSRF validation

The initial `discover` URL checks scheme and obvious private hosts, but the browser
can still follow redirects or resolve public names to private addresses. Revalidate
every hop/request or isolate discovery in a constrained process/network boundary.
Keep response-size and timeout limits visible in the tool result.

## Priority 1: high-value REPL/TUI improvements

### 1. Add a lifecycle/status layer without switching to full-screen mode

Introduce a small event model and render states such as:

```text
requesting model...
retrying request (2/3) in 4s
awaiting approval for call c2
running discover call c2 (1/5) 12.4s
queued behind stateful discovery session
compacting context (42% -> 18%)
```

Every state should have an elapsed time and a terminal outcome. The first visible
state should appear immediately after Enter; there should never be an unexplained
long blank interval. Keep final assistant output stable and Markdown-rendered.

### 2. Add a compact `/status` command

`/status` should answer the questions a user otherwise has to reconstruct from
several commands:

```text
model:       nvidia/...:free
session:     default (resumed, last saved 14:03)
workdir:     ~/Projects/example
tools:       on | policy: ask (session scope)
discovery:   real | stateful/queued | 30s timeout
context:     38/60 messages, ~7.4k estimated tokens
usage:       process 12.1k prompt + 2.3k completion tokens
```

Startup should distinguish `fresh` from `resumed`, show whether a policy is
persistent, and surface a risk label for unrestricted shell execution.

### 3. Replace one-line tool logs with progressive disclosure

Use a compact transcript row by default and retain full details locally:

```text
o c2  discover  running  8.2s  "search: Python 3.14 compatibility"
o c1  run_shell succeeded 0.8s  "pytest -q"
```

Provide `/inspect c2`, `/tool c2`, or a key binding to view the full request/result.
For large output, page it, write it to a temporary transcript file, or expose a
continuation cursor. Do not make the model's next response the only way to inspect
what happened.

### 4. Make approval a review queue, not a sequence of surprises

For a batch, show all pending calls together, then let the user approve once,
approve selected calls, deny selected calls, or approve the batch for one turn.
This preserves concurrency when the user has already made the decision.

Example:

```text
2 tool calls need approval (workdir: ~/repo)

c1 HIGH  run_shell  pytest -q
c2 LOW   read_file  src/app.py (lines 1-120)

[a]ll once  [s]elected  [b]atch  [n]one  [e]xpand  [Esc] cancel
```

### 5. Improve keyboard discoverability

Keep the current bracketed-paste behavior and add:

- slash-command completion and descriptions after typing `/`;
- tool-name and path completion for policy commands;
- persistent searchable command history;
- `Ctrl-C` to clear/cancel the current operation and `Ctrl-D` to exit;
- a clear multiline/editor mode for long prompts;
- typo suggestions for unknown slash commands.

Use `prompt_toolkit` for permission input too, rather than switching to raw
`input()`, so the editing, interrupt, and terminal behavior is consistent.

### 6. Make destructive state changes recoverable

- Confirm `/clear`, or make it undoable.
- Add `/sessions` and `/resume <id>` with last activity and cwd metadata.
- Add `/export` for a readable transcript and `/undo` for the last compaction or
  file write where safe.
- Warn when `/cwd` or `/model` changes while retaining existing context.
- Make session writes atomic and set restrictive file permissions because tool
  results may contain source code, local paths, or secrets.

## Priority 2: visual polish and optional full-screen TUI

### Recommended compact transcript layout

Do this first in normal scrollback mode:

```text
 OpenRouter Agent | model: nemotron-free | session: resumed
 cwd: ~/repo | tools: ON | policy: ASK | context: 38%
 ------------------------------------------------------------------
 you> Inspect the failing tests and propose a fix
 .. requesting model                                             1.2s
 .. awaiting approval: run_shell                                  0.0s
 .. c1 run_shell  pytest -q                         failed (2.8s)
 assistant>
 The failing test is ...
 ------------------------------------------------------------------
 Ctrl-C cancel  Ctrl-R history  /help commands
 you>
```

Visual rules:

- Use color as a secondary channel; always include text labels for status.
- Reserve red for blocked/failed actions, yellow for approval/warnings, and green
  for completed safe operations.
- Keep tool rows compact and final answers readable in scrollback.
- Avoid displaying raw model reasoning as a substitute for an answer.
- Preserve copy/paste and narrow-terminal behavior; wrap rather than relying on
  horizontal panels.

A full-screen TUI becomes justified when there are multiple active jobs, a need to
  browse source evidence beside the transcript, or a persistent approval queue.
If built, use a two-pane model: transcript on the left/main pane, selected tool or
evidence details on the right, with a bottom command/status bar. It must degrade to
the current scrollback REPL for dumb terminals, SSH, redirected output, and
non-interactive use.

## Tool contract improvements

| Tool | Current issue | Recommended contract |
| --- | --- | --- |
| `run_bash` | Name says Bash but implementation uses the system shell; unrestricted cwd/environment; output is an untyped string | Rename to `run_shell` or invoke an explicit shell; return `{ok, exit_code, stdout, stderr, timed_out, duration_ms, truncated}`; kill the process group; scrub secrets; show risk and cwd |
| `read_file` | Reads an entire file before slicing; no byte limit or continuation; contents are sensitive | Add max bytes/lines, encoding metadata, paging cursor, binary-file handling, and an explicit “content sent to model” indication |
| `write_file` | Overwrites in one operation; no diff, atomicity, size limit, or conflict check | Add dry-run/diff, max size, atomic temp-write + rename, file hash precondition, and a result with old/new hash and byte count |
| `edit_file` | Exact unique string replacement is brittle and has no stale-file precondition | Add expected file hash, line/range context, diff preview, atomic write, and structured failure reasons |
| File surface | No safe directory listing/search/patch workflow; model may use shell for basic navigation | Add bounded `list_dir`, `search_text`, and patch application with explicit file-level review; keep shell as a higher-risk escape hatch |
| `discover` | `kind` has conditional fields, search can fall back to `goal`, output shape varies, and stateful sessions make advertised concurrency misleading | Split into `search` and `navigate`/`fetch`, validate fields conditionally, return normalized source records, include status/latency/quality warnings, expose stateful vs stateless mode, and make budgets explicit |
| Permissions | Tool-name-only persistent allow/deny is too broad | Support once/batch/turn/session/persistent scopes and later command/path/domain matchers |
| Orchestrator | Caps can affect mixed batches; results are strings capped by character count; calls lack user-facing IDs | Apply caps per tool type, return one typed result per call ID, attach duration and cancellation state, and preserve structured payloads with cursors |

## Suggested command surface

Keep existing commands for compatibility and add:

```text
/status                 Show all active runtime state
/sessions               List saved sessions and last activity
/resume <id>            Switch to a saved session with confirmation
/inspect <call-id>      View full tool request/result
/cancel                 Cancel the active turn/tool
/policy                 Show policy entries and their scopes
/export [path]          Export a readable transcript
/compact --preview      Preview what would be summarized
/undo                   Undo the last reversible state change
```

`/tools` should show tool descriptions, risk class, and current scope rather than
only names and two lists.

## Acceptance criteria for the next iteration

### Trust and correctness

- Every model tool call ID receives exactly one tool result, including denied,
  capped, malformed, and cancelled calls.
- No model-generated or web/shell-generated control sequence can alter the terminal
  or create a hidden hyperlink in interactive output.
- Persistent permission requires explicit confirmation and is visibly labeled as
  persistent; changing cwd/session cannot silently broaden a one-time grant.
- A failed compaction leaves the prior session history unchanged and recoverable.
- Ctrl-C cancels an active turn and returns to a usable prompt within a predictable
  bounded time; timed-out discovery cannot hold the session lock indefinitely.
- Discovery blocks private/metadata destinations after DNS resolution and redirects,
  or runs in a boundary that makes that access impossible.

### Human experience

- A lifecycle state appears immediately after submission and updates during every
  retry, approval wait, queued call, and long-running tool.
- A user can answer “what model, cwd, session, tools, policy, and context are
  active?” with one `/status` command.
- A user can inspect the complete request and result for any tool call without
  relying on the model's final answer.
- Tab completion works for slash commands and policy tool names.
- Narrow terminals, redirected output, and non-interactive `--prompt` mode remain
  usable.

## Implementation status (2026-08-29)

Completed in rounds 1-2:
- scoped approvals, lifecycle status, `/status`, `/inspect`, terminal sanitization
- tool-call/result invariants, compaction undo, shell process-group safety
- typed `run_bash` JSON results, `list_dir`/`search_text`, read paging cursors
- write/edit hashes + dry-run + one-shot file undo, compact preview, richer completion
- color-coded status/tool-result rows in the scrollback REPL

Still open / later:
- split discover into dedicated search/navigate tools
- argument-level permission matchers (command/path/domain)
- optional full-screen multi-pane TUI

## Implementation order

1. Add regression tests for output sanitization, tool-call/result invariants,
   compaction failure, cancellation, and truthful discovery concurrency.
2. Introduce typed tool events/results and a single safe terminal renderer.
3. Implement scoped approval and `/status`, then lifecycle/progress rendering.
4. Add bounded/diff-aware file tools and normalized discovery results.
5. Add history/session inspection and recovery commands.
6. Reassess whether a full-screen TUI is still necessary after observing real users.
