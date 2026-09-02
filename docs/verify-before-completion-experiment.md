# Experiment Contract — Verify-Before-Accepting-Completion

**Status:** contract per advisor review 2026-08-31. The local prototype is
implemented and tested. A feasibility experiment, not a product commitment.
One-page intent; boundaries explicit.

## Purpose

Determine whether a verifier-assisted execution policy (probe the workspace
before accepting an agent's completion, repair once when incomplete, record
assisted outcomes separately) fires correctly, repairs failures, stops
successful work early, or merely adds cost — before we invest in it as a
product feature.

## Policy under test (minimal credible version)

**One hook: verification before accepting completion.** Not after every tool
call — after each attempted final answer or completed mutating batch.

Three-result probe, run host-side on the attempt workspace:

| Probe result | Policy action |
|---|---|
| `complete` | Stop the agent; rerun the **canonical final verifier** (unchanged, immutable verdict). |
| `incomplete` | Normally continue silently. If the model is trying to finish, inject ONE generic repair request and allow ONE additional cycle. No more than one injection per attempt. |
| `infrastructure_error` | Continue without intervention; record the error. |

## Separation and integrity rules

- **Two planes, never mixed:** the measurement plane runs unassisted agents
  (existing pipeline, immutable verdicts). The control plane applies this
  policy. Every record carries a `treatment` tag: `model_alone` vs
  `model_plus_policy` — assisted results NEVER enter the existing leaderboard
  as ordinary model performance.
- **Weak probe + hidden final verifier:** the probe may reveal only a stable,
  non-secret diagnostic ("the trusted completion check did not pass; inspect
  your changes and tests"). Never expose private expected values or raw
  oracle output. The canonical verifier's expected state stays outside the
  writable workspace.
- **Post-stop re-verification:** after an early stop, rerun the canonical
  verifier — a partial/flaky probe must not freeze a transient success.
- **One-injection cap:** corrections capped at one to bound cost/latency.
- **Recorded per attempt:** probe result, intervention action, checkpoint,
  final verdict, added tokens, added time, and whether probe and final
  verifier disagreed (the disagreement rate is a key output).

## Prerequisites (acknowledged)

- **Linux containment is now in place and required.** The experiment runs on a
  host with Bubblewrap plus a working systemd user session, with
  `AGENT_EVAL_SANDBOX=1`. Agent bash commands and the verifier subprocess are
  contained; the verifier receives the attempt workspace read-only. If that
  stack is unavailable, the run fails closed rather than falling back to host
  execution. The explicit `AGENT_EVAL_ALLOW_HOST_EXECUTION=1` path remains
  available for operator-directed development checks, but is not valid evidence
  for this experiment.
- The prototype adds a **runtime checkpoint concept** — a clean event/control
  seam for "probe now / inject / stop" — NOT coupling evaluation policy to
  the engine's internal `_tool_records`. `model_transport` stays a
  model-provider seam.

## Feasibility run (predeclared)

- Intended suite: the existing 12-task crash-diagnosis family, **one model**.
  The checked-in `eval_suites/crash_novel_v1/suite.json` currently contains 10
  tasks, not 12.
- **Execution amendment approved 2026-08-31:** proceed with the checked-in
  10-task suite for this feasibility run. Two treatments × two repeats produces
  40 attempts; this run is explicitly not the original 48-attempt claim.
- 2 modes (baseline unassisted vs verifier-assisted) × 2 repeats = **40
  attempts** for the amended 10-task run.
- Success criteria (any of these makes the policy interesting; all-false
  means drop it): the mechanism fires at least once per run where the agent
  attempts completion; repair converts ≥1 failure to pass without breaking a
  previously-passing task; assisted mode does not reliably cost more tokens
  than unassisted on tasks the agent would have passed anyway.

## Explicitly out of scope (first prototype)

Protected-file prevention (needs pre-execution tool mediation + containment);
per-tool-call verification (races/half-finished batches); heterogeneous
agent adapters (Inspect Agent Bridge pattern — copy later); routing.

## Follow-up gate after the feasibility run

The feasibility run is complete, but the Linux controller rejected its
systemd sleep-inhibitor preflight with `Access denied`; it therefore used a
persistent `tmux` session without the inhibitor. That is recorded as an
operational deviation and does not change the Bubblewrap result. Before any
larger or confirmatory CLI campaign, the controller must make the Linux
inhibitor preflight succeed (or obtain an explicit feasibility-only waiver),
run the completed-record audit, and freeze a new CLI-specific preregistration.
