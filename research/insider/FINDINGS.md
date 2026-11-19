# Insider trading (Form 4)

**Status:** failed  
**Verdict:** FAILED / parked: no significant opportunistic-buy effect; needs small-cap data

## Hypothesis
Opportunistic insider purchases (Cohen-Malloy-Pomorski) predict excess returns.

## Data window
2016-01..2026-09.

## Method
Form 3/4/5 trades classified routine vs opportunistic; 38 statistics.

## Results
- Example: opp_buy_xr1 mean -0.62%, t -1.09. Parked; needs small-cap data.

## Code
- Entry point: `qr run insider` (`python -m quant_research.strategies.insider.make_results`)
- Config: `configs/insider.toml`

## Sources
Numbers above are copied from these documents:
- [reports/RESULTS.md](reports/RESULTS.md)
- [reports/README.md](reports/README.md)
