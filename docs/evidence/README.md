# Evidence bundle

Sanitized, review-friendly copies of the records behind the claims in this
repository's docs. The raw records live outside the repo (`.agent-eval/` is
gitignored; workbench attempts live under `~/.openrouter-agent-cli/workbench/`)
and may contain full model transcripts, so these digests keep only what the
docs cite: verdicts, aggregates, and identifiers.

## What is here

| File | Backs this claim | Source |
|---|---|---|
| `tool-profile-bank-v1-summary.json` | The 40-pair tool-profile comparison: full7 36/40 vs core4 33/40, 7.5-point difference, paired outcomes, token/request counts (`docs/tool-profile-bank-experiment.md`) | `.agent-eval/tool-profile-bank-v1/summary.json` |
| `verify-smoke-8-outcomes.json` | The 8-attempt verifier trial: baseline 4/4, assisted 3/4, 0 rescues, 1 regression (`docs/verify-smoke-8-result.md`) | run records in `.agent-eval/verify-smoke-8/runs/`, verdicts from the doc's outcomes table (acceptance was run separately from the attempt records) |
| `dogfood-gate-attempts.json` | The dogfood gate: 20 attempts, statuses per task, which tasks fired the no-progress nudge, structural findings (`docs/internal-dogfooding-pilot.md`) | `~/.openrouter-agent-cli/workbench/gate-batch{1,2,3-guarded}/` |

## Provenance

- All three evidence sets were recorded on 2026-09-07 while running the code
  on this branch (`feat/workbench-guard-and-evidence`).
- The bank summary records the frozen inputs: seed `20260907`, prompt SHA-256
  `03f0713da89cf697a251f098eae0b0a7ce2cdfa7f7e9ba93dcf7e875e76427db`, model
  `nvidia/nemotron-3.5-lightning:free`.
- Each gate attempt record keeps its `source_commit` (the repo revision the
  attempt ran against) and duration.
- No API keys, authorization headers, transcripts, or machine-local file
  paths are included. Raw run records redact request headers down to three
  non-secret experiment headers (see `scripts/capture_proxy.py`).

## Known limitations (stated honestly)

- The smoke-trial verdicts are joined from the doc's outcomes table; the raw
  attempt records contain usage and policy data but not the acceptance
  verdict itself.
- The gate digest covers the 20 gated attempts (batches 1–3); the 3 earlier
  pilot attempts predate this directory layout and are summarized only in
  `docs/internal-dogfooding-pilot.md`.
- The guard fix in this branch (baseline captured before the first model
  call) landed AFTER batch 3 was recorded; the batch-3 runs used the earlier
  guard behavior. The 30-attempt held-out validation described in the pilot
  doc has not been run yet.
