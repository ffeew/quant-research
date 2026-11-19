# AV news sentiment -> returns (H1a/H1b/H2/H2C/H3)

**Status:** failed  
**Verdict:** H1b FAILED OOS economic gate (IC 0.0207 significant, net < 0); H2C FAILED holdout (p 0.1506, net of 10 bp < 0), closed; H3 FAILED DEV gate, closed

## Hypothesis
Alpha Vantage ticker sentiment predicts cross-sectional returns (H1a weekly, H1b daily) and event returns (H2).

## Data window
DEV then one sealed OOS run for H1b (433 periods).

## Method
Pre-registered IC tests with Newey-West t, Holm correction, L/S net at 10 bps; UTC and ET readings.

## Results
- H1a: DEV FAIL (mean IC -0.0181 UTC); no OOS run.
- H1b OOS: UTC IC 0.020664, NW t 2.405, Holm p 0.0166, but L/S net at 10 bps -0.001591 per period (gross 0.001154) -> FAILED the economic gate. ET reading: IC 0.018029, t 1.979, net -0.001793.
- H2 (exploratory DEV only): IC 0.0947.
- H2C holdout (2011Q1-2013Q4, 12 quarters): mean IC 0.0480, one-sided p 0.1506 (gate <= 0.01), net of 10 bp -0.0037 per quarter -> FAILED; closed, holdout spent.
- H3: DEV gate failed under both readings -> closed; holdout never opened.

## Code
- Entry point: `qr run sentiment_returns` (`python -m quant_research.strategies.sentiment_returns.oos_runner`)
- Config: `configs/sentiment_returns.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v5.md](reports/PREREG_v5.md)
- [reports/DEV_RESULTS.md](reports/DEV_RESULTS.md)
- [reports/OOS_RESULT_H1b.md](reports/OOS_RESULT_H1b.md)
- [reports/OOS_RESULT_H2C.md](reports/OOS_RESULT_H2C.md)
- [reports/H2_DEV_RESULTS.md](reports/H2_DEV_RESULTS.md)
- [reports/FISCAL_DIAGNOSTIC_S6B.md](reports/FISCAL_DIAGNOSTIC_S6B.md)
- [reports/PREREG_H2C_r3.md](reports/PREREG_H2C_r3.md)
- [reports/PREREG_H3_v2.md](reports/PREREG_H3_v2.md)

## Status update: H2-C and H3
- H2-C: closed. The single holdout run (2011-2013) failed the pre-registered gate on significance and on net-of-cost return; the holdout is spent and will not be rerun. See [reports/OOS_RESULT_H2C.md](reports/OOS_RESULT_H2C.md).
  - Code (reference only; `run_h2c` refuses the holdout partition): `src/quant_research/strategies/sentiment_returns/h2c/`
- H3: closed. The DEV gate failed under both readings; the holdout was never opened; no rerun, re-tune or variant.
  - Code (reference only): `src/quant_research/strategies/sentiment_returns/h3/`
