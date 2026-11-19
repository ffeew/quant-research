# Adding a trial

1. **Pre-register** in `research/<trial>/reports/PREREG.md`: hypothesis, universe, data window,
   in-sample / OOS split, metrics and pass/fail thresholds, cost assumptions, trial count.
2. **Code** in `src/quant_research/strategies/<trial>/`:
   - read data through `quant_research.data.client` or `quant_research.utils.paths.data_path(...)`;
   - reuse `quant_research.backtest` (engine, `validation` metrics, `stats` for DSR/PBO/NW t)
     and `quant_research.backtest.costs` rather than copying them;
   - put the entry point in a module with `if __name__ == "__main__":` and no work at import time.
3. **Config**: add `configs/<trial>.toml` (`title`, `status`, `verdict`, `entry`, `findings`, `[data].requires`).
4. **Tests** in `tests/strategies/<trial>/` on synthetic data. Tests that need the data store must
   skip cleanly without it (see `tests/conftest.py`).
5. **Run**: `qr run <trial>`; write `research/<trial>/FINDINGS.md` (hypothesis, data window, method,
   results incl. costs and OOS, verdict, source docs) and add a row to `RESEARCH_SUMMARY.md`.
