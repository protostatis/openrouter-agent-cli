# Public Release Checklist

## Every release (repeatable — run this each time)

- [ ] version bumped in `pyproject.toml`; `uv.lock` matches
- [ ] `uv run pytest -q` passes
- [ ] `uv run openrouter-agent --self-test` passes
- [ ] existing evaluation records still audit: `uv run openrouter-agent-eval-audit --records <last campaign file>`
- [ ] `uv build` produces both wheel and sdist; new modules present in the wheel
- [ ] `git diff --check` clean; no secrets in the diff
- [ ] commit, tag `v<N>`, push tag, and `gh release create v<N>` with plain-language notes
- [ ] publish to PyPI (GitHub Actions trusted publishing once registered, otherwise the local token path)

## First public release (one-time — already done for v0.1.6)

### Secrets and credentials

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
