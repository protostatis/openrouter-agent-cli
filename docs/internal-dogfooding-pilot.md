# Internal dogfooding smoke test — 2026-09-06

**Status:** one author-run smoke test; not external-user evidence and not a
benchmark result.

Dogfooding here means using our own coding agent on this repository. The goal
was to see whether the harness can safely carry a small real maintenance task
from a written request through an acceptance check.

## Task

In an isolated worktree, the agent was asked to add a regression test proving
that a timed-out user acceptance command is recorded as `not_verified` rather
than as success. The acceptance command was:

```text
uv run pytest -q tests/test_long_running.py
```

The worktree was based on commit `3db51fc`; no changes were made in the main
worktree by the agent.

## What happened

The first agent session inspected the implementation and ran small timeout
experiments, but did not finish the test. The process was stopped after ten
minutes while waiting for another model response. This is consistent with the
free provider route being slow or unavailable; it is a real usability problem
for interactive work, even though it is not evidence of a code failure.

A second session was given the observed test failure. It corrected the test and
the acceptance command then passed 20 tests. After review, the test was copied
into the main worktree with a small cleanup to make the timeout explicit.

The main worktree now passes all 155 tests:

```text
155 passed in 29.81s
```

## What this teaches us

1. The harness can inspect, edit, run tests, and stop with a verified result on
   a real repository task.
2. The acceptance command caught a real mistake in the agent's first test.
3. The agent needed the failure explained explicitly before it repaired the
   test. The current completion check detects failure; it does not guarantee
   that an unassisted agent will recover from it.
4. The free provider route can leave a session waiting for a long time. A
   stable provider or a visible request timeout is needed for practical use.
5. A test-only task is a useful smoke test, but it is easier than a real feature
   change. This does not establish that the harness is reliable on longer
   multi-file work.

This smoke test does not count toward the external-user pilot or the frozen
completion-policy evaluation. The next meaningful dogfood task should be a
small multi-file change with a real build or integration check, run in a fresh
worktree and reviewed by a human before merging.

## Follow-up smoke test: failure-driven test repair

The next task asked the agent to add a configurable provider request timeout
across the CLI, HTTP client setup, tests, and README. This was chosen because
the first smoke test had exposed a long wait for a provider response.

The agent inspected the code for twelve turns but made no edit. Its first full
acceptance check was also stopped at the harness's default 30-second shell
timeout. A retry with a 120-second shell timeout reached the full suite, which
then exposed a separate clean-checkout problem: one test expected an API key to
exist before it could test the host-execution gate. The agent was given that
failure and asked to repair only the test. It added a dummy key scoped to that
test, and the clean worktree then passed all 143 tests.

After review, the test portability fix was applied to the main worktree. The
main worktree still passes all 155 tests. The request-timeout feature itself was
not merged because the agent did not implement it.

This follow-up shows three useful limits of the current workflow:

1. The harness can recover well when the failure is specific and the next edit
   is narrowly described.
2. A broader multi-file feature can consume the turn budget in inspection
   without producing a change.
3. Acceptance-command timeouts need to be chosen for the repository; a full
   test suite should not use a 30-second limit when it normally takes about 27
    to 30 seconds.

## Bounded workbench smoke test — isolated runner

The new `openrouter_agent_cli/workbench.py` runner now creates one detached
worktree per task, records an event stream and runtime limits, saves the patch
and logs, runs the verifier separately, and never merges or pushes. It also
rejects a passing verifier when a task that requires a change produced no
changed files, and can reject changes outside an explicitly allowed path list.

Three real attempts were then run from the committed `HEAD` baseline. An early
attempt exposed a false pass: the agent made no edit while the acceptance tests
passed. The no-change rule now records that case as `not_verified`. A second
attempt exposed that a clean `HEAD` baseline did not contain the later test
portability fix, so its full-suite check failed before the requested work was
done. With the smaller `core4` tool set and a more direct task, the third
attempt made the requested two-file test-and-documentation change, passed its
acceptance check, and left a patch in an isolated worktree. Human review found
an unnecessary duplicated README command block, so the patch was not accepted
or merged.

The review queue is generated by
`scripts/review_internal_workbench.py`. A passing check is therefore treated as
evidence for human review, not as permission to merge. This is useful progress,
but it is not the 20-task dependability result required by the roadmap.

## Dogfood gate batch 1 — ten small tasks (2026-09-07)

Ten small, precisely specified tasks ran in isolated worktrees against the
committed baseline (`3db51fc`), using the four-tool profile, 24 turns, and one
task at a time. The manifest is `examples/dogfood-gate-batch1.json`; records
are under `~/.openrouter-agent-cli/workbench/gate-batch1/`.

The acceptance command verified 9 of 10 attempts. One task produced no
repository change while its acceptance command still passed; the no-change
rule correctly recorded that attempt as `not_verified` instead of a pass.

Human review of the 9 patches (table: each verified attempt and the reviewer's
verdict):

| Task | Review verdict |
|---|---|
| test-content-dict-serialized | accept |
| test-empty-session-id | accept |
| test-session-path-sanitized | accept |
| test-tools-constant-unique | accept |
| test-truncate-boundaries | accept |
| new-utils-test-module | accept after cleanup (`__import__("json"). loads` instead of a plain import, unused `pytest` import, missing final newline) |
| version-flag | accept after cleanup (duplicate `subprocess` import, import order) |
| readme-max-commands | wording fix first (`/max-rounds` described as "max reasoning rounds"; it caps discover rounds) |
| test-help-covers-commands | **reject — false pass** |

The rejected attempt is the most important result of this batch. The agent
wrote its new test class as ONE line containing literal `\n` characters —
the whole block parses as a comment, so the requested guard test does not
exist. The acceptance command (the existing test file still passing) could not
detect this, and only human review caught it. This is the same literal-`\n`
failure mode already observed on the Harbor report-pipeline task, now seen in
a second context.

Gate progress after this batch: 13 complete audited records (3 earlier
attempts + this batch) toward the 20-task exit criterion. No patch was merged;
accepted patches await the operator's merge decision.

## Dogfood gate batch 2 — seven small tasks (2026-09-07)

Seven more small tasks ran the same way (manifest
`examples/dogfood-gate-batch2.json`, records under
`~/.openrouter-agent-cli/workbench/gate-batch2/`). The retry of the
help-guard test included explicit formatting guidance after batch 1's
literal-`\n` rejection; no new literal-`\n` case appeared in this batch.

The acceptance layer verified 3 of 7 attempts, and human review accepted all
three patches as-is (estimate-tokens minimum, status-lines content, deny
beats wildcard allow). The other four attempts were agent failures, recorded
honestly: three produced no repository change within the 24-turn budget (the
known inspection-without-editing failure mode), and the README flags task
never edited the file, so its check failed. No false passes occurred in this
batch.

## Gate result: 20 records complete (2026-09-07)

The 20-record exit criterion is now met: 3 earlier attempts plus batches 1 and
2 leave 20 complete, isolated, auditable records, the runner issues no merge
or push commands, and every acceptance pass was treated as review evidence
only.

What those records can and cannot prove: changes are measured with git inside
each task's worktree, so repo-local edits and acceptance results are fully
covered, and the runner rejects recorded changes outside a task's
allowed-path list when one is set. The runner does NOT OS-sandbox the host
shell — host execution is an explicit opt-in flag
(`AGENT_EVAL_ALLOW_HOST_EXECUTION=1`) and is unrestricted on macOS — so a
command writing files outside the worktree would not show up in these
records. Containment rests on disposable per-task worktrees, the allowed-path
check, and human review, not on an operating-system sandbox. (Corrected
after review: an earlier version of this paragraph claimed "zero workspace
escapes", which is stronger than the mechanism supports.)

What the 20 records actually show, in plain terms:

- The workbench is dependable as a CONTAINER: every attempt left a worktree,
  patch, logs, event stream, and an independently run acceptance result, and
  nothing ever touched the main checkout.
- The agent is NOT yet dependable as a WORKER on small tasks: across this
  session's 17 agent attempts, 12 produced a verified change and 5 produced
  none; human review then accepted 8 patches as-is, accepted 2 after minor
  cleanup, asked for one wording fix, and rejected 1 as a false pass (a test
  that did not actually exist).
- The top failure mode is running out of the turn budget on inspection without
  editing (5 of 17 attempts). The second is writing text with literal `\n`
  escapes instead of real newlines (1 of 17, caught only by review).

Recommended next steps, in order: (1) operator decides on the 10 accepted
patches (merge or discard); (2) before more dogfood batches, address the
no-edit failure mode — candidates are a larger turn budget for inspection,
a mid-turn nudge when many turns pass with no file change, or a stronger
worker prompt; (3) keep human review in the loop; acceptance commands alone
cannot catch a phantom test.

## Generalized failure-mode fix + live validation (2026-09-07)

Three generalized mechanisms were implemented (all recommended by an advisor
review; none are point patches):

1. **No-progress guard** (`--require-repo-change`, enabled by the workbench
   for every required-change task). The engine watches the ACTUAL worktree
   content — a content hash of changed/untracked files, not tool names —
   after every model turn. After 6 turns with no content change it injects
   one nudge; a final answer on an unchanged worktree is suppressed and
   nudged even earlier; a second unchanged final answer stops the turn with
   an explicit message. A failed `edit_file` or a read-only command counts
   as no progress; any real change resets the counter.
2. **Test-growth verification** (workbench task field `test_growth`). For
   declared add-a-test tasks, pytest node IDs are collected from the clean
   baseline before the agent runs and re-collected after the patch. The
   attempt only counts as verified if at least the required number of
   genuinely NEW nodes exist in changed files, none were removed, and the
   new nodes pass when run directly. A comment that only looks like a test
   produces no node and cannot pass.
3. **Escaped-newline structural scan.** Added lines of changed Python files
   are tokenized; literal `\n` sequences outside string tokens (two or more,
   or followed by code-shaped text) mark the attempt `structural_violation`
   instead of verified.

All are covered by offline tests (6 guard tests via the scripted mock
transport; 8 workbench structural tests). Full suite: 192 passed.

### Live validation batch 3 (3 previously failed tasks, guard active)

The three tasks that had failed with no change were re-run with the guard
active (`examples/dogfood-gate-batch3.json`, records under
`~/.openrouter-agent-cli/workbench/gate-batch3-guarded/`):

| Task | Before | With generalized fixes | What fired |
|---|---|---|---|
| test-decode-tool-args-nonstr | no change (twice) | verified, patch accepted | none needed — model edited directly |
| test-help-covers-commands | phantom test (human-caught) | structural_violation, auto-rejected | no-progress nudge + escaped-newline scan |
| test-cwd-not-found-message | no change | real edit, honest failure | no-progress nudge; acceptance caught a nonexistent fixture |

The decisive evidence: the model emitted the literal-`\n` phantom test AGAIN,
and this time the structural scan caught it AUTOMATICALLY — the same false
pass that previously required human review now cannot reach the review queue
as "verified". The nudge fired in 2 of the 3 tasks (the decode-tools task
needed none — the model edited directly, verified on its own), and both
nudged tasks then produced real file edits. The remaining failure (a test
using a nonexistent fixture) is a normal model error, caught by the
acceptance command as designed.

Gate records now total 23 (20 + batch 3). Validation plan for calling the
no-edit problem fixed: 30 held-out required-change attempts with the guard;
0 no-change endings would put the old ~30% no-edit rate out of play at the
5% significance level.

## Operator decision: all accepted patches merged (2026-09-07)

The operator accepted the review outcome, and all 12 accepted patches were
merged into the main checkout by hand (the worktree patches were diffs against
the committed baseline; the main checkout had diverged, so the changes were
applied to the current files directly):

- 8 small regression tests added to `tests/test_cli.py` (empty session id,
  character-based truncation, non-string tool arguments, dict content
  serialization, missing content key, deny-beats-wildcard, unique tool names
  and descriptions, sanitized session file names).
- New `tests/test_utils.py` (review-cleaned: plain imports, no unused
  imports, trailing newline).
- `--version` flag added to the CLI parser with a subprocess test
  (review-cleaned: single `subprocess` import).
- Status-lines content test added.
- README slash-command list completed with correctly worded
  `/max-discover` and `/max-rounds` entries (review had requested a wording
  fix: `/max-rounds` caps discover rounds, not "reasoning rounds").

Post-merge verification: 212 tests passed (20 more than before the merge),
`--version` prints `openrouter-agent-cli 0.2.1`, and a scripted check
confirms every slash command in `SLASH_COMMANDS` now appears in the README.
No commits were made; the merged changes remain part of the working tree.
