# PEAD-gap, trend-filtered, long only: survivorship-aware PIT re-test

Run: Fri 30 Oct 2026, finished about 01:45 SGT (UTC+8). Read-only. No orders were placed. Every figure below comes from the scripts in this folder.
Regenerate everything with `$QR_DATA_DIR/.venv/bin/python run_all.py && .../python report_extra.py && .../python align_check.py`. The venv is used read-only.
Data snapshot: `$QR_DATA_DIR` with bars `updated_at_utc` 2026-10-29T17:20Z (01:20 SGT 30 Oct), last session 2026-10-28, FF factors through 2026-09-30.

## What was run
- **Prices.** `bars/daily/total_return` `open/high/low/close_adj`. I checked that `close_adj` is exactly proportional to `tr_index_best` for all 774 symbols (worst max/min ratio 1.0000000000000162), so close-to-close = `ret_total_best`.
- **Volume.** SIP `volume_adj` (split-adjusted consolidated). No IEX file is read.
- **Rule** (identical to `../backtest.py` PEAD_trend_L):
  - Signal at close t: o_t/c_{t-1}-1 > 4%, v_t > 1.8x mean(v_{t-20..t-1}), and close > SMA50 and SMA200.
  - Entry at the t+1 open. Stop = E - 2xATR14(<=t). TP = E + 2R. Max hold 60 sessions, exiting at the close.
  - Stop wins if both are touched in one bar. A gap through a level fills at the open. One open position per symbol.
  - First signal day is 2017-01-03 (warm-up from 2016 bars).
- **Universe.** S&P 500 member on the signal date, from `sp500_membership.parquet` [start, end). Run 5 uses the old 117 symbols (MMC maps to MRSH, which is the same entity) with no PIT filter, so its 22 ETFs stay in, as before.
- **Delistings.**
  - A position still open at a name's last bar exits at the last close × (1 + `terminal_return`) from `delisting_returns`.
  - When the terminal return is null, it is taken as the last close. Sensitivity: SIVB/FRC/SBNY or a last close under $5 is set to -100%.
  - 11 R1 trades hit a delisting: 7 matched deals, 4 null (WFM, CSRA, COL, ABMD). None was a failure, so the -100% sensitivity leaves the results unchanged.
- **Costs** (TCA owner v1.1, `trade_cost`):
  - $10k clip at the raw price. 20-day SIP ADV and sigma are lagged to the signal close. Spreads are the bucket defaults, because the store has no quotes.
  - Entry = `venue="open"` (MOO). Stop/TP exits = `continuous` (crossing, conservative for TP). Gap exits = `open`. Time and delisting exits = `close`.
  - 2x = 2 × total. The flat 5 bp/side of the prior study is also reported (`summary.csv`, costs=flat5).
- **IS/OOS.**
  - IS = signal date <= 2021-12-31. OOS = signal date >= 2022-01-03. Each period's daily curve contains only that period's trades.
  - Nothing was fitted. Because no IS trade's P&L enters the OOS curve, the STANDARD §3 embargo is met by construction.
- **Statistics.**
  - Sharpe = daily R-unit P&L (equal 1R per trade, additive, marked to close), annualised over all sessions.
  - Beta = R per 1% SPY total-return move. FF alpha = Newey-West(10) t on daily P&L regressed on Mkt-RF, SMB, HML and Mom.

### Earnings alignment (`align_check.csv`, no returns used)
| class (source) | n | median abs gap on day d / d+1 (bp) | share abs gap>4% on d / d+1 |
|---|---|---|---|
| BMO (EDGAR) | 12,665 | 209.3 / 54.1 | 0.269 / 0.009 |
| AMC (EDGAR) | 11,334 | 48.8 / 254.4 | 0.019 / 0.348 |
| DURING_MKT (EDGAR) | 840 | 140.5 / 50.6 | 0.187 / 0.014 |
| UNKNOWN (Nasdaq-only) | 1,316 | 74.2 / 104.4 | 0.086 / 0.185 |

`first_tradable_session` is consistent with the XNYS opens for every past event. But DURING_MKT 8-Ks behave like BMO: the press release precedes the 8-K, so the news hits day d, not the d+1 the store assigns.
- **Run 2 ("aligned")** uses the first tradable session, plus day d for DURING_MKT/UNKNOWN. This is PIT at the close of d.
- **R2s ("strict")** uses the store's session only. I logged it as a trial.
- **Run 3 (non-earnings).** No event's announce day or first tradable session within ±2 sessions. The symbol must also have PIT earnings coverage (an event in the prior 135 calendar days).

## Main table (TCA owner costs 1x unless stated)
| Run | Period | Trades | Hit | Exp R (1x) | Sharpe 1x | Sharpe 2x | MaxDD R (1x) | Beta (R per 1% SPY) | FF4 alpha t (NW) |
|---|---|---|---|---|---|---|---|---|---|
| 1 Prior rule, PIT S&P 500 | IS | 1165 | 0.472 | +0.262 | 0.78 | 0.64 | -65.0 | 1.749 | 1.49 |
| 1 Prior rule, PIT S&P 500 | OOS | 1298 | 0.410 | +0.115 | 0.49 | 0.33 | -89.0 | 2.099 | 0.47 |
| 2 Earnings-gap only | IS | 681 | 0.464 | +0.275 | 1.01 | 0.83 | -44.9 | 1.04 | 1.59 |
| 2 Earnings-gap only | OOS | 911 | 0.413 | +0.112 | 0.44 | 0.28 | -58.6 | 1.587 | 0.21 |
| 3 Non-earnings gap | IS | 286 | 0.510 | +0.343 | 0.45 | 0.40 | -43.7 | 0.485 | 0.93 |
| 3 Non-earnings gap | OOS | 324 | 0.389 | +0.124 | 0.35 | 0.27 | -47.6 | 0.429 | 0.59 |
| 4 Benchmark: all >50/200dma, PIT, every 5th day | IS | 65096 | 0.421 | +0.152 | 0.73 | 0.38 | -3795.7 | 76.923 | 0.9 |
| 4 Benchmark: all >50/200dma, PIT, every 5th day | OOS | 51954 | 0.355 | -0.027 | -0.15 | -0.45 | -4781.1 | 68.404 | -1.85 |
| 5 Old 117-name universe | IS | 315 | 0.470 | +0.317 | 0.97 | 0.88 | -19.1 | 0.511 | 1.58 |
| 5 Old 117-name universe | OOS | 289 | 0.481 | +0.375 | 1.27 | 1.20 | -18.5 | 0.471 | 2.47 |

- **Beta is in R units and scales with the number of concurrent positions.** Average concurrent positions: R1 23.1, R2 14.9, R3 5.4, R5 5.1. Per average position, OOS beta is 0.091 / 0.107 / 0.079 / 0.092. OOS correlation to SPY is R1 0.575, R2 0.570, R3 0.317, R5 0.462.
- **Reproduction check.** Run 5 at flat 5 bp gives 315 IS / 289 OOS trades, expectancy +0.325 / +0.379 R and hit 0.470 / 0.481. These match the prior study exactly.
  - Its OOS Sharpe is 1.285 against the prior 1.19. The gap comes only from curve attribution: the prior OOS curve also carried late-2021 trades.
- **Full-history NW t of mean daily P&L** (1x):
  - R1 2.29, R2 2.18, R3 1.52, R5 3.55.
  - Bars: 3.0 for a new signal, 2.8 for a published-anomaly replication (R2).

## Robustness and multiple testing
| Item | R1 PIT all | R2 earnings | R3 non-earn | R5 U117 |
|---|---|---|---|---|
| Date-matched excess vs eligible >50/200 names, IS (t, date-clustered) | +0.027R (0.51) | +0.076R (0.76) | +0.034R (1.01) | +0.011R (0.12) |
| same, OOS | +0.066R (3.27) | +0.055R (2.51) | +0.073R (1.35) | +0.253R (3.79) |
| Random same-date same-exit entries (200 reps), p(Sharpe), IS / OOS | 0.57 / 0.05 | 0.135 / 0.17 | 0.675 / 0.26 | 0.46 / 0.00 |
| DSR, N=95 cumulative, SR0 = 0.807 ann (1x / 2x) | 0.245 / 0.148 | 0.210 / 0.124 | 0.162 / 0.121 | 0.846 / 0.802 |
| ±20% sweep: OOS Sharpe range, one-at-a-time (6) | 0.159–0.511 | 0.224–0.482 | -0.066–0.422 | not swept |
| fails "≥50% of centre", one-at-a-time / joint (of 26) | 1 / 9 | 0 / 4 | 1 / 10 (and <0) | – |
| Year share of total P&L, max | 2020 27.8% | 2024 29.1% | **2020 55.5%** | 2024 27.1% |
| Worst regime Sharpe (SPY<200 / realised-vol proxy >25%) | OOS SPY<200 -0.04 | OOS RV>25% 0.16 | **IS SPY<200 -1.98; OOS RV>25% -0.56** | OOS SPY<200 0.35 |
| Break-even cost bp/side (× assumed avg) | 62.2 (5.6x) | 58.9 (5.2x) | 80.7 (8.0x) | 96.7 (15.1x) |
| Avg assumed cost bp/side; trades/yr; avg hold | 11.18; 250.9; 23.2d | 11.32; 162.2; 23.1d | 10.14; 62.1; 21.9d | 6.41; 61.5; 20.7d |

- **The benchmark is not a candidate rule and is not counted in N.** Under PIT, buying anything above its 50/200dma with these exits earns +0.152R IS and -0.027R OOS (1x). In the survivor 117 it earns +0.263R / +0.069R.
- **PBO (CSCV, S=16, 12,870 splits, `pbo.json`):**
  - All 95 logged trials: **0.085**.
  - The 83 new trials only: 0.054.
  - The 81-variant PIT long-only sweep family: **0.423**.
  - The all-trials figure is flattered: it includes the prior short legs, which lose in every period, so "pick the best IS" easily beats the median OOS. The like-for-like configuration choice is the 0.42 figure.
- **Trial count.** The 12 prior trials plus 81 sweep cells (27 each for R1/R2/R3, centres included) plus R5 plus R2s gives **N = 95**. Trials are listed in `trial_log.csv`; the T × N daily matrix is `daily_pnl_matrix_all_trials.csv`.
  - Not counted: the cost settings, the delisting sensitivity, the benchmarks and the in/out-of-117 decomposition below.
- **Capacity.** The 5th-percentile traded ADV is $82.7M (R1), so 1% of ADV is about $827k per trade. Bucket mix for R1 is L1 403, L2 1,322, L3 715, L4 23.
- **VIX.** VIX is not in the store. The regime rows use SPY 21-day realised volatility as a labelled proxy.

### Survivorship effect, measured directly
- Same rule, same data. The 117-name universe gives OOS Sharpe 1.27 and +0.375R. PIT S&P 500 gives 0.49 and +0.115R.
- Inside R1, the 275 OOS trades in the 117 names earned **+0.365R**, and the other 1,023 earned **+0.048R**. In IS the two groups were similar (+0.247R vs +0.267R).
- The prior study's OOS "edge" is therefore concentrated in names that were chosen in 2026 for having become mega-caps. That is look-ahead through universe selection, not signal.

### By year (Sharpe of daily P&L, 1x)
| Run | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|
| R1 | 2.22 | -0.57 | 0.90 | 1.00 | 0.79 | -1.57 | 0.35 | 0.85 | 1.07 | 0.60 |
| R2 | 2.03 | -0.19 | 0.93 | 1.38 | 1.38 | -1.47 | 0.34 | 1.23 | 0.43 | 0.21 |
| R3 | 2.22 | -1.18 | 0.93 | 0.93 | 0.14 | -0.85 | 0.12 | -0.17 | 1.67 | 0.92 |
| R5 | 1.19 | 0.01 | 1.73 | 1.71 | 0.44 | -1.43 | 0.77 | 2.13 | 2.41 | 0.12 |

Trade counts and expectancy by year are in `by_year.csv`. All regime cuts (IS/OOS/FULL) are in `by_regime.csv`.

## Verdicts (STANDARD v1.0)
- **Run 1, prior rule on PIT S&P 500: FAIL.**
  - OOS Sharpe 0.49 at 1x and 0.33 at 2x, below the 0.5 bar.
  - DSR 0.245 at N=95, NW t 2.29 < 3.0, and FF4 alpha t 0.47 OOS / 1.49 IS. There is no IS edge over same-date eligible names (t 0.51).
  - Sweep: 1 of 6 one-at-a-time and 9 of 26 joint cells fall below 50% of the centre. Sweep-family PBO is 0.42.
  - Positive: it survives 2x costs (Sharpe > 0), break-even is 5.6x the assumed cost, no year is above 40% of P&L, and no regime is below -0.5.
- **Run 2, earnings-gap only (aligned): FAIL.**
  - OOS Sharpe 0.44 / 0.28 at 2x. DSR 0.210. NW t 2.18 < 2.8, the replication bar.
  - FF4 alpha t 0.21 OOS. Random same-date entries match its OOS Sharpe with p = 0.17.
  - The strict alignment (R2s) is no better: OOS 0.435, DSR 0.207.
- **Run 3, non-earnings gap: FAIL.**
  - OOS Sharpe 0.35, DSR 0.162, NW t 1.52.
  - The sweep goes negative: ATR 1.6 gives -0.07 OOS, and the joint minimum is -0.30.
  - 2020 is 55.5% of P&L, above the 40% cap. Regime Sharpe is -1.98 IS when SPY < 200dma (11 trades) and -0.56 OOS when RV > 25%.
- **Benchmark (run 4):** not a candidate, so no verdict. As a strategy it would FAIL: OOS Sharpe -0.15 at 1x.
- **Run 5, old 117-name universe: FAIL.**
  - §2 bars hand-picked "today's mega-caps" universes outright; the survivorship haircut is not available for this universe type.
  - Even with a 20% haircut (1.27 → about 1.02), DSR is 0.846 < 0.95. FF4 alpha t is 2.47 OOS.
  - It has no IS edge over same-date eligible names (t 0.12) and no IS edge vs random entries (p 0.46).
  - The decomposition above shows its OOS edge is a universe-selection artefact.
- **Not done / open artefacts:** VIX regime (proxy only), correlation to the existing book (no book history in the store), and quote-based spreads (bucket defaults). The 2022+ OOS was already viewed when the prior study chose this variant, so it is not "never touched" (§3); the cumulative N accounts for this only partially.

## Data problems found in `$QR_DATA_DIR`
1. **DURING_MKT timing is misaligned.** For 853 EDGAR events (840 testable), `first_tradable_session` = d+1, but the price reaction is on d (18.7% of events gap more than 4% on d vs 1.4% on d+1). The press release precedes the 8-K. Fix: for DURING_MKT, treat the gap day as d, or use the press-release time.
2. **Earnings coverage of former members is thin.** 105 of 220 former members have any event. Member-day coverage is 84.6% in 2017, rising to 99.3% in 2026. Non-earnings classification is therefore restricted to covered symbol-dates.
3. **PIT members with no bars before their first bar** (current ticker mapped onto predecessor history):
   - SKYD 2,412 member-days. Paramount/ViacomCBS history is absent: membership start is unknown, and bars start 2025-08-07.
   - BBWI 1,405 (L Brands, bars from 2021-08-03); VTRS 1,225 (Mylan, from 2020-11-12); LIN 713 (Praxair, from 2018-10-31); APTV 474 (Delphi, from 2017-11-17); FTI 261.
   - AA 192 (the post-2016 AA bars are the new Alcoa, while the index member was Alcoa Inc/Arconic); SNDK 91; UAA 66; Q 55.
   - Separately, 104 member-days across 49 symbols fall after the last bar. That is the usual lag between delisting and index removal.
4. **`delisting_returns.parquet` has 70 of 120 names unmatched** (47 matched, 3 missing acquirer price; the README agrees). Their terminal returns are null, and most are pre-2020 deals because Alpaca merger history starts 2020-04. So 4 R1 trades (WFM, CSRA, COL, ABMD) exit at the last close instead of the deal value.
5. **Membership anomalies.** `sp500_membership_anomalies` has 26 rows. The SNDK case (old SanDisk membership interval vs new-company bars from 2025-02-13) shows that ticker reuse still leaks into membership.
6. **No VIX and no quotes in the store**, so the STANDARD §7 VIX regime and measured spreads are not possible.
7. **Minor.** The old 117 list contains MMC, which is now MRSH in the store. The TR bar file has 980 zero-volume rows in 13 symbols (DOW 396, SMCI 349, EXE 156, ...). I checked: no trade had a zero-volume row in the 45 days before its signal. Of the 853 DURING_MKT events, 840 have bars on both d and d+1 and are in the alignment table.

## Files
`core.py`, `run_all.py`, `report_extra.py`, `align_check.py`; `summary.csv` (all runs × IS/OOS/FULL × 1x/2x/flat5, with FF betas); `by_year.csv`; `by_regime.csv`; `benchmark_date_matched.csv`; `benchmark_random_matched.csv`; `sweep.csv`; `sweep_stability.csv`; `trial_log.csv`; `daily_pnl_matrix_all_trials.csv` (equity curve = cumsum); `dsr.csv`; `pbo.json`; `costs_capacity.csv`; `trades_main.csv`; `data_issues.json`; `extra_diagnostics.json`; `align_check.csv`; `run_stdout.txt`.
