# Contributing

- Setup: `python3.12 -m venv .venv && . .venv/bin/activate && make install`.
- Before pushing: `make lint test`. CI runs compileall, ruff (non-blocking) and pytest on Python 3.12.
- Never commit data, `.env`, API keys or generated outputs (`.gitignore` covers the usual paths).
- Read keys only from environment variables; read and write files only under `QR_DATA_DIR`
  (via `quant_research.utils.paths`).
- Shared logic goes in `backtest/`, `features/`, `data/` or `utils/`, not copied into a strategy.
- Do not change frozen pre-registered runners in ways that alter results; add a new version instead.
- New trials: see [docs/adding_a_trial.md](docs/adding_a_trial.md).
- Tests mirror `src/` under `tests/`; use synthetic data. Tests needing real data must skip without it.
