# Contributing

- Setup: install [uv](https://docs.astral.sh/uv/), then `uv sync` from the repo root.
  That creates `.venv` on Python 3.12 (see `.python-version`) and installs the project plus the
  `dev` dependency group (ruff, mypy, pytest, pytest-cov, pytest-randomly, pytest-timeout,
  pip-audit, pre-commit, and the type stubs).
- Before pushing: `make check`.

## Required CI checks

Branch protection on `main` should require the single status check `ci-ok` and an up-to-date
branch. `ci-ok` is the aggregator job in [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
It succeeds only when every job below succeeds, so protection can require one check.

| Job | What CI runs | Locally |
| --- | --- | --- |
| lint | `uv sync --locked`, `ruff check`, `ruff format --check` | `make lint` |
| typecheck | `uv sync --locked`, `mypy` | `make typecheck` |
| test | Python 3.12 and 3.13 on `ubuntu-latest`, plus Python 3.12 on `macos-latest`, with `fail-fast: false`. Pytest uses `--strict-markers`, `--strict-config`, and a 300s `--timeout`. There is no flaky-test rerun plugin. Ubuntu 3.12 also runs coverage and uploads the report. Ubuntu 3.13 runs in random order (`pytest-randomly`). | `make test`, `make coverage`, `make test-random` |
| package | `uv lock --check`, `uv build`, then install that wheel in a clean venv and import `quant_research`, including the `py.typed` marker | `make package-smoke` |
| pre-commit | `pre-commit run --all-files` | `make pre-commit` |
| audit | `pip-audit` against `uv export --frozen` of the lock (all groups and extras) | `make audit` |
| gitleaks | gitleaks 8.30.1 over the full git history | `make gitleaks` (binary 8.30.1 must be on `PATH`) |
| hygiene | root `data/` files, parquet/csv/feather/pickle over 64 KiB, any file over 1 MiB, absolute home or workspace paths, UUID-like ids, and Alpha Vantage key assignments | `make hygiene` |

`make check` runs lint, typecheck, coverage (the `fail_under` gate), one randomized pytest run,
hygiene, `uv lock --check`, and pre-commit. `make package-smoke`, `make audit`, and `make gitleaks`
are the remaining CI jobs: the first two need network, and gitleaks needs the pinned binary.

If a random-order run fails, fix the test so it does not depend on order. Do not change research
logic or registered numbers to silence it.

Coverage is line coverage of the `quant_research` package. `fail_under` is **24**, the measured
total on CPython 3.12 (24.06%, 6681/27768 statements) rounded down. CI uploads `coverage.xml` and
the HTML report as the `coverage` artifact. The hygiene rules and the allowlist are in
[`scripts/check_repo_hygiene.py`](scripts/check_repo_hygiene.py). The allowlist stays empty except
for one synthetic key value the iv_gap runner test assigns on purpose.

[CodeQL](.github/workflows/codeql.yml) analyzes Python in its own workflow (`codeql` job). It is not
part of `ci-ok`. Both workflows run on push, pull request, a nightly schedule, and
`workflow_dispatch`. Third-party actions are pinned to commit SHAs. Dependabot groups weekly
updates for `github-actions` and `uv`.

## Style and research rules

- Hooks: `uv run pre-commit install`. The config runs ruff, ruff-format, mypy, and the hygiene
  script through `uv run`, plus end-of-file, trailing-whitespace, YAML, and gitleaks checks.
  Ruff hooks pass `--force-exclude`, so they honor the `research` exclude in `pyproject.toml`.
  The whitespace hooks skip `research/` and `docs/data/sue_spec.md` for the same reason: that
  prose is frozen. CI runs that same config with `pre-commit run --all-files`.
- mypy is strict on `src/` and on `scripts/check_repo_hygiene.py`. Tests are included with untyped
  defs allowed, so fixtures can stay loose while typed test code is still checked.
- Ruff enables a broad rule set (pycodestyle, pyflakes, isort, bugbear, pyupgrade, simplify,
  comprehensions, ruff, pylint, pep8-naming, pathlib, bugbear-args, return, tryceratops, perf,
  numpy, pandas, bandit, datetime, eradicate, print, and flake8-annotations on `src`).
  Ignores are per rule in `pyproject.toml`, each with a one-line reason. Do not add a new ignore
  without a reason, and do not silence mypy with a blanket `# type: ignore`. A targeted ignore
  needs an error code and a reason.
- Never commit data, `.env`, API keys, or generated outputs (`.gitignore` covers the usual paths).
- Read keys only from environment variables; read and write files only under `QR_DATA_DIR`
  (via `quant_research.utils.paths`).
- Shared logic goes in `backtest/`, `features/`, `data/`, or `utils/`, not copied into a strategy.
- Do not change frozen pre-registered runners in ways that alter results; add a new version instead.
- New trials: see [docs/adding_a_trial.md](docs/adding_a_trial.md).
- Tests mirror `src/` under `tests/`; use synthetic data. Tests needing real data must skip without it.
