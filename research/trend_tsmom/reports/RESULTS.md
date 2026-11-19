# Cross-asset trend sleeve (TSMOM, ETFs only) replication: RESULTS

**Owner:** the macro strategist · **Run:** Fri 30 Oct 2026 · **Status:** replicated, awaiting validation (the review). Research only: no orders and no broker calls.
**Papers:**
- `tsmom-moskowitz-ooi-pedersen-2012`: 12m sign, 40% vol per asset
- `trend-century-hurst-ooi-pedersen-2017`: 1/3/12 blend, 10% book vol

**Scope note:** crypto (BTC/ETH) was excluded by desk decision on 30 Oct 2026. This sleeve is ETFs only.
**Code:** `$QR_DESK_DIR/research/replications/trend-sleeve/`
- `tsmom/data.py`, `tsmom/engine.py`, `tsmom/stats.py`, `run.py`
- Rerun with `.venv/bin/python run.py`
- Outputs go to `outputs/`. The full tables are in `outputs/tables.md`, plus CSVs and `meta.json`.

## TL;DR
- **Gross: the signal replicates qualitatively.** The 12-month TSMOM baseline on 23 ETFs earns **6.8%/yr gross excess at 11.2% vol (Sharpe 0.61, t = 1.90)**.
  - Correlation to SPY is about zero: +0.04 daily, −0.16 monthly.
  - Monthly skew is positive (+0.94), and 2022 was strong (+25.7%).
  - This is weaker than the >1.0 Sharpe MOP report for 1985–2009, but consistent with the post-2010 decay in the literature: Hurst et al. report a net Sharpe of 0.41 for 2010–16, and the SG Trend index had a Sharpe of 0.05 for 2010–18.
- **Net of the TCA owner's cost model (base case): 2.3%/yr, vol 11.3%, Sharpe 0.20, t = 0.63, max drawdown −25.6%.**
  - Costs plus borrow come to **4.5%/yr**, on **15.5× annual one-way turnover** at an average of 26 bps one-way.
  - The net result is **not statistically different from zero**. The TCA owner's flag is **WARN**: costs exceed 50% of gross, and the result turns negative at 2× costs.
- **Implementable variant** (gross ≤ 2×, long/flat in ETFs that are not shortable/ETB today): net **1.8%/yr, vol 7.5%, Sharpe 0.24, t = 0.75, max drawdown −18.2%**. TCA owner flag: WARN.
- **Robustness verdict: NOT robust net of costs.**
  - Only the 12m/monthly specs stay positive at base costs (baseline, sizing variants, implementable).
  - Every 1/3/6m lookback, the Hurst 1/3/12 blend and every weekly-rebalance variant **FAIL** net, at −2% to −30%/yr.
  - Gross, all 19 variants are positive (Sharpe 0.11–0.66). So the trend is there; the problem is costs and turnover.
  - Against 19 trials, the deflated Sharpe of the *gross* baseline is 0.82, below the 0.95 bar. The net DSR is about 0.
- **The cost assumptions drive the conclusion.**
  - With the TCA owner's MOC venue (fill at the official close, which our timing allows), net rises to 4.8%, Sharpe 0.43 (PASS).
  - The gap comes from **default L3/L4 spread assumptions** of about 45–65 bps one-way for the FX ETFs (FXE/FXB/FXC/FXA/UUP/FXY) and DBA/DBC.
  - It also comes from **SHY**: its vol is about 1.5%, so its average |weight| is about 1.0× NAV and it churns 4.8× a year.
  - Measured spreads for these names are the most valuable next input.

## 1. Data used (real data on disk only; nothing simulated)
| Item | Detail |
|---|---|
| ETF universe (card, pre-specified) | **Equity:** SPY QQQ IWM EFA EWJ EWG EWU EEM · **Rates:** SHY IEF TLT · **Commodity:** GLD SLV USO UNG DBA DBC · **FX:** UUP FXE FXY FXB FXA FXC (23 ETFs) |
| Missing from card | **BWX, CPER** (not in the bar store) |
| ETF prices | `$QR_DATA_DIR/bars/daily/total_return/daily_total_return.parquet` → `tr_index_best`. This is Alpaca `adjustment=all` close-to-close (split and dividend adjusted), SIP feed, **2016-01-04 → 2026-10-28** (2,721 sessions). The 20 new ETFs landed in raw/adjusted/TR at about 01:16–01:19 SGT today; this run uses that build. |
| Extended universe (robustness) | adds EWZ FXI INDA EWY EWT EWA EWC AGG BND TIP LQD HYG |
| Risk-free | Ken French daily RF (`data/factors/ken_french/ff3_daily.parquet`). Last date is 2026-09-30, **forward-filled through 28 Oct**. KF daily RF is rounded to 0.01%/day. |
| Shortability | `data/assets/snapshots/assets_2026-10-29.parquet`. This is today's snapshot only, not point-in-time. **Not shortable/ETB today: USO, FXE, FXB** (also BWX and EWA). |
| Liquidity inputs | Raw close × 20-day average raw volume, lagged 1 day, sets the TCA owner's bucket. Realised σ is 20-day, also lagged. |

**Data caveats:**
- The desk corporate-actions file has **no dividend or split records for the 20 newly added ETFs**.
  - Their total return therefore relies only on Alpaca's adjustment, with no independent desk check.
  - The data owner's TR validation flags unrecorded splits on 2016-11-07 (EWJ/EWU/EWT) and 2020-04-29 (USO).
- USO, UNG, DBC and DBA embed futures roll. That roll is real, tradable P&L.

## 2. Cost model used
- **The TCA owner's v1.1 model:** `src/quant_research/backtest/costs/cost_model.py`, `trade_cost`.
  - Fees: SEC, TAF and CAT.
  - Half-spread: no measured per-name spreads, so **bucket defaults** are used.
  - Impact: square-root model with k = 1.0, using lagged σ and ADV.
  - A paper-to-live buffer.
- Base venue is `continuous`. Book size is **$1M NAV** (my assumption).
- **Borrow: 25 bps/yr** on short market value (the TCA owner's `BORROW_RATE_ETB_DEFAULT`), 360-day basis, accrued over calendar days.
- **Not modelled:**
  - Margin interest above RF when gross leverage exceeds 1. The baseline averages 3.2× gross, so this is material on Alpaca.
  - Interest on short proceeds.
  - Historical borrow status.

## 3. Method (MOP 2012 / HOP 2017)
- **Signal:** sign of the trailing cumulative excess return over 12 months (252 sessions). The blend variant uses the mean of the 1/3/12-month signs.
- **Volatility:** EWMA variance of daily excess returns, centre of mass 60 days (as in the paper), annualised ×252.
- **Sizing:**
  - Each asset's position is signal × 40% / σ_i, equal-weighted across live assets (MOP).
  - The **baseline** then scales the whole book to a **10% ex-ante vol**, using a 252-day sample covariance (HOP-style).
  - The `mop_40pct_unscaled` variant is pure MOP, with no book-level scaling.
- **Timing:**
  - The signal uses data through the close of the last session of the month (or week).
  - The fill is at the **next session's close** (lag 1).
  - Weights drift between rebalances.
  - P&L is the excess return over RF.
- **Evaluation window:** all variants are measured over the same window, **2017-02-01 → 2026-10-28 (9.7 years)**.
- **Pre-registration:**
  - The variant grid was written into `run.py` before I saw any results, and **all of it is reported**.
  - The headline is the paper's own spec (12m, monthly), chosen because it is the paper's spec.
  - It also happens to rank best gross among the lookbacks, which matches MOP.

## 4. Headline (baseline: 12m, monthly, 10% book vol, 23-ETF card universe)
| | Gross | Net (base costs) |
|---|---|---|
| Ann. excess return | 6.8% | 2.3% |
| Ann. vol | 11.2% | 11.3% |
| Sharpe (t-stat) | 0.61 (1.90) | 0.20 (0.63); Sharpe SE ≈ 0.32 |
| Max drawdown | | −25.6% |
| Annual one-way turnover | 15.5× NAV | average cost 26.3 bps one-way; break-even 43.8 bps |
| Cost + borrow drag | | 4.5%/yr |
| Avg / max gross leverage | 3.19× / 5.92× | |
| Corr to SPY (daily / monthly) | | +0.04 / −0.16 |
| SPY's worst-decile months (n = 12, SPY avg −7.7%) | | sleeve avg **+2.1%**, hit rate 50% |
| Benchmark: long-only, same vol-scaling (signal = +1) | gross 1.3% | net 0.7%, Sharpe 0.06, drawdown −40%, corr to SPY 0.74 |
| Benchmark: SPY excess TR | | 13.2%, Sharpe 0.74, drawdown −34% |

Against the same risk-parity book held long-only, the trend timing adds about **+5.5%/yr gross**.

## 5. Sensitivity / robustness grid (19 trials on the common window, plus cost variants on the baseline)
| variant                                  | gross_ret   |   gross_sharpe | net_ret   | net_vol   |   net_sharpe |   net_t | net_maxdd   |   turnover_x |   avg_cost_bps_1way |   breakeven_bps_1way |   avg_gross_lev |   corr_spy_d | tomas_flag   |
|:-----------------------------------------|:------------|---------------:|:----------|:----------|-------------:|--------:|:------------|-------------:|--------------------:|---------------------:|----------------:|-------------:|:-------------|
| BASELINE = lb12_M (pvt10, card universe) | 6.8%        |           0.61 | 2.3%      | 11.3%     |         0.2  |    0.63 | -25.6%      |         15.5 |                26.3 |                 43.8 |            3.19 |         0.04 | WARN         |
| lb1_M                                    | 1.5%        |           0.14 | -11.5%    | 11.9%     |        -0.97 |   -3.02 | -71.1%      |         46.1 |                27.4 |                  3.3 |            3.3  |        -0.13 | FAIL         |
| lb1_W                                    | 1.3%        |           0.11 | -29.7%    | 12.4%     |        -2.39 |   -7.45 | -94.9%      |        115.1 |                26.5 |                  1.1 |            3.31 |        -0.25 | FAIL         |
| lb3_M                                    | 5.1%        |           0.45 | -3.6%     | 11.8%     |        -0.31 |   -0.96 | -45.8%      |         29.9 |                27.7 |                 17.1 |            3.38 |        -0.17 | FAIL         |
| lb3_W                                    | 2.4%        |           0.21 | -17.5%    | 11.8%     |        -1.48 |   -4.61 | -83.7%      |         69.5 |                27.9 |                  3.4 |            3.36 |        -0.21 | FAIL         |
| lb6_M                                    | 4.8%        |           0.44 | -2.0%     | 11.2%     |        -0.18 |   -0.55 | -37.2%      |         22.5 |                28.3 |                 21.4 |            3.36 |         0.02 | FAIL         |
| lb6_W                                    | 4.1%        |           0.36 | -11.2%    | 11.7%     |        -0.95 |   -2.98 | -72.5%      |         54   |                27.6 |                  7.7 |            3.37 |        -0.14 | FAIL         |
| lb12_W                                   | 6.1%        |           0.54 | -3.4%     | 11.3%     |        -0.3  |   -0.95 | -41.3%      |         35.6 |                25.5 |                 17   |            3.23 |        -0.08 | FAIL         |
| lb1-3-12_M                               | 5.0%        |           0.44 | -3.9%     | 11.8%     |        -0.33 |   -1.04 | -49.0%      |         32.1 |                26.8 |                 15.7 |            2.97 |        -0.1  | FAIL         |
| lb1-3-12_W                               | 3.8%        |           0.33 | -18.1%    | 11.8%     |        -1.54 |   -4.79 | -84.2%      |         84.1 |                25.6 |                  4.5 |            2.98 |        -0.21 | FAIL         |
| mop_40pct_unscaled                       | 8.4%        |           0.49 | 2.9%      | 17.5%     |         0.17 |    0.52 | -36.5%      |         19   |                25.9 |                 44.4 |            4.83 |         0.01 | WARN         |
| class_balanced                           | 7.0%        |           0.64 | 1.8%      | 11.2%     |         0.16 |    0.49 | -25.2%      |         20.6 |                22.7 |                 34   |            4.21 |        -0.02 | WARN         |
| gross_cap_2x                             | 3.6%        |           0.49 | 1.5%      | 7.3%      |         0.21 |    0.66 | -18.7%      |          6.9 |                25.3 |                 51.5 |            1.95 |        -0.08 | WARN         |
| honour_shortable                         | 6.9%        |           0.61 | 2.7%      | 11.4%     |         0.24 |    0.74 | -23.8%      |         15.5 |                24.3 |                 44.3 |            3.08 |         0.06 | WARN         |
| implementable(cap2x+shortable)           | 3.7%        |           0.49 | 1.8%      | 7.5%      |         0.24 |    0.75 | -18.2%      |          6.9 |                23.6 |                 53   |            1.95 |        -0.05 | WARN         |
| implementable_blend_M                    | 2.2%        |           0.26 | -2.8%     | 8.5%      |        -0.33 |   -1.04 | -40.3%      |         19   |                25.2 |                 11.5 |            1.9  |        -0.15 | FAIL         |
| vol_com20                                | 6.5%        |           0.59 | 1.7%      | 11.1%     |         0.16 |    0.49 | -26.0%      |         16.7 |                25.9 |                 38.8 |            3.2  |         0.03 | WARN         |
| lag0(same-close fill)                    | 7.4%        |           0.66 | 2.9%      | 11.3%     |         0.26 |    0.81 | -23.8%      |         15.3 |                26.4 |                 48.3 |            3.19 |         0.04 | WARN         |
| extended_universe                        | 5.4%        |           0.49 | 1.3%      | 11.1%     |         0.12 |    0.37 | -32.2%      |         17.9 |                20.7 |                 30.3 |            3.22 |         0.02 | WARN         |
| costs_2x                                 | 6.8%        |           0.61 | -1.8%     | 11.7%     |        -0.15 |   -0.47 | -39.3%      |         15.5 |                52.6 |                 43.8 |            3.19 |         0.04 | FAIL         |
| venue_close(MOC)                         | 6.8%        |           0.61 | 4.8%      | 11.2%     |         0.43 |    1.34 | -19.7%      |         15.5 |                10.1 |                 43.8 |            3.19 |         0.04 | PASS         |
| impact_k0.5                              | 6.8%        |           0.61 | 2.6%      | 11.3%     |         0.23 |    0.72 | -24.7%      |         15.5 |                24.4 |                 43.8 |            3.19 |         0.04 | WARN         |
| nav_10m                                  | 6.8%        |           0.61 | 1.0%      | 11.5%     |         0.09 |    0.27 | -29.3%      |         15.5 |                34.7 |                 43.8 |            3.19 |         0.04 | WARN         |
| borrow_50bps                             | 6.8%        |           0.61 | 1.9%      | 11.3%     |         0.17 |    0.52 | -26.4%      |         15.5 |                26.3 |                 43.8 |            3.19 |         0.04 | WARN         |

**Grid key:**
- `pvt` = 10% book-vol target.
- `implementable` = gross cap of 2× plus long/flat for ETFs that are not shortable.
- `lag0` = fill at the signal close. This only works if the signal is computed before the 15:50 ET MOC cutoff on near-close prices, so it is optimistic.
- Flags follow the TCA owner's §6 rule: PASS = net > 0 at 2× costs and costs ≤ 50% of gross.

**Reading of the grid:**
1. **Gross:** all 19 variants are positive.
   - The 12m lookback is the strongest (Sharpe 0.54–0.66); the 1m is the weakest (0.11–0.14).
   - Monthly rebalancing beats weekly in every pair.
2. **Net:** turnover kills the fast signals.
   - The 1m lookback trades 46× a year (monthly rebalance) to 115× (weekly), against a break-even of 1–3 bps.
   - The Hurst 1/3/12 blend (their headline spec) fails on our ETF costs, at −3.9% net.
3. **Sizing:** these choices barely move net Sharpe.
   - Capping gross at 2× roughly halves both return and costs, so net Sharpe stays about the same: 0.21, or 0.24 with the shortability constraint.
   - The extended universe is *worse* (gross Sharpe 0.49).
   - Class-balanced weighting does not help net (0.16).
4. **Cost assumptions dominate the conclusion:**
   - MOC venue: net Sharpe 0.43.
   - 2× costs: −0.15.
   - $10M NAV: 0.09, because of impact on the thin FX ETFs. Capacity in this form is therefore limited.

## 6. Per-asset and per-class contributions (baseline, annualised, % of NAV)
| Class | Gross | Cost | Net (ex-borrow) | Turnover |
|---|---|---|---|---|
| Equity (8) | 2.6% | 0.3% | 2.3% | 2.6× |
| Commodity (6) | 2.1% | 0.5% | 1.6% | 1.8× |
| Rates (3) | 1.4% | 0.8% | 0.6% | 6.4× (SHY alone 4.8×) |
| FX (6) | 0.8% | **2.5%** | **−1.8%** | 4.7× |

- **Top gross contributors:**
  - SHY +0.9%, at about 1× NAV notional
  - QQQ +0.7%
  - EEM and DBC +0.6% each
  - FXY, UNG and EWJ +0.5% each
- **Negative gross contributors:** IWM −0.2%, UUP −0.2%, FXB and FXC −0.1% each.
- **FX is a net drag in this form:**
  - All six FX ETFs fall in the L4 cost bucket.
  - Four of the six are net-negative.
  - FXE and FXB are not shortable today.
- Full table: `outputs/per_asset_baseline.csv`.

## 7. Subperiods and calendar years
| Variant | 2017–19 net (SR) | 2020–22 net (SR) | 2023–26YTD net (SR) |
|---|---|---|---|
| Baseline | −1.2% (−0.11) | +6.7% (0.53) | +1.5% (0.14) |
| Implementable | −0.9% (−0.15) | +3.7% (0.40) | +2.4% (0.35) |
| Baseline, MOC venue | +0.9% (0.09) | +9.0% (0.71) | +4.5% (0.43) |
| Blend 1/3/12 M | −6.4% (−0.55) | +3.1% (0.23) | −7.6% (−0.75) |

**Baseline by calendar year:**

| Year | Gross | Net | SPY excess |
|---|---|---|---|
| 2017 | 10.3% | 5.5% | 19.6% |
| 2018 | −5.8% | −9.1% | −7.3% |
| 2019 | 2.5% | −1.1% | 27.9% |
| 2020 | 6.2% | −0.2% | 17.7% |
| 2021 | 1.1% | −2.7% | 28.6% |
| 2022 | 25.7% | 23.1% | −19.2% |
| 2023 | −4.2% | −8.1% | 20.0% |
| 2024 | 7.1% | −1.0% | 18.8% |
| 2025 | 10.4% | 5.0% | 12.0% |
| 2026 (to 28 Oct) | 11.9% | 8.7% | 11.1% |

- **Much of the full-sample return comes from 2022.**
- Correlation to SPY changes with the regime: +0.28 in 2017–19, −0.37 in 2020–22, +0.53 in 2023–26. The sleeve has been long equities through a bull market, so its diversification value depends on the regime.
- **Current baseline book (28 Oct close):** short duration (SHY/IEF/TLT), short EUR/GBP/CAD/JPY, long USD (UUP) and AUD, mostly long equities (short EWG) and long commodities (short UNG).

## 8. Multiple testing and sample honesty
- **The sample is short: 9.7 years.**
  - At annual Sharpes of about 0.2–0.6, a t-stat of 2 would need roughly 10–100+ years.
  - **No net variant is statistically significant.**
  - The best gross t is 2.06 (lag0); the baseline gross t is 1.90.
  - None clears the Harvey-Liu-Zhu (2016) hurdle of t > 3.
- **Deflated Sharpe (Bailey & López de Prado 2014), N = 19 trials:**
  - Gross baseline: DSR = **0.82** (SR0 = 0.31 annual). This is suggestive but below the 0.95 bar.
  - Net: DSR ≈ 0.0001. Costs swamp the fast variants, so the spread of Sharpes across trials is wide and SR0 = 1.42. Read this as "fails", not as a precise number.
  - The probabilistic Sharpe of the net baseline vs 0 is 0.74.
- **Avoiding cherry-picking:**
  - The headline is the paper's own spec, and all grid and cost rows are reported.
  - The best-looking net result (MOC venue) depends on a cost and venue assumption, not on the signal. It is a hypothesis for the TCA owner to verify, not a result.
  - The long-history evidence (MOP 1985–2009, HOP 1880–2016) remains the real prior. Our sample can only test consistency with it, and it is consistent on a gross basis.

## 9. Gaps / blockers
1. **History (the data owner):** the ETF store starts in 2016.
   - Most of these ETFs listed in 2002–2008 (SPY in 1993). A 2005+ backfill would roughly double the sample and include 2008.
   - An index or futures backfill is needed for a HOP-style long test.
   - BWX and CPER are missing (and FXF, if we want it).
2. **ETF corporate actions (the data owner):** there are no dividend or split records for the 20 new ETFs, so we cannot validate their total returns. We rely on Alpaca's adjusted closes.
3. **Costs (the TCA owner):**
   - Measured spreads for the L3/L4 ETFs: FXE, FXB, FXC, FXA, FXY, UUP, DBA, DBC, EWG, EWU and UNG. The conclusion flips between WARN/FAIL and PASS on this.
   - Validation of paper MOC fills.
   - The margin interest rate for gross leverage above 1×.
4. **Shortability:** the flags are today-only. USO, FXE and FXB are not shortable today, and historical borrow is unknown.
5. **Leverage:** the paper-faithful book runs about 3.2× gross (max 5.9×), because of the low-vol SHY and FX ETFs. On Alpaca's Reg T, a 2× cap binds, so the implementable version targets about 7.5% vol.
6. **Design questions for validation.** I did not tune these, to avoid in-sample fitting, and each would add trials that should be pre-registered with 
   - no-trade bands or smoothing of the vol updates to cut turnover
   - a per-asset notional cap (for SHY)
   - dropping the FX ETFs, or using FX futures (not available on Alpaca)
7. **Carry (second priority, NOT started).** Data needs, per the card:
   - G10 3m rates
   - ETF/index dividend yields
   - the UST curve
   - front and second commodity futures prices

## 10. Files
- **Code:**
  - `tsmom/data.py`: loaders. Source priority is TR → adjusted → raw, and the source used is recorded per symbol.
  - `tsmom/engine.py`: the backtest (signal, EWMA vol, sizing, drift, lag, TCA owner cost hook, borrow).
  - `tsmom/stats.py`: performance stats, Sharpe SE and deflated Sharpe.
  - `run.py`: runs the pre-listed grid and writes to `outputs/`.
- **Outputs (`outputs/`):**
  - `tables.md`: all tables.
  - Grid and benchmarks: `grid.csv`, `cost_variants.csv`, `benchmarks.csv`.
  - Breakdowns: `per_asset_baseline.csv`, `subperiods.csv`, `calendar_years_baseline.csv`.
  - Daily series: `baseline_daily.csv`, `baseline_weights.csv`, `implementable_daily.csv`.
  - `meta.json`: sources, data dates and DSR.
- **Environment:** `requirements.lock.txt`, plus a local venv in `.venv/` (pandas 3.1, pyarrow 26, scipy).
