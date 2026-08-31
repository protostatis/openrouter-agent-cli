# Product Decision Brief — Verifier-Assisted Execution (revised)

**Status:** revised 2026-08-31 per advisor review. Supersedes the earlier
draft's categorical novelty claim.

## Decision question

Is verifier-driven, task-oriented steering inside a measurement harness a
defensible product gap, and where does it sit in our roadmap?

## Recommendation (revised)

**Build it — but as a bounded experiment and an opt-in experimental policy,
NOT as a default product feature or a novelty claim.** The landscape shows
the underlying control loop already exists in multiple forms; our opening is
a packaging/trust gap, not an invention.

## The corrected landscape claim

> Few mainstream evaluation harnesses provide a **turnkey policy** that checks
> a live coding workspace at defined checkpoints, automatically stops or
> requests repair, and records **assisted outcomes separately** from
> unassisted model performance.

The previous draft claimed nobody does "verifier-driven task steering inside
a measurement harness." That is false at the programmable-framework level:

| Pattern | Who | What it is | Relevance to us |
|---|---|---|---|
| **Intermediate scoring + early termination (counterevidence)** | Inspect (UK AISI) | Custom solver can call `score(state)` mid-run to decide whether/how to continue; `TaskState.completed` terminates early. `inspect.aisi.org.uk/solvers.html#intermediate-scoring` and `#early-termination` | Direct capability-level proof the loop exists; we cannot claim it |
| Human-in-the-loop intervention | Inspect | Agent Client Protocol: stream transcript, Esc-interrupt, cancel tool calls, redirects, ask_user()/notify_user() | Seam pattern to copy (Agent Bridge) |
| Per-action automated control | OpenAI Agents SDK | Guardrails before/after each function-tool invocation; tripwires | Runtime, not a harness — shows per-action control is established |
| Safety monitoring → truncate/halt | OpenAI/AISI/METR-class gatekeepers | Separate monitor model flags untrusted actions, halts | Safety gate, not task steering |
| Harness self-evolution | HarnessLens (arXiv 2608.27311, v1 preprint Aug 27 2026) | Harness proposes its own next verification from trajectories; +7.6–13.6% held-out (author-reported) | **Emerging signal, not a trend** — 3-day-old v1 |
| Terminal-verdict evals | OpenAI Evals, promptfoo, DeepEval, typical Inspect usage, METR | Run → grade at the end, no mid-run steering | The status quo and our current shape |
| Our own runtime | openrouter_agent_cli | Already detects a repeated tool call and injects a corrective instruction before forcing a final answer (`cli.py` loop-break nudge) | Our proposed feature generalizes an existing heuristic |

## Evidence corrections (from review)

- **Inspect must be listed as counterevidence**, not just a seam to copy.
- **HarnessLens / BekchiAI (arXiv 2608.26867):** both are three-day-old v1
  preprints (2026-08-27); numbers are author-reported, not field consensus.
  BekchiAI's abstract supports remote termination only — weak until its code
  is audited.
- **"OpenAI Agentic Safety: Monitoring" (2025):** could not be verified under
  that exact title — retain only with an exact URL/authors or drop.
- **March-2026 METR/Anthropic gatekeeper claim:** conflated/under-sourced.
  The verifiable Anthropic agentic-misalignment article is June 2025 and is
  not the gatekeeper study. Remove until the primary source is pinned.

## What this means for us

1. **The gap is turnkey trust, not novelty:** a packaged, honest policy
   (workspace checkpoints, bounded repair, assisted outcomes kept separate,
   immutable records) on top of a verifier contract nobody else exposes as a
   product. That is buildable and defensible.
2. **Sequencing:** containment → validate on several task families → publish
   the smallest useful eval workflow → verifier-assisted execution as an
   opt-in experimental policy → commit to a runtime product only if the
   policy measurably improves held-out success/cost → routing last.
3. **The intervention prototype is step 4, not step 1** — and it is an
   experiment until it earns its place with data (see the experiment
   contract: `docs/verify-before-completion-experiment.md`).