# Evaluation Layer Integration (eval/)

How the measurement layer relates to the agent engine, and the rules that
keep it trustworthy. Companion to the research repo's
`notes/harness-cli-integration-plan.md`.

## The one rule: one execution path

Interactive mode, `--prompt` mode, and every evaluation run go through the
same `OpenRouterAgentCLI` engine. The evaluation layer *constructs and
observes* the engine; it never reimplements the agent loop. The old
`scripts/ab_test_system_prompts.py` predates this rule and owns a private
mini-loop — it is kept only until its flags are migrated and is deprecated in
favor of `scripts/run_suite.py`.

## Architecture

```
openrouter_agent_cli/
  cli.py               the real engine (untouched except: model_transport hook)
  eval/
    records.py   versioned append-only run records — facts only; the verdict
                 field is filled solely by a verifier and is immutable once set
    suite.py     suite manifests: tasks, per-attempt disposable workspaces,
                 setup steps; verifier commands live OUTSIDE agent workspaces
    verify.py    host-side verifier execution: exit 0 = pass, 2 = task_fail,
                 anything else = infrastructure_error (never blamed on the agent)
    transport.py scripted MockTransport — a mock "brain" whose tool calls are
                 executed for real by the engine (mock brain, real hands);
                 the full loop runs offline with zero tokens
    runner.py    paired counterbalanced schedule; builds the engine exactly as
                 --prompt mode does; allow-all permissions are safe ONLY
                 because every attempt runs in a fresh disposable workspace
    compare.py   descriptive paired report
    uncertainty.py  Wilson intervals per profile; task-level cluster bootstrap
                 for paired differences + P(A beats B)
  eval_suites/         suite fixtures + mock profiles
  scripts/run_suite.py command-line entry point
```

## The model-transport seam

`OpenRouterAgentCLI._call_openrouter` is the single place the engine talks to
the model API. It now accepts an optional `model_transport` callable; when
set, it receives the exact request kwargs the real API would receive and must
return the same wire format. Production behavior is unchanged when the hook
is `None`. This is the only engine modification the evaluation layer requires.

## Measurement rules (what keeps this from being slop)

1. Records state facts; only verifiers assign success/failure.
2. Verifier code and expected answers never live where the agent can edit.
3. Every scheduled attempt is recorded; nothing is silently dropped.
4. Paired comparison resamples tasks, never runs (within-task outcomes are
   correlated — run-level resampling would overstate precision).
5. Uncertainty ships with every comparison: a difference is called only when
   the interval excludes zero; otherwise the report says to add tasks.
6. Reports describe THIS suite only — never a general ranking.

## Discipline prompt overlays

`prompts/overlay_execution_discipline.md` and
`prompts/overlay_execution_recovery.md` are adapted from the research
screening arms. Both are **experimental overlays**, not defaults. On the
research substrate (48 all-strata runs) the recovery variant *reduced*
success (29% vs 54–57% for the others); treat it as a hypothesis to test with
this evaluation layer, not a recommended setting.

## Smoke test

```bash
python3 scripts/run_suite.py \
  --suite eval_suites/coding_smoke_v1/suite.json \
  --profile worker=eval_suites/mock_worker.json
```

Runs offline (no API key, no tokens), executes real bash in disposable
workspaces via the mock brain, verifies host-side, and prints the paired
report with uncertainty. Tests: `pytest tests/test_eval_runner.py
tests/test_eval_uncertainty.py`.
