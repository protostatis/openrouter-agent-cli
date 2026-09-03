# Roadmap — where this project is going

**Status:** written 2026-09-03 after the v0.2.1 release and an advisor review of
the options. Read this when deciding what to build next.

## The one-line conclusion

The next milestone is to find out whether anyone besides the author will use
this tool for real work. Everything else we considered — containerized
execution, diff review, a bigger experiment — assumes there is a user, and we
have no evidence of that yet.

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

None of the individual pieces are unique: Aider already supports OpenRouter,
runs user tests, and has diff review and undo; Claude Code has checkpoints and
lifecycle hooks; Codex has repository sessions and sandboxed execution. The
project's potential distinction is the combination, aimed at a specific kind of
developer:

- model choice through OpenRouter;
- a user-owned acceptance command as the definition of done;
- bounded repair instead of open-ended looping;
- explicit verified / failed / not-verified outcomes;
- no invented cache claims; and
- assisted evaluation results kept separate from ordinary model results.

That developer is a guess, not a fact. The current milestone tests it.

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

- 2026-09-03 — pilot deferred. The operator signed the pilot protocol, then
  chose to polish the product before recruiting. No pilot sessions have run;
  the pilot milestone above is paused, not cancelled. The current milestone
  is the product-polish pass described below.

## Current milestone (updated 2026-09-03): polish before the pilot

**Decision being made:** whether the product surface matches its own promises
closely enough to put in front of non-author users.

**What we will do (1–2 weeks):**

1. Add a diff-review command (`/diff`) so the "reviewable diff" promise in the
   product target is real, with an honest baseline and bounded output.
2. Make undo honest: it restores only what the tool itself tracked (file-tool
   edits and compaction); it says so and never claims to restore shell or
   external changes.
3. Land the three small code fixes from the advisor reviews: robust changed-
   file parsing, eval-runner environment restoration, and assisted-profile
   name validation up front.
4. Polish the session surface: `/resume` reports the restored contract and
   acceptance state; `/status` and `/usage` read cleanly.
5. Rewrite the README opening: who this is for and the honest-completion rule,
   not a feature inventory.

**Exit criteria:** all tests pass; self-test passes; `/diff` behaves on a git
and a non-git working directory; every product promise in
`docs/long-running-coding-session.md` maps to a real command; README states
the user and the completion rule in the first page.

**After this passes:** resume the deferred pilot milestone above unchanged.