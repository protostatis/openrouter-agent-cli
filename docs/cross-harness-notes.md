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