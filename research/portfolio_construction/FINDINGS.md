# Portfolio construction (risk models, vol caps)

**Status:** research  
**Verdict:** Reference result: HRP vs MV-Ledoit-Wolf delta Sharpe CI [-0.29, 0.44] (no significant difference)

## Hypothesis
Covariance shrinkage / HRP / vol-capping improve OOS risk-adjusted returns of the book.

## Data window
Walk-forward on statarb bars, 120-day lookback, weekly rebalance; OOS 2021-01-20..2026-10-28.

## Method
Walk-forward comparison of MV-sample, MV-LW, HRP, GP and vol-cap variants with stationary bootstrap CIs.

## Results
- HRP - MV-LW: delta Sharpe CI [-0.29, 0.44] (p>0 = 0.662); HRP has higher vol.

## Code
- Entry point: `qr run portfolio_construction` (`python -m quant_research.strategies.portfolio_construction.research.riskmodels_wf`)
- Config: `configs/portfolio_construction.toml`

## Sources
Numbers above are copied from these documents:
- [reports/RESULTS.md](reports/RESULTS.md)
- [reports/FRAMEWORK.md](reports/FRAMEWORK.md)
