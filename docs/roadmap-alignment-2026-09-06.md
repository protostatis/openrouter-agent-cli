# Roadmap alignment decision — 2026-09-06

**Status:** strategy decision; implementation is limited to the first phase
below. This document does not authorize automatic merging, deployment, or a
large policy campaign.

## Task type judgment

- **Primary:** product strategy and system design.
- **Secondary:** alignment between the developer tool and the evaluation lab.
- **Implicit:** a measurement-method decision about what counts as useful work.
- **Direct execution:** not recommended until the first system boundary and
  safety rules are fixed.

## The aligned north-star

The practical goal is:

> Produce more correct, merge-ready repository changes per unit of human review
> time and provider cost, without weakening safety.

“Generate policies and keep the winners” remains an important research method,
but it is not the user outcome. The policy lab should help us learn which
execution choices improve real work; it should not become the product we build
before we know that it helps.

## What we learned and how it changes the direction

- Pi was more successful and cheaper on one longer exploratory task, but the
  sample was too small to identify whether tool count, prompt size, or loop
  behavior caused the difference.
- Several early benchmark failures were caused by unclear tasks, contaminated
  configurations, weak task selection, and provider failures. The evaluation
  machinery is now much fairer, but its task bank is not ready for a final
  policy claim.
- The completion check can detect a bad result, but it has not yet shown that
  one repair reliably rescues a failed real task.
- Internal dogfooding showed that narrow tasks can be completed and checked,
  while a broad multi-file task can consume the agent's turn budget without an
  edit.

The immediate product question is therefore not “which policy wins?” It is
“can one bounded worker reliably produce a change that a person can approve?”

## System boundary

Build these as separate layers:

1. **CLI:** a thin interface for submitting work, inspecting progress,
   approving, retrying, and cancelling.
2. **Execution kernel:** the one-attempt lifecycle. It owns the pinned source
   commit, isolated workspace, provider call, tool access, deadlines,
   cancellation, event record, patch, and evidence.
3. **Internal workbench:** task queues, dependencies, worker roles, progress,
   human approval, and change proposals.
4. **Verification and review:** independent checks and a fresh review of the
   patch and evidence.
5. **Evaluation and policy lab:** offline analysis of immutable attempt records.
   It may recommend policies, but must not silently change product behavior.
6. **Held-out benchmark bank:** separate from product dogfooding and task
   authoring.

Do not combine the authoring agent with its final verifier, infrastructure
retries with behavioral recovery, product records with benchmark records, task
orchestration with automatic merging, or policy generation with deployment.

## Phased roadmap

### Phase 1 — Months 0–2: make one worker dependable

**Outcome:** every bounded attempt leaves an auditable result, whether it
passes, fails, times out, is cancelled, or cannot reach the provider.

Build the smallest verified-change runner:

- versioned task contract;
- one pinned worktree per attempt;
- durable attempt state and event record;
- separate provider, tool, deadline, cancellation, and verification results;
- patch plus evidence packet;
- deterministic fake-provider tests for hangs, rate limits, truncated replies,
  duplicate replies, and late replies;
- no merge, push, or deployment.

Proceed only if 20 varied internal tasks produce complete records for at least
95% of attempts, no known writes escape the assigned workspace, and no known
false pass is recorded. If isolated execution is not dependable, stop here and
simplify the runtime before adding more agents.

### Phase 2 — Months 2–4: make supervised work useful

**Outcome:** a person can queue work, observe it, review the evidence, and
approve a patch faster than doing the task manually.

Add:

- task queue, status, cancellation, and bounded retry;
- at most one independent reviewer/tester with a fresh context;
- structured handoff containing the task, diff, checks, unresolved risks, and
  cost;
- human approval for every merge;
- comparison with the single-worker baseline.

Continue only if 20 accepted internal changes across at least three task types
show a meaningful reduction in review time, with no increase in escaped defects
or rollbacks. Drop multi-agent review if it adds cost without improving
acceptance or review effort.

### Phase 3 — Months 4–7: establish credible policy evidence

**Outcome:** we can tell whether a specific execution change improves difficult
repository work, rather than merely appearing useful on one task.

Only after Phases 1 and 2:

- calibrate roughly 30 genuinely independent tasks, not 30 copies of one bug;
- use four paired repetitions per task only if the final sample-size analysis
  supports it;
- freeze prompts, tools, model route, budgets, task contracts, verifiers,
  fingerprints, and exclusion rules before collecting policy results;
- compare only a few predefined changes, such as completion rechecking,
  reduced tool exposure, bounded recovery, or independent review;
- keep policy results separate from ordinary product records.

Keep a policy only if it clears the existing precommitted success, regression,
cost, and integrity rules. Pause policy research if the task bank remains
unstable or no simple policy beats the fixed baseline.

### Phase 4 — Months 7–12: add selective orchestration

**Outcome:** multiple workers can handle independent or staged work without
losing control or making the evidence less trustworthy.

Add only with evidence:

- dependency-aware queues;
- at most three explicit roles: implementer, verifier, reviewer;
- structured artifact handoffs instead of unrestricted agent-to-agent chat;
- policy recommendations in shadow mode before automatic selection;
- a narrowly allowlisted automatic-merge trial.

Keep human approval permanent for security, authentication, permissions, CI,
dependencies, migrations, verifier code, governance files, and other high-risk
changes. Disable automatic merging after any permission escape, verifier
tampering, security-sensitive unintended change, or unacceptable regression.

## First internal tools to build

1. **Verified change runner:** turns one task into an isolated attempt, trusted
   checks, a patch, and a review packet.
2. **Provider failure laboratory:** deterministically tests hangs, rate limits,
   truncated replies, retries, cancellation, and late responses.
3. **Independent patch reviewer:** checks the task contract, diff, tests, and
   evidence from a fresh context without access to the author's private
   reasoning or writable workspace.
4. **Dependency-aware task queue:** runs independent work concurrently only
   after isolation is proven, and passes staged work through explicit artifacts.

Do not begin with a free-form agent swarm, automatic policy selection, or
automatic merging.

## Safety rules

- A Git worktree prevents branch collisions; it is not a security sandbox.
- Agent commands need container or Bubblewrap containment, least privilege,
  and no access to credentials.
- Verifiers and expected answers stay outside the agent-writable workspace.
- Set separate deadlines for provider requests, tool calls, turns, and the
  whole task; cancellation must kill the entire process group.
- Retry automatically only for classified infrastructure failures. An agent
  timeout is not automatically a provider failure.
- Rebase and rerun checks against the target branch before any merge.
- During frozen experiments, preserve the repository rule that source,
  policy, and test files cannot change.

## Measures of success

For developer usefulness, measure accepted changes, human review minutes,
time-to-approval, cost per accepted change, material rewrites, rollbacks,
escaped defects, repeat use, and wasted infrastructure retries.

For benchmark evidence, measure verified pass rate, paired task differences,
first-attempt success, final rechecking, cost at matched success, task-family
variation, false passes, false failures, verifier errors, and infrastructure
errors.

Benchmark improvements must eventually predict better internal acceptance. If
they do not, the benchmark is measuring the wrong behavior.

## Decision and next authorization

The current build priority is **Phase 1 only**: a verified-change runner and a
deterministic provider-failure test laboratory. Dogfood those tools on 20 real
internal tasks in isolated worktrees. The policy lab remains an offline,
separate research track until the worker and workbench show practical value.

The runner and basic failure tests now exist, but the Phase 1 exit bar is not
met: only one real task has completed as a usable verified dogfood result, and
its passing patch still needed a human correction. The next evidence step is
20 varied internal tasks with complete records, no workspace escapes, and no
false passes; do not promote a policy or automate merging before that evidence
exists.
