# Security Policy

## Supported versions

This project is early-stage. Security fixes are applied on `main`.

## Reporting a vulnerability

Please do not open public issues for sensitive vulnerabilities.

Report privately to the repository owner with:

- impact summary
- reproduction steps
- affected file(s)/line(s)
- suggested fix (if available)

## Tool safety note

- `run_bash` executes shell commands on the local machine (`cwd=workdir` only, not jailed). It runs in a separate process group, bounds captured output, removes OpenRouter/Brave API keys from the child environment, and kills descendants on timeout. Treat model-generated commands as untrusted input and keep permission gating enabled.
- `list_dir`/`search_text`/`read_file`/`write_file`/`edit_file` enforce workdir jail (`relative_to(workdir)`).
- `read_file` is capped at 2 MiB by default, pages with `max_lines`/`next_cursor`, and refuses obvious binary files; writes/edits are atomic, capped at 2 MiB, support optional SHA-256 preconditions/dry-run, and can be undone once via `/undo`.
- `discover` fetches web content: `https` only (http rejected), private/loopback/link-local/metadata hosts blocked after DNS resolution and on observed final URLs. Browser subrequests and DNS rebinding remain dependent on the underlying browser boundary, so treat this as defense-in-depth rather than a complete network sandbox. All web content is untrusted and may contain prompt-injection; independent discovery batches use stateless clients for concurrency, while stateful calls are queued. Each call has a configurable 1-120s timeout, 30s default; a timed-out browser thread may still need process-level cleanup by the underlying client. `auto` requires `pyunbrowser` or errors; use `--discovery mock` for synthetic `example.com/mock`.
- Permission approvals support once, batch, turn, session, and explicitly persistent scopes. Persistent `/allow` and `/deny` rules remain global across sessions and working directories; use narrower approval scopes for normal work.
