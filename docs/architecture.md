# Architecture

```
src/quant_research/
  data/        dataset fetchers, cleaners and builders (see data_pipeline.md)
  features/    reusable signal features (e.g. finance-tuned VADER sentiment)
  backtest/    shared engine, metrics/validation, stats (DSR, PBO, NW t), reporting
    costs/     transaction-cost models shared across trials
  strategies/  one subpackage per trial: signal + trial-specific runner
  utils/       paths (env-driven data roots) and trial config loading
  cli.py       `qr` command (list / run trials, build datasets)
```

Principles

- **Shared code lives once.** The backtest engine, metrics and cost models in `backtest/` are
  used by several trials; the data client in `data/client/` is shared by every strategy.
- **Frozen trial code.** Several strategies were pre-registered and run once; their runners keep
  their own engines and constants exactly as run (e.g. `trend_tsmom/_engine_v1_frozen.py`).
  Do not refactor them in ways that change numbers. New trials should use `backtest/`.
- **No hard-coded paths.** All file locations derive from `quant_research.utils.paths`, which reads
  `QR_DATA_DIR` (datasets), `QR_DESK_DIR` (legacy desk-relative outputs) and `QR_SCRATCH_DIR`.
- **Keys from the environment only** (`ALPHAVANTAGE_API_KEY`, `ALPACA_*`, `FRED_API_KEY`, `SEC_USER_AGENT`).
- **Research write-ups are separate from code.** `research/<trial>/FINDINGS.md` summarises each trial;
  `research/<trial>/reports/` holds the original pre-registrations and result reports.
- **Configs.** `configs/<trial>.toml` records the entry module, status, verdict and data needs;
  `configs/datasets.toml` maps dataset names to builder modules.

Running code

Modules use absolute imports, so run them as modules or through the CLI:

```
qr run trend_tsmom            # == python -m quant_research.strategies.trend_tsmom.run_v3
python -m quant_research.strategies.pead_gap.pit.run_all
```

Known limitations

- Many runner modules execute their study at import time (script style) and need the data store.
- Some runners verify sha256 pins of their own inputs or code. Files were edited for this repo
  (paths, imports), so those runtime pin checks will not match the original hashes.
