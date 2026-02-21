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

`run_bash` executes shell commands on the local machine. Treat model-generated commands as untrusted input and keep permission gating enabled.
