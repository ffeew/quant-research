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

## Status update: H2-C and H3
- H2-C: DEV passed gates G0 and G1. The holdout test is pending; no holdout result yet.
  - Code: `src/quant_research/strategies/sentiment_returns/h2c/`
  - Run command: the LOCK command in [PREREG_H2C_r3.md](reports/PREREG_H2C_r3.md) §12 predates the required-input
    change. `h2c_dev_run.py` now refuses a real run (exit 10) unless it is given `--pull_root <dir>` (the AV pull copy
    root) and also `--purge`, `--tx_dev_root`, `--fye_month_frozen`, `--cost_clean` and `--cost_tx_root`. None has a
    default. Add these flags to the §12 command at LOCK. The prereg is frozen and is not edited.
- H3: code only. Not run; no findings.
  - Code: `src/quant_research/strategies/sentiment_returns/h3/`
  - Design choices that are not yet settled are explicit parameters with no committed value in `configs/sentiment_returns.toml`.
