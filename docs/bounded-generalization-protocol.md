# Bounded Generalization Protocol

**Status:** frozen before target-model collection on 2026-08-30.
**Suite:** `eval_suites/crash_novel_v1/suite.json`, whose manifest identifier is
`bounded-generalization-v1`.

## Question

Does the earlier result on the 12-task crash-diagnosis suite extend to other
small coding-task families, or was it specific to that original hand-built
suite?

This is a bounded generalization check. It is not a claim about overall model
quality, programming ability, or price tier.

## Task families

The suite contains 10 tasks that were not run on any target model before this
protocol was frozen:

| Family | Task IDs | What it tests |
|---|---|---|
| Error recovery | `novel01`–`novel04` | Repairing different runtime failures: missing data, a missing function argument, an incorrectly scoped variable, and runaway recursion. |
| Silent semantic errors | `novel05`–`novel07` | Correcting code that runs but computes the wrong result. |
| Structured data transformation | `novel08`–`novel10` | Producing exact JSON results from normalized, filtered, and joined input data while leaving inputs unchanged. |

Before collection, each task must meet all of these checks:

1. A reference repair passes its verifier.
2. The initial faulty fixture fails or produces the declared wrong result.
3. Every protected input hash in the verifier matches the fixture.
4. The verifier is either pure file inspection or runs inside the same
   Bubblewrap namespace as the agent; no target-model pilot is permitted.

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
2. Nemotron versus Qwen3 Coder 30B — secondary generalization comparison.
3. GPT-4o-mini versus Qwen3 Coder 30B — secondary generalization comparison.

Model identifiers are not treated as price or capability classes. The result
belongs only to these exact model releases and this collection window.

## Schedule and fixed count

- One attempt per task per model per pairwise comparison.
- Each pairwise comparison therefore contains 10 tasks × 2 models = 20
  attempts.
- The complete collection contains 3 comparisons × 20 attempts = **60
  attempts**.
- The runner rotates which profile goes first within each task. No adaptive
  re-runs, task substitutions, or post-hoc prompt changes are allowed.
- Real-model collection runs only on Linux with `AGENT_EVAL_SANDBOX=1`.
  If containment is unavailable, collection stops rather than falling back to
  host execution.
- A verifier infrastructure error is recorded separately and is not silently
  converted into a model success. No attempt is replaced after collection.

The same model appears in two pairwise comparisons. Those observations are
not pooled as independent evidence; each comparison is analyzed separately at
the task level.

## Primary analysis

For Nemotron versus GPT-4o-mini, calculate one pass/fail result for each of the
10 tasks and report:

- pass rate for each model;
- the task-level paired difference;
- the number of tied tasks;
- a two-sided exact sign test over non-tied tasks; and
- the existing task-cluster bootstrap interval as a secondary description.

The predeclared directional criterion is that Nemotron has more successful
tasks than GPT-4o-mini and the exact sign-test p-value is below 0.05. With 10
non-tied tasks, at least 9 favorable tasks are required; 8 favorable tasks is
not enough. If fewer than 9 tasks are non-tied, the result is reported as
inconclusive rather than rescued with a different test.

The two other pairwise comparisons use the same descriptive statistics and
are explicitly secondary. They do not create a new global model ranking and
are not combined with the primary comparison.

## Reporting boundaries

Report results by task family as descriptive context only. Do not claim that a
model is generally better at debugging, data transformation, or coding. State
the number of infrastructure errors, the exact collection window, model
identifiers, prompt fingerprints, and the fact that there was one attempt per
cell.

If the primary criterion is not met, stop the generalization claim here. The
next step is engine calibration or suite improvement, not adding more tasks to
the same comparison until the preferred result appears.
