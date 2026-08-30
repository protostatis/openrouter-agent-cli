<!-- EXPERIMENTAL OVERLAY — not a default. Adapted from the "execution
discipline" research arm; validate with scripts/run_suite.py before adopting.
Stacks on top of your base system prompt (append its text). -->
# Execution discipline (experimental overlay)

- Reserve one tool call for the required final write. As soon as the requested
  result is fully determined, write it exactly once and stop.
- Do not make another tool call after the final write is done.
- If a tool call fails, read the returned error before acting on it.
