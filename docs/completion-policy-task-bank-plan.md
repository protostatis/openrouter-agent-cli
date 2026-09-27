# Completion-policy task-bank plan

**Status:** preparation only; not a frozen campaign specification.

The completion-checking policy needs tasks where the ordinary agent sometimes
fails and sometimes succeeds. The task bank should therefore target an
unassisted pass rate near 50%, rather than collecting many repetitions of one
easy task.

## Keep this separate from tool-profile research

The completion-policy campaign compares the unassisted agent with the
completion-checking policy on the frozen default tool interface. The
full7-versus-core4 comparison is a separate research question and must not
change the policy campaign's tool profile, thresholds, or treatment labels.

## Candidate pool

The first local Harbor pool had nine candidates:

- multi-file or longer tasks: `report_pipeline`, `hard_ledger_refunds`,
  `invoice_totals`, and `hard_crashing_script`;
- smaller bug-fix tasks: `xfix01_indexerror`, `xfix05_zerodiv_empty`,
  `xfix09_silent_whitespace`, `xfix11_typeerror_items`, and
  `xfix12_silent_case`.

Five harder candidates have now been added for the next calibration:
`xfix_session_windows`, `xfix_config_precedence`, `xfix_atomic_reservations`,
`xfix_dependency_plan`, and `xfix_safe_archive_extract`. They remain
provisional until the same verifier and difficulty checks are complete.

The current pool therefore has 14 provisional candidates. The nine original
tasks have the verifier and calibration results described below. The five new
tasks have now completed their independent calibration, but only three are
currently suitable for the bank.

These are candidates, not approved hard-bank members. Their difficulty must be
measured with the frozen unassisted configuration before selection.

An initial structural check on 2026-09-05 found that all nine candidates have
an instruction, task configuration, Docker environment, and verifier files.
That check does not establish that their verifiers are correct or that their
difficulty is suitable.

On 2026-09-05, `scripts/check_harbor_task_contracts.py` also checked every
candidate's real verifier in Docker: each broken fixture returned the expected
failure result, and each known-good fixture returned `verified`. The invoice
task required correcting the known-good fixture's discount boundary during
this check. This validates the basic broken/pass contract, but not verifier
independence or task difficulty.

The same check was rerun after adding the five harder candidates. All 14
candidates now pass the broken-fixture and known-good-fixture checks. The new
tasks additionally exercise alternate inputs for timestamp ordering,
configuration precedence, atomic inventory updates, graph errors, and archive
rejection.

## Admission checks

Every task must pass all of these checks before it enters the bank:

1. The instruction states the expected output or an observable requirement.
2. The intended fix is unambiguous to two independent agents.
3. The difficulty comes from a real crash or wrong behavior, not an unstated
   rule.
4. The broken fixture fails its verifier.
5. A known-good fixture or patch passes its verifier.
6. The verifier returns a distinct infrastructure result when the verifier
   itself cannot run.
7. The task is independent enough from the other tasks that it adds new
   evidence rather than repeating the same trap.

### New-task authoring checklist

Before adding a harder candidate, record this checklist beside the task:

- The instruction states the complete behavior, output schema, boundary cases,
  protected inputs, and error/exit behavior.
- The application bundle contains no answer-bearing acceptance script,
  verifier copy, defect comments, or hidden test data visible to the agent.
- The task uses at least two independent inputs or cases so a one-line partial
  fix cannot pass by accident.
- The broken fixture has a specific, reproducible failure, and the expected
  result is calculated by hand or by a separate reference implementation.
- A known-good patch passes in a fresh container, and each likely partial fix
  fails at least one stated case.
- The verifier checks observable behavior rather than importing the solution,
  compares structured output semantically where appropriate, and reports
  verifier failures separately from infrastructure errors.
- The task does not repeat the same single bug family as an existing candidate.

For calibration retention, keep a candidate only when it has between one and
four passes in five usable unassisted trials. Treat provider, container, and
verifier failures as unusable trials and replace them before applying this
rule. A task with fewer than five usable trials remains provisional; a task
with zero or five passes is rejected unless it is deliberately retained as an
edge-case control.

## Calibration before freezing

1. Run the unassisted agent only, with the default frozen tool profile, on all
   candidates in randomized order.
2. Use the same model route, turn budget, workspace isolation, verifier, and
   request capture used by the later campaign.
3. Record task-level pass/fail, infrastructure errors, calls, tokens, turn
   exhaustion, and failure reason.
4. Keep tasks near a 50% unassisted pass rate. Remove tasks that are nearly
   always solved or nearly always failed, unless they represent a deliberately
   important task family.
5. Run the power calculation after the calibration results are available, but
   before any policy results are collected. The calculation determines the
   number of independent tasks and repetitions; four or six repetitions alone
   is not a decision rule.

### First calibration result (2026-09-05)

The first three-repetition calibration ran all nine candidates in randomized
order with the unassisted `full7` configuration. Of 27 trials, 21 passed, one
was a genuine task failure, and five stopped because the Nvidia route reported
that it was temporarily overloaded. The five provider failures are not counted
as task failures.

Among the 22 trials that reached a usable task result, 21 passed. Every
candidate except `report_pipeline` passed every usable trial; `report_pipeline`
had one usable failure, while its other two trials were provider failures.
This means the current pool is too easy to use as a balanced task bank. The
result is calibration evidence only, not a policy result.

The complete run manifest is at
`jobs/completion-calibration/completion-calibration-manifest.json`. The request
capture is at `/tmp/capture-calibration.jsonl`.

The calibration runner now treats provider and harness failures as attempts
but not usable trials. Its default is five usable trials per task, with up to
three total attempts per required trial to avoid an endless run when the
provider is unavailable.

### Five harder-task calibration result (2026-09-06)

The second calibration used the same unassisted `full7` setup and stopped after
every task reached five usable trials. It made 32 total attempts: 16 passed, 9
were genuine task failures, and 7 were provider failures. The provider
failures were recorded separately and did not count toward task difficulty.

| Candidate | Usable trials | Passes | Task failures | Provider failures | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| `xfix_session_windows` | 5 | 4 | 1 | 2 | retain provisionally |
| `xfix_config_precedence` | 5 | 5 | 0 | 2 | reject as too easy |
| `xfix_atomic_reservations` | 5 | 3 | 2 | 1 | retain provisionally |
| `xfix_dependency_plan` | 5 | 4 | 1 | 0 | retain provisionally |
| `xfix_safe_archive_extract` | 5 | 0 | 5 | 2 | reject as too hard |

The table shows how often the unassisted agent passed each candidate after
provider failures were removed. Three candidates fall inside the planned
one-to-four-pass range. The configuration task was solved in every usable
trial, while the archive task was not solved in any usable trial; neither is a
balanced task for the main bank. The archive task also generated agent logs
showing uncertainty about which error label the instruction intended for a
file-parent conflict, so it should not be retained without clarifying its
specification and recalibrating it.

The complete second manifest is at
`jobs/completion-calibration-new-v2/completion-calibration-manifest.json`. The
request capture is at `/tmp/capture-calibration-new-v2.jsonl`. This remains
calibration evidence only, not a policy result.

### Power planning result (2026-09-06)

The three retained candidates are not enough independent evidence for the main
claim. Repeating a small number of tasks would measure those particular tasks
more precisely, but would not support a broad task-level conclusion. The
recommended design is about 30 independent tasks with four paired repetitions
per task, or 240 final agent attempts: four unassisted attempts and four policy
attempts for each task.

The reproducible planning simulation is
`scripts/power_completion_campaign.py`. It models a baseline pass probability
centered at 50%, task-to-task treatment effects, paired binary outcomes, and a
task-level two-sided 95% t interval. The primary detection rule is an observed
improvement of at least 10 percentage points whose interval is entirely above
zero. It evaluates 20, 30, and 40-task designs at true improvements of 0, 10,
15, and 20 points. The checked-in script defaults to 10,000 simulations with
seed `20260906`; its output must be saved with the frozen campaign record.

With the default assumptions (baseline probability SD 0.25, treatment-effect
SD 0.15, and 0.15 paired-outcome discordance), the effect-only detection
probabilities were:

| Independent tasks | Final attempts | 0-point effect | 10-point effect | 15-point effect | 20-point effect |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 20 × 4 pairs | 160 | 2% | 33% | 64% | 87% |
| 30 × 4 pairs | 240 | 1% | 40% | 77% | 96% |
| 40 × 4 pairs | 320 | 1% | 41% | 82% | 98% |

The zero-effect figures are the estimated false-promotion rates for the
10-point-and-positive-interval rule. The 30-task design is therefore a
reasonable minimum for detecting a 15-point improvement, but it has only
boundary-level power when the true improvement is exactly 10 points.

The reproducible 10,000-run output for the 30-task design also applied the
current five-point regression guard and gave 28.83% complete-rule probability
for a 15-point effect and 53.30% for a 20-point effect. It is saved at
`jobs/completion-calibration-new-v2/power-plan-30x4-20260906.json`. That low
result is mainly because the simulation allowed enough paired harms to violate
the five-point guard. It is not a claim about the policy. Before freezing,
define the regression denominator and simulate a policy behavior that is
expected to satisfy the guardrail; if a candidate policy cannot satisfy it,
more tasks will not solve that problem.

This calculation is planning evidence, not a guarantee. At a true improvement
of exactly 10 points, the observed-threshold rule has roughly boundary-level
power even with many tasks. A realistic 80% planning target should be checked
at a 15- or 20-point true improvement, and the final analysis must report the
boundary case as well. The regression definition and token-cost rule also need
to be frozen before the simulation can claim power for the complete keep/reject
decision.

## Campaign boundary

Only after the bank, sample size, budgets, fingerprints, and treatment labels
are written down should the completion-policy campaign be frozen. Apply the
existing keep/reject rule in `docs/campaign-xfix-policy.md` once, without
moving its thresholds after results exist.

The verifier contract checks are complete. The immediate next work is to author
and calibrate enough independent candidates to approach the recommended
30-task design, while fixing the archive-task ambiguity or replacing that
candidate. Then freeze the task bank, budgets, fingerprints, treatment labels,
power assumptions, and exclusion rules before collecting any policy results.
No policy conclusion should be drawn from the current tool-profile pilot or
from either calibration.
