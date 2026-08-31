# Bounded Generalization Results

**Collection completed:** 2026-08-30 on `ubuntu-local`.
**Protocol:** `docs/bounded-generalization-protocol.md`.
**Suite:** `bounded-generalization-v1`.

## Conclusion

The earlier crash-diagnosis ordering did **not** receive confirmatory support
from this broader suite. Nemotron passed 10 of 10 tasks and GPT-4o-mini passed
8 of 10, but 8 tasks were passed by both models. The two-sided exact sign test
therefore had only two non-tied tasks and returned **p = 0.5**, far above the
predeclared 0.05 threshold. The correct conclusion is **inconclusive**, not
that Nemotron is generally better.

The broader suite also showed a high ceiling: all three models passed nearly
every task. That makes this collection useful as a generalization check, but
not a strong discriminator between models.

## Collection coverage

The table below reports verified pass counts by task family. Each entry is
`first model passes / second model passes` for that comparison. The three
pairwise comparisons used separate model requests, so the same model appears
in more than one comparison.

| Pairwise comparison | Error recovery (4 tasks) | Silent semantic errors (3 tasks) | Structured data transformation (3 tasks) | Overall |
|---|---:|---:|---:|---:|
| Nemotron vs GPT-4o-mini | 4/3 | 3/2 | 3/3 | **10/8** |
| Nemotron vs Qwen3 Coder 30B | 4/3 | 3/3 | 3/3 | **10/9** |
| GPT-4o-mini vs Qwen3 Coder 30B | 3/4 | 2/3 | 3/2 | **8/9** |

All 60 attempts were recorded and verified. There were zero infrastructure
errors and all 60 records carry `engine.sandbox = "bubblewrap"`.

## Paired outcomes and uncertainty

This table describes the 10 shared tasks in each comparison. “Only” means that
one model passed and the other failed; “both” means both passed.

| Comparison | First model only | Second model only | Both passed | Neither passed | Exact sign-test p-value |
|---|---:|---:|---:|---:|---:|
| Nemotron vs GPT-4o-mini | 2 | 0 | 8 | 0 | 0.5000 |
| Nemotron vs Qwen3 Coder 30B | 1 | 0 | 9 | 0 | 1.0000 |
| GPT-4o-mini vs Qwen3 Coder 30B | 1 | 2 | 7 | 0 | 1.0000 |

The existing task-level bootstrap gave these paired pass-rate differences and
95% intervals:

- Nemotron minus GPT-4o-mini: **+0.20**, interval **[0.00, +0.50]**;
  the interval touches zero, so the difference is not reliable yet.
- Nemotron minus Qwen3 Coder 30B: **+0.10**, interval **[0.00, +0.30]**;
  the interval touches zero.
- GPT-4o-mini minus Qwen3 Coder 30B: **−0.10**, interval **[−0.40, +0.20]**;
  the interval includes zero.

## Tokens and latency

The following figures describe the 10 attempts made by each profile in each
comparison. Token counts are provider-reported totals; they are not converted
to price because provider pricing and release conditions are not part of this
protocol.

| Comparison | Profile | Attempts | Tokens | Median latency |
|---|---|---:|---:|---:|
| Nemotron vs GPT-4o-mini | Nemotron | 10 | 134,147 | 22.034 s |
| Nemotron vs GPT-4o-mini | GPT-4o-mini | 10 | 46,209 | 4.470 s |
| Nemotron vs Qwen3 Coder 30B | Nemotron | 10 | 141,303 | 21.093 s |
| Nemotron vs Qwen3 Coder 30B | Qwen3 Coder 30B | 10 | 134,290 | 28.271 s |
| GPT-4o-mini vs Qwen3 Coder 30B | GPT-4o-mini | 10 | 54,611 | 4.796 s |
| GPT-4o-mini vs Qwen3 Coder 30B | Qwen3 Coder 30B | 10 | 122,180 | 29.986 s |

## Audit identifiers

The protocol and containment changes were committed in `7a52b02`. The suite
manifest SHA-256 is:

```text
d17ec53d0a1d0ffcb837705fc25e62e1ca23940edfe602abb24cacb3cd19f9f5
```

The control-prompt SHA-256 is:

```text
03f0713da89cf697a251f098eae0b0a7ce2cdfa7f7e9ba93dcf7e875e76427db
```

Run-record SHA-256 values are listed below. The raw `.agent-eval/` directory
is intentionally ignored by Git; these hashes identify the copied local
records without treating generated attempt data as source code.

| Comparison records | SHA-256 |
|---|---|
| `nemotron-vs-gpt/runs/bounded-generalization-v1.jsonl` | `01037ca5bc7d959ea257dfefa12a66398d6906937da8eda3cf2f2b40aaf67079` |
| `nemotron-vs-qwen/runs/bounded-generalization-v1.jsonl` | `0b7d002428150f747eccb1fc56c39782461e7e0469e4f4579395fe3a71543be3` |
| `gpt-vs-qwen/runs/bounded-generalization-v1.jsonl` | `055ae868ea9ca768e18d9d784d3e329a309aa1b218035738d5206572baca8a75` |

## Decision

Do not expand the model-ranking claim from this result. The next useful step
is to calibrate the Bayesian outcome engine on the accumulated ledger and to
improve the suite's ability to distinguish successful and unsuccessful work.
The verifier-assisted policy remains an opt-in experiment; this collection
does not justify making it a default runtime behavior.
