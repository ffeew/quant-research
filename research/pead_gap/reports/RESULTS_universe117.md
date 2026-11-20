# Systematic validation: PEAD-gap and trend-filtered 12-1 momentum (U from quant.py)

Run: Fri 30 Oct 2026, ~00:55–01:45 SGT (UTC+8). Read-only market data. No orders were placed, modified or cancelled.
Every number below comes from the scripts in this folder. Outputs: `results_summary.csv`, `results_by_year.csv`, `results_by_regime.csv`, `trades_all_variants.csv`, `daily_pnl_R_all_variants.csv`, `dsr.json`, `diagnostics.json`, `diag_controls.csv`, `diag_beta_vs_spy.csv`, `data_meta.json`.

## Data
- **Source:** Alpaca `v2/stocks/bars`, **feed=sip** (consolidated tape), `adjustment=all`, 1Day. SIP worked once `end` was set to a completed session. I did not need the IEX fallback. `fetch.py` → `data/bars_sip.json`.
- **Span:** 2016-01-04 → 2026-10-28, with 2,721 SPY sessions and all 117 symbols in U. The 29 Oct session was still in progress when I fetched, so it is excluded.
  - Shorter histories: LIN from 2018-10-31, UBER from 2019-05-10, XLC from 2018-06-19.
  - MMC ends on 2026-01-13 (ticker change to MRSH). Open trades at a data end are closed at the last available close.
- **Warm-up:** 252 bars, so the first signal day is 2017-01-03. IS = signals to 2021-12-31; OOS = 2022-01-03 → 2026-10-28.

## Rules implemented (`backtest.py`)
- **Timing:** signal on bar t close; fill at bar t+1 **open**. ATR(14) uses bars up to t, all before the entry bar.
- **Bracket:** stop = entry − 2×ATR; TP = entry + 2×(2×ATR) (2R); max hold 60 sessions, exit at the close of day 60.
  - If one bar touches both stop and TP, I assume the stop fills (conservative).
  - Gaps through a level fill at the open.
  - One open position per symbol.
- **Costs:** 5 bp per side on entry and exit notional, plus 1%/yr borrow on shorts (trading days/252). All are charged in R.
- **(A) PEAD gap:** |o_t/c_{t-1} − 1| > 4% and v_t > 1.8× mean(v_{t-20..t-1}). Long up-gaps, short down-gaps. The trend variant requires close > 50 and 200 dma for longs, < both for shorts.
- **(B) Momentum:** at each month-end close:
  - score = mom12_1/max(vol20,10) + rs63/max(vol20,10), with % units as in quant.py. mom12_1 = c[t-21]/c[t-252] − 1; rs63 = r63 − r63(SPY).
  - Decile size = ceil(10% of names with a valid score) (~12).
  - Longs = highest scores among names above 50&200dma; shorts = lowest among names below both.
  - **Bracket version:** the same bracket exits.
  - **Monthly version:** hold from the open after month-end to the open after the next month-end.
    - Each month counts as one trade, with R = 2×ATR at entry for equal risk.
    - A full round-trip cost is charged every month, which is conservative.
- **Daily equity curve:** equal 1R risk per trade, additive, marked to close.
  - Sharpe = mean/sd × √252 over **all** sessions in the period, including flat days.
  - MaxDD is shown in R and as % of equity at 0.25% equity per R.
- **Regime:** SPY close vs SPY 200dma on the signal day.

## N trials = 12
These are the four requested variants (PEAD raw L/S, PEAD trend L/S, MOM bracket L/S, MOM monthly L/S) plus their long-only and short-only legs (8 more). I count the legs as trials because I looked at them.
Controls in `diagnostics.py` (unconditional entries, trend-only entries, all-names monthly hold) are benchmarks, not candidate rules.
I did no parameter search, but thresholds were inherited from quant.py. Implicit researcher degrees of freedom therefore exist; see the DSR sensitivity to N.

## Key metrics (net of costs)
| Variant | Period | Trades | Hit | Avg win R | Avg loss R | Exp R (net) | t | Sharpe (ann) | MaxDD R | MaxDD % @0.25%/R |
|---|---|---|---|---|---|---|---|---|---|---|
| PEAD_raw_LS | IS | 730 | 0.400 | 1.83 | -1.01 | +0.127 | 2.38 | +0.44 | -72.5 | -18.1 |
| PEAD_raw_LS | OOS | 903 | 0.365 | 1.82 | -1.04 | +0.005 | 0.10 | -0.02 | -54.9 | -13.7 |
| PEAD_trend_LS | IS | 508 | 0.404 | 1.81 | -1.01 | +0.126 | 1.97 | +0.34 | -73.8 | -18.4 |
| PEAD_trend_LS | OOS | 577 | 0.380 | 1.82 | -1.04 | +0.046 | 0.76 | +0.15 | -42.0 | -10.5 |
| MOM_bracket_LS | IS | 1123 | 0.370 | 1.99 | -1.07 | +0.063 | 1.41 | +0.47 | -65.1 | -16.3 |
| MOM_bracket_LS | OOS | 1121 | 0.327 | 1.96 | -1.07 | -0.079 | -1.84 | -0.52 | -136.5 | -34.1 |
| MOM_monthly_LS | IS | 1328 | 0.513 | 1.52 | -1.51 | +0.044 | 0.81 | +0.26 | -65.1 | -16.3 |
| MOM_monthly_LS | OOS | 1330 | 0.487 | 1.47 | -1.36 | +0.019 | 0.37 | +0.03 | -101.4 | -25.3 |
| PEAD_raw_L | IS | 416 | 0.478 | 1.87 | -1.01 | +0.367 | 5.03 | +1.22 | -26.5 | -6.6 |
| PEAD_raw_L | OOS | 449 | 0.437 | 1.89 | -1.05 | +0.230 | 3.23 | +0.83 | -45.7 | -11.4 |
| PEAD_raw_S | IS | 351 | 0.316 | 1.74 | -1.01 | -0.138 | -1.94 | -0.24 | -128.9 | -32.2 |
| PEAD_raw_S | OOS | 494 | 0.294 | 1.71 | -1.04 | -0.230 | -3.92 | -0.75 | -125.1 | -31.3 |
| PEAD_trend_L | IS | 315 | 0.470 | 1.85 | -1.03 | +0.325 | 3.88 | +1.08 | -19.1 | -4.8 |
| PEAD_trend_L | OOS | 289 | 0.481 | 1.92 | -1.05 | +0.379 | 4.17 | +1.19 | -24.2 | -6.0 |
| PEAD_trend_S | IS | 193 | 0.295 | 1.71 | -1.00 | -0.199 | -2.12 | -0.21 | -88.4 | -22.1 |
| PEAD_trend_S | OOS | 288 | 0.278 | 1.66 | -1.04 | -0.288 | -3.84 | -0.72 | -103.5 | -25.9 |
| MOM_bracket_L | IS | 612 | 0.456 | 2.01 | -1.06 | +0.343 | 5.47 | +1.41 | -40.2 | -10.0 |
| MOM_bracket_L | OOS | 580 | 0.357 | 1.96 | -1.07 | +0.012 | 0.20 | -0.05 | -65.0 | -16.3 |
| MOM_bracket_S | IS | 511 | 0.268 | 1.94 | -1.08 | -0.271 | -4.45 | -1.15 | -147.2 | -36.8 |
| MOM_bracket_S | OOS | 541 | 0.296 | 1.96 | -1.07 | -0.178 | -2.92 | -0.62 | -136.9 | -34.2 |
| MOM_monthly_L | IS | 712 | 0.588 | 1.66 | -1.33 | +0.432 | 6.03 | +1.16 | -57.0 | -14.3 |
| MOM_monthly_L | OOS | 676 | 0.525 | 1.58 | -1.21 | +0.255 | 3.68 | +0.62 | -85.0 | -21.3 |
| MOM_monthly_S | IS | 616 | 0.425 | 1.31 | -1.67 | -0.405 | -5.15 | -1.21 | -259.2 | -64.8 |
| MOM_monthly_S | OOS | 654 | 0.448 | 1.35 | -1.50 | -0.226 | -3.10 | -0.65 | -221.0 | -55.3 |
## Deflated Sharpe Ratio (Bailey & López de Prado 2014), best OOS variant
- **Best OOS variant:** PEAD_trend_L (long-only leg of PEAD with trend alignment).
  - OOS annualised Sharpe 1.187 (daily SR 0.0748), T = 1,210 sessions.
  - Skew 0.29, kurtosis 17.47.
- **Trial dispersion:** N = 12; variance of the daily OOS SR across the 12 trials = 0.001675.
  - That gives SR0 (expected max under the null) = 0.0681 daily = 1.082 annualised.
- **Results:** PSR vs 0 = 0.995, but **DSR = 0.591**.
  - If N = 20 / 50 / 100, DSR = 0.458 / 0.261 / 0.159.
- **Sensitivities** (`diagnostics.json`):
  - SR variance taken from the 6 long legs only: DSR 0.758.
  - Best of the 4 primary L/S variants (PEAD_trend_LS, SR 0.148): DSR 0.363.
  - Beta-hedged PEAD_trend_L (SR 0.947): DSR 0.384.
- **No variant clears DSR > 0.95.**

## Controls and beta (`diag_controls.csv`, `diag_beta_vs_spy.csv`)
- **Benchmark Sharpe:** SPY buy and hold had Sharpe 1.01 IS and 0.75 OOS. The long legs are strongly beta-driven.
- **Unconditional long brackets** (every name, every 5th session, same exits):
  - IS +0.323R (n=29,192); OOS +0.117R (n=28,274).
  - Unconditional shorts: −0.371R IS, −0.197R OOS.
  - This survivor universe rewards any long and punishes any short.
- **PEAD_trend_L vs the trend-only long control** (above 50&200dma, same exits):
  - IS: +0.325 vs +0.278R, Welch t 0.56, i.e. **no edge IS**.
  - OOS: +0.379 vs +0.075R, Welch t 3.31.
  - The edge appears only OOS, so it is not stable.
- **PEAD_raw_L vs the unconditional long control:** Welch t 0.59 IS, 1.57 OOS.
- **MOM_monthly_L vs the all-names equal-risk monthly hold:** Welch t 0.97 IS, **0.13 OOS**. Momentum ranking adds nothing over owning the survivor universe.
- **OOS beta to SPY** (R per 1% SPY move):
  - PEAD_trend_L: 0.48; alpha t 2.07; beta-hedged Sharpe 0.95.
  - PEAD_raw_L: 0.92; alpha t 0.95.
  - MOM_monthly_L: 1.88; alpha t 0.39.
  - MOM_bracket_L: 0.90; alpha t −1.06.

## Regime: SPY above vs below 200dma (OOS; IS/FULL in `results_by_regime.csv`)
| Variant | Regime | OOS trades | OOS exp R | OOS t | Sharpe on regime days (OOS) |
|---|---|---|---|---|---|
| PEAD_raw_LS | SPY>200 | 691 | +0.078 | 1.41 | 0.544 |
| PEAD_raw_LS | SPY<200 | 212 | -0.235 | -2.63 | -0.975 |
| PEAD_trend_LS | SPY>200 | 436 | +0.146 | 2.05 | 0.683 |
| PEAD_trend_LS | SPY<200 | 141 | -0.265 | -2.44 | -0.763 |
| MOM_bracket_LS | SPY>200 | 859 | -0.040 | -0.8 | -0.267 |
| MOM_bracket_LS | SPY<200 | 262 | -0.208 | -2.43 | -1.44 |
| MOM_monthly_LS | SPY>200 | 1026 | +0.087 | 1.5 | 0.234 |
| MOM_monthly_LS | SPY<200 | 304 | -0.211 | -2.04 | -0.723 |
| PEAD_raw_L | SPY>200 | 367 | +0.257 | 3.23 | 0.987 |
| PEAD_raw_L | SPY<200 | 82 | +0.112 | 0.69 | 0.3 |
| PEAD_raw_S | SPY>200 | 348 | -0.146 | -2.02 | -0.681 |
| PEAD_raw_S | SPY<200 | 146 | -0.431 | -4.44 | -1.027 |
| PEAD_trend_L | SPY>200 | 267 | +0.374 | 3.95 | 1.341 |
| PEAD_trend_L | SPY<200 | 22 | +0.440 | 1.31 | 0.361 |
| PEAD_trend_S | SPY>200 | 169 | -0.213 | -2.08 | -0.863 |
| PEAD_trend_S | SPY<200 | 119 | -0.395 | -3.62 | -0.817 |
| MOM_bracket_L | SPY>200 | 452 | +0.103 | 1.46 | 0.435 |
| MOM_bracket_L | SPY<200 | 128 | -0.311 | -2.66 | -1.845 |
| MOM_bracket_S | SPY>200 | 407 | -0.200 | -2.87 | -0.899 |
| MOM_bracket_S | SPY<200 | 134 | -0.110 | -0.88 | 0.016 |
| MOM_monthly_L | SPY>200 | 528 | +0.335 | 4.07 | 1.034 |
| MOM_monthly_L | SPY<200 | 148 | -0.027 | -0.23 | -0.727 |
| MOM_monthly_S | SPY>200 | 498 | -0.176 | -2.19 | -0.938 |
| MOM_monthly_S | SPY<200 | 156 | -0.385 | -2.33 | -0.031 |

## By calendar year (signal year)

Expectancy (net R per trade) by signal year:

| year | PEAD_raw_LS | PEAD_trend_LS | MOM_bracket_LS | MOM_monthly_LS | PEAD_trend_L | MOM_monthly_L |
|---|---|---|---|---|---|---|
| 2017 | 0.051 | 0.263 | 0.198 | 0.14 | 0.385 | 0.906 |
| 2018 | 0.077 | -0.09 | 0.127 | 0.025 | -0.061 | 0.229 |
| 2019 | 0.114 | 0.067 | -0.145 | -0.015 | 0.577 | 0.461 |
| 2020 | 0.328 | 0.28 | 0.175 | 0.218 | 0.486 | 0.459 |
| 2021 | -0.198 | -0.087 | -0.04 | -0.147 | 0.07 | 0.104 |
| 2022 | -0.179 | -0.043 | -0.136 | -0.11 | -0.013 | -0.242 |
| 2023 | 0.107 | 0.046 | 0.033 | 0.031 | 0.243 | 0.437 |
| 2024 | 0.096 | 0.308 | -0.075 | 0.182 | 0.681 | 0.617 |
| 2025 | 0.033 | 0.057 | -0.139 | 0.046 | 0.771 | 0.308 |
| 2026 | -0.056 | -0.172 | -0.081 | -0.076 | -0.084 | 0.088 |

Trades by year:

| year | PEAD_raw_LS | PEAD_trend_LS | MOM_bracket_LS | MOM_monthly_LS | PEAD_trend_L | MOM_monthly_L |
|---|---|---|---|---|---|---|
| 2017 | 110 | 80 | 219 | 259 | 59 | 144 |
| 2018 | 127 | 87 | 242 | 283 | 50 | 144 |
| 2019 | 130 | 86 | 221 | 269 | 52 | 144 |
| 2020 | 255 | 183 | 218 | 259 | 101 | 136 |
| 2021 | 108 | 72 | 223 | 258 | 53 | 144 |
| 2022 | 157 | 91 | 232 | 273 | 22 | 136 |
| 2023 | 143 | 95 | 239 | 280 | 62 | 144 |
| 2024 | 204 | 124 | 224 | 273 | 86 | 144 |
| 2025 | 220 | 148 | 240 | 288 | 54 | 144 |
| 2026 | 179 | 119 | 186 | 216 | 65 | 108 |

Annualised Sharpe by calendar year:

| year | PEAD_raw_LS | PEAD_trend_LS | MOM_bracket_LS | MOM_monthly_LS | PEAD_trend_L | MOM_monthly_L |
|---|---|---|---|---|---|---|
| 2017 | 0.09 | 1.14 | 0.89 | 0.35 | 1.24 | 1.96 |
| 2018 | 1.0 | -0.01 | 1.3 | 0.68 | 0.04 | 0.88 |
| 2019 | 0.67 | -0.04 | -1.64 | -0.63 | 1.76 | 1.09 |
| 2020 | 0.94 | 0.65 | 1.16 | 0.86 | 1.73 | 1.16 |
| 2021 | -0.68 | -0.08 | 0.23 | -0.28 | 0.45 | 0.89 |
| 2022 | -1.88 | -0.45 | -0.41 | -0.21 | -1.41 | -1.17 |
| 2023 | 0.81 | -0.21 | -0.66 | -1.08 | 0.79 | 0.69 |
| 2024 | 0.84 | 1.68 | -0.23 | 1.08 | 2.14 | 1.8 |
| 2025 | -0.0 | -0.04 | -1.16 | 0.02 | 2.42 | 0.64 |
| 2026 | 0.12 | -0.41 | -0.1 | 0.06 | 0.13 | 0.86 |
## Flags
- **Survivorship bias (severe).** U is today's mega-caps and ETFs, selected *because* they won through 2026. Names that shrank, were acquired or delisted are absent.
  - Likely direction: it **inflates long-side results** and **depresses short-side results**. A short on a stock that later became a mega-cap is a short on an ex-post winner.
  - Measured: the unconditional long bracket earned +0.32R IS and +0.12R OOS; the unconditional short lost 0.37R and 0.20R.
  - So the long-only "winners" here are upper bounds, and the short-leg losses partly reflect the bias. A point-in-time universe (e.g. historical top-100 by market cap with delisted names) is needed before any PASS.
- **Sample size.**
  - OOS trade counts are ≥100 for every variant (PEAD_trend_L 289; PEAD_trend_LS 577).
  - But SPY<200dma OOS has only 274 sessions, and PEAD_trend_L has only 22 OOS trades in that regime.
  - About 4.8 years of OOS includes one bear episode (2022). Monthly momentum has only ~58 OOS rebalances.
  - Trades overlap heavily (gap clusters in earnings season), so effective N is well below the trade count.
- **Look-ahead / timing issues in quant.py** (the live screen; none of these is in `backtest.py`):
  1. **Hard-coded `"2026-10-29"` bar drop** plus a timezone bug. `dt.date.today()` runs on the box in SGT (30 Oct), so the "today" check never matches the US session date; the hard-coded string patches it for this one day only. On any other run date the partial bar is kept or a complete bar is dropped. This is not reusable.
  2. **Mixed timestamps.** The live IEX `latestTrade` (~12:50 ET, intraday, possibly stale on IEX) is compared with 50/200 SMAs, r5/r21/r63, rs63 and ATR computed from *prior closes*, while mom12_1 ignores the live price. The live signal is an intraday hybrid that no close-to-close or open-fill backtest can reproduce. Above/below-dma flags and RS can flip by the close.
  3. **The gap/PEAD detector skipped the gap it was traded on.** It only scans the 15 sessions *before* today, so the LLY/MA/GOOGL/CAT day-0 earnings gaps were not produced by the code. Selection was a discretionary news overlay.
  4. **Volume ratio off by one.** `v[i-21:i-1]` excludes day i−1 and includes i−21. Volume is **IEX-only** (single venue), so the 1.8× filter is noisy.
  5. Smaller issues:
     - RSI is a simple 14-day average, not Wilder.
     - ETFs, and crypto in `rows`, are ranked in the same list as stocks.
     - IEX `latestTrade` can be stale for illiquid names.
     - execute.py re-reads a *fresh* IEX trade price for stop/target while ATR is from signals.json, so levels are relative to a price that differs from the fill.
  - No future data leaks into quant.py itself; the problems are reproducibility and timing, not peeking.
- **Backtest limitations.**
  - Daily bars cannot resolve the intrabar order of stop vs TP; I assumed the stop first (conservative).
  - No earnings calendar is used in (A); gaps include non-earnings news.
  - `adjustment=all` back-adjusts for dividends, which can slightly alter historical gap sizes.
  - No slippage beyond 5 bp, which is optimistic for 4%+ gap opens.
  - Borrow is a flat 1%/yr.

## Verdicts (bar: ≥100 OOS trades, OOS Sharpe > 0 after costs, DSR > 0.95, not dependent on one regime)
- **(A) PEAD gap, as traded (long + short, bracket): FAIL.**
  - Raw L/S OOS: 903 trades, Sharpe −0.02, exp +0.005R.
  - Trend L/S OOS: 577 trades, Sharpe +0.15, exp +0.046R (t 0.76).
  - DSR 0.36 even within the 4 primary variants.
  - OOS edge is only in SPY>200 (+0.146R) and is negative in SPY<200 (−0.265R, t −2.44).
  - The short leg loses in every period: OOS −0.23R raw and −0.29R trend.
- **(A′) PEAD long-only + trend (PEAD_trend_L): FAIL against the bar, but the best candidate for a forward paper test.**
  - In favour: OOS 289 trades, Sharpe 1.19, exp +0.379R (t 4.17), positive in both regimes OOS (n=22 in SPY<200).
  - Against: DSR 0.59 < 0.95. It shows no edge over trend-only longs in-sample (Welch t 0.56). Beta 0.48. Survivorship-inflated. 2026 YTD is negative (−0.084R).
  - Needs a point-in-time universe and earnings-date-confirmed events before it could become a CONDITIONAL PASS.
- **(B) Trend-filtered 12-1 momentum: FAIL.**
  - Bracket L/S OOS: Sharpe −0.52, exp −0.079R.
  - Monthly L/S OOS: Sharpe +0.03, exp +0.019R (t 0.37).
  - The long legs' positive Sharpe is beta/survivorship: monthly long beta 1.88, alpha t 0.39, and no better than holding all names (Welch t 0.13).
  - Shorts lose in every period. SPY<200 OOS is negative for all L/S versions.
- **Implication for the 5 live trades.** None of the families supports shorting GOOGL or CAT: the short legs of both families have negative OOS expectancy. The LLY/MA longs fit the only marginally interesting variant (trend-aligned up-gap), but it is unvalidated (DSR 0.59). XLE (momentum) has no support.

---
# Section E: Audit of the Equity Analyst's earnings-drift check (`equity/pead_check.py`)
Files were copied read-only to `ethan_rerun/` (`pead_check_orig.py`, `pead_data_orig/`, report `.md`). The originals were not edited.
- `pead_check_rerun.py` is identical except that CACHE points to `ethan_rerun/pead_data_rerun/`. It uses their cached EDGAR/Nasdaq pulls and my `bars_sip.json`.
- `indep_pead.py` is my independent reimplementation, with fresh EDGAR pulls in `indep_data/`.
- `multiple_testing.json` holds the trial count.

## E1. Code audit (look-ahead and design)
- **Event dates: point-in-time, OK.** The code uses EDGAR `acceptanceDateTime`, converted to ET.
  - I spot-checked that the field is true UTC: GOOGL 20:01Z = 16:01 ET after close; CAT 10:32Z = 06:32 ET pre-market.
  - Accepted before 09:30 ET → day0 = that session; otherwise the next session.
  - About 2% of filings are accepted in market hours, and the 8-K can lag the press release. Both push day0 *later*, which is conservative, not look-ahead.
- **Event definition: noisy.** Every 8-K Item 2.02 counts as an event, which includes guidance pre-announcements and non-earnings filings.
  - TSLA has 87 events, ABBV and REGN 61 each, versus ~43 quarters.
  - LLY's last 8 include the 2025-01-14 guidance pre-announcement.
- **Coverage gaps from CIK changes** (current-ticker → CIK map only):
  - XOM has 1 event (new holding CIK 2115436; old 34088 missed).
  - BLK starts in Oct 2024 (old CIK 1364742 missed).
  - DIS, CI and AVGO miss pre-2018/19 history (old CIKs 1001039, 701221, 1649338).
  - MMC has none (now MRSH, CIK 62709).
- **Earnings-day move:** AR0 = close-to-close stock return minus SPY on day0. This is correct for both pre-market and after-close reporters.
  - The "+1" windows enter at the **day0 close**, the same print that defines the signal, a mild same-close look-ahead.
  - Their d2 windows, and my next-open entry, are clean. Results barely change, so this is immaterial.
- **Real look-ahead in the Q5−Q1 test.** EAR quintiles are formed within each *calendar quarter* using all of that quarter's events, so an early-quarter event is ranked against later events' reactions. That makes it untradable as specified.
  - Its headline t-stats (t=2.63 at 20d; max |t| 4.95 for 2023–24 at 60d) should not be relied on.
- **EPS surprises are not point-in-time.**
  - They come from api.nasdaq.com (Zacks), the current snapshot of the last ~4 quarters only, so there is no history and revisions are possible.
  - 90.3% are beats, so the surprise-signed test is nearly a long-only market-adjusted test.
  - Some values are not operating surprises (GOOGL +216% in Jul 2026, +93.6% in Apr 2026).
- **t-statistics.**
  - "Month-clustered t" is the t of the mean of *monthly means*. That re-weights events equally by month; it is not a cluster-robust SE of the event mean.
  - My CR1 cluster-robust t (by month) is close to the naive event t, e.g. 3.23 vs 3.14 for all-events 20d. So within-month correlation is not what drives their lower t; the equal-month weighting is.
  - Neither statistic handles **overlapping 60-day windows** across adjacent months. I report a Newey-West t on monthly means (lag = ceil(H/21)+1).
  - The Q5−Q1 per-quarter series also overlaps at 60d.
- **Other.**
  - Survivorship is correctly flagged by them (unsigned baseline +0.91% at 60d).
  - Costs: 10 bp round trip, no borrow.
  - The sub-period choices ("2025–26", "last 4 qtrs") were picked after looking.

## E2. Rerun: do their numbers reproduce?
Their code on their cached inputs plus my bars gives **byte-identical** `events.csv` and identical `results.json` tables and pilot block.

| Headline claim | Their number | Rerun of their code | Independent reimplementation (next-open entry, earnings-only events, fixed CIKs) | Verdict |
|---|---|---|---|---|
| Universe / events | 94 names, 4,030 events | 94 names; 4,076 events total, 4,030 with a full 20d window | 95 names, 4,056 events (4,027 with a 20d window) | **Reproduces** (count). Coverage gaps noted in E1 |
| All events, signed CAR(+1,+20) | +0.30%, clustered t=1.46 | +0.304%, event t 2.79, month-mean t 1.46 | +0.329%; event t 3.14; month-mean t 1.38; CR1 t 3.23; NW t 1.36 | **Reproduces.** But the "t=1.46" depends on the estimator: a cluster-robust t is ~3.2. Signed drift ≈ unsigned survivorship baseline (+0.29%, t 2.76) |
| 2025–26, CAR(+1,+20) | +0.23%, t=0.71, N=673 | +0.234%, t 0.71, N 673 | +0.371%, t 1.10 (CR1 0.94), N 657 | **Reproduces** (insignificant either way) |
| Last 4 qtrs, CAR(+1,+60) reversal | −1.64%, t≈−1.9, N=362 | −1.636%, event t −1.97, month-mean t −1.93, N 362 | −1.883%, event t −2.00, CR1 −1.64, NW −1.72, N 348 | **Reproduces in sign/size; not significant.** Post-hoc window; 11 months of overlapping 60d windows; fails multiplicity (E4) |
| Signed by EPS surprise, 20d | −0.44%, t=−0.81, N=306 | −0.441%, t −0.81, N 306 | Not reimplemented: no point-in-time surprise source | **Reproduces mechanically only.** Input is not point-in-time; uninformative |
| LLY last 8 events, t | t=0.54 | n 8, +2.54%, t 0.54 | Earnings-only events (drops the 2025-01-14 guidance 8-K): +6.28%, t 1.40 | **Reproduces their code, but the number is fragile.** Still n=8, not significant |
| MA, GOOGL, CAT unsupported | t 0.41, −0.23, −0.05 | same | MA +1.05% t 0.88; GOOGL −0.39% t −0.16; CAT +0.32% t 0.11 | **Reproduces** (none supported) |

## E3. Independent reimplementation (`indep_pead.py`, `indep_data/indep_results.csv`)
- **Events:** for each 10-Q/10-K, take the latest Item 2.02 8-K accepted after the fiscal period end and no later than 1 day after the 10-Q/10-K filing. Former CIKs are added.
  - 36 periods had no matching 2.02.
  - 75 events (~1.8%) were accepted in market hours.
- **Signal and returns:** signal = sign(AR0). Entry = open of day0+1; exit = close of day0+H.
  - SPY-adjusted return over the identical open→close window.
- **t-stats:** naive, month-means, CR1-by-month and Newey-West on monthly means.

Full table:

| subset | period | H | n | mean_pct | net10bp_pct | hit | t_event | t_month_means | t_CR1_month | t_NW_month | months |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | ALL 2016-2026 | 20 | 4027 | 0.329 | 0.229 | 0.519 | 3.14 | 1.38 | 3.23 | 1.36 | 129 |
| all | ALL 2016-2026 | 60 | 4002 | 0.039 | -0.061 | 0.505 | 0.2 | -0.71 | 0.2 | -0.62 | 128 |
| |AR0|>=4% | ALL 2016-2026 | 20 | 1457 | 0.679 | 0.579 | 0.544 | 3.49 | 0.81 | 3.6 | 0.86 | 129 |
| |AR0|>=4% | ALL 2016-2026 | 60 | 1444 | 0.345 | 0.245 | 0.514 | 0.96 | 0.64 | 0.75 | 0.71 | 127 |
| long AR0>=+4% | ALL 2016-2026 | 20 | 750 | 0.95 | 0.85 | 0.537 | 3.5 | 1.59 | 3.8 | 1.66 | 123 |
| long AR0>=+4% | ALL 2016-2026 | 60 | 744 | 1.538 | 1.438 | 0.528 | 3.2 | 2.59 | 2.82 | 2.85 | 122 |
| short AR0<=-4% | ALL 2016-2026 | 20 | 707 | 0.392 | 0.292 | 0.55 | 1.4 | 0.39 | 1.29 | 0.45 | 128 |
| short AR0<=-4% | ALL 2016-2026 | 60 | 700 | -0.923 | -1.023 | 0.499 | -1.75 | -1.32 | -1.51 | -1.43 | 126 |
| baseline unsigned (survivorship) | ALL 2016-2026 | 20 | 4027 | 0.29 | 0.19 | 0.504 | 2.76 | 1.92 | 1.89 | 1.84 | 129 |
| baseline unsigned (survivorship) | ALL 2016-2026 | 60 | 4002 | 0.846 | 0.746 | 0.509 | 4.35 | 3.68 | 3.34 | 3.8 | 128 |
| all | IS <=2021 | 20 | 2237 | 0.275 | 0.175 | 0.515 | 2.11 | 1.39 | 2.32 | 1.38 | 72 |
| all | IS <=2021 | 60 | 2237 | 0.131 | 0.031 | 0.503 | 0.55 | 0.35 | 0.6 | 0.36 | 72 |
| |AR0|>=4% | IS <=2021 | 20 | 669 | 0.882 | 0.782 | 0.561 | 3.32 | 1.26 | 3.94 | 1.4 | 72 |
| |AR0|>=4% | IS <=2021 | 60 | 669 | 0.733 | 0.633 | 0.516 | 1.54 | 1.16 | 1.5 | 1.32 | 72 |
| long AR0>=+4% | IS <=2021 | 20 | 346 | 1.045 | 0.945 | 0.558 | 2.75 | 1.29 | 2.77 | 1.37 | 70 |
| long AR0>=+4% | IS <=2021 | 60 | 346 | 2.581 | 2.481 | 0.561 | 3.77 | 3.07 | 4.11 | 2.69 | 70 |
| short AR0<=-4% | IS <=2021 | 20 | 323 | 0.707 | 0.607 | 0.563 | 1.91 | 0.56 | 2.04 | 0.7 | 71 |
| short AR0<=-4% | IS <=2021 | 60 | 323 | -1.248 | -1.348 | 0.467 | -1.94 | -1.32 | -1.78 | -1.39 | 71 |
| baseline unsigned (survivorship) | IS <=2021 | 20 | 2237 | 0.281 | 0.181 | 0.515 | 2.16 | 1.43 | 1.52 | 1.37 | 72 |
| baseline unsigned (survivorship) | IS <=2021 | 60 | 2237 | 1.141 | 1.041 | 0.53 | 4.84 | 3.28 | 4.1 | 3.9 | 72 |
| all | OOS 2022+ | 20 | 1790 | 0.397 | 0.297 | 0.523 | 2.32 | 0.68 | 2.28 | 0.67 | 57 |
| all | OOS 2022+ | 60 | 1765 | -0.077 | -0.177 | 0.509 | -0.24 | -1.03 | -0.21 | -0.85 | 56 |
| |AR0|>=4% | OOS 2022+ | 20 | 788 | 0.508 | 0.408 | 0.529 | 1.81 | 0.05 | 1.74 | 0.06 | 57 |
| |AR0|>=4% | OOS 2022+ | 60 | 775 | 0.01 | -0.09 | 0.512 | 0.02 | -0.12 | 0.01 | -0.14 | 55 |
| long AR0>=+4% | OOS 2022+ | 20 | 404 | 0.87 | 0.77 | 0.52 | 2.26 | 1.1 | 2.6 | 1.16 | 53 |
| long AR0>=+4% | OOS 2022+ | 60 | 398 | 0.631 | 0.531 | 0.5 | 0.94 | 1.27 | 0.76 | 1.56 | 52 |
| short AR0<=-4% | OOS 2022+ | 20 | 384 | 0.127 | 0.027 | 0.539 | 0.31 | -0.01 | 0.27 | -0.01 | 57 |
| short AR0<=-4% | OOS 2022+ | 60 | 377 | -0.646 | -0.746 | 0.525 | -0.79 | -0.5 | -0.67 | -0.56 | 55 |
| baseline unsigned (survivorship) | OOS 2022+ | 20 | 1790 | 0.302 | 0.202 | 0.491 | 1.76 | 1.28 | 1.16 | 1.21 | 57 |
| baseline unsigned (survivorship) | OOS 2022+ | 60 | 1765 | 0.473 | 0.373 | 0.483 | 1.46 | 2.06 | 1.07 | 1.97 | 56 |
| all | 2025-2026 | 20 | 657 | 0.371 | 0.271 | 0.525 | 1.1 | 0.25 | 0.94 | 0.24 | 21 |
| all | 2025-2026 | 60 | 632 | -0.971 | -1.071 | 0.521 | -1.45 | -1.48 | -1.12 | -1.26 | 20 |
| |AR0|>=4% | 2025-2026 | 20 | 309 | 0.187 | 0.087 | 0.498 | 0.35 | -0.47 | 0.31 | -0.49 | 21 |
| |AR0|>=4% | 2025-2026 | 60 | 296 | -2.139 | -2.239 | 0.483 | -2.12 | -0.15 | -1.36 | -0.2 | 19 |
| long AR0>=+4% | 2025-2026 | 20 | 146 | 0.599 | 0.499 | 0.486 | 0.73 | 0.47 | 0.79 | 0.5 | 20 |
| long AR0>=+4% | 2025-2026 | 60 | 140 | -1.464 | -1.564 | 0.45 | -1.07 | 0.82 | -0.76 | 1.05 | 19 |
| short AR0<=-4% | 2025-2026 | 20 | 163 | -0.182 | -0.282 | 0.509 | -0.25 | -0.22 | -0.2 | -0.22 | 21 |
| short AR0<=-4% | 2025-2026 | 60 | 156 | -2.745 | -2.845 | 0.513 | -1.86 | -0.31 | -1.59 | -0.44 | 19 |
| baseline unsigned (survivorship) | 2025-2026 | 20 | 657 | 0.236 | 0.136 | 0.484 | 0.7 | 0.31 | 0.46 | 0.28 | 21 |
| baseline unsigned (survivorship) | 2025-2026 | 60 | 632 | 0.698 | 0.598 | 0.472 | 1.04 | 2.14 | 0.82 | 2.68 | 20 |
| all | last 4 qtrs (2025-10..2026-09) | 20 | 373 | 0.2 | 0.1 | 0.512 | 0.42 | -0.38 | 0.41 | -0.43 | 12 |
| all | last 4 qtrs (2025-10..2026-09) | 60 | 348 | -1.883 | -1.983 | 0.494 | -2.0 | -1.68 | -1.64 | -1.72 | 11 |
| |AR0|>=4% | last 4 qtrs (2025-10..2026-09) | 20 | 186 | 0.049 | -0.051 | 0.484 | 0.07 | -0.76 | 0.06 | -0.85 | 12 |
| |AR0|>=4% | last 4 qtrs (2025-10..2026-09) | 60 | 173 | -2.701 | -2.801 | 0.468 | -1.99 | -0.05 | -1.14 | -0.06 | 10 |
| long AR0>=+4% | last 4 qtrs (2025-10..2026-09) | 20 | 100 | 0.28 | 0.18 | 0.44 | 0.25 | 0.64 | 0.33 | 0.69 | 11 |
| long AR0>=+4% | last 4 qtrs (2025-10..2026-09) | 60 | 94 | -2.125 | -2.225 | 0.426 | -1.2 | 0.76 | -0.78 | 0.97 | 10 |
| short AR0<=-4% | last 4 qtrs (2025-10..2026-09) | 20 | 86 | -0.219 | -0.319 | 0.535 | -0.22 | -0.78 | -0.19 | -0.85 | 12 |
| short AR0<=-4% | last 4 qtrs (2025-10..2026-09) | 60 | 79 | -3.386 | -3.486 | 0.519 | -1.61 | -0.7 | -1.37 | -1.23 | 10 |
| baseline unsigned (survivorship) | last 4 qtrs (2025-10..2026-09) | 20 | 373 | 0.082 | -0.018 | 0.461 | 0.17 | 0.58 | 0.13 | 0.5 | 12 |
| baseline unsigned (survivorship) | last 4 qtrs (2025-10..2026-09) | 60 | 348 | 0.921 | 0.821 | 0.48 | 0.97 | 1.96 | 0.81 | 4.13 | 11 |
**Reading:**
- There is a small 20-day continuation over the full sample: +0.33%, roughly the same size as the unsigned survivorship drift.
- There is no reliable 60-day effect.
- Large reactions (|AR0| ≥ 4%):
  - +0.68% at 20d over the full sample; OOS 2022+ +0.51% (month-mean t 0.05).
  - Long side (AR0 ≥ +4%): +1.54% at 60d over the full sample (NW t 2.85), but OOS +0.63% (t 0.76–1.56).
  - Short side (AR0 ≤ −4%): −0.92% at 60d (reversal) over the full sample (t −1.3 to −1.75); OOS −0.65% (t −0.5 to −0.8).
- **Conclusion:** the sentiment researcher's qualitative conclusion holds. Large-cap earnings drift is weak or absent recently, and shorting big negative reactions has not paid. This agrees with my bracket backtest, where the PEAD short legs lose in every period.

## E4. Trials and significance
- Their `results.json` reports **192 test cells with a t-stat**, excluding the unsigned baselines:
  - 11 subsets × 6 windows (+1/+2 start, 20/60d, beta-adjusted) × up to 7 period cuts;
  - thresholds 4%/5%/10%;
  - signal EAR vs CAR(−1,+1);
  - surprise variants.
- 26 cells have |t| ≥ 1.96, versus ~9.6 expected by chance if the cells were independent. They are not independent, so the excess is overstated.
- The max |t| is 4.95 (Q5−Q1, 2023–24, 60d), and that test has the quintile look-ahead.
- The Bonferroni two-sided 5% critical value for 192 tests is **|t| = 3.65**; E[max |t|] under the null is ≈ 3.24.
- After multiplicity adjustment, **none of the headline numbers is significant in either direction**:
  - ALL 20d: p 0.005 on the event t, Šidák-adjusted 0.64.
  - The "last 4 qtrs 60d reversal" (p 0.054) adjusts to p = 1.
- **Net:** the evidence supports "no demonstrable large-cap PEAD", not "PEAD has reversed". The −1.64% 60d reversal is a post-hoc sub-period result and should not drive positioning on its own.
