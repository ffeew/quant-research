# Stat-arb research — v1, research only

Owner: the stat-arb researcher (Stat Arb). Last run: 2026-10-30. **Paper/research only. Nothing here places or changes orders or positions.**
Judged against `$QR_DESK_DIR/validation/STANDARD.md` v1.0, not against "holdout t > 2".

## Bottom line
**All 48 v1 trials FAIL the desk standard.** No variant reaches holdout net Sharpe > 0.5, and none stays above 0 at 2× costs. None has t ≥ 2.8/3.0 or DSR ≥ 0.95, and none has break-even cost ≥ 2× the assumed cost. The data-issue sensitivity checks change no verdict.

The best result is AL sector-ETF s-score with wider bands plus a no-trade buffer (`AL_ETF_B2_1.75/0.00/0.00_buf0.5`).
- Gross edge is about 5.5 bps per $ traded, against about 10.6 bps of cost.
- Holdout gross Sharpe is 0.46; holdout net Sharpe is −0.56 on the validation cost floor and −0.35 on the TCA owner's base.
- It is research-only: it still has to clear t-stat and costs.

## One command to regenerate everything
```
cd code
../.venv/bin/python run_v1.py                         # base: 24 pre-registered variants x 2 executions = 48 trials
../.venv/bin/python run_v1.py --mode complete         # sensitivity: drop reused/re-added/gap tickers
../.venv/bin/python run_v1.py --mode delist_stress    # sensitivity: -30% on non-merger delistings
../.venv/bin/python validate_v1.py v1 && ../.venv/bin/python validate_v1.py v1_complete && ../.venv/bin/python validate_v1.py v1_delist_stress
../.venv/bin/python compare_modes.py
```
Runtime is about 6 minutes per mode with an empty cache. Weights and AL s-scores are cached in `results/<mode>/cache/`; delete them to rebuild.

## Data (every v1 result uses it)
- **Source:** `$QR_DATA_DIR/` (DE final build), read-only, read from the data owner's local store.
  - Bars: Alpaca SIP daily `bars/daily/adjusted`, split and dividend adjusted, 2016-01-04 to 2026-10-28.
  - $ADV uses raw close × raw SIP volume (point-in-time).
  - Universe: PIT S&P 500 from `sp500_membership.parquet` [start, end), 723 symbols including 220 former members, about 503 members per day.
  - Sectors: current GICS from `universe.parquet`. Former members are imputed by max-correlation sector SPDR.
  - Hedges: 11 sector SPDRs + SPY.
- **Jump filter:** 34 member-days flagged (|r| > 40% or split-ratio-sized ≥ 2:1) and excluded.
- **Ken French factors:** from `factors/ken_french/` (decimals, through 2026-09-30).
- **VIX:** FRED VIXCLS public CSV, saved in `data_ext/VIXCLS_fred.csv`. Used for regime tables only.
- **total_return:** not used, because no strategy needs dividends beyond the adjusted bars. If added, use `ret_total_best` / `tr_index_best`.

### Desk rule #5 change (2026-10-30)
- `code/fetch_alpaca.py`, which made direct Alpaca HTTP calls, is **retired**. It is now `code/_retired/fetch_alpaca.py.retired`.
- The replacement is `code/fetch_bars.py`, a thin wrapper over `$QR_DATA_DIR/lib/desk_data_client.py`. It does local-store reads, and any live call goes only through the shared throttled client.
- No code in `code/` calls Alpaca directly.
- **`data/daily_bars.json` is DEPRECATED.** It was an IEX fallback with a survivorship-biased universe. It has moved to `data/_deprecated/` with a note.
  - `statarb.data.load_panel` now refuses every source except `cio_data`, so no result depends on it.
  - It was used only by the early IEX smoke tests, which are counted as prior trials.

## Design
- **Walk-forward.** Every parameter (betas, PCA, OU fits, FF3 betas, pair formation) is estimated on past data only.
  - Dev period: 2017–2021.
  - Holdout: 2022-02-01 to 2026-10-28. The split is 2022-01-01, with about 21 trading days (one monthly rebalance) of embargo. That gives 4.7 years OOS, which is ≥ 3 years.
- **Execution.** Signal at close t; trade at open t+1 (`open_t1`, primary, meets the standard's "next-bar open or worse"), or at close t+1 (`close_t1`).
- **Book.** Gross book = 1; returns are on gross. Costs are modelled at $10M gross.
- **Cost scenarios** (`config.SCENARIOS`):
  - `tca_base`: the TCA owner `cost_model` with k = 0.75 and 25 bp/yr borrow.
  - `tca_stress`: k = 1.0 and 50 bp borrow.
  - `tca_2x`: 2× tca_base.
  - **`std`**: STANDARD §5 floor, per side max(TCA, floor + full half-spread). The floor is 5 bps for S&P 500 names (large-cap by index), 20 bps for thin names (ADV < $50M), and 2 bps for SPDRs. Borrow is 1%/yr.
  - **`std_2x`**: 2× std.
  - **Verdicts use `std` and `std_2x`.** The TCA columns are for information.
- **Pre-registered variants** (`config.V1_VARIANTS`, fixed before any v1 result was seen; the turnover levers were the priority):

  | Family | Variants |
  |---|---|
  | AL sector-ETF s-score | 5 band sets (open/close-long/close-short: 1.25/0.5/0.75 (paper), 1.5/0.25/0.25, 1.75/0/0, 2/0.5/0.5, 2/0/0) × no-trade buffer {0, 0.5} |
  | AL PCA-15 | paper bands × buffer {0, 0.5}, plus 1.75/0/0 with buffer 0.5 |
  | (b) sector-ETF residual reversal | lookback {5, 10, 21} × buffer {0, 0.5} |
  | (c) PCA-5 residual reversal | lookback 5 × buffer {0, 0.5} |
  | Blitz FF3 36-month residual reversal | monthly, decile |
  | EG pairs | BH-FDR q = 0.05, and no multiple-testing correction |

  - Selection rule: in each family, pick the best **dev** net Sharpe (std costs, open_t1). The holdout is read once.

## Validation results (base, `results/v1/`)
- **Trial count for DSR:** N = 80, made of 48 v1 trials and 32 prior trials (IEX smoke tests and v0 cio_data runs; see `trial_log.csv`).
  - Each pairs config counts as **one** trial. The 273,344 Engle-Granger tests are one family, controlled by BH inside.
- **SR₀:** 0.74 annualised.
  - V[SR] is taken from the dispersion of gross trial SRs, the most lenient of three options. The others give net-trial dispersion 2.90 and pure-noise 1/T 1.13. See `dsr.json`.
- **PBO (CSCV, S = 16, 12,870 splits):**
  - All 48 trials, std costs: 0.10. On TCA costs: 0.23.
  - By family: AL_ETF 0.008; b 0.0; c 0.05; pairs 0.79 (N = 4, uninformative).
  - **Caveat:** a low PBO here only means the ranking of mostly *losing* variants is stable. It says nothing about profitability.

Pre-registered picks, open_t1, holdout 2022-02 onward. Net figures use std costs unless the column says TCA.

| Pick | Gross SR | Net SR (TCA base) | Net SR (TCA stress) | Net SR (std) | Net SR (std, 2×) | NW t, full, net | Hurdle | DSR | Turnover /yr | Gross edge, bps/$ | Cost, bps/$ (std) | Avg hold, days | Cap @1% ADV | Bars passed of 7 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AL_ETF 1.75/0/0, buf 0.5 | 0.46 | −0.35 | −0.43 | −0.56 | −1.57 | −1.40 | 2.8 | 0.00 | 28 | 5.5 | 10.6 | 17 | $222M | 2 |
| AL_PCA15 1.75/0/0, buf 0.5 | −0.22 | −1.85 | −2.00 | −2.18 | −4.13 | −5.45 | 2.8 | 0.00 | 41 | −1.5 | 12.6 | 12 | $171M | 2 |
| b sector-ETF rev21, buf 0.5 | 0.13 | −1.03 | −1.10 | −1.37 | −2.85 | −3.40 | 3.0 | 0.00 | 48 | 1.1 | 11.6 | 9 | $742M | 2 |
| c PCA5 rev5, buf 0.5 | −0.06 | −2.52 | −2.68 | −3.03 | −5.82 | −9.77 | 3.0 | 0.00 | 89 | −0.3 | 12.4 | 3.5 | $459M | 2 |
| Blitz FF3 monthly | −0.30 | −0.60 | −0.64 | −0.67 | −1.03 | −0.60 | 2.8 | 0.00 | 22 | −11.7 | 12.5 | 23 | $95M | 2 |
| EG pairs, no MT correction | −0.15 | −0.57 | −0.62 | −0.63 | −1.11 | −1.40 | 3.0 | 0.00 | 6.6 | −5.2 | 14.5 | 19 | $62M | 2 |

- The two bars passed are PBO < 0.2 and the OOS trade count. EG pairs with BH also fails the trade count: it has 49 holdout round trips, below the 100 required, so it passes 1 bar.
- Full per-trial table: `results/v1/headline_v1.csv`. Criteria C1–C7: `validation_passfail.csv`.
- Turnover levers worked mechanically: for AL_ETF, turnover fell from 62/yr (paper bands, no buffer) to 28/yr, and holdout net (std) improved from −1.52 to −0.56. But gross edge per $ traded never reached cost, let alone 2× cost.

### Blitz decay (monthly, open_t1; `blitz_decay_monthly.csv`)
| Period | Months | Gross ann. mean | Gross Sharpe | NW t (mean) | FF3 α t | FF3+Mom+ST_Rev α t | β ST_Rev (t) | Net (std) Sharpe |
|---|---|---|---|---|---|---|---|---|
| Dev (to 2021-12) | 49 | +7.8% | 1.01 | 2.42 | 1.92 | 2.11 | 0.19 (2.4) | 0.54 |
| Holdout 2022-02 to 2026-09 | 56 | −3.3% | −0.38 | −0.98 | −1.08 | −0.25 | 0.43 (3.7) | −0.76 |

- Other holdout loadings: Mkt −0.04, SMB −0.17, HML 0.06, Mom −0.06. R² is 0.44.
- **Reading:** the residual-reversal premium decayed fully out of sample, consistent with McLean-Pontiff post-publication decay.
- Its loading on the published ST_Rev factor doubled in the holdout. Controlling for ST_Rev, holdout alpha is about 0 (t −0.25). **It is largely the published reversal factor, and that factor has not paid since 2022.**

### Regime and stability (STANDARD §7; `results/v1/regime_*.csv`)
- **AL_ETF pick:** gross P&L is concentrated in stress. 2020 is 45% of total gross P&L, above the 40% cap, so it is flagged.
  - VIX > 25 days carry 89% of gross P&L (gross Sharpe 2.4); VIX ≤ 25 has gross Sharpe 0.10.
  - Net Sharpe is < −0.5 in calendar 2017, 2019, 2022 and 2024. That breaks the "no regime with Sharpe < −0.5" check.
- **Blitz:** 2020 is 83% of gross P&L. Net is < −0.5 in 2022, 2024 and 2025.
- The parameter ±20% neighbourhood test was not run separately; the band grid is the neighbourhood. Correlation to the existing book was not computed.

### Factor regressions (daily FF3+Mom+ST_Rev, HAC; `factor_regressions_daily.csv`)
- The daily strategies have tiny factor loadings: |β| ≤ 0.05 and R² ≤ 4%. The exception is sector-ETF reversal (b), which loads *negatively* on daily ST_Rev in the holdout (t −3.6 to −4.6).
- Their dev gross alphas do not survive into the holdout. For the AL_ETF pick, dev gross α t is 2.19 and holdout t is 0.92. Net α t is negative in both periods.

## Affected by data issues
Source: `$QR_DESK_DIR/validation/backtests/pead_long_pit/data_issues.json` (read-only).
- **Earnings dates (intraday events dated a day late, coverage gaps): not used.** None of these strategies reads earnings dates, fundamentals or announcement timestamps. They use only prices, volumes, PIT membership, GICS and Ken French factors. So that defect cannot affect them.
- **Ticker reuse and predecessor gaps.** 88 symbols are flagged in total; 82 of them are in the panel.
  - 36 are reused or re-added tickers: SNDK, any symbol with more than one membership interval, the post-2015 anomaly list, and the DE-fixed list POM/SPLS/NFX/APC/CA/CSRA/DNB/TE.
  - 59 were members without bars.
  - **Straddle audit:** no position (residual, AL, Blitz or pair leg) is held across, or on both sides of, an internal bar gap in any of the 48 trials (`straddle_flags = 0`).
  - SNDK has bars only from 2025-02-13 (the new Sandisk). Old SanDisk's 2016 membership has no bars, so it never enters.
  - Flagged names carry about 3–6% of average gross exposure.
- **Delisting returns are missing** (base treats delisted names as flat at their last price).
  - Stress (`v1_delist_stress`): −30% on the 70 non-merger delistings, and the DE `terminal_return` on matched mergers.
  - It hits 0–86 positions per trial. The cumulative P&L impact is between −0.9% and +0.6%, and holdout net Sharpe moves by at most 0.034.
- **Complete-history universe** (`v1_complete`: all flagged names removed).
  - Holdout net (std) Sharpe changes by −0.12 to +0.15. For example, AL_ETF pick −0.56 → −0.54, and AL_ETF 1.5/0.25/0.25 buf 0.5 −0.73 → −0.58.
- **Verdict changes under these checks: none.** All 48 trials FAIL in all three modes. See `results/v1/data_issues_sensitivity.csv`.
- **Bug found and fixed by this audit.** AL kept positions open after a name delisted or left the index ("zombie" positions with 0 return). AL now force-exits names that are no longer members or have no bar. The tables above use the fixed code. Blitz still holds delisted names flat until the next monthly rebalance (5 cases), which is realistic, and they are covered by the delisting stress.

## Other caveats
- **Costs.** Spreads are bucket defaults, not measured quotes. Impact is at $10M gross. Borrow is flat general collateral; there is no hard-to-borrow list. Even the TCA owner's cheaper model leaves every pick net-negative in the holdout.
- **Sectors.** GICS is today's snapshot; former members' sectors are imputed.
- **Factors.** Ken French factors are used ex post. In live trading they publish with a lag; this matters only for Blitz betas.
- **Pairs.** A simplified GGR/EG variant (252-day formation, 126-day trading, top 20, at most 2 pairs per stock). It is not a faithful GGR replication.

## Files
- **Code** (`code/`):
  - `config.py`: variants, scenarios, prior trials, label.
  - `run_v1.py`, `validate_v1.py`, `compare_modes.py`.
  - `statarb/{data,backtest,costs,pairs,reversal,papers,validation,data_issues}.py`.
  - `fetch_bars.py`: client wrapper.
  - `run_all.py`: v0 runner, kept for reference.
- **Results** (`results/v1/`):
  - Summaries: `headline_v1.csv`, `validation_passfail.csv`, `metrics_all.csv`.
  - Trial log and return matrices: `trial_log.csv`, `returns_matrix_net_std.parquet` and `returns_matrix_gross.parquet` (T × N).
  - Statistics: `dsr.json`, `pbo.json`, `blitz_decay_monthly.csv`, `factor_regressions_daily.csv`, `regime_*.csv`, `data_issues_sensitivity.csv`.
  - Per-trial data: `daily/*.parquet` (gross, net per scenario, turnover, legs), `trades/` (pair trade lists), `trial_meta.csv` (capacity, audits).
- **Sensitivity runs:** `results/v1_complete/`, `results/v1_delist_stress/`. Logs: `results/logs/`.
- **Superseded v0 / preliminary outputs:** `results/_v0_superseded/`. These were run before the DE's final build and before the standard was adopted; do not cite them.

## Correction (30 Oct 2026, after review)
- The best holdout net Sharpe (standard cost floor) across all 48 v1 trials is **-0.475**, from `AL_ETF_B2_1.75/0.00/0.00_buf0.5__close_t1`. That is the same AL sector-ETF setting, executed at the next close instead of the next open. The pre-registered pick (next open) scored -0.56. Both FAIL.
- The DSR used the gross-trial variance (SR0 0.74, the less strict option). Future runs will use the net-trial variance. Cumulative stat-arb family N = 80, so new ideas pre-register at N >= 81.
