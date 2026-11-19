# Academic replications: residual momentum, BAB, industry momentum

**Status:** failed  
**Verdict:** FAILED: all three replications net Sharpe <= 0.06

## Hypothesis
Three published anomalies (residual momentum, betting-against-beta, industry momentum) survive costs on a PIT S&P 500 universe.

## Data window
Residual momentum from 2019-01 (first fully warmed-up month); BAB from 2019-02; industry momentum (ETF version) from 2017-02 (see SUBMISSION files).

## Method
Shared engine in quant_research.backtest (engine, validation, stats); PIT S&P 500 membership incl. delisted names; SIP total-return prices; DSR across the trial count.

## Results
- Residual momentum L/S: net Sharpe 0.06 (0.11 from 2019-02), t 0.19, DSR 0.017 (N=75). Long-only 0.69 Sharpe is mostly beta (0.95).
- BAB (Frazzini-Pedersen): net Sharpe -0.30; low-vol long-only 0.50 with beta 0.63.
- Industry momentum (ETF L/S): net Sharpe 0.02, PBO 0.62.

## Code
- Entry point: `qr run academic_replications` (`python -m quant_research.strategies.academic_replications.run_all`)
- Config: `configs/academic_replications.toml`

## Sources
Numbers above are copied from these documents:
- [reports/README.md](reports/README.md)
- [reports/SUBMISSION_residual_momentum.md](reports/SUBMISSION_residual_momentum.md)
- [reports/SUBMISSION_betting_against_beta.md](reports/SUBMISSION_betting_against_beta.md)
- [reports/SUBMISSION_industry_momentum.md](reports/SUBMISSION_industry_momentum.md)
