# Roadmap — where this project is going

**Status:** written 2026-09-03 after the v0.2.1 release and an advisor review of
the options. Read this when deciding what to build next.

## The one-line conclusion

The end goal is a harness that generates candidate policies, measures each
against real tasks with experiment integrity, and keeps only the ones that
substantially improve what coding agents produce. The CLI is the first
artifact under study; the harness is the durable asset.

## The end goal (stated 2026-09-03)

A harness that generates policies — interventions at defined points in the
coding-agent loop (completion checks, prompt overlays, tool rules, model
choice) — and validates each one with experiment-grade integrity: contained
execution, treatment-separated records, campaign audit, adequate power,
preregistered selection rules. "Substantially improves" means clearing a
pre-committed bar for effect size, regression ceiling, and cost ceiling on a
hard task bank — never a vibes-based claim.

The current milestone below is the first step toward that goal. The pilot
remains on the path but is re-scoped: it validates the harness's worth with
evaluation-conscious users, and the CLI's fate is a secondary question.

## Where we are now

The released tool (v0.2.1 on PyPI) is a terminal agent that lets a developer:

- give the agent a bounded task and an acceptance command (`--task` +
  `--verify-command`, or `/task` + `/verify` at runtime);
- have that command run before the agent's answer is accepted;
- see one of three honest outcomes: the command passed (verified), the command
  ran and failed (failed), or no trustworthy result exists (not verified);
- get exactly one additional model response when the first check fails; and
- see context and cache information only when the provider actually reports it.

It also ships an evaluation harness, which is arguably the more unusual asset:
the real agent engine driven by a scripted fake model, real host-side
verifiers, contained execution for real-model runs, and an audit that checks
campaign integrity. This harness is used only for measurement, never for
routing or ordinary leaderboards.

One experiment ran before this roadmap: 20 attempts with the completion-checking
policy versus 20 without. The policy passed 18, the plain agent passed 17. Two
attempts were rescued by the policy, one passed attempt regressed, and there
were zero disagreements between the check and the final verifier. That result
proves the mechanism can intervene. It is not enough to make the policy a
default feature.

## Why this project exists

Positioned against today's coding agents — opencode, pi, Claude Code, Aider —
the difference is not more models, lower cost, or more polish: those are
already covered. The claim is narrower and specific:

- completion is a checked state the developer owns (a command you control
  decides whether completion is recorded as verified, failed, or not
  verified), and
- the same engine doubles as an experiment harness — contained, audited,
  treatment-separated — so claims about whether the completion policy helps
  are measured instead of asserted.

The product is the face of the first claim; the harness is the evidence
producing the second. Neither is durable yet: the mechanism is demonstrated by
one 40-attempt feasibility run, and durability will come from accumulated
reproducible campaigns and real adoption, not from claims. The pilot decides
whether the product side earns its place; the harness's fate is decided by
whether its measurement discipline is wanted by anyone outside this project.

That developer is a guess, not a fact. The pilot milestone tests it.

## The pilot milestone (paused — see the evidence log below)

**Decision being made:** continue building this as a developer product, narrow
it to an evaluation/research tool, or put it in maintenance.

**What we will do (2–3 weeks):**

1. Spend no more than two days on release hygiene: register the PyPI trusted
   publisher so the next release is one command, write release notes for
   v0.2.1, and replace the pre-public checklist with a repeatable one.
2. Write a short pilot protocol: who the target user is, what a session looks
   like, what we record (setup time, approvals, review, verification, whether
   the user would use it again), and which alternatives we compare against.
3. Run six observed sessions with three developers who are not the author,
   each doing one real bounded task on their own repository with an acceptance
   command. The author may dogfood first to find obvious friction, but the
   author's own sessions do not count toward the decision.
4. Write a dated decision: continue, narrow, or stop.

**How we know it worked (exit criteria):**

- at least two of the three users complete a genuinely useful task that the
  acceptance command verified;
- at least two users can explain correctly what verified / failed /
  not-verified mean;
- at least two users come back for a second task without being asked; and
- the session logs identify a repeated friction point clearly enough to choose
  the next smallest improvement.

**When we stop (kill criteria):**

- if no user returns for a second task, or every user would choose Aider,
  Claude Code, or Codex without personal help, then stop building features and
  make the narrowing decision; and
- if three willing users cannot be found after about ten direct invitations
  and two public demonstrations, treat demand and positioning — not missing
  features — as the problem.

A version number is an output of a passed milestone, not the milestone itself.
We do not promise a v0.3.0 before this gate.

## What comes after, decided by evidence

Each of these is conditional. None is promised.

- **Diff review and honest undo** (a `/diff` command, and undo that only
  claims to restore what the tool itself tracked): build only if review
  friction shows up repeatedly in the pilot. Never promise to undo arbitrary
  shell commands.
- **Containerized execution profile:** build only if a real user refuses the
  tool because commands run on the host. It needs a written threat model
  first — "runs in Docker" is not a safety conclusion — and must fail closed
  (no silent fallback to host execution).
- **A bigger experiment on the completion-checking policy:** run only when its
  result would change a real product decision (promote the policy to a default,
  keep it opt-in, or remove it) and a power analysis shows a feasible sample
  size. The current evidence (+1 pass in 20 attempts) does not justify several
  hundred attempts.
- **Cache and cost experiment:** first spend one or two days checking whether
  OpenRouter exposes observable cache or billing data for a real path. If it
  does not, park it. If it does, measure whether a default-off option actually
  cuts billed cost by a meaningful amount.
- **Model compatibility matrix:** build only if model choice proves valuable to
  real users. It must distinguish tested, expected-to-work, and unsupported.

## Parked — and what would reactivate each

- **Full-screen interface:** reactivates if the pilot's top complaint is
  visibility during long sessions.
- **Automatic model routing:** stays last; the product must work first.
- **Native cache persistence:** parked; providers do not expose it.
- **Autonomous commits, pushes, or deployments:** out of scope by design.
- **Broad Windows or browser support:** only if maintainer capacity grows.

## Release and maintenance policy

- Release when a milestone passes, not on a schedule.
- One canonical publishing path: GitHub Actions trusted publishing once
  registered; until then the local token path, documented clearly.
- Support claims in the README equal what the operator can actually test:
  platforms, Python versions, and a short list of tested models.
- A monthly maintenance budget (about four hours) and a security-reporting
  path.
- No contributor processes beyond the minimum until there are contributors.

## Evidence log

- 2026-09-03 — end goal stated: a harness that generates policies that
  substantially improve coding-agent output (see the section above). The
  product-polish pass (below) was completed the same day.
- 2026-09-03 — pilot deferred. The operator signed the pilot protocol, then
  chose to polish the product before recruiting. No pilot sessions have run;
  the pilot milestone below is paused, not cancelled. With the end goal
  stated, the pilot is re-scoped toward evaluation-conscious users; its
  pre-committed thresholds stand unless the operator changes them.

## Current milestone: prove one policy substantially improves agent output

**Decision being made:** whether the harness can produce a policy whose
effect on coding-agent output clears a preregistered, powered bar — the first
real step toward the end goal.

**What we will do (the near-term plan):**

1. Define the policy space (`docs/policy-space.md`): the intervention points
   and the first candidate policies (the acceptance gate, the discipline and
   recovery prompt overlays, tool-discipline rules, model choice), plus the
   preregistered selection rule for "substantial."
2. Build a hard task bank: tasks where unassisted agents fail around 40–50%,
   so a good policy has room to show a real effect.
3. Run a power analysis, then preregister the first multi-policy campaign
   (fingerprints, budgets, thresholds) per the experiment-contract pattern.
4. Clear the Linux keep-awake gate in parallel — the critical dependency for
   real-model campaigns at scale.
5. Run the campaign, audit it, and write the decision doc.

**Exit criteria:** at least one policy clears the preregistered bar
(effect at/above a pre-committed threshold, regressions within the ceiling,
cost within the ceiling) on an adequately powered, audited campaign; the
result is reported with the same separation discipline as every other
measurement.

## Completed milestone: product polish (done 2026-09-03)

**Decision being made:** whether the product surface matches its own promises
closely enough to put in front of non-author users.

**What was done (1–2 weeks):**

1. Added a diff-review command (`/diff`) so the "reviewable diff" promise in
   the product target is real, with an honest baseline and bounded output.
2. Made undo honest: it restores only what the tool itself tracked (file-tool
   edits and compaction); it says so and never claims to restore shell or
   external changes.
3. Landed the three small code fixes from the advisor reviews: robust changed-
   file parsing, eval-runner environment restoration, and assisted-profile
   name validation up front.
4. Polished the session surface: `/resume` reports the restored contract and
   acceptance state; `/status` and `/usage` read cleanly.
5. Rewrote the README opening: who this is for and the honest-completion rule,
   not a feature inventory.

**Exit criteria (met):** 142 tests pass; self-test passes; `/diff` behaves on
a git and a non-git working directory; every product promise in
`docs/long-running-coding-session.md` maps to a real command; README states
the user and the completion rule in the first page.