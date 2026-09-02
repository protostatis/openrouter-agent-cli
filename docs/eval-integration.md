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
  cli.py               the real engine (model_transport + checkpoint hooks)
  eval/
    records.py   versioned append-only run records — facts only; the verdict
                 field is filled solely by a verifier and is immutable once set
    suite.py     suite manifests: tasks, per-attempt disposable workspaces,
                 setup steps; verifier commands live OUTSIDE agent workspaces
    verify.py    verifier execution: exit 0 = pass, 2 = task_fail, anything else
                  = infrastructure_error (never blamed on the agent); sandboxed
                  real runs execute this process in a read-only Bubblewrap namespace
    transport.py scripted MockTransport — a mock "brain" whose tool calls are
                 executed for real by the engine (mock brain, real hands);
                 the full loop runs offline with zero tokens
    runner.py    paired counterbalanced schedule; builds the engine exactly as
                  --prompt mode does; allow-all permissions are safe ONLY
                  because every attempt runs in a fresh disposable workspace;
                  real sandboxed runs also contain their verifier
  compare.py   descriptive paired report
  audit.py     structural integrity checks for completed campaigns
  uncertainty.py  Wilson intervals per profile; task-level cluster bootstrap
                  for paired differences + P(A beats B)
    policy.py    hidden verifier probe + one generic repair injection; assisted
                 records remain outside the ordinary model leaderboard
  eval_suites/         suite fixtures + mock profiles
   eval/cli.py    installed ``openrouter-agent-eval`` entry point
   scripts/run_suite.py compatibility wrapper
```

## The model-transport seam

`OpenRouterAgentCLI._call_openrouter` is the single place the engine talks to
the model API. It accepts an optional `model_transport` callable; when set, it
receives the exact request kwargs the real API would receive and must return
the same wire format. The engine also accepts an optional `checkpoint_hook`.
The hook receives only a `RuntimeCheckpoint` event at a final-answer or
mutating-batch boundary and returns `continue`, `repair`, or `stop`. It does
not receive private tool records, verifier data, the workspace, or the
transcript. Production behavior is unchanged when either hook is `None`.

## Measurement rules (what keeps this from being slop)

1. Records state facts; only verifiers assign success/failure.
2. Verifier code and expected answers never live where the agent can edit.
3. Every scheduled attempt is recorded; nothing is silently dropped.
4. Paired comparison resamples tasks, never runs (within-task outcomes are
   correlated — run-level resampling would overstate precision).
5. Uncertainty ships with every comparison: a difference is called only when
   the interval excludes zero; otherwise the report says to add tasks.
6. Reports describe THIS suite only — never a general ranking.
7. Completed campaigns pass the independent record audit before the runner
   returns; use `openrouter-agent-eval-audit` to audit an existing JSONL file.

## Verifier-assisted feasibility policy

`eval/policy.py` implements the feasibility policy, selected by
`Profile(treatment="model_plus_policy")` or the command-line
`--assisted-profile NAME` option. After a final answer or a completed mutating
tool batch it runs a hidden verifier probe. A complete probe stops the agent;
an incomplete probe injects one generic repair request; an infrastructure
error continues without intervention. The canonical verifier still runs after
the engine stops and is the only component allowed to assign the final
verdict. A repair permits exactly one additional model response.

Each assisted record stores checkpoint results, repair count, attributable
tokens and time, and whether the terminal probe disagreed with the final
verifier. Assisted rows are shown in a separate report section and are
excluded by the ordinary leaderboard and uncertainty helpers.

The record audit checks schema and verdict completion, unique run/workspace/
schedule identities, expected task/profile repeat counts, treatment separation,
and Bubblewrap receipts for real-model rows. It does not inspect model text or
private verifier evidence.

## Long-running launch checklist

Run a real-model campaign only after all of these checks succeed:

```bash
# macOS controller
caffeinate -ism -- tmux new-session -d -s agent-eval '...'

# Linux controller
systemd-inhibit --what=idle:sleep --mode=block --why=agent-eval true
tmux new-session -d -s agent-eval 'AGENT_EVAL_SANDBOX=1 ...'
```

The Linux inhibitor command is a required preflight, not just a convenience.
If it returns `Access denied`, fix the host's user-session permission or record
an explicit feasibility-only deviation; do not silently treat a `tmux`-only
launch as equivalent for a larger confirmatory campaign. In either case,
`AGENT_EVAL_SANDBOX=1` must remain set so missing Bubblewrap containment fails
closed.

For a real run with `AGENT_EVAL_SANDBOX=1`, the agent's bash commands and the
verifier subprocess both run under Bubblewrap. The verifier sees trusted suite
files at `/trusted` and the attempt workspace read-only at `/workspace`. An
explicit `AGENT_EVAL_ALLOW_HOST_EXECUTION=1` is still available for operators,
but it is a visibly weaker path and is not valid for the bounded real-model
confirmation protocol.

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
