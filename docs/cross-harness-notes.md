# Cross-Harness Comparison — First Baseline (2026-09-03)

**What this is:** the first run of `scripts/compare_harnesses.py` — the same
three tasks, the same model
(`nvidia/nemotron-3-super-120b-a12b:free`), the same verifiers, through three
harnesses: our engine (plain, no acceptance gate), opencode (headless), and
pi (headless). One attempt per cell. Descriptive, not powered.

## Results

| Task | ours | opencode | pi |
|---|---|---|---|
| xfix12 (case-insensitive count) | pass | pass | pass |
| xfix01 (wrap-around pairs) | pass | pass | pass |
| xfix09 (trailing-space in data) | pass | **task_fail** | pass |

Raw cells: `.agent-eval/comparisons/harness-cmp-*.jsonl` (ignored by git).

## What the log details show

1. **The ambiguity fix worked.** The two tasks that previously failed 100%
   (hidden goal) are now passed by all three harnesses once the goal is
   stated in the prompt. Proof the old failures were ambiguity, not skill —
   and those two tasks are now too easy for the hard bank.

2. **Clear goals activate natural verification.** In the passing cells, all
   three harnesses read, edited, ran the program, and confirmed the output
   before finishing (visible in the logs: opencode and pi both run
   `python3 domains.py` / `python3 chain.py` and check). This is the
   concrete answer to "how do other harnesses figure out verification": the
   model does it, once the goal is unambiguous.

3. **A third failure mode appeared.** opencode failed xfix09 by *reading both
   files but never making the fix* — output empty, no edit. The earlier logs
   gave us two failure modes (didn't verify; verified but couldn't infer the
   rule); this one is "read everything but didn't act." It is exactly what a
   force-run-before-done policy targets.

4. **xfix09 is a genuine discriminator** — pi caught the trailing-space trap,
   opencode missed it, with the goal stated. It stays in the bank.

## Consequence for the hard bank

Tasks whose difficulty comes from a hidden goal collapse once the goal is
stated. The bank must be built from tasks like xfix09: a clear goal plus a
subtle silent bug that agents miss anyway — or from tasks that need tools the
agent must choose to use (see the unbrowser web-task family), or multi-step
logic traps.

## Raw prompts captured through the proxy (2026-09-03)

Using the capture proxy (`scripts/capture_proxy.py`, in front of the
sky-proxy or OpenRouter directly), we recorded the FULL request bodies each
harness sends — the actual prompts loaded into the model's context. Same
task (web_format_duration), same model
(`nvidia/nemotron-3-super-120b-a12b:free`), all three passed.

| Dimension | ours | opencode | pi |
|---|---|---|---|
| System prompt | "You are a careful coding agent." (minimal) | full default agent prompt + environment block + user's global AGENTS.md + MCP instructions + skills list | "expert coding assistant inside pi" + tool guidelines + skills list |
| Verification instruction | none (verification is the external gate) | **explicit, soft**: "Run targeted tests, builds, or checks when they are relevant and feasible"; "Prefer concrete implementation and verification" | none |
| Tool schemas per request | 7 | **66** | 4 |
| Request size | (small; 7 tools) | **82–97 KB** per call | 7–19 KB per call |
| Model calls for the task | 8 | 6 | 10 |
| Verdict | pass | pass | pass |

Findings:

1. **opencode is the only harness with explicit verification guidance in its
   prompt — and it is soft** ("when relevant and feasible"), which matches
   the observed read-but-didn't-act failure on xfix09: the instruction lets
   the model skip it.
2. **pi has no verification instruction at all**, yet its model verified on
   its own (it ran the examples) — verification there is pure model habit.
   Ours has no instruction either; verification is deliberately external.
3. **opencode's 66 tool schemas make each request ~5–10× larger than pi's or
   ours** (82–97 KB vs 7–19 KB). That is a large fixed context cost per call
   and a candidate policy target: a minimal tool surface.
4. opencode also runs a separate small "title generator" call before the
   agent calls (2.9 KB, no tools).

Setup note: ours routes via `OPENROUTER_BASE_URL`; opencode via a `skycap`
provider in `~/.config/opencode/opencode.json`; pi via a `skycap` provider in
`~/.pi/agent/models.json`. Both point at the capture proxy (localhost:8789),
which forwards to OpenRouter.

## Contamination found and removed (isolated harnesses)

The first capture revealed that opencode's prompt included the OPERATOR'S
global config: the global AGENTS.md, the unchainedsky MCP server (~30 tools),
npcterm (~17 tools), and webfetch tools — inflating opencode to 66 tool
schemas and ~82–97 KB per request. pi included an operator skill (unbrowser).
We were measuring the operator's configured harnesses, not the harnesses.

Fix: run each harness with an isolated config directory containing ONLY the
capture provider (`scripts/isolated_harnesses.sh` creates them):
- opencode: `XDG_CONFIG_HOME=/tmp/opencode-clean/config opencode run ...`
- pi: `HOME=/tmp/pi-clean pi -p ...`

Isolated sizes (same web task, same model, all verified):

| Dimension | ours | opencode (isolated) | pi (isolated) |
|---|---|---|---|
| Tool schemas | 7 | **10** | 4 |
| Request size per call | 5–21 KB | 35–41 KB | 6–15 KB |
| Calls for the task | 3 (12k tokens) | 5 | 6 |

Before/after for opencode: 66 → 10 tools, ~97 KB → ~35 KB requests. The
isolation also removed the operator's AGENTS.md and MCP tools from its prompt.

Consequences:
1. **opencode is still ~2–3× larger per request than pi or ours even when
   clean** (10 tools + richer system prompt) — part of the size gap is
   intrinsic, but the bulk of it was MCP/config contamination.
2. The isolated baseline is the fair comparison going forward. Container
   isolation (Docker) would add filesystem/process isolation and version
   pinning; the Docker daemon was not running on the dev machine, so config
   isolation was used for everything that had contaminated the measurement.

## Clean captured baseline with true token usage (2026-09-03)

The comparison runner now routes every harness through the capture proxy and
extracts TRUE provider-reported tokens from the captured responses (the
capture proxy decompresses gzip bodies and parses SSE streams for the final
chunk's usage). Isolated configs, same model, one attempt per cell (noisy —
direction only).

| Task | ours (tok/calls) | opencode (tok/calls) | pi (tok/calls) |
|---|---|---|---|
| xfix12 (case) | pass 14,932 / 6 | **task_fail** 18,306 / 3 | pass 13,952 / 6 |
| xfix01 (wrap) | pass 14,435 / 6 | pass 65,430 / 7 | pass 21,120 / 9 |
| xfix09 (whitespace) | pass 14,870 / 6 | pass 46,243 / 6 | pass 21,323 / 8 |
| web_format_duration | pass 46,623 / 8 | pass 48,366 / 7 | pass 13,749 / 5 |

Patterns (single attempts, so read as direction, not conclusion):

1. **pi is consistently the cheapest** (13–21k tokens across all four tasks)
   with its 4-tool surface and minimal prompt.
2. **opencode is the most variable and often the most expensive** (18–65k),
   driven by its 10-tool surface + larger system prompt.
3. **ours sits mid-range** (14–15k on the local xfix tasks, 46k on the web
   task — the web task needs the discover tool and more turns).
4. Single-attempt variance is real: opencode failed xfix12 here (missed the
   case trap) after passing it in the pre-isolation run. Repeats are needed
   before drawing conclusions about pass rates; the token/cost pattern is
   more stable.
## Harbor-backed pi-vs-ours comparison with proxy capture (2026-09-03)

Through Harbor (same task hard_crashing_script, same model
nemotron-super, same verifier, one run each), with both harnesses routed
through the capture proxy:

| | pi | ours |
|---|---|---|
| Score | 1.0 | 1.0 |
| Model calls | 6 | 8 |
| Tools | 4 | 7 |
| Avg request size | 8,080 bytes | 12,847 bytes |
| Total tokens (provider-reported) | 13,284 | 27,572 |

pi used about half our tokens for the same result (minimal prompt, 4 tools).
Setup notes: pi's Harbor adapter requires `--ak model_api=openai-completions`
to use a custom base URL (the proxy); ours routes via the adapter's
OPENROUTER_BASE_URL injection. Proxy capture verifies both harnesses' raw
contexts (system prompts, tool schemas, per-call usage).

## First cross-harness discriminator: report_pipeline (2026-09-03)

The longer-horizon 7-file task (3 coordinated cross-file bugs), same model,
same verifier, 3 runs each through Harbor:

| | ours | pi |
|---|---|---|
| Pass rate | **1/3 (33%)** | **3/3 (100%)** |
| Model calls (3 runs) | 72 | 53 |
| Total tokens (3 runs) | **616,956** | 198,664 |

pi both passes more AND uses ~3x fewer tokens. Our failure mode (from run
logs): the agent reads all files, edits multiple, breaks the syntax in one
edit, and does not re-run to catch the breakage. pi's loop maintains
verification discipline on the longer task.

This is the first task where the harness difference is decisive, not just
cost: on 6-8 step tasks both pass at ~100%; on the ~15-20 step task ours
fails ~2/3 of runs. Hypothesis this feeds: our acceptance-gate policy (must
run before done, one repair) is aimed exactly at the break-without-verify
failure mode — the campaign should test whether the gate rescues these runs.

## Acceptance gate on report_pipeline (exploratory, 2026-09-04)

The same task and model were then run three times with our one-repair
acceptance gate enabled. The fixed-grader results were:

| | unassisted | acceptance gate |
|---|---:|---:|
| Passes | 1/3 (33%) | 1/3 (33%) |
| Model calls (3 runs) | 72 | 63 |
| Total provider tokens (3 runs) | 616,956 | 443,036 |
| Median tokens per run | 208,818 | 158,642 |

This is **not evidence that the gate rescued a failure**. No repair injection
occurred in these three runs:

- Run 1 reached the 24-turn limit before producing a final answer; the
  acceptance boundary was never reached.
- Run 2 manually ran the acceptance command, saw it fail, and then spent the
  remaining turns rewriting `formatter.py`; it reached the 24-turn limit
  without a final answer, so the gate again had no chance to inject its one
  repair request.
- Run 3 fixed both files, ran the acceptance command successfully, and the
  gate verified the final answer without needing a repair.

The lower token total is therefore confounded by earlier stopping and must
not be treated as a policy cost advantage. The current result is a null
comparison (same 1/3 pass rate) plus a design finding: a final-answer-only
gate cannot rescue agents that exhaust the turn budget while editing. A
follow-up must either reserve a completion boundary or test a higher, equally
fixed turn budget for both arms; that follow-up must remain exploratory until
the budget is pinned before results are collected.
