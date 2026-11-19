# Dave's replications (research/replication/)

One command (re-runs everything, appends to the trial log, writes one validation submission per strategy):

```
$QR_DESK_DIR/research/replication/.venv/bin/python $QR_DESK_DIR/research/replication/run_all.py            # all three
$QR_DESK_DIR/research/replication/.venv/bin/python $QR_DESK_DIR/research/replication/run_all.py --only bab # one family
```
Flags: `--force-stock-imom` (stock-level industry momentum
with current GICS, labelled survivorship-biased diagnostic), `--book USD` (impact sizing, default $100k), `--skip-grid`.

| piece | path |
|---|---|
| venv (Dave's) | `.venv/` (`requirements.lock.txt`); $QR_SCRATCH_DIR/dave_venv is retired and deleted |
| data loaders (read-only on Dmitri's store) | `_common/desk_data.py` (total returns, PIT membership mask + ticker-reuse/coverage checks, FF3; `client()` = the desk's shared Alpaca data client, the only allowed live path; no statarb fallback since 2026-10-30) |
| simulator + costs | `_common/engine.py` (next-open fills, Tomas cost_model v1.1 with Victor §5 floors, 1%/yr borrow, 2x stress) |
| validation stats | `_common/validation.py` (Newey-West, DSR, PBO-CSCV, walk-forward, alpha/beta, regimes) |
| trial log | `TRIAL_LOG.csv` (append-only, every variant incl. pre-v2 runs); T x N daily matrix in `results/trials_daily_net_*.parquet` |
| strategy rules | `<paper>/pipeline.py` docstrings |
| submissions | `<paper>/submission/SUBMISSION.md` + CSVs + `equity_curve.png` |
| run log / meta | `results/run_all.log`, `results/run_meta.json`, `results/suspect_returns.csv`, `results/history/` (v1 outputs) |

Legacy turn-1 scripts (`*/backtest.py`, statarb IEX data) are kept for the record; their results are superseded.

## 2026-10-30 02:26 SGT: corrections after Victor's check (all three FAILED, confirmed)
- Residual momentum warm-up bug fixed in `blitz-huij-martens-2011-residual-momentum/pipeline.py` (24-of-36-month minimum enforced on the nominal window; no clipped windows). Rerun of resmom_ls / resmom_long only: `blitz-huij-martens-2011-residual-momentum/bugfix_warmup_rerun.py`. Logged as role `bugfix_rerun` (same spec key, N unchanged). Restated from 2019-01.
- BAB leverage wording (average applied, not a cap); no unlevered beta-neutral version run.
- Industry momentum: ETF version only; long-only is monthly-rebalanced (docstring fixed).
- Coverage caveat verified and corrected (`results/membership_intervals_coverage_bars.csv` added).
