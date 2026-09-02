"""Evaluation layer for openrouter-agent-cli.

Extends (never duplicates) the real agent engine: the suite runner drives the
same ``OpenRouterAgentCLI`` headless path used by ``--prompt`` mode, records
factual run events, and grades outcomes with trusted host-side verifiers.

Modules:
- ``records``  versioned append-only run records (facts only)
- ``suite``    suite manifests: tasks, fresh workspaces, verifier contracts
- ``verify``   host-side verifier execution -> pass / task_fail / infrastructure_error
- ``transport`` scripted MockTransport at the engine's model-call seam
- ``runner``   paired, counterbalanced suite execution
- ``compare``  descriptive paired-comparison report
- ``audit``    structural integrity checks for completed campaigns

Design rules (see docs/eval-integration.md):
- Records state facts only; "success" is claimed solely by a verifier.
- Verifier commands and expected answers live outside the agent-writable dir.
- Every scheduled attempt is recorded; nothing is silently dropped.
"""
