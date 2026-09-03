# Policy Space — candidate interventions for the smart harness

**Status:** written 2026-09-03. Feeds the end goal in `docs/roadmap.md`: a
harness that generates policies, measures each against real tasks with
experiment integrity, and keeps only the ones that substantially improve what
coding agents produce.

## The end goal, in one line

The harness proposes a policy, measures it on a hard task bank with a
preregistered bar, and keeps it only if the effect clears that bar.

## Where policies can intervene

The engine exposes one hard seam and three softer ones. A policy is anything
that changes behavior at one of these points.

1. **Checkpoint seam** (`RuntimeCheckpoint` / `CheckpointDecision`) — the
   policy decides continue / repair / stop at final-answer and mutating-batch
   boundaries. This is where the acceptance gate lives, and where the
   verifier-assisted policy hooks in for experiments.
2. **Prompt overlay** — the system prompt or user-message shape the agent
   sees. Two overlays already exist and were used in earlier campaigns:
   `prompts/overlay_execution_discipline.md` and
   `prompts/overlay_execution_recovery.md`.
3. **Tool rules** — budgets, allow/deny decisions, serialization. Partly
   built into the engine already (permission policy, discover caps, repeated-
   call detection).
4. **Model choice** — which model drives the loop, held fixed or varied, to
   separate model variance from policy effect.

## The first candidate policies

1. **Acceptance gate** (implemented, feasibility-tested): a developer-chosen
   command must pass before completion is accepted; one additional model
   response on failure, then stop with evidence. This is policy #1 — the
   baseline the harness starts from.
2. **Discipline overlay** (exists, untested this cycle): prompt overlay
   demanding plan-first, tool-disciplined behavior.
3. **Recovery overlay** (exists, untested this cycle): prompt overlay for
   recovery behavior after failed tool calls.
4. **Tool-discipline rule** (not yet built): a seam-enforced rule, e.g. a hard
   cap on repeated tool calls before the agent must answer, or a rule that a
   mutating change must be verified by the agent's own test run before
   completion.
5. **Model comparison** (not a policy per se, but a control): the same task
   bank across models, to know how much of the variance is the model.

## The selection rule for "substantially improves"

Per campaign, preregistered before any results exist, a policy is kept only
if, on the held-out task bank with adequate power, it clears:

- **effect:** verified pass rate at or above a pre-committed threshold (the
  first campaign should target a double-digit improvement, not a point or
  two);
- **regressions:** no more than a pre-committed ceiling of baseline-passing
  tasks turning into failures;
- **cost:** added tokens and elapsed time within a pre-committed ceiling; and
- **integrity:** no material probe-versus-final-verifier disagreement, and
  the campaign audit passes.

These numbers are frozen in the campaign preregistration, not chosen after
seeing results.

## The task-bank requirement

A policy can only show substantial improvement where unassisted agents fail
enough to leave headroom. The first task bank must have a baseline verified
pass rate around 50–60% on unassisted runs — failing roughly half the tasks —
so a good policy has room to move the number in a detectable way. Existing
families (crash-diagnosis, bounded-generalization) need their baseline
failure rates measured, and tasks added until the failure floor is reached.

## The measurement machinery (already built)

The suite runner drives the real engine; verifier contracts grade workspaces;
records are treatment-separated and append-only; the campaign audit checks
schema, pairing, containment, and separation; real-model runs are contained.
The harness's job is to push candidate policies through this machinery and
keep the winners.

## External dependencies

- **Linux keep-awake gate** — the `systemd-inhibit` preflight must succeed for
  real-model campaigns at scale; this is the critical path.
- **Power analysis** — size the campaign before preregistration so a
  pre-committed effect is detectable with the planned task count and repeats.