# Public Release Checklist

Use this before changing repository visibility to public.

## Secrets and credentials

- [ ] confirm `.env` is not tracked (`git ls-files .env` should return nothing)
- [ ] rotate any previously exposed keys
- [ ] ensure docs/examples use placeholder keys (`sk-or-...`)

## Repository hygiene

- [ ] generated benchmark artifacts are ignored (`ab_tests/results/`)
- [ ] local env directories are ignored (`.venv/`, `__pycache__/`)
- [ ] no private/internal URLs or identifiers in committed files
- [ ] update README with stable usage instructions

## Safety documentation

- [ ] confirm tool risk statements are present in `README.md` (`run_bash` executes local shell commands)
- [ ] document responsible use and permission controls
- [ ] include disclosure path for security issues

## Packaging and DX

- [ ] verify install path works (`pip install -e .`)
- [ ] verify CLI entrypoint works (`openrouter-agent --help`)
- [ ] verify A/B scripts run from a clean checkout

## Legal and metadata

- [ ] verify `LICENSE` is present and intended
- [ ] verify repository description/topics in GitHub UI
- [ ] verify default branch protections before public release

## Suggested release sequence

1. Merge latest docs + benchmark findings.
2. Run a final smoke test with free model.
3. Tag initial public version.
4. Flip visibility to public.
