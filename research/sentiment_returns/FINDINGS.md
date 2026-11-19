# AV news sentiment -> returns (H1a/H1b/H2/H2C/H3)

**Status:** failed  
**Verdict:** H1b FAILED OOS economic gate (IC 0.0207 significant, net < 0); H2C/H3 in progress

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
- H2C and H3: pre-registered / frozen, no results yet.

## Code
- Entry point: `qr run sentiment_returns` (`python -m quant_research.strategies.sentiment_returns.oos_runner`)
- Config: `configs/sentiment_returns.toml`

## Sources
Numbers above are copied from these documents:
- [reports/PREREG_v5.md](reports/PREREG_v5.md)
- [reports/DEV_RESULTS.md](reports/DEV_RESULTS.md)
- [reports/OOS_RESULT_H1b.md](reports/OOS_RESULT_H1b.md)
- [reports/H2_DEV_RESULTS.md](reports/H2_DEV_RESULTS.md)
- [reports/FISCAL_DIAGNOSTIC_S6B.md](reports/FISCAL_DIAGNOSTIC_S6B.md)
- [reports/PREREG_H2C_r3.md](reports/PREREG_H2C_r3.md)
- [reports/PREREG_H3_v2.md](reports/PREREG_H3_v2.md)
