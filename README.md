# quant-research

Equity and macro quant research: dataset pipelines, a shared backtest toolkit, one package per
research trial, and a written-up finding for every trial. **Research code only. Not trading advice.**
No data is included (vendor licensing); see [Regenerating data](#regenerating-data).

Results at a glance: [RESEARCH_SUMMARY.md](RESEARCH_SUMMARY.md).

## Layout

```
quant-research/
├── src/quant_research/
│   ├── data/            fetchers, cleaners, dataset builders (pipelines, alphavantage, sec_edgar, ...)
│   ├── features/        reusable features (finance-tuned VADER)
│   ├── backtest/        shared engine, metrics, stats (DSR/PBO/NW), reporting
│   │   └── costs/       transaction-cost models
│   ├── strategies/      one subpackage per trial (trend_tsmom, pead_gap, statarb_v1, ...)
│   ├── utils/           env-driven paths, trial config loader
│   └── cli.py           `qr` command
├── configs/             <trial>.toml (entry, status, verdict, data needs) + datasets.toml
├── research/<trial>/    FINDINGS.md + reports/ (pre-registrations and result reports)
├── scripts/             run_trial.py, build_data.py, data/ shell fetchers
├── tests/               mirrors src/ (backtest, strategies, utils)
├── docs/                architecture, data pipeline, adding a trial, dataset specs, paper registry
├── pyproject.toml       package, dependency groups, ruff, mypy, and pytest
├── uv.lock              locked environment (uv sync --locked)
├── .python-version      3.12
├── Makefile             install / lint / typecheck / test / build-data
└── .github/workflows/   CI (Python 3.12: ruff, mypy, pytest)
```

## Quick start

```bash
# Install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync                 # Python 3.12, project, and the dev group (ruff, mypy, pytest)
uv run qr list          # trials, status, verdict
uv run qr run trend_tsmom   # run a trial's entry module (needs data)
make test               # compileall + pytest; data-dependent tests skip without QR_DATA_DIR
```

Optional extras (plots, nlp, data) are not installed by a plain `uv sync`. Add them with
`uv sync --all-extras` when a dataset builder needs openpyxl, yfinance, or lxml.

## Regenerating data

1. `cp .env.example .env`, fill in **`ALPHAVANTAGE_API_KEY`** (and `ALPACA_API_KEY_ID`,
   `ALPACA_API_SECRET_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` where needed), then export them.
2. `export QR_DATA_DIR=$PWD/data` (the default; git-ignored).
3. `qr datasets` lists builders; `qr build-data <name>` (or `make build-data DATASET=<name>`) builds one.
   Install `.[data]` for the builders that use openpyxl / yfinance / lxml.

See [docs/data_pipeline.md](docs/data_pipeline.md).

## Notes

- Several trials were pre-registered and run once; their runners are kept as run.
  Paths and imports were rewritten for this repo, so any runtime sha256 pin checks in them will
  no longer match the original hashes.
- Run modules with `python -m quant_research...` or `qr run`, not by file path.
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Architecture: [docs/architecture.md](docs/architecture.md).
