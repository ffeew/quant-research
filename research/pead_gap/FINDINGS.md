# Post-earnings drift / earnings-gap

**Status:** failed  
**Verdict:** FAILED: PIT OOS Sharpe 0.49 / 0.44 / 0.35 across three runs

## Hypothesis
Long post-earnings-announcement drift (with earnings-gap filter) earns a risk-adjusted excess return out of sample.

## Data window
OOS window per RESULTS_pit.md; earlier universe-117 study per RESULTS_universe117.md.

## Method
Point-in-time S&P 500 universe; three pre-registered runs; costs at 1x and 2x; DSR and Newey-West t.

## Results
- Run 1 (PIT S&P 500): FAIL, OOS Sharpe 0.49 (0.33 at 2x costs).
- Run 2 (earnings-gap only): FAIL, OOS Sharpe 0.44, DSR 0.210, NW t 2.18.
- Run 3: FAIL, OOS Sharpe 0.35.
- Survivorship check: the earlier fixed 117-name universe gave 1.27 vs 0.49 on the PIT universe; that earlier study (PEAD_trend_L OOS Sharpe 1.19) is superseded.

## Code
- Entry point: `qr run pead_gap` (`python -m quant_research.strategies.pead_gap.pit.run_all`)
- Config: `configs/pead_gap.toml`

## Sources
Numbers above are copied from these documents:
- [reports/RESULTS_pit.md](reports/RESULTS_pit.md)
- [reports/RESULTS_universe117.md](reports/RESULTS_universe117.md)
