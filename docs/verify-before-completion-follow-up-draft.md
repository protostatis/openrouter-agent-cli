# Follow-up Study Draft — Verify Before Accepting Completion

**Status:** draft only; not frozen and not authorized for live collection.  
**Purpose:** define the decisions that must be settled before expanding the
small feasibility run into a larger CLI-specific study.

## What the feasibility run established

The policy that checks the workspace before accepting completion can be wired
into the real agent loop, can trigger a bounded repair, and can keep its rows
out of the ordinary model-performance report. In the amended 10-task run it
produced 18 passes from 20 attempts, compared with 17 passes from 20
unassisted attempts.

That result is not enough to make the policy a default. One unassisted pass
became an assisted failure, and the run used only one model and ten tasks.

## Proposed question

On a newly frozen task population, does the completion-checking policy improve
verified task success without creating an unacceptable rate of regressions or
resource use?

This is a new CLI experiment. It must not pool outcomes with the feasibility
run or with the earlier research screening generations.

## Candidate design to settle before freeze

- Compare the unassisted model with the same model plus the completion-checking
  policy.
- Keep prompt bytes, model settings, tool set, budgets, and task order rules
  fixed between treatments.
- Use a newly frozen task bank, with task-level grouping and at least two
  attempts per task-treatment cell if the power analysis says repetition is
  needed to separate stable task differences from random model variation.
- Keep assisted rows outside ordinary model leaderboards.
- Do not test routing, automatic policy selection, or training-data reuse in
  this study.

## Outcomes to predeclare

Primary outcome: the independent verifier's `pass`, `task_fail`, or
`infrastructure_error` verdict, counted by intention to treat.

Secondary outcomes:

- baseline-pass to assisted-fail regressions;
- baseline-fail to assisted-pass rescues;
- hidden-probe and canonical-verifier disagreement;
- repair count, added tokens, and added time;
- infrastructure failures and containment failures; and
- whether a successful probe stopped unnecessary additional model turns.

The success margin, regression tolerance, task-clustered uncertainty method,
and minimum task count must be frozen before the new task prompts or outcomes
are available to the policy designer. A small study may remain descriptive and
must not be presented as a general ranking.

## Required launch gates

1. The source tree, dependencies, model, sampling settings, task bank, and
   verifier versions have committed fingerprints.
2. The record audit passes on a dry run and is enabled for the live runner.
3. Real-model execution reports Bubblewrap containment for every attempt.
4. The Linux `systemd-inhibit --what=idle:sleep --mode=block` preflight
   succeeds, or a documented operator waiver limits the run to feasibility
   evidence.
5. All scheduled task-treatment-repeat cells are enumerated before launch.
6. An interruption makes the generation terminal-invalid; there is no resume.
7. The budget, stop rule, and analysis outputs are frozen before launch.

## Open decisions

- Which task families are mature enough for the first larger CLI study?
- How many independent task clusters and repeats are required by the power
  analysis?
- What regression and resource-cost limits are acceptable?
- Should the policy's generic repair message be held fixed or compared with a
  separately predeclared alternative?
- How will the Linux keep-awake permission be repaired on `ubuntu-local`?

Until those decisions are frozen, the supported product behavior is the
explicit `--assisted-profile` opt-in and the separate policy report only.
