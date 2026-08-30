<!-- EXPERIMENTAL OVERLAY — treat as a hypothesis, not a recommendation.
On the research substrate this variant REDUCED success (29% vs 54-57% for
baseline and execution-only; 48 all-strata runs). Test it with
scripts/run_suite.py on your own suite before drawing any conclusion.
Stacks on top of the execution-discipline overlay. -->
# Recovery discipline (experimental overlay, stacked on execution discipline)

- When a tool call fails or is rejected, inspect the returned error before
  acting. Never repeat an unchanged failed request.
- Make at most one corrected retry for that failure. If it fails again, stop
  retrying that operation and choose a different route or stop.
- After a write/patch failure caused by stale content, re-read the target
  before retrying; do not resubmit the same change unchanged.
