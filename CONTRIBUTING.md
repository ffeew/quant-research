# Contributing

- Setup: install [uv](https://docs.astral.sh/uv/), then `uv sync` from the repo root.
  That creates `.venv` on Python 3.12 (see `.python-version`) and installs the project plus the
  `dev` dependency group (ruff, mypy, pytest, pre-commit, and the type stubs).
- Before pushing: `make check`. That is `make lint` (ruff check and `ruff format --check`),
  `make typecheck` (`uv run mypy`), and `make test` (compileall and pytest).
- CI runs the same three as separate blocking jobs (lint, typecheck, test) on Ubuntu with Python 3.12.
  mypy is strict on `src/`. Tests are included with untyped defs allowed, so fixtures can stay loose
  while typed test code is still checked.
- Hooks: `uv run pre-commit install`. The config runs ruff, ruff-format, and mypy through `uv run`,
  plus end-of-file, trailing-whitespace, YAML, and gitleaks checks.
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
