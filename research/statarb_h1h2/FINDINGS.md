# Statarb H1/H2 harness (bellwether lag, earnings peer read-through)

**Status:** in_progress  
**Verdict:** harness code-reviewed; no DEV run yet; no results

## Hypotheses
- **H1 (bellwether lag).** Within a GICS sub-industry with at least 4 eligible members, an unusual
  60-session return gap between the 2 most-traded names (leaders) and the rest (followers) closes
  over the next 4 weeks. Long the lagging side, short the leading side. Predicted sign: positive.
- **H2 (earnings peer read-through).** When a sub-industry's exact-timestamp reporters on d0 react
  strongly together (|N| >= 1.5 residual sigmas vs the sector ETF), peers that already reported this
  season drift in the direction of N over the next 40 sessions, hedged with beta x sector ETF.
  Predicted sign: positive.

## Pre-registered design (summary)
- Universe: point-in-time S&P 500 members, clipped to listing windows; reused tickers, names with
  no usable history, identity exclusions and ETFs removed. Eligibility: price >= $5, 20-day ADV >= $20M,
  no zero-volume print, no |daily return| > 40% in the last 20 sessions, 252 sessions of history.
- H1 primary: L = 60, |z| >= 1, 2 leaders, min group 4, 4 weekly tranches, no earnings event in the
  hold window (2-session margin), name cap 9.5% of equity at 58% gross.
- H2 primary: H = 40, |N| >= 1.5, already-reported window 50 sessions, unit 0.5%, at most 100 live
  positions; hedge = sector SPDR (SPY if it has < 252 sessions).
- Execution: signal at the close of t, fill at the close of t+1; participation capped at 1% of 20-day ADV.
- Costs: required path uses >= 10%/yr borrow on every historically unknown short, ETF hedges included;
  impact k = 1.0 base (0.75 is a lighter sensitivity); 1%/yr general-collateral path is a labelled
  counterfactual only.
- Terminal treatments: H1 stranded positions in unresolved delistings take an adverse bound (long -100%,
  short max(last price, deal value)); H2 counted delisting stress is -30% long / 0% short.
- Trial count N = 212 for the deflated Sharpe ratio. Stage A (DEV) pass bar: net Sharpe > 0.85 on the
  required cost path with the predicted sign; a fail ends the idea and the holdout stays closed.

## Data window
| Split | Dates | Notes |
|---|---|---|
| DEV | 2017-01-03 to 2021-12-31 | positions must exit 2 sessions before the end |
| Embargo | 2022-01-03 to 2022-03-29 | nothing entered or evaluated |
| Holdout | 2022-03-30 to 2026-10-28 | read once, in a single sitting; not bound in this harness |

## Method
`quant_research.strategies.statarb_h1h2` is a config-driven port of the pre-registered runner. All
input paths and sha256 pins come from a TOML config (`configs/statarb_h1h2.toml` is an all-PENDING
example). The harness fails closed: any PENDING or mismatched pin, a total-return cut holding rows
after the embargo end, or rows past the read-time end stops the run before any return is computed.

## Results
- None. No DEV run has been made; no returns computed.

## Code
- Entry point: `qr run statarb_h1h2` (`python -m quant_research.strategies.statarb_h1h2.run --syntax-check`)
- Config: `configs/statarb_h1h2.toml`
- Tests (synthetic fixtures only): `tests/strategies/statarb_h1h2/`
