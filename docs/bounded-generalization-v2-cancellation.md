# Bounded Generalization v2 — Budget Cancellation

**Date:** 2026-08-30
**Protocol:** `docs/bounded-generalization-v2-protocol.md`
**Status:** cancelled; no confirmatory conclusion is permitted.

The account balance reached approximately **$1**, so the real-model collection
was stopped immediately. No further OpenRouter calls are authorized by the
current work plan.

## What ran

The preregistered collection required 60 attempts:

- 20 attempts for Nemotron versus GPT-4o-mini completed.
- 9 attempts for Nemotron versus Qwen3 Coder 30B were recorded before the stop.
- 0 attempts for GPT-4o-mini versus Qwen3 Coder 30B started.
- **29 of 60 attempts were recorded; 31 were never started.**

All recorded attempts were made on Linux with the Bubblewrap sandbox enabled.
The partial records were copied to the local ignored path
`.agent-eval/bounded-generalization-v2-partial/` and are retained for audit
purposes only.

## Evidence rule

The partial v2 collection is not analyzed as a confirmatory result. It has no
complete pairwise design and was stopped for an external budget reason. The
earlier v1 collection is also exploratory only because six of its ten task IDs
had pre-existing target-model records; see
`docs/bounded-generalization-results.md`.

The remaining work is local-only: calibrate the outcome engine from completed
historical records, improve the evaluation workflow, and test the
verifier-assisted policy with mock transports. Any new real-model collection
requires a separate explicit budget decision.
