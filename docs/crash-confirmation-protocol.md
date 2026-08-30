# Crash-Diagnosis Confirmation Protocol (frozen before collection)

**Status:** protocol frozen 2026-08-30 per advisory ruling. The existing
3-task crash family is hypothesis-generating only — it was selected because
its result looked promising, so it cannot confirm itself. This protocol
predeclares everything needed for a confirmatory run.

## Primary claim (exact wording, predeclared)

> During this collection window, on the preregistered crash-diagnosis task
> family and averaged equally across the two tested prompt styles, the tested
> Nemotron profile completed more tasks successfully than the tested
> GPT-4o-mini profile.

No claims beyond this: not "better at debugging generally," not "free beats
paid" (price tier is confounded with model identity), not per-bug-mechanism
wins. Results are suite-specific.

## Design

- **12 new crash-diagnosis tasks**, independent of the exploratory three.
  Acceptance criteria (checked before any target model runs):
  1. A reference solution exists and passes the verifier (solvability proven).
  2. The bug mechanism varies across the set — error visibility (crash vs
     wrong output), data flow, repository shape, and root cause must not be
     twelve cosmetic clones of one traceback.
  3. Data/config files are sha-pinned where the spec forbids editing them.
  4. Tasks are NOT piloted on the two target models — any task that ran on
     them before the freeze belongs to the exploratory set.
- **Every task × all 4 profiles** (2 models × 2 prompt styles).
- **Two attempts per profile per task**, temporally interleaved (rounds
  alternate; profile order randomized within each task). 12 × 4 × 2 = 96
  attempts. Replicates estimate run variability; they do not add independent
  task count.
- Model name, timestamps, token usage, and per-tool outcomes are recorded in
  every run record (returned route/identifier, sampling parameters, and tool
  versions are NOT captured by the current record schema); collection
  completed in a short window to bound provider/release drift.

## Primary statistic (predeclared, single primary family)

- One paired difference per task: pass-rate difference between models,
  averaged equally across the two prompt styles and both replicates.
- **Two-sided exact sign test over tasks** (ties excluded from the count but
  reported): the decisiveness bar is p < 0.01 — 8 of 8 non-tied tasks is the
  mathematical minimum (p = 0.0078) with zero tolerance for a contrary task;
  11 of 12 favorable tasks yields p ≈ 0.0063 and is the safe target.
- The task-cluster bootstrap interval (existing `uncertainty.py`) is reported
  alongside as a secondary description. No other family is tested
  confirmatorily in this window; everything else stays exploratory.

## Tie handling and exclusions

- Tasks where every profile passes or every profile fails contribute no sign
  information; they are reported as ties, never removed after collection.
- An attempt whose verifier returns `infrastructure_error` counts as a
  failure for that attempt and is reported separately from task failures.
  (Automatic re-run-once was specified here but is not implemented in the
  collection runner; manual re-collections were used and are recorded as
  separate attempts.)
- A task whose verifier is later found defective is excluded with the reason
  logged; its partial data is discarded entirely (no partial credit).

## Protected-artifact adherence (secondary, separate from capability)

The existing integrity tripwire becomes a named metric: **protected-file
violation rate** (share of attempts that modified a sha-pinned artifact) and
**compliant repair rate** (share that fixed the source without touching the
protected file), reported separately from the capability leaderboard. A
variant family where editing the file IS allowed (matched controls) is added
so violations measure instruction adherence, not confusion.

## Explicit limitations (carried into any report)

Two models only; one collection window; hand-built suite with documented
task-sampling rules; prompt styles are crossed conditions, not independent
replications.
