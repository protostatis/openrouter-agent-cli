# Bounded Generalization Protocol (v2)

**Status:** frozen before target-model collection on 2026-08-30.
**Suite:** `eval_suites/bounded_generalization_v2/suite.json`.

This v2 protocol replaces the invalidated v1 collection. Before freezing, an
audit found that six v1 task IDs already had older target-model records. None
of the ten v2 task IDs occur in the existing `.agent-eval/` ledger.

## Question

Does the earlier result on the crash-diagnosis suite extend to other small
coding-task families, or was it specific to that original task collection?

This is a bounded generalization check. It is not a claim about overall model
quality, programming ability, or price tier.

## Task families

The suite contains 10 unseen tasks:

| Family | Task IDs | What it tests |
|---|---|---|
| Error recovery | `repair01`–`repair04` | Repairing missing data, a missing dictionary key, an incorrectly scoped running total, and missing recursion termination. |
| Silent semantic errors | `silent01`–`silent03` | Correcting code that runs but computes the wrong result. |
| Structured data transformation | `transform01`–`transform03` | Producing exact JSON from normalized, filtered, and joined input data while leaving inputs unchanged. |

Before collection, each task must meet all of these checks:

1. A reference repair passes its verifier.
2. The initial faulty fixture fails or produces the declared wrong result.
3. Every protected input hash in the verifier matches the fixture.
4. No target model has seen the task ID or fixture before the freeze.
5. Verifiers that execute agent-produced code run inside the same read-only
   verifier Bubblewrap namespace as the agent's contained execution.

## Models and prompt

All models receive the same control prompt from
`prompts/system_prompt_control.md`; no experimental overlay is used.

The three exact OpenRouter model identifiers are:

- `nvidia/nemotron-3.5-lightning:free`
- `openai/gpt-4o-mini`
- `qwen/qwen3-coder-30b-a3b-instruct`

The three prespecified pairwise comparisons are:

1. Nemotron versus GPT-4o-mini — the primary comparison, because this is the
   comparison from the earlier crash-diagnosis result.
2. Nemotron versus Qwen3 Coder 30B — secondary comparison.
3. GPT-4o-mini versus Qwen3 Coder 30B — secondary comparison.

Model identifiers are not treated as price or capability classes. Results
belong only to these exact model releases and this collection window.

## Schedule and fixed count

- One attempt per task per model per pairwise comparison.
- Each pairwise comparison contains 10 tasks × 2 models = 20 attempts.
- The complete collection contains 3 comparisons × 20 attempts = **60
  attempts**.
- The runner rotates which profile goes first within each task.
- No adaptive re-runs, task substitutions, task edits, or post-hoc prompt
  changes are allowed.
- Collection runs only on Linux with `AGENT_EVAL_SANDBOX=1`. If containment is
  unavailable, collection stops rather than falling back to host execution.
- Verifier infrastructure errors are recorded separately and are not silently
  converted into model successes. No attempt is replaced after collection.

The same model appears in two pairwise comparisons. Those observations are
not pooled as independent evidence; each comparison is analyzed separately at
the task level.

## Primary analysis

For Nemotron versus GPT-4o-mini, calculate one pass/fail result for each of the
10 tasks and report pass rates, the paired task-level difference, tied tasks,
the two-sided exact sign test over non-tied tasks, and the existing task-level
bootstrap interval.

The predeclared directional criterion is that Nemotron has more successful
tasks than GPT-4o-mini and the exact sign-test p-value is below 0.05. With 10
non-tied tasks, at least 9 favorable tasks are required; 8 favorable tasks is
not enough. If fewer than 9 tasks are non-tied, the result is reported as
inconclusive rather than rescued with a different test.

The two other pairwise comparisons use the same descriptive statistics and
are secondary. They do not create a new global model ranking and are not
combined with the primary comparison.

## Reporting boundaries

Report results by task family as descriptive context only. Do not claim that a
model is generally better at debugging, data transformation, or coding. State
the number of infrastructure errors, exact collection window, model
identifiers, prompt fingerprint, and the fact that there was one attempt per
cell.

If the primary criterion is not met, stop the generalization claim here. The
next step is engine calibration or suite improvement, not adding tasks to the
same comparison until a preferred result appears.
