# A/B Findings (2026-02-21)

This report summarizes the hard-suite prompt A/B benchmark run and evaluator output.

## Run configuration

- benchmark run: `ab_tests/results/hard_suite_v1_r3/results.json`
- benchmark summary: `ab_tests/results/hard_suite_v1_r3/summary.csv`
- evaluator output: `ab_tests/results/hard_suite_v1_r3/eval/leaderboard.md`
- matrix: 2 prompts x 6 tasks x 3 repeats = 36 cases
- model: `arcee-ai/trinity-large-preview:free`
- tool mode: `execute`

## Overall leaderboard

From `ab_tests/results/hard_suite_v1_r3/eval/leaderboard.md`:

| prompt_variant | cases | avg_overall_adj | avg_groundedness | avg_correctness | avg_specificity | avg_valid_ref_ratio | avg_tokens | avg_latency_s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| system_prompt_control | 18 | 2.085 | 2.111 | 2.500 | 2.500 | 0.167 | 4256.4 | 45.847 |
| system_prompt_agentic_v1 | 18 | 1.916 | 1.833 | 2.333 | 2.944 | 0.056 | 5473.8 | 50.550 |

## Cost and runtime

From `ab_tests/results/hard_suite_v1_r3/summary.csv` (aggregated):

- `system_prompt_control`
  - total tokens: `76,616`
  - average tokens/case: `4,256.4`
  - average latency/case: `45.847s`
  - average tool calls/case: `2.722`
- `system_prompt_agentic_v1`
  - total tokens: `98,528`
  - average tokens/case: `5,473.8`
  - average latency/case: `50.550s`
  - average tool calls/case: `3.000`

## Task-level outcomes

- `task_01` (reliability/safety review): control wins
- `task_03` (compaction failure patch): tie
- `task_05` (refactor/test plan): tie
- `task_07` (`read_file` tool plan): agentic wins
- `task_09` (regression matrix): slight agentic edge
- `task_11` (security hardening): control wins

## Decision

Use `system_prompt_control` as default for this repo.

Reason:

- better overall adjusted score on this benchmark
- lower token spend
- lower latency
- better groundedness and valid file:line reference ratio

## Limitations

- judge model is also a free-tier model; scoring quality is not perfect
- some responses still hallucinate line numbers or pseudo-diffs
- this benchmark evaluates planning/design style tasks, not full code-edit execution quality

## Recommended next benchmark iteration

1. Add "edit-and-validate" tasks where output is an actual patch + test command plan.
2. Add a strict local checker for `file:line` and patch applicability.
3. Re-run with 5 repeats and compare variance per task.
