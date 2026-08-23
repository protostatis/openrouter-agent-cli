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

- `run_bash` executes shell commands on the local machine (`cwd=workdir` only, not jailed). Treat model-generated commands as untrusted input and keep permission gating enabled.
- `read_file`/`write_file`/`edit_file` enforce workdir jail (`relative_to(workdir)`).
- `discover` fetches web content: `https` only (http rejected), private/loopback/link-local/metadata hosts blocked on initial URL (redirects not yet revalidated — best-effort SSRF). All web content is untrusted and may contain prompt-injection; `discover` batches run concurrently (`max_concurrency`, `30s` timeout per call, thread abandoned on timeout — not yet killable subprocess). `auto` requires `pyunbrowser` or errors; use `--discovery mock` for synthetic `example.com/mock`.
