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