# Statistical arbitrage v1 (pairs / ETF residuals)

**Status:** failed  
**Verdict:** FAILED: all 48 configurations; best gross edge 5.5 bps < 10.6 bps cost

## Hypothesis
Mean reversion of stock-vs-ETF / pair residuals clears realistic trading costs.

## Data window
Dev and holdout splits as in RESULTS.md.

## Method
48 pre-declared configurations (run_v1/validate_v1/compare_modes) with desk cost floor and alternative base costs.

## Results
- All 48 trials FAIL.
- Best (AL_ETF): gross edge 5.5 bps vs 10.6 bps cost; holdout gross Sharpe 0.46; holdout net Sharpe -0.56 (desk cost floor) / -0.35 (lower base cost).
- **Survivorship-suspect:** the sector grouping uses a current GICS snapshot that lacks delisted names, so these results are survivorship-suspect until rerun on point-in-time industry data (desk GICS-dependence audit, sha 0c6efe39). No rerun for now.

## Code
- Entry point: `qr run statarb_v1` (`python -m quant_research.strategies.statarb_v1.run_all`)
- Config: `configs/statarb_v1.toml`

## Sources
Numbers above are copied from these documents:
- [reports/RESULTS.md](reports/RESULTS.md)
