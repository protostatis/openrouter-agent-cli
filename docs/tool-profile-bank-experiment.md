# Tool-Profile Comparison — Frozen Plan (2026-09-07)

**Status:** frozen before any attempt ran. The machine-readable contract is
`eval_suites/tool_profile_bank_v1/bank.json`; the runner is
`scripts/run_tool_profile_bank.py`. Nothing in this plan may change after the
first attempt.

## The question

Does exposing only the four coding-loop tools (`core4`: run bash, read file,
write file, edit file) complete more verified tasks than exposing all seven
tools (`full7`, which adds list directory, search text, and web discovery)?

Current evidence is promising but too narrow: on one hard task the four-tool
profile passed 3/3 versus 1/3, using about a third of the tokens. One task is
not a product decision.

## Arms and controls (identical for both arms)

- Same model: `nvidia/nemotron-3.5-lightning:free` (free tier).
- Same prompt bytes: `eval_suites/campaign_control.md`
  (SHA-256 `03f0713d…`, recorded in the bank and re-verified before every run).
- Same turn budget: 16 turns per attempt; same 30-second tool timeout.
- Same verifier per task; same disposable workspace per attempt.
- Both arms run as ordinary model-only attempts. The verifier-assisted
  completion policy is NOT part of this comparison.
- The only intended difference is the tool list the engine sends.

## Task bank: 40 distinct tasks, one matched pair each

| Family | Count | Examples |
|---|---:|---|
| Crash fixes | 10 | None method call, unbound local, recursion, index error |
| Silent wrong output | 9 | min instead of max, off-by-one, wrong count |
| Data transforms | 7 | CSV→JSON, filters, joins with totals |
| Basic functions | 4 | greet, sum, clamp, dedup |
| Multi-file / tests / debugging | 10 | stale refactor, shared constant, failing test fix, API rename, docs conflict |

Tasks come from three existing suites (`crash_novel_v1`,
`bounded_generalization_v2`, `coding_smoke_v1`) whose verifiers have already
run in prior campaigns. The two web tasks and the adherence-control task are
excluded: live web content makes verdicts flaky, and the control task measures
honesty, not completion.

## Schedule

- 40 pairs = 80 attempts, one attempt per arm per task.
- Task order fixed by seed 20260907 before the first attempt (order printed by
  `--dry-run`). Each task's two attempts run back-to-back with the leading arm
  alternating, so provider drift over hours hits both arms equally.
- Resume-safe: an interrupted batch skips pairs that already have verdicts on
  disk and never duplicates an attempt.

## Decision rules (written before running)

To detect the smallest difference worth acting on — 25 percentage points of
pass rate — roughly 36 matched pairs are needed for an 80% chance of seeing it
at about a 5% false-positive risk, assuming the arms disagree on about 35% of
tasks. The bank runs 40 pairs.

- **Primary metric:** verified pass rate per arm over 40 pairs. An
  infrastructure error counts as a failure for its arm and is also reported
  separately.
- **Change the default tool profile to core4** only if core4 beats full7 by
  25 points or more.
- **10–25 points:** a trend. Keep the current default, change nothing, record
  the result.
- **Below 10 points:** treat the profiles as equivalent on this bank.
- **Interim stop:** after the first 20 pairs, stop early only if one arm leads
  by 35 points or more (7 or more net pairs). Otherwise finish all 40.

## Accounting (recorded per arm)

Verified pass/fail (primary), infrastructure errors separately, total provider
tokens, model request counts, and median attempt latency.

## Known limits of the result

- Attempts run on this macOS host with acknowledged host-level execution (no
  Linux sandbox here). Findings apply to that setting until reproduced with
  containment.
- The free model's routing can drift during the run; the seeded interleaved
  order spreads that drift across both arms rather than removing it.
- The four-tool profile keeps full host-shell capability, so this comparison
  tests interface simplicity, not capability removal.
- 40 tasks bound what can be detected: effects smaller than 25 points remain
  invisible, and that is accepted in advance rather than argued after the fact.

## What will not happen during the run

No prompt, model, turn-budget, verifier, or policy changes; no verifier-policy
arm; no training-data collection; no product defaults changed before the
decision rule says so.

---

## Results (completed 2026-09-07; the frozen plan above is unchanged)

All 40 pairs completed with zero duplicated attempts. One infrastructure error
occurred (a transient provider outage on the core4 arm during the stale
refactor task); it counted as a core4 failure per the frozen rule.

| Measure | full7 (seven tools) | core4 (four tools) |
|---|---:|---:|
| Verified passes | 36/40 (90%) | 33/40 (82.5%) |
| Infrastructure errors | 0 | 1 |
| Total tokens | 621,457 | 443,307 |
| Model requests | 235 | 186 |
| Median attempt time | 97.6s | 77.7s |

Paired outcomes: 31 both-pass, 2 both-fail, 5 full7-only passes
(hard_shared_constant, sumlib, novel05, transform02, hard_stale_refactor),
2 core4-only passes (novel08, xfix03).

**Decision per the frozen rule: 7.5 points difference — below the 10-point
threshold. Treat the profiles as equivalent on this bank. Keep full7 as the
default; change nothing.**

Reading: the dramatic earlier signal (core4 3/3 vs full7 1/3 on one hard task)
did not generalize — across 40 varied tasks the tool count barely matters for
completion. The earlier interim lead (full7 +15 points at 20 pairs) also shrank
by pair 40, which is why the frozen rule required completing all pairs. The
descriptive cost observation stands: core4 used about 29% fewer tokens and 21%
fewer requests while completing nearly the same work — worth remembering, but
not a completion argument. Per the frozen plan, the product default is
unchanged and the result is recorded as final for this bank, model, and host
setting.
