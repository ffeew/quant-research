# Validation submission: Betting against beta / low volatility (Frazzini & Pedersen 2014)

> **Status: FAILED** (the validator, 2026-10-30; validation/replication_checks/2026-10-30-dave-replications.md). Corrections applied 2026-10-30 02:26 SGT after his check.

Submitted by the derivatives researcher (Quant Research) to the validator, 2026-10-30 01:47 SGT. Built against validation/STANDARD.md v1.0. Self-assessment only; the verdict is the validator's.

## Reproduce (one command)
```
$QR_DESK_DIR/research/replication/.venv/bin/python $QR_DESK_DIR/research/replication/run_all.py --only bab
```
Code: `research/replication/frazzini-pedersen-2014-betting-against-beta/pipeline.py`, `_common/engine.py` (fills, costs, borrow), `_common/validation.py` (DSR, PBO, NW, walk-forward), `run_all.py`. Env: `research/replication/.venv` (`requirements.lock.txt`).
Data snapshot: data owner SIP total_return ret_total_best (clean), fingerprint c50abc068669d327; file mtimes {"daily_total_return.parquet": "2026-10-30 01:32:38 SGT", "sp500_membership.parquet": "2026-10-30 01:31:38 SGT", "ff3_daily.parquet": "2026-10-30 01:10:57 SGT"}. Trial log: `research/replication/TRIAL_LOG.csv`; T x N daily net matrix: `research/replication/results/trials_daily_net_*.parquet`.

## Codified rules
See the docstring of `pipeline.py` (copied below). No discretion, no overrides.
```
BAB / low volatility (Frazzini & Pedersen 2014) on the data owner's SIP total returns, PIT S&P 500. The derivatives researcher, 2026-10-30 (v2).
Codified rules (base params; perturbed +/-20% in the sensitivity grid):
  Universe at month-end t: PIT S&P 500 members with a bar on t. Market = SPY total return.
  Beta (FP sec. 3.1): sigma_i, sigma_m = std of daily log returns over vol_days (252, >= 120 obs);
       rho = corr of overlapping 3-day log returns over corr_years (5; >= 750 obs, FP's minimum);
       beta_TS = rho*sigma_i/sigma_m; beta = shrink*beta_TS + (1-shrink)*1 (shrink 0.6).
       (Desk data starts 2016-01 -> the 750-obs minimum delays the first signal to ~2019-01.)
  Books: bab_fp  = rank-weighted legs (w ∝ |rank - mean rank|), each leg levered to ex-ante beta 1:
                   h = wL/beta_L - wH/beta_H (net long, financed at rf; NEEDS LEVERAGE: long leg gross = 1/beta_L);
         bab_q   = EW bottom-q minus top-q beta, dollar-neutral (q = 0.2);
         lowvol_long = EW lowest-q 1y total volatility (vol_days), long-only, excess of rf.
  Rebalance monthly; fill next session's open (engine). Ex-ante book beta and leg leverage are recorded per rebalance.
```
Execution: signal at the close of the last session of each month; market-on-open fill at the next session's open; costs TCA owner v1.1 max validator floor; borrow 1.00%/yr; book $100,000; 2x stress doubles costs and borrow. Primary (pre-specified, paper-faithful) book: **bab_fp**; secondary books: lowvol_long, bab_q.

## Headline (base parameters, next-open fills, full desk sample)

| book | start | net SR | gross SR | net SR 2x | net ann | t (NW) | maxDD | alpha vs SPY (ann, t) | beta SPY | FF3+UMD alpha (ann, t) | WF-OOS SR (yrs) | DSR fam (N) | PBO grid |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bab_fp | 2019-02-01 | -0.30 | -0.23 | -0.37 | -5.6% | -0.88 | -55.1% | -2.5% (-0.39) | -0.22 | -7.3% (-1.19) | -0.19 (5.3) | 0.00 (59) | 0.30 |
| lowvol_long | 2016-08-02 | 0.50 | 0.53 | 0.48 | 7.3% | 1.80 | -35.1% | -1.0% (-0.33) | 0.63 | -2.4% (-0.83) | 0.45 (7.1) | 0.06 (59) | 0.77 |
| bab_q | 2019-02-01 | -0.46 | -0.40 | -0.52 | -13.3% | -1.35 | -80.2% | -1.4% (-0.17) | -0.84 | -7.8% (-1.07) | -0.37 (5.3) | 0.00 (59) | 0.36 |

![equity curve](equity_curve.png)

## STANDARD.md checklist for the primary book (bab_fp)

| requirement | status | evidence |
|---|---|---|
| §1 artefacts: rules, one-command code, trial log + TxN matrix, report/equity curve/trade list | MET | files listed above |
| §2 PIT universe incl. delisted names | MET (with caveat) | PIT S&P 500 membership incl. 220 former members; ticker-reuse intervals (SNDK, AA, Q) excluded. Delisting returns only partly available: 52 held positions hit a delisting; base = cash at last close; conservative-delisting SR -0.30, adverse -0.31 (see Data-affected caveats) |
| §2 SIP volume, adjusted total-return prices | MET | SIP; ret_total_best; 12 suspect corporate-action days zeroed (results/suspect_returns.csv); no-clean SR -0.30 |
| §2 no look-ahead / next-bar open fills | MET | signal at close t, fill at open t+1. Next-close alt SR -0.32 |
| §2 history >= 10 years | NOT MET | bars 2016-01..2026-10 (10.8y) but lookbacks leave 7.7y of strategy returns |
| §3 OOS: walk-forward >= 5 folds spanning >= 3y, embargo >= 1 rebalance | MET | 6 annual folds, 5.3y OOS, 21-session embargo; selection over the +/-20% grid. Caveat: the period was not untouched (v1 runs at 01:21 SGT and turn-1 runs on 2020+ IEX data are in the trial log) |
| §3 >= 30 independent OOS rebalance periods | MET | 64 OOS months |
| §4 OOS Sharpe net > 0.5 | NOT MET | WF-OOS net SR -0.19; full-sample net SR -0.30 |
| §4/§5 Sharpe > 0 at 2x costs | NOT MET | full -0.37, WF-OOS -0.26 |
| §4 DSR >= 0.95 | NOT MET | family N=59: DSR 0.000, SR0 0.99 ann; all-derivatives-researcher N=184: DSR 0.000, SR0 1.06; T=1946, skew -0.30, kurt 7.75 |
| §4 t-stat >= 2.8 (replication of published anomaly; NW) | NOT MET | t_NW -0.88 (iid -0.84) |
| §4 PBO < 0.20 (<= 0.05 for PASS) | NOT MET | book grid PBO 0.30 (N=11); whole family PBO 0.00 (N=33). N~11 per grid -> weakly informative |
| §5 costs >= validator minimums; borrow >= 1%/yr; exclude unborrowable | MET (borrow caveat) | avg 15.6 bps/side (TCA-owner-only 12.5); borrow 1%/yr; no PIT borrow history exists, so unborrowable names cannot be excluded at signal time |
| §6 post-publication haircut | computed | expected SR for sizing = min(WF-OOS -0.19, 0.40 x 0.70) = -0.19 (AQR BAB USA 1930-12..2012-03 (post_pub_checks.csv), proxy for the paper's US BAB) |
| §7 no year > 40% of PnL | NOT MET | max year share n/a (n/a if total PnL <= 0) |
| §7 no regime Sharpe < -0.5 | NOT MET | worst regime SR -0.96 |
| §7 +/-20% neighbourhood: SR > 0 and >= 50% of base | NOT MET | 0/11 configs pass on full-sample net SR; 0/11 on 2022+ net SR |
| §7 legs reported; correlation to book | MET (book history 1 day) | long leg gross SR 0.47, short leg gross SR -0.60; desk book has 1 day of history, so correlations are vs SPY/FF factors and the validator's validation backtests |
| §8 trade size <= 1% of 20d ADV | MET | max 0.0043% at $100,000; at 10x book max 0.043% |
| §8 break-even cost >= 2x assumed | NOT MET | break-even -119.9 bps/side vs assumed 15.6 |

**Self-assessed verdict: FAIL** (10 requirement(s) not met: §2 history >= 10 years; §4 OOS Sharpe net > 0.5; §4/§5 Sharpe > 0 at 2x costs; §4 DSR >= 0.95; §4 t-stat >= 2.8 (replication of published anomaly; NW); §4 PBO < 0.20 (<= 0.05 for PASS); §7 no year > 40% of PnL; §7 no regime Sharpe < -0.5; §7 +/-20% neighbourhood: SR > 0 and >= 50% of base; §8 break-even cost >= 2x assumed). A FAIL is a verdict on evidence.

## Details per book

### bab_fp

- Net {"start": "2019-02-01", "end": "2026-10-28", "T": 1946, "ann_ret": -0.0562, "ann_vol": 0.1871, "sharpe": -0.3006, "t_nw": -0.8788, "t_iid": -0.8353, "max_dd": -0.5514, "skew": -0.2995, "kurt": 7.7531}
- Gross SR -0.23, 2x-cost SR -0.37; long leg gross SR 0.47 (ann 9.1%), short leg gross SR -0.60 (ann -13.4%).
- Market: {"alpha_ann_vs_spy": -0.025, "alpha_t_nw_vs_spy": -0.386, "beta_spy": -0.221, "beta_t_nw": -2.409, "beta_neutral_test": "NOT beta-neutral", "alpha_sharpe_vs_spy": -0.138, "alpha_ann_ff4": -0.073, "alpha_t_nw_ff4": -1.194, "load_Mkt-RF": -0.133, "load_SMB": -0.477, "load_HML": -0.065, "load_UMD": 0.204}
- Gross-return beta vs SPY -0.22, gross alpha vs SPY -1.2% (t -0.18).
- Turnover/costs: {"traded_per_yr_x_nav": 3.562, "avg_gross_exposure": 2.093, "oneway_turnover_per_yr_of_gross": 0.851, "avg_holding_months": 14.099, "gross_ret_per_unit_traded_bps": -119.948, "breakeven_cost_bps_per_side": -119.948, "assumed_avg_cost_bps_per_side": 15.597, "tomas_only_avg_cost_bps": 12.476, "breakeven_over_assumed": -7.691, "cost_drag_ann": 0.006, "borrow_drag_ann": 0.008, "avg_long_mv": 1.311, "avg_short_mv": 0.782}
- Capacity: {"book_usd": 100000.0, "max_participation": 4e-05, "p99_participation": 0.0, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.00043, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR -0.19, t_NW -0.44, folds 6, picks ['all_p20', 'all_p20', 'shrink_p20', 'shrink_p20', 'all_p20', 'all_p20'], 2x SR -0.26
- DSR (family N=59): 0.000; DSR (all derivatives researcher trials N=184): 0.000
- PBO grid 0.30 (N=11), family 0.00 (N=33)
- Alt trials: next-close fill SR -0.32; no-clean data SR -0.30; delisting returns table/conservative/adverse SR -0.30 / -0.30 / -0.31
- Delisting exits while held: 52 (SCG, NFX, LLL, RHT, APC, TSS, CELG, VIAB, STI, WCG, RTN, AGN...)
- Correlations: {"SPY": -0.22, "FF_Mkt-RF": -0.24, "FF_SMB": -0.38, "FF_HML": -0.11, "FF_UMD": 0.32, "validation_backtest_MOM_monthly_LS": 0.04, "validation_backtest_PEAD_raw_LS": -0.14, "validation_backtest_PEAD_trend_LS": -0.13, "validation_backtest_MOM_bracket_LS": 0.11}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2019 |  0.011 |     0.019 |    0.153 | 231.000 |                  nan |
|   2020 | -0.164 |    -0.135 |   -0.456 | 253.000 |                  nan |
|   2021 | -0.016 |    -0.004 |   -0.027 | 252.000 |                  nan |
|   2022 |  0.053 |     0.067 |    0.388 | 251.000 |                  nan |
|   2023 | -0.216 |    -0.233 |   -1.663 | 250.000 |                  nan |
|   2024 |  0.005 |     0.011 |    0.103 | 252.000 |                  nan |
|   2025 | -0.156 |    -0.149 |   -0.746 | 250.000 |                  nan |
|   2026 | -0.030 |    -0.010 |   -0.053 | 207.000 |                  nan |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   1606 |     -0.02 |    -0.11 |
| SPY<200dma  |    340 |     -0.23 |    -0.96 |
| VIX>median  |    972 |     -0.17 |    -0.79 |
| VIX<=median |    973 |      0.06 |     0.41 |
| VIX>25      |    346 |     -0.14 |    -0.57 |
| VIX<=25     |   1599 |     -0.04 |    -0.21 |

+/-20% neighbourhood (net SR):

| param_tag      |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:---------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base           |         -0.30 |             -0.38 |            -0.37 | False     | False         |
| vol_days_m20   |         -0.28 |             -0.37 |            -0.35 | False     | False         |
| vol_days_p20   |         -0.30 |             -0.40 |            -0.37 | False     | False         |
| corr_years_m20 |         -0.28 |             -0.34 |            -0.35 | False     | False         |
| corr_years_p20 |         -0.30 |             -0.39 |            -0.38 | False     | False         |
| shrink_m20     |         -0.35 |             -0.40 |            -0.42 | False     | False         |
| shrink_p20     |         -0.25 |             -0.36 |            -0.32 | False     | False         |
| q_m20          |         -0.30 |             -0.38 |            -0.37 | False     | False         |
| q_p20          |         -0.30 |             -0.38 |            -0.37 | False     | False         |
| all_m20        |         -0.30 |             -0.35 |            -0.38 | False     | False         |
| all_p20        |         -0.26 |             -0.39 |            -0.32 | False     | False         |

### lowvol_long

- Net {"start": "2016-08-02", "end": "2026-10-28", "T": 2575, "ann_ret": 0.0734, "ann_vol": 0.1457, "sharpe": 0.5038, "t_nw": 1.8013, "t_iid": 1.6105, "max_dd": -0.3507, "skew": -0.7579, "kurt": 28.5449}
- Gross SR 0.53, 2x-cost SR 0.48; long leg gross SR 0.53 (ann 7.7%), short leg gross SR n/a (ann n/a).
- Market: {"alpha_ann_vs_spy": -0.01, "alpha_t_nw_vs_spy": -0.326, "beta_spy": 0.634, "beta_t_nw": 11.144, "beta_neutral_test": "NOT beta-neutral", "alpha_sharpe_vs_spy": -0.102, "alpha_ann_ff4": -0.024, "alpha_t_nw_ff4": -0.829, "load_Mkt-RF": 0.648, "load_SMB": -0.232, "load_HML": 0.182, "load_UMD": 0.013}
- Gross-return beta vs SPY 0.63, gross alpha vs SPY -0.6% (t -0.22).
- Turnover/costs: {"traded_per_yr_x_nav": 2.086, "avg_gross_exposure": 1.0, "oneway_turnover_per_yr_of_gross": 1.043, "avg_holding_months": 11.503, "gross_ret_per_unit_traded_bps": 367.218, "breakeven_cost_bps_per_side": 367.218, "assumed_avg_cost_bps_per_side": 15.389, "tomas_only_avg_cost_bps": 11.003, "breakeven_over_assumed": 23.862, "cost_drag_ann": 0.003, "borrow_drag_ann": 0.0, "avg_long_mv": 1.0, "avg_short_mv": 0.0}
- Capacity: {"book_usd": 100000.0, "max_participation": 5e-05, "p99_participation": 1e-05, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.00049, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR 0.45, t_NW 1.32, folds 8, picks ['vol_days_p20', 'vol_days_p20', 'vol_days_m20', 'vol_days_m20', 'base', 'base', 'vol_days_m20', 'vol_days_m20'], 2x SR 0.43
- DSR (family N=59): 0.064; DSR (all derivatives researcher trials N=184): 0.041
- PBO grid 0.77 (N=11), family 0.00 (N=33)
- Alt trials: next-close fill SR 0.50; no-clean data SR 0.50; delisting returns table/conservative/adverse SR 0.50 / 0.49 / 0.49
- Delisting exits while held: 15 (TE, GAS, EMC, MON, TWX, COL, AET, AGN, TIF, CERN, JNPR, K...)
- Correlations: {"SPY": 0.76, "FF_Mkt-RF": 0.76, "FF_SMB": 0.03, "FF_HML": 0.09, "FF_UMD": -0.07, "validation_backtest_MOM_monthly_LS": -0.03, "validation_backtest_PEAD_raw_LS": -0.44, "validation_backtest_PEAD_trend_LS": -0.43, "validation_backtest_MOM_bracket_LS": -0.01}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2016 | -0.015 |    -0.013 |   -0.317 | 106.000 |               -0.018 |
|   2017 |  0.176 |     0.164 |    2.880 | 251.000 |                0.218 |
|   2018 | -0.018 |    -0.011 |   -0.085 | 251.000 |               -0.014 |
|   2019 |  0.236 |     0.217 |    2.309 | 252.000 |                0.289 |
|   2020 |  0.057 |     0.105 |    0.333 | 253.000 |                0.140 |
|   2021 |  0.235 |     0.216 |    2.041 | 252.000 |                0.288 |
|   2022 | -0.042 |    -0.029 |   -0.171 | 251.000 |               -0.038 |
|   2023 | -0.044 |    -0.040 |   -0.373 | 250.000 |               -0.053 |
|   2024 |  0.086 |     0.086 |    0.960 | 252.000 |                0.115 |
|   2025 | -0.017 |    -0.008 |   -0.062 | 250.000 |               -0.011 |
|   2026 |  0.059 |     0.063 |    0.697 | 207.000 |                0.083 |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2117 |      0.08 |     0.75 |
| SPY<200dma  |    458 |      0.05 |     0.19 |
| VIX>median  |   1283 |      0.07 |     0.37 |
| VIX<=median |   1291 |      0.08 |     0.93 |
| VIX>25      |    363 |      0.10 |     0.32 |
| VIX<=25     |   2211 |      0.07 |     0.71 |

+/-20% neighbourhood (net SR):

| param_tag      |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:---------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base           |          0.50 |              0.12 |             0.48 | True      | True          |
| vol_days_m20   |          0.51 |              0.12 |             0.49 | True      | True          |
| vol_days_p20   |          0.49 |              0.10 |             0.47 | True      | True          |
| corr_years_m20 |          0.50 |              0.12 |             0.48 | True      | True          |
| corr_years_p20 |          0.50 |              0.12 |             0.48 | True      | True          |
| shrink_m20     |          0.50 |              0.12 |             0.48 | True      | True          |
| shrink_p20     |          0.50 |              0.12 |             0.48 | True      | True          |
| q_m20          |          0.47 |              0.10 |             0.44 | True      | True          |
| q_p20          |          0.48 |              0.10 |             0.45 | True      | True          |
| all_m20        |          0.49 |              0.12 |             0.46 | True      | True          |
| all_p20        |          0.49 |              0.11 |             0.47 | True      | True          |

### bab_q

- Net {"start": "2019-02-01", "end": "2026-10-28", "T": 1946, "ann_ret": -0.1327, "ann_vol": 0.2871, "sharpe": -0.4624, "t_nw": -1.3514, "t_iid": -1.2849, "max_dd": -0.8022, "skew": -0.3475, "kurt": 8.7939}
- Gross SR -0.40, 2x-cost SR -0.52; long leg gross SR 0.47 (ann 6.8%), short leg gross SR -0.58 (ann -18.3%).
- Market: {"alpha_ann_vs_spy": -0.014, "alpha_t_nw_vs_spy": -0.171, "beta_spy": -0.844, "beta_t_nw": -7.332, "beta_neutral_test": "NOT beta-neutral", "alpha_sharpe_vs_spy": -0.059, "alpha_ann_ff4": -0.078, "alpha_t_nw_ff4": -1.068, "load_Mkt-RF": -0.704, "load_SMB": -0.67, "load_HML": -0.261, "load_UMD": 0.317}
- Gross-return beta vs SPY -0.84, gross alpha vs SPY 0.4% (t 0.04).
- Turnover/costs: {"traded_per_yr_x_nav": 5.189, "avg_gross_exposure": 2.033, "oneway_turnover_per_yr_of_gross": 1.276, "avg_holding_months": 9.402, "gross_ret_per_unit_traded_bps": -221.544, "breakeven_cost_bps_per_side": -221.544, "assumed_avg_cost_bps_per_side": 14.224, "tomas_only_avg_cost_bps": 10.196, "breakeven_over_assumed": -15.575, "cost_drag_ann": 0.007, "borrow_drag_ann": 0.01, "avg_long_mv": 1.012, "avg_short_mv": 1.021}
- Capacity: {"book_usd": 100000.0, "max_participation": 7e-05, "p99_participation": 1e-05, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.00066, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR -0.37, t_NW -0.88, folds 6, picks ['q_m20', 'q_m20', 'q_m20', 'q_m20', 'all_m20', 'all_m20'], 2x SR -0.43
- DSR (family N=59): 0.000; DSR (all derivatives researcher trials N=184): 0.000
- PBO grid 0.36 (N=11), family 0.00 (N=33)
- Alt trials: next-close fill SR -0.48; no-clean data SR -0.45; delisting returns table/conservative/adverse SR -0.46 / -0.46 / -0.47
- Delisting exits while held: 23 (SCG, NFX, APC, AGN, ETFC, NBL, TIF, XLNX, CERN, CTXS, FBHS, ABMD...)
- Correlations: {"SPY": -0.55, "FF_Mkt-RF": -0.57, "FF_SMB": -0.44, "FF_HML": -0.16, "FF_UMD": 0.38, "validation_backtest_MOM_monthly_LS": 0.07, "validation_backtest_PEAD_raw_LS": 0.03, "validation_backtest_PEAD_trend_LS": 0.04, "validation_backtest_MOM_bracket_LS": 0.11}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2019 | -0.100 |    -0.089 |   -0.519 | 231.000 |                  nan |
|   2020 | -0.298 |    -0.240 |   -0.505 | 253.000 |                  nan |
|   2021 | -0.186 |    -0.175 |   -0.696 | 252.000 |                  nan |
|   2022 |  0.145 |     0.176 |    0.620 | 251.000 |                  nan |
|   2023 | -0.314 |    -0.354 |   -1.682 | 250.000 |                  nan |
|   2024 | -0.038 |    -0.022 |   -0.123 | 252.000 |                  nan |
|   2025 | -0.209 |    -0.195 |   -0.699 | 250.000 |                  nan |
|   2026 | -0.153 |    -0.126 |   -0.489 | 207.000 |                  nan |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   1606 |     -0.08 |    -0.32 |
| SPY<200dma  |    340 |     -0.36 |    -0.97 |
| VIX>median  |    972 |     -0.33 |    -0.96 |
| VIX<=median |    973 |      0.07 |     0.30 |
| VIX>25      |    346 |     -0.22 |    -0.54 |
| VIX<=25     |   1599 |     -0.11 |    -0.44 |

+/-20% neighbourhood (net SR):

| param_tag      |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:---------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base           |         -0.46 |             -0.42 |            -0.52 | False     | False         |
| vol_days_m20   |         -0.45 |             -0.41 |            -0.52 | False     | False         |
| vol_days_p20   |         -0.45 |             -0.39 |            -0.52 | False     | False         |
| corr_years_m20 |         -0.44 |             -0.37 |            -0.50 | False     | False         |
| corr_years_p20 |         -0.47 |             -0.43 |            -0.53 | False     | False         |
| shrink_m20     |         -0.46 |             -0.42 |            -0.52 | False     | False         |
| shrink_p20     |         -0.46 |             -0.42 |            -0.52 | False     | False         |
| q_m20          |         -0.43 |             -0.40 |            -0.49 | False     | False         |
| q_p20          |         -0.48 |             -0.42 |            -0.55 | False     | False         |
| all_m20        |         -0.42 |             -0.35 |            -0.48 | False     | False         |
| all_p20        |         -0.47 |             -0.42 |            -0.53 | False     | False         |

### BAB beta neutrality and leverage actually applied (ex-ante, base params, per rebalance; averages and ranges, not limits)

|                    |   mean |   min |   max |
|:-------------------|-------:|------:|------:|
| beta_L             |   0.77 |  0.65 |  0.92 |
| beta_H             |   1.32 |  1.08 |  1.69 |
| lev_long_leg       |   1.30 |  1.09 |  1.53 |
| lev_short_leg      |   0.77 |  0.59 |  0.93 |
| fp_gross           |   2.07 |  1.73 |  2.39 |
| fp_net             |   0.53 |  0.43 |  0.74 |
| fp_exante_beta     |  -0.00 | -0.00 |  0.00 |
| q_exante_beta      |  -0.68 | -1.18 | -0.48 |
| lowvol_exante_beta |   0.78 |  0.67 |  0.95 |

bab_fp is ex-ante beta-neutral by construction: each leg is scaled to beta 1 (h = wL/βL − wH/βH), and ex-ante book beta is 0 at every rebalance. **The leverage figures are what was actually applied, not a limit.** There is no leverage cap in the code. On the low-beta (long) leg, leverage averaged **1.30x** (range 1.09x–1.53x per rebalance) and was applied in full. Total gross averaged 2.07x NAV (max 2.39x) and net long averaged 0.53x, financed at rf. As specified, this breaches the desk's no-leverage rule. Realised beta vs SPY was −0.22 despite the ex-ante 0 (an outcome, not a coding error). **No unlevered beta-neutral version was run** (e.g. long leg at 1.0x and short leg scaled to βL/βH). The validator's rough rescaling of the saved series suggests a Sharpe near −0.26, but that is an approximation, not a run. The unlevered book that *was* run, bab_q (EW bottom-minus-top quintile), is dollar-neutral and NOT beta-neutral (ex-ante beta −0.68, realised −0.84).

## Data-affected caveats (read before the numbers)

**Earnings timing: none of the three strategies (residual momentum, BAB / low vol, industry momentum) uses earnings dates, earnings surprises or announcement timing.** The known earnings defects in the store (intraday earnings dated a day late; earnings and predecessor history missing for many former members; see validation/backtests/pead_long_pit/data_issues.json) therefore do not enter any signal here. The other defects do, as below.

### 1. Missing delisting returns (material for long books)

The data owner's `data/universe/delisting_returns.parquet` has terminal returns only for deals matched in Alpaca's corporate-action feed (which starts 2020-04). Of the 120 stocks whose bars end before the sample end, 47 have a terminal return and 73 do not (they cannot be told apart as merger vs performance delisting from the data available, so they are treated as performance-related in the stress). Base runs treat a held position whose bars stop as cash at the last close (0%). Sensitivity (base params, next-open fills, each logged as a data_alt trial):
- **table**: matched terminal return where known, else 0%;
- **conservative**: matched terminal return where known, else **-30% on both legs** (the validator's suggested assumption; shorts gain);
- **adverse**: matched where known, else -30% on longs and **+30% on shorts** (takeover-premium case; worst for every book).

| book | delisting events while held (long / short) | net SR base | table | conservative | adverse | net ann base | ann conservative | ann adverse |
|---|---|---|---|---|---|---|---|---|
| bab_fp | 52 (25 / 27) | -0.30 | -0.30 | -0.30 | -0.31 | -5.62% | -5.57% | -5.87% |
| lowvol_long | 15 (15 / 0) | 0.50 | 0.50 | 0.49 | 0.49 | 7.34% | 7.16% | 7.16% |
| bab_q | 23 (12 / 11) | -0.46 | -0.46 | -0.46 | -0.47 | -13.27% | -13.13% | -13.52% |

Per-event detail (symbol, weight held, last bar, return applied in the base run = 0): `delisting_exits_<book>.csv`. The validator's file lists 120 delisting rows (47 matched, 70 no deal, 3 acquirer price missing); pre-2020 delistings have no terminal return at all, so the 2016-2019 part of every book is the most exposed.

### 2. Ticker reuse (SNDK and others)

- AA membership interval 2016-01-04 to 2016-11-01: excluded. member until 2016-11-01 was Alcoa Inc. (renamed Arconic/ARNC); the AA bars from 2016-10 are the new Alcoa Corp. spin-off (when-issued). Interval excluded.
- FOSL membership interval 2016-01-04 to 2016-01-05: excluded. no bars for this interval
- Q membership interval 2017-08-29 to 2017-11-15: excluded. member 2017-08..11 was Quintiles IMS; the Q bars (from 2025-11) are a different company. Interval excluded.
- SNDK membership interval 2016-01-04 to 2016-05-13: excluded. old SanDisk (member until 2016-05-13) has no bars; SNDK bars are the new Sandisk (listed 2025-02, member from 2025-11-28). Old interval excluded, new interval kept.
- Every membership interval is mapped to the symbol's bars (`_common/desk_data.validate_intervals`, output `results/membership_intervals_coverage.csv`); a name is eligible at a signal date only if it is a PIT member in a kept interval AND has a bar on that date. The SNDK interval from 2025-11-28 maps to the new Sandisk bars and is kept. The data owner's fixes for POM, SPLS, NFX, APC, CA, CSRA, DNB, TE (former members cut at the first gap > 10 sessions) are inherited.

### 3. Former / renamed members missing price history while in the index (verified 2026-10-30 02:26 SGT)

Source: `results/membership_intervals_coverage.csv` (return basis) and `results/membership_intervals_coverage_bars.csv` (bar basis).

**Membership source.** PIT membership is the data owner's rebuild from Wikipedia's crowd-sourced "Historical components of the S&P 500" change log (plus the current-constituents snapshot). It has **not** been checked against S&P DJI's official constituent history, which is paid. Data owner logs 26 internal inconsistencies, mostly unrecorded ticker renames (`universe/sp500_membership_anomalies.parquet`).

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
