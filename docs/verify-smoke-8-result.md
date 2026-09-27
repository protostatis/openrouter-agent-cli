# Verifier Smoke Trial — 8 Attempts (2026-09-07)

**Status:** Small opt-in trial of the workspace-checking completion policy on 4
tasks. Descriptive only. It does not change the earlier decision: the policy
stays opt-in, never a default, never used for routing, and not a training-data
source.

## Plain conclusion

The verifier-assisted policy passed 3 of 4 tasks; the unassisted baseline
passed all 4. The one difference is a regression: the policy turned a passing
baseline attempt on the unbound-local bug (`novel03`) into a failure after its
single repair. No attempt was rescued this time. This matches the pattern from
the earlier 40-attempt feasibility run (2 rescues, 1 regression there; 0
rescues, 1 regression here).

## Setup

- Suite: `eval_suites/crash_novel_v1/suite.json`, tasks `novel01`, `novel03`,
  `novel05`, `novel08` (two crash bugs, one silent wrong-output bug, one
  data transform).
- Both arms used the identical control prompt
  (`eval_suites/campaign_control.md`, same SHA-256) and the same free model
  (`nvidia/nemotron-3.5-lightning:free`).
- 10 turns maximum, one repeat, 8 attempts total.
- Execution: host bash in disposable workspaces on macOS (no Linux sandbox
  available); accepted explicitly via `AGENT_EVAL_ALLOW_HOST_EXECUTION=1`.
- Artifacts: `.agent-eval/verify-smoke-8/runs/bounded-generalization-v1.jsonl`.

## Outcomes

The table shows each task's verified result for the unassisted baseline and
the verifier-assisted policy. The assisted arm must pass the workspace check
before completing and gets one repair response.

| Task | Baseline | Assisted |
|---|---|---|
| novel01 (crash: None.upper()) | pass | pass |
| novel03 (crash: unbound local) | pass | **fail** |
| novel05 (silent: min instead of max) | pass | pass |
| novel08 (transform: CSV to JSON) | pass | pass |

Paired counts: 3 both-pass, 1 baseline-only pass, 0 assisted-only pass
(no rescues), 0 both-fail.

## Cost and latency

- Baseline: 55,072 tokens total, median attempt 270 seconds.
- Assisted: 35,659 tokens total (lower because attempts finished earlier),
  median 151 seconds, plus one repair costing 6,843 tokens and 201 seconds.
- The repair fired once; hidden probe disagreed with the verifier zero times;
  zero infrastructure errors.

## Reading

The sample is far too small for any rate claim (4 tasks per arm). The only
new signal is that the regression mode observed in the 40-attempt run
reappeared: the policy can spend its one repair on an already-correct
workspace and end worse than doing nothing. Keep the feature opt-in; a larger
study needs the newly frozen, task-level design already required by the
earlier disposition before any change to that decision.
