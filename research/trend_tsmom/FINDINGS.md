# Trend / time-series momentum (ETFs)

**Status:** failed  
**Verdict:** FAILED: v3 full net Sharpe 0.021, quasi-OOS -0.065

## Hypothesis
Time-series momentum (Moskowitz-Ooi-Pedersen 2012; Hurst-Ooi-Pedersen 2017) earns a positive net Sharpe on a liquid ETF universe.

## Data window
v3 single pre-registered run: full sample, quasi-OOS 2005-2016 and blind 2005-2007 segments (see RESULTS-v3).

## Method
v1 levered; v2 unlevered pre-registered L/S where shortable; v3 frozen single run with costs, DSR and PBO (CSCV) checks.

## Results
- v1: levered net Sharpe 0.20 (with costs).
- v2: unlevered pre-registered primary net Sharpe 0.395, net max drawdown -16.4% (failed the -15% drawdown criterion).
- v3: full net Sharpe 0.021; quasi-OOS 2005-2016 net Sharpe -0.065; blind 2005-2007 Sharpe -1.054; full gross Sharpe 0.179.
- v3: DSR 0.087; PBO 0.380 (criterion < 0.20).

## Code
- Entry point: `qr run trend_tsmom` (`python -m quant_research.strategies.trend_tsmom.run_v3`)
- Config: `configs/trend_tsmom.toml`

## Sources
Numbers above are copied from these documents:
- [reports/RESULTS.md](reports/RESULTS.md)
- [reports/RESULTS-v2.md](reports/RESULTS-v2.md)
- [reports/RESULTS-v3.md](reports/RESULTS-v3.md)
- [reports/PREREG-v2.md](reports/PREREG-v2.md)
- [reports/PREREG-v3.md](reports/PREREG-v3.md)
- [../../docs/paper_registry.md](../../docs/paper_registry.md)
