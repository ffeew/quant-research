# Validation submission: Residual momentum (Blitz, Huij & Martens 2011)

> **Status: FAILED** (Victor, 2026-10-30; validation/replication_checks/2026-10-30-dave-replications.md). Corrections applied 2026-10-30 02:26 SGT after his check.

Submitted by Dave (Quant Research) to Victor, 2026-10-30 01:47 SGT. Built against validation/STANDARD.md v1.0. Self-assessment only; the verdict is Victor's.

## CORRECTION 2026-10-30 02:26 SGT: warm-up bug fixed (read this first; supersedes the 01:47 resmom_ls / resmom_long numbers)

**Verdict: FAIL** (self-assessed, and confirmed by Victor in validation/replication_checks/2026-10-30-dave-replications.md). The fix does not change it.

**The bug.** In `pipeline.py::_scores`, the 36-month FF3 fit window and the 12-month formation window were silently clipped at the first session of the data (2016-01-04). The rule "at least 24 of 36 months" was not enforced: `min_obs` was 2/3 of the *clipped* window, and names with complete (clipped) data skipped the check entirely.
- For signals 2016-02 to 2016-12, the fit window equalled the formation window. OLS with an intercept then forces the residuals to sum to zero, so every score was floating-point noise (~1e-12). Trades from 2016-03 to 2017-01 held an effectively random book.
- For signals 2017-01 to 2018-11, the fit window was 12-35 months instead of 36.
- The earlier full-sample headline (2016-03 on, net SR −0.07) included those random books. **It is withdrawn and should not be quoted.**

**The fix.**
- `min_obs` = ceil(2/3 x nominal window) = 504 sessions (24 of 36 months), applied to every name.
- No score is produced until the clipped window has 504 sessions.
- The formation window may not be clipped.

With the fix, the first signal with scores is 2018-02-28 (trading 2018-03-01). That window is still shorter than 36 months, so the result is restated from the first *fully warmed-up* month.
- **The correct first month is 2019-01, not 2019-02.** The 2018-12-31 signal's 36-month window starts 2015-12-31. The first session after that is 2016-01-04 (Jan 1 is a holiday, Jan 2-3 a weekend), which is the data start, so no session is missing (733 sessions vs 735 for 2019-01-31).
- 2019-02 is shown alongside for comparison with Victor's check. The one-month difference moves the L/S Sharpe from 0.11 to 0.06, which shows how noisy this estimate is.

**What was rerun.** Only the primary L/S (`resmom_ls`) and the long-only (`resmom_long`), at base parameters, next-open fills, the same data snapshot and the same costs (`bugfix_warmup_rerun.py`). From 2019-02 on, the corrected daily series matches the 01:47 series to within 0.09% per day (the difference is the starting book). This confirms the bug only affected the warm-up.

**Corrected numbers.** Net is net of max(Tomas, Victor floor) costs and 1%/yr borrow; DSR uses the 75-trial family N and the family trial-Sharpe variance as before.

| book | sample | start | net SR | gross SR | net SR 2x | net ann | t (NW) | maxDD | alpha vs SPY (ann, t) | beta SPY | FF3+UMD alpha (ann, t) | DSR (N) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| resmom_ls | 2019-01 on (first fully warmed-up month) **[headline]** | 2019-01-02 | 0.06 | 0.30 | -0.17 | 0.8% | 0.19 | -34.3% | 1.9% (0.44) | -0.07 | -1.0% (-0.31) | 0.017 (75) |
| resmom_ls | 2019-02 on (Victor's window) | 2019-02-01 | 0.11 | 0.35 | -0.12 | 1.6% | 0.35 | -31.1% | 2.6% (0.58) | -0.07 | -0.8% (-0.25) | 0.026 (75) |
| resmom_ls | 2018-04 on (all trades allowed by the 24-of-36 rule) | 2018-04-02 | 0.02 | 0.26 | -0.22 | 0.2% | 0.05 | -40.9% | 0.9% (0.23) | -0.06 | -1.8% (-0.61) | 0.010 (75) |
| resmom_long | 2019-01 on (first fully warmed-up month) **[headline]** | 2019-01-02 | 0.69 | 0.74 | 0.64 | 13.7% | 2.11 | -38.5% | -0.3% (-0.12) | 0.95 | -1.0% (-0.47) | 0.364 (75) |
| resmom_long | 2019-02 on (Victor's window) | 2019-02-01 | 0.65 | 0.71 | 0.60 | 13.0% | 1.99 | -38.5% | -0.3% (-0.10) | 0.95 | -1.0% (-0.47) | 0.327 (75) |
| resmom_long | 2018-04 on (all trades allowed by the 24-of-36 rule) | 2018-04-02 | 0.57 | 0.63 | 0.52 | 11.3% | 1.82 | -40.3% | -1.1% (-0.38) | 0.95 | -1.4% (-0.68) | 0.241 (75) |

Victor's rough check, trimming the bugged series at 2019-02, gave net SR 0.11 and DSR 0.025. Our rerun gives 0.114 and 0.026 (0.108 and 0.025 on the trimmed old series): **they match.**

**Against STANDARD.md (resmom_ls, headline 2019-01 on):**

| requirement | status |
|---|---|
| net SR > 0.5 | NOT MET (0.06) |
| SR > 0 at 2x costs | NOT MET (-0.17) |
| t ≥ 2.8 | NOT MET (0.19) |
| DSR ≥ 0.95 | NOT MET (0.017) |
| history ≥ 10 years of strategy returns | NOT MET (7.8 years) |

**What the long-only book is.** It is market beta (0.95), with alpha vs SPY of about 0 (t −0.1). It is not evidence for residual momentum.

**Not recomputed.** The walk-forward, PBO, ±20% grid, delisting stress, regimes and calendar-year tables further down come from the 01:47 run, which includes the bug. They are kept for audit only. Their post-2019 parts are essentially unaffected, but the full-period figures are not valid. The totmom comparator also used a formation window shorter than 12-1 in 2016 and was not rerun.

**How the rerun is logged.** It is logged in `research/replication/TRIAL_LOG.csv` as 2 rows with role `bugfix_rerun`:
- trial_ids `resmom|resmom_ls|base|open|clean|<ts>_bugfix_warmup` and `resmom|resmom_long|base|open|clean|<ts>_bugfix_warmup`
- notes: "BUG-FIX RERUN of ... same config ... Not a new trial"

The trial-count code counts distinct specs (trial_id without its run stamp), so these collapse onto the existing base specs and **N stays 75**. Counting rows instead, exclude the `superseded_rerun` and `bugfix_rerun` roles.

Files: `daily_resmom_ls_bugfix.csv`, `daily_resmom_long_bugfix.csv`, `trades_*_bugfix.csv.gz`, `bugfix_warmup_rerun.json`.

## Reproduce (one command)
```
$QR_DESK_DIR/research/replication/.venv/bin/python $QR_DESK_DIR/research/replication/run_all.py --only resmom
```
Code: `research/replication/blitz-huij-martens-2011-residual-momentum/pipeline.py`, `_common/engine.py` (fills, costs, borrow), `_common/validation.py` (DSR, PBO, NW, walk-forward), `run_all.py`. Env: `research/replication/.venv` (`requirements.lock.txt`).
Data snapshot: Dmitri SIP total_return ret_total_best (clean), fingerprint c50abc068669d327; file mtimes {"daily_total_return.parquet": "2026-10-30 01:32:38 SGT", "sp500_membership.parquet": "2026-10-30 01:31:38 SGT", "ff3_daily.parquet": "2026-10-30 01:10:57 SGT"}. Trial log: `research/replication/TRIAL_LOG.csv`; T x N daily net matrix: `research/replication/results/trials_daily_net_*.parquet`.

## Codified rules
See the docstring of `pipeline.py` (copied below). No discretion, no overrides.
```
Residual momentum (Blitz, Huij & Martens 2011) on Dmitri's SIP total returns, PIT S&P 500. Dave, 2026-10-30 (v2).
Codified rules (base params; every number below is a parameter perturbed +/-20% in the sensitivity grid):
  Universe at month-end t: PIT S&P 500 members (membership interval contains t) with a bar on t.
  Fit: OLS with intercept of daily excess returns on FF3 (Mkt-RF, SMB, HML) over (t - fit_months, t - skip_days],
       >= 2/3 of the window's observations required (24 of 36 months at base).
  Score: residuals (r - a - b'F) over (t - form_months, t - skip_days]; score = sum / std (Blitz et al. eq. 2).
  Comparator: total-return momentum over the same formation window.
  Books: EW quantile `q` (0.20): L/S top-minus-bottom ($1 per leg) and long-only top (excess of rf).
  Rebalance: monthly (last session of month); fill next session's open (engine).
```
Execution: signal at the close of the last session of each month; market-on-open fill at the next session's open; costs Tomas v1.1 max Victor floor; borrow 1.00%/yr; book $100,000; 2x stress doubles costs and borrow. Primary (pre-specified, paper-faithful) book: **resmom_ls**; secondary books: resmom_long, totmom_ls.

## SUPERSEDED: 01:47 run headline (contains the warm-up bug; resmom_ls / resmom_long rows withdrawn, do not quote; see CORRECTION above)

| book | start | net SR | gross SR | net SR 2x | net ann | t (NW) | maxDD | alpha vs SPY (ann, t) | beta SPY | FF3+UMD alpha (ann, t) | WF-OOS SR (yrs) | DSR fam (N) | PBO grid |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ~~resmom_ls~~ (withdrawn, warm-up bug) | 2016-03-31 | -0.07 | 0.20 | -0.34 | -0.9% | -0.25 | -48.4% | -0.2% (-0.06) | -0.05 | -2.6% (-0.96) | 0.18 (7.1) | 0.00 (75) | 0.20 |
| ~~resmom_long~~ (withdrawn, warm-up bug) | 2016-03-31 | 0.61 | 0.67 | 0.54 | 11.2% | 2.15 | -40.4% | -1.5% (-0.63) | 0.96 | -2.0% (-1.13) | 0.61 (7.1) | 0.25 (75) | 0.41 |
| totmom_ls (2016 warm-up affected, not rerun) | 2016-03-31 | -0.07 | 0.07 | -0.20 | -1.4% | -0.24 | -53.0% | -0.5% (-0.09) | -0.07 | -5.3% (-2.08) | 0.03 (7.1) | 0.00 (75) | 0.45 |

![equity curve](equity_curve.png)

## STANDARD.md checklist for the primary book (resmom_ls), 01:47 run (superseded where it cites full-sample figures; corrected bars in CORRECTION above)

| requirement | status | evidence |
|---|---|---|
| §1 artefacts: rules, one-command code, trial log + TxN matrix, report/equity curve/trade list | MET | files listed above |
| §2 PIT universe incl. delisted names | MET (with caveat) | PIT S&P 500 membership incl. 220 former members; ticker-reuse intervals (SNDK, AA, Q) excluded. Delisting returns only partly available: 38 held positions hit a delisting; base = cash at last close; conservative-delisting SR -0.08, adverse -0.12 (see Data-affected caveats) |
| §2 SIP volume, adjusted total-return prices | MET | SIP; ret_total_best; 12 suspect corporate-action days zeroed (results/suspect_returns.csv); no-clean SR -0.08 |
| §2 no look-ahead / next-bar open fills | MET | signal at close t, fill at open t+1. Next-close alt SR -0.10 |
| §2 history >= 10 years | MET | bars 2016-01..2026-10 (10.8y) but lookbacks leave 10.6y of strategy returns |
| §3 OOS: walk-forward >= 5 folds spanning >= 3y, embargo >= 1 rebalance | MET | 8 annual folds, 7.1y OOS, 21-session embargo; selection over the +/-20% grid. Caveat: the period was not untouched (v1 runs at 01:21 SGT and turn-1 runs on 2020+ IEX data are in the trial log) |
| §3 >= 30 independent OOS rebalance periods | MET | 86 OOS months |
| §4 OOS Sharpe net > 0.5 | NOT MET | corrected 2019-01+ net SR 0.06 (2019-02+ 0.11); WF-OOS 0.18 from the bugged 01:47 grid |
| §4/§5 Sharpe > 0 at 2x costs | NOT MET | full -0.34, WF-OOS -0.05 |
| §4 DSR >= 0.95 | NOT MET | family N=75: DSR 0.002, SR0 0.82 ann; all-Dave N=184: DSR 0.000, SR0 1.06; T=2661, skew -0.49, kurt 6.77 |
| §4 t-stat >= 2.8 (replication of published anomaly; NW) | NOT MET | t_NW -0.25 (iid -0.22) |
| §4 PBO < 0.20 (<= 0.05 for PASS) | MET | book grid PBO 0.20 (N=11); whole family PBO 0.25 (N=44). N~11 per grid -> weakly informative |
| §5 costs >= Victor minimums; borrow >= 1%/yr; exclude unborrowable | MET (borrow caveat) | avg 15.7 bps/side (Tomas-only 10.7); borrow 1%/yr; no PIT borrow history exists, so unborrowable names cannot be excluded at signal time |
| §6 post-publication haircut | computed | expected SR for sizing = min(WF-OOS 0.18, 0.40 x 0.80) = 0.18 (Ken French UMD 1965-01..1989-12 (JT93 in-sample window), proxy; resmom paper Sharpe not used) |
| §7 no year > 40% of PnL | NOT MET | max year share n/a (n/a if total PnL <= 0) |
| §7 no regime Sharpe < -0.5 | MET | worst regime SR -0.45 |
| §7 +/-20% neighbourhood: SR > 0 and >= 50% of base | NOT MET | 0/11 configs pass on full-sample net SR; 10/11 on 2022+ net SR |
| §7 legs reported; correlation to book | MET (book history 1 day) | long leg gross SR 0.69, short leg gross SR -0.49; desk book has 1 day of history, so correlations are vs SPY/FF factors and Victor's validation backtests |
| §8 trade size <= 1% of 20d ADV | MET | max 0.0235% at $100,000; at 10x book max 0.235% |
| §8 break-even cost >= 2x assumed | NOT MET | break-even 16.7 bps/side vs assumed 15.7 |

**Self-assessed verdict: FAIL** (7 requirement(s) not met: §4 OOS Sharpe net > 0.5; §4/§5 Sharpe > 0 at 2x costs; §4 DSR >= 0.95; §4 t-stat >= 2.8 (replication of published anomaly; NW); §7 no year > 40% of PnL; §7 +/-20% neighbourhood: SR > 0 and >= 50% of base; §8 break-even cost >= 2x assumed). A FAIL is a verdict on evidence.

## Details per book (01:47 run, includes the warm-up bug; audit only)

### resmom_ls

- Net {"start": "2016-03-31", "end": "2026-10-28", "T": 2661, "ann_ret": -0.0088, "ann_vol": 0.1286, "sharpe": -0.0683, "t_nw": -0.2458, "t_iid": -0.222, "max_dd": -0.4839, "skew": -0.492, "kurt": 6.7689}
- Gross SR 0.20, 2x-cost SR -0.34; long leg gross SR 0.69 (ann 12.3%), short leg gross SR -0.49 (ann -9.7%).
- Market: {"alpha_ann_vs_spy": -0.002, "alpha_t_nw_vs_spy": -0.057, "beta_spy": -0.051, "beta_t_nw": -1.89, "beta_neutral_test": "beta within +/-0.1 and |t|<2", "alpha_sharpe_vs_spy": -0.016, "alpha_ann_ff4": -0.026, "alpha_t_nw_ff4": -0.96, "load_Mkt-RF": 0.001, "load_SMB": 0.024, "load_HML": 0.112, "load_UMD": 0.515}
- Gross-return beta vs SPY -0.05, gross alpha vs SPY 3.2% (t 0.91).
- Turnover/costs: {"traded_per_yr_x_nav": 15.448, "avg_gross_exposure": 2.01, "oneway_turnover_per_yr_of_gross": 3.842, "avg_holding_months": 3.123, "gross_ret_per_unit_traded_bps": 16.665, "breakeven_cost_bps_per_side": 16.665, "assumed_avg_cost_bps_per_side": 15.739, "tomas_only_avg_cost_bps": 10.749, "breakeven_over_assumed": 1.059, "cost_drag_ann": 0.024, "borrow_drag_ann": 0.01, "avg_long_mv": 1.005, "avg_short_mv": 1.005}
- Capacity: {"book_usd": 100000.0, "max_participation": 0.00023, "p99_participation": 2e-05, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.00235, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR 0.18, t_NW 0.56, folds 8, picks ['form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20'], 2x SR -0.05
- DSR (family N=75): 0.002; DSR (all Dave trials N=184): 0.000
- PBO grid 0.20 (N=11), family 0.25 (N=44)
- Alt trials: next-close fill SR -0.10; no-clean data SR -0.08; delisting returns table/conservative/adverse SR -0.07 / -0.08 / -0.12
- Delisting exits while held: 38 (ADT, TE, GAS, TYC, STJ, SE, SPLS, TWX, XL, ANDV, CA, COL...)
- Correlations: {"SPY": -0.07, "FF_Mkt-RF": -0.07, "FF_SMB": -0.13, "FF_HML": -0.08, "FF_UMD": 0.68, "validation_backtest_MOM_monthly_LS": 0.57, "validation_backtest_PEAD_raw_LS": 0.05, "validation_backtest_PEAD_trend_LS": 0.16, "validation_backtest_MOM_bracket_LS": 0.49}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2016 | -0.074 |    -0.070 |   -0.723 | 192.000 |                  nan |
|   2017 | -0.044 |    -0.041 |   -0.470 | 251.000 |                  nan |
|   2018 | -0.043 |    -0.039 |   -0.416 | 251.000 |                  nan |
|   2019 | -0.184 |    -0.198 |   -1.935 | 252.000 |                  nan |
|   2020 | -0.133 |    -0.135 |   -1.025 | 253.000 |                  nan |
|   2021 |  0.021 |     0.027 |    0.252 | 252.000 |                  nan |
|   2022 |  0.052 |     0.064 |    0.393 | 251.000 |                  nan |
|   2023 | -0.040 |    -0.035 |   -0.314 | 250.000 |                  nan |
|   2024 |  0.074 |     0.076 |    0.800 | 252.000 |                  nan |
|   2025 |  0.007 |     0.015 |    0.118 | 250.000 |                  nan |
|   2026 |  0.249 |     0.243 |    1.308 | 207.000 |                  nan |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2117 |      0.00 |     0.01 |
| SPY<200dma  |    544 |     -0.05 |    -0.32 |
| VIX>median  |   1327 |      0.03 |     0.22 |
| VIX<=median |   1333 |     -0.05 |    -0.45 |
| VIX>25      |    364 |      0.13 |     0.81 |
| VIX<=25     |   2296 |     -0.03 |    -0.24 |

+/-20% neighbourhood (net SR):

| param_tag       |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:----------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base            |         -0.07 |              0.51 |            -0.34 | False     | True          |
| fit_months_m20  |          0.08 |              0.58 |            -0.20 | False     | True          |
| fit_months_p20  |         -0.09 |              0.55 |            -0.35 | False     | True          |
| form_months_m20 |          0.08 |              0.27 |            -0.20 | False     | True          |
| form_months_p20 |         -0.12 |              0.40 |            -0.38 | False     | True          |
| skip_days_m20   |         -0.20 |              0.45 |            -0.44 | False     | True          |
| skip_days_p20   |         -0.11 |              0.47 |            -0.36 | False     | True          |
| q_m20           |         -0.07 |              0.48 |            -0.32 | False     | True          |
| q_p20           |         -0.09 |              0.49 |            -0.37 | False     | True          |
| all_m20         |         -0.08 |              0.17 |            -0.34 | False     | False         |
| all_p20         |         -0.15 |              0.40 |            -0.40 | False     | True          |

### resmom_long

- Net {"start": "2016-03-31", "end": "2026-10-28", "T": 2661, "ann_ret": 0.1119, "ann_vol": 0.1847, "sharpe": 0.6057, "t_nw": 2.1534, "t_iid": 1.9683, "max_dd": -0.4044, "skew": -0.5164, "kurt": 16.319}
- Gross SR 0.67, 2x-cost SR 0.54; long leg gross SR 0.67 (ann 12.3%), short leg gross SR n/a (ann n/a).
- Market: {"alpha_ann_vs_spy": -0.015, "alpha_t_nw_vs_spy": -0.633, "beta_spy": 0.956, "beta_t_nw": 36.158, "beta_neutral_test": "NOT beta-neutral", "alpha_sharpe_vs_spy": -0.184, "alpha_ann_ff4": -0.02, "alpha_t_nw_ff4": -1.125, "load_Mkt-RF": 0.942, "load_SMB": 0.114, "load_HML": 0.322, "load_UMD": 0.152}
- Gross-return beta vs SPY 0.96, gross alpha vs SPY -0.3% (t -0.14).
- Turnover/costs: {"traded_per_yr_x_nav": 7.423, "avg_gross_exposure": 1.0, "oneway_turnover_per_yr_of_gross": 3.712, "avg_holding_months": 3.233, "gross_ret_per_unit_traded_bps": 166.248, "breakeven_cost_bps_per_side": 166.248, "assumed_avg_cost_bps_per_side": 15.566, "tomas_only_avg_cost_bps": 10.614, "breakeven_over_assumed": 10.68, "cost_drag_ann": 0.012, "borrow_drag_ann": 0.0, "avg_long_mv": 1.0, "avg_short_mv": 0.0}
- Capacity: {"book_usd": 100000.0, "max_participation": 0.00025, "p99_participation": 2e-05, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.00248, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR 0.61, t_NW 1.81, folds 8, picks ['form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20', 'form_months_m20'], 2x SR 0.55
- DSR (family N=75): 0.249; DSR (all Dave trials N=184): 0.075
- PBO grid 0.41 (N=11), family 0.25 (N=44)
- Alt trials: next-close fill SR 0.60; no-clean data SR 0.60; delisting returns table/conservative/adverse SR 0.61 / 0.58 / 0.58
- Delisting exits while held: 25 (ADT, TE, GAS, TYC, STJ, SPLS, XL, ANDV, CA, ESRX, SCG, CELG...)
- Correlations: {"SPY": 0.9, "FF_Mkt-RF": 0.91, "FF_SMB": 0.26, "FF_HML": 0.11, "FF_UMD": -0.02, "validation_backtest_MOM_monthly_LS": 0.13, "validation_backtest_PEAD_raw_LS": -0.36, "validation_backtest_PEAD_trend_LS": -0.32, "validation_backtest_MOM_bracket_LS": 0.09}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2016 |  0.075 |     0.078 |    0.882 | 192.000 |                0.066 |
|   2017 |  0.158 |     0.151 |    1.559 | 251.000 |                0.128 |
|   2018 | -0.124 |    -0.116 |   -0.654 | 251.000 |               -0.098 |
|   2019 |  0.145 |     0.142 |    1.224 | 252.000 |                0.120 |
|   2020 |  0.117 |     0.177 |    0.488 | 253.000 |                0.150 |
|   2021 |  0.350 |     0.314 |    1.860 | 252.000 |                0.266 |
|   2022 | -0.087 |    -0.068 |   -0.314 | 251.000 |               -0.057 |
|   2023 |  0.046 |     0.055 |    0.391 | 250.000 |                0.046 |
|   2024 |  0.096 |     0.101 |    0.768 | 252.000 |                0.085 |
|   2025 |  0.080 |     0.092 |    0.541 | 250.000 |                0.078 |
|   2026 |  0.277 |     0.256 |    1.833 | 207.000 |                0.217 |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2117 |      0.10 |     0.66 |
| SPY<200dma  |    544 |      0.18 |     0.61 |
| VIX>median  |   1327 |      0.19 |     0.80 |
| VIX<=median |   1333 |      0.04 |     0.31 |
| VIX>25      |    364 |      0.34 |     0.95 |
| VIX<=25     |   2296 |      0.08 |     0.55 |

+/-20% neighbourhood (net SR):

| param_tag       |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:----------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base            |          0.61 |              0.54 |             0.54 | True      | True          |
| fit_months_m20  |          0.66 |              0.59 |             0.59 | True      | True          |
| fit_months_p20  |          0.58 |              0.57 |             0.52 | True      | True          |
| form_months_m20 |          0.65 |              0.46 |             0.59 | True      | True          |
| form_months_p20 |          0.56 |              0.49 |             0.50 | True      | True          |
| skip_days_m20   |          0.59 |              0.54 |             0.53 | True      | True          |
| skip_days_p20   |          0.60 |              0.51 |             0.55 | True      | True          |
| q_m20           |          0.62 |              0.58 |             0.55 | True      | True          |
| q_p20           |          0.62 |              0.54 |             0.56 | True      | True          |
| all_m20         |          0.61 |              0.42 |             0.55 | True      | True          |
| all_p20         |          0.57 |              0.56 |             0.52 | True      | True          |

### totmom_ls

- Net {"start": "2016-03-31", "end": "2026-10-28", "T": 2661, "ann_ret": -0.0145, "ann_vol": 0.2208, "sharpe": -0.0657, "t_nw": -0.239, "t_iid": -0.2133, "max_dd": -0.5304, "skew": -1.2046, "kurt": 20.8649}
- Gross SR 0.07, 2x-cost SR -0.20; long leg gross SR 0.65 (ann 12.3%), short leg gross SR -0.43 (ann -10.7%).
- Market: {"alpha_ann_vs_spy": -0.005, "alpha_t_nw_vs_spy": -0.086, "beta_spy": -0.07, "beta_t_nw": -1.405, "beta_neutral_test": "beta within +/-0.1 and |t|<2", "alpha_sharpe_vs_spy": -0.023, "alpha_ann_ff4": -0.053, "alpha_t_nw_ff4": -2.077, "load_Mkt-RF": 0.02, "load_SMB": -0.087, "load_HML": -0.155, "load_UMD": 1.061}
- Gross-return beta vs SPY -0.07, gross alpha vs SPY 2.5% (t 0.42).
- Turnover/costs: {"traded_per_yr_x_nav": 12.977, "avg_gross_exposure": 2.018, "oneway_turnover_per_yr_of_gross": 3.215, "avg_holding_months": 3.732, "gross_ret_per_unit_traded_bps": 12.225, "breakeven_cost_bps_per_side": 12.225, "assumed_avg_cost_bps_per_side": 15.491, "tomas_only_avg_cost_bps": 10.641, "breakeven_over_assumed": 0.789, "cost_drag_ann": 0.02, "borrow_drag_ann": 0.01, "avg_long_mv": 1.007, "avg_short_mv": 1.011}
- Capacity: {"book_usd": 100000.0, "max_participation": 0.00028, "p99_participation": 2e-05, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.00282, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR 0.03, t_NW 0.09, folds 8, picks ['all_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20'], 2x SR -0.08
- DSR (family N=75): 0.002; DSR (all Dave trials N=184): 0.000
- PBO grid 0.45 (N=11), family 0.25 (N=44)
- Alt trials: next-close fill SR -0.08; no-clean data SR -0.07; delisting returns table/conservative/adverse SR -0.07 / -0.08 / -0.10
- Delisting exits while held: 43 (POM, ADT, CPGX, TYC, STJ, SE, HAR, LLTC, WFM, BCR, CSRA, GGP...)
- Correlations: {"SPY": -0.06, "FF_Mkt-RF": -0.06, "FF_SMB": -0.22, "FF_HML": -0.36, "FF_UMD": 0.9, "validation_backtest_MOM_monthly_LS": 0.59, "validation_backtest_PEAD_raw_LS": -0.04, "validation_backtest_PEAD_trend_LS": 0.07, "validation_backtest_MOM_bracket_LS": 0.49}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2016 | -0.166 |    -0.177 |   -2.105 | 192.000 |                  nan |
|   2017 |  0.035 |     0.041 |    0.346 | 251.000 |                  nan |
|   2018 |  0.019 |     0.025 |    0.221 | 251.000 |                  nan |
|   2019 | -0.132 |    -0.127 |   -0.745 | 252.000 |                  nan |
|   2020 | -0.141 |    -0.040 |   -0.086 | 253.000 |                  nan |
|   2021 | -0.189 |    -0.190 |   -0.962 | 252.000 |                  nan |
|   2022 |  0.100 |     0.118 |    0.554 | 251.000 |                  nan |
|   2023 | -0.131 |    -0.126 |   -0.753 | 250.000 |                  nan |
|   2024 |  0.147 |     0.147 |    1.065 | 252.000 |                  nan |
|   2025 |  0.009 |     0.024 |    0.139 | 250.000 |                  nan |
|   2026 |  0.125 |     0.152 |    0.639 | 207.000 |                  nan |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2117 |     -0.00 |    -0.02 |
| SPY<200dma  |    544 |     -0.06 |    -0.26 |
| VIX>median  |   1327 |      0.06 |     0.21 |
| VIX<=median |   1333 |     -0.08 |    -0.55 |
| VIX>25      |    364 |      0.35 |     1.04 |
| VIX<=25     |   2296 |     -0.07 |    -0.37 |

+/-20% neighbourhood (net SR):

| param_tag       |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:----------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base            |         -0.07 |              0.33 |            -0.20 | False     | True          |
| fit_months_m20  |         -0.06 |              0.34 |            -0.20 | False     | True          |
| fit_months_p20  |         -0.06 |              0.34 |            -0.20 | False     | True          |
| form_months_m20 |         -0.02 |              0.08 |            -0.17 | False     | False         |
| form_months_p20 |         -0.13 |              0.15 |            -0.26 | False     | False         |
| skip_days_m20   |         -0.04 |              0.31 |            -0.17 | False     | True          |
| skip_days_p20   |         -0.04 |              0.34 |            -0.18 | False     | True          |
| q_m20           |         -0.04 |              0.37 |            -0.17 | False     | True          |
| q_p20           |         -0.07 |              0.30 |            -0.22 | False     | True          |
| all_m20         |          0.04 |              0.14 |            -0.10 | False     | False         |
| all_p20         |         -0.17 |              0.14 |            -0.31 | False     | False         |

## Data-affected caveats (read before the numbers)

**Earnings timing: none of the three strategies (residual momentum, BAB / low vol, industry momentum) uses earnings dates, earnings surprises or announcement timing.** The known earnings defects in the store (intraday earnings dated a day late; earnings and predecessor history missing for many former members; see validation/backtests/pead_long_pit/data_issues.json) therefore do not enter any signal here. The other defects do, as below.

### 1. Missing delisting returns (material for long books). Table below is from the bugged 01:47 run; base-column resmom figures are withdrawn

Dmitri's `data/universe/delisting_returns.parquet` has terminal returns only for deals matched in Alpaca's corporate-action feed (which starts 2020-04). Of the 120 stocks whose bars end before the sample end, 47 have a terminal return and 73 do not (they cannot be told apart as merger vs performance delisting from the data available, so they are treated as performance-related in the stress). Base runs treat a held position whose bars stop as cash at the last close (0%). Sensitivity (base params, next-open fills, each logged as a data_alt trial):
- **table**: matched terminal return where known, else 0%;
- **conservative**: matched terminal return where known, else **-30% on both legs** (Victor's suggested assumption; shorts gain);
- **adverse**: matched where known, else -30% on longs and **+30% on shorts** (takeover-premium case; worst for every book).

| book | delisting events while held (long / short) | net SR base | table | conservative | adverse | net ann base | ann conservative | ann adverse |
|---|---|---|---|---|---|---|---|---|
| resmom_ls | 38 (24 / 14) | -0.07 | -0.07 | -0.08 | -0.12 | -0.88% | -0.99% | -1.51% |
| resmom_long | 25 (25 / 0) | 0.61 | 0.61 | 0.58 | 0.58 | 11.19% | 10.80% | 10.80% |
| totmom_ls | 43 (30 / 13) | -0.07 | -0.07 | -0.08 | -0.10 | -1.45% | -1.77% | -2.17% |

Per-event detail (symbol, weight held, last bar, return applied in the base run = 0): `delisting_exits_<book>.csv`. Victor's file lists 120 delisting rows (47 matched, 70 no deal, 3 acquirer price missing); pre-2020 delistings have no terminal return at all, so the 2016-2019 part of every book is the most exposed.

### 2. Ticker reuse (SNDK and others)

- AA membership interval 2016-01-04 to 2016-11-01: excluded. member until 2016-11-01 was Alcoa Inc. (renamed Arconic/ARNC); the AA bars from 2016-10 are the new Alcoa Corp. spin-off (when-issued). Interval excluded.
- FOSL membership interval 2016-01-04 to 2016-01-05: excluded. no bars for this interval
- Q membership interval 2017-08-29 to 2017-11-15: excluded. member 2017-08..11 was Quintiles IMS; the Q bars (from 2025-11) are a different company. Interval excluded.
- SNDK membership interval 2016-01-04 to 2016-05-13: excluded. old SanDisk (member until 2016-05-13) has no bars; SNDK bars are the new Sandisk (listed 2025-02, member from 2025-11-28). Old interval excluded, new interval kept.
- Every membership interval is mapped to the symbol's bars (`_common/desk_data.validate_intervals`, output `results/membership_intervals_coverage.csv`); a name is eligible at a signal date only if it is a PIT member in a kept interval AND has a bar on that date. The SNDK interval from 2025-11-28 maps to the new Sandisk bars and is kept. Dmitri's fixes for POM, SPLS, NFX, APC, CA, CSRA, DNB, TE (former members cut at the first gap > 10 sessions) are inherited.

### 3. Former / renamed members missing price history while in the index (verified 2026-10-30 02:26 SGT)

Source: `results/membership_intervals_coverage.csv` (return basis) and `results/membership_intervals_coverage_bars.csv` (bar basis).

**Membership source.** PIT membership is Dmitri's rebuild from Wikipedia's crowd-sourced "Historical components of the S&P 500" change log (plus the current-constituents snapshot). It has **not** been checked against S&P DJI's official constituent history, which is paid. Dmitri logs 26 internal inconsistencies, mostly unrecorded ticker renames (`universe/sp500_membership_anomalies.parquet`).

**Member-days without data (return basis, which is what the strategies see).**
- 7,186 of 1,375,021 PIT member-sessions are missing (0.52%), spread over **538** kept membership intervals (538 different symbols).
- 531 of the 538 intervals miss only 1 to 6 sessions; 483 miss exactly one.
- **7 symbols account for 6,563 of the 7,186 (91.3%):** SKYD 2,413, BBWI 1,406, VTRS 1,226, LIN 714, APTV 475, FTI 262, UAA 67. In each case the predecessor ticker's history is missing: PARA/VIAC for SKYD, L Brands for BBWI, Mylan for VTRS, Praxair for LIN, Delphi for APTV, FMC Technologies for FTI, and UA's class history for UAA.
- Correction to that framing: most of the one-session intervals are **not missing prices**. 461 are 2016-01-04, the first session of the data, where a return cannot be computed. Most of the rest are a new listing's first day (e.g. CARR, OTIS, CEG, GEV). The bars exist.
- On a bar (price) basis, 6,660 member-sessions are missing (0.48%) in **56** intervals. The same 7 symbols account for 98.4% of them. The other 49 intervals miss 1 to 5 sessions, mostly at the end of a company's life, where trading stopped a few days before the index deletion (e.g. SIVB, FRC, SBNY, CTLT).

**Month-end rebalance dates.** The **14 symbols** are those that are PIT members on at least one month-end signal date without a bar: AET, AMTM, APTV, BBWI, BCR, COL, CTXS, FTI, INFO, LIN, SKYD, TWTR, UAA, VTRS. Those member-dates are simply out of the universe, which is a survivorship-type bias. By year:

| year | member month-ends | without bar | share |
|---|---|---|---|
| 2016 | 5574 | 68 | 1.22% |
| 2017 | 6086 | 59 | 0.97% |
| 2018 | 6077 | 48 | 0.79% |
| 2019 | 6072 | 36 | 0.59% |
| 2020 | 6072 | 34 | 0.56% |
| 2021 | 6072 | 19 | 0.31% |
| 2022 | 6056 | 15 | 0.25% |
| 2023 | 6048 | 12 | 0.20% |
| 2024 | 6049 | 13 | 0.21% |
| 2025 | 6048 | 7 | 0.12% |
| 2026 | 5032 | 0 | 0.00% |

(Partial-coverage intervals: see the two CSVs above.)

### 4. Other data items
- PIT shares outstanding: in progress. All books are equal-weighted; the papers' value-weighted variants (and the FP BAB / Moskowitz-Grinblatt VW industry returns) cannot be run yet.
- Suspect corporate-action days: 12 stock-days with |return| > 40% on split / other-action / TR-mismatch days set to 0 (`results/suspect_returns.csv`); the no-clean run is logged (SR in the details).
- PIT borrow / ETB history does not exist (snapshots from 2026-10-29): §5 exclusion of unborrowable names is not applied historically; all shorts pay 1%/yr. Hard-to-borrow failed names on the short side are therefore flattered.
- PIT GICS codes for former members: 0% coverage, so stock-level industry momentum is blocked.
- The store is still being written (symbol count changed 772 -> 774 during the sprint); results are tied to the file mtimes above.
