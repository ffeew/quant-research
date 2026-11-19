# Validation submission: Industry momentum (Moskowitz & Grinblatt 1999), sector-ETF version

> **Status: FAILED** (the validator, 2026-10-30; validation/replication_checks/2026-10-30-dave-replications.md). Corrections applied 2026-10-30 02:26 SGT after his check.

Submitted by the derivatives researcher (Quant Research) to the validator, 2026-10-30 01:47 SGT. Built against validation/STANDARD.md v1.0. Self-assessment only; the verdict is the validator's.

**Scope: ETF version only.** This tests 11 SPDR sector ETFs, 3 per side (about 27% of the sectors on each side; XLC only from 2018-06, which also changed the other sectors' composition). The paper uses 20 value-weighted industries, 3 per side (15%). **The paper-faithful 20-industry (stock-level) result on desk data is unknown.** It cannot be built without point-in-time industry codes for former S&P 500 members (0% coverage). Using current GICS would add survivorship bias, so it was not run. The FAIL applies to the ETF implementation only. For context, the FF49 VW J6/K6 public check for 2016 onward is gross SR 0.28 (t 0.93). Book definitions: imom_etf_ls holds 6 overlapping monthly cohorts (J=6/K=6); **imom_etf_long and imom_etf_ls_1m are rebalanced fully each month (no overlapping cohorts)**. That is why their hold_months ±20% rows are identical to base.

## Reproduce (one command)
```
$QR_DESK_DIR/research/replication/.venv/bin/python $QR_DESK_DIR/research/replication/run_all.py --only imom
```
Code: `research/replication/moskowitz-grinblatt-1999-industry-momentum/pipeline.py`, `_common/engine.py` (fills, costs, borrow), `_common/validation.py` (DSR, PBO, NW, walk-forward), `run_all.py`. Env: `research/replication/.venv` (`requirements.lock.txt`).
Data snapshot: data owner SIP total_return ret_total_best (clean), fingerprint; file mtimes {"daily_total_return.parquet": "2026-10-30 01:32:38 SGT", "sp500_membership.parquet": "2026-10-30 01:31:38 SGT", "ff3_daily.parquet": "2026-10-30 01:10:57 SGT"}. Trial log: `research/replication/TRIAL_LOG.csv`; T x N daily net matrix: `research/replication/results/trials_daily_net_*.parquet`.

## Codified rules
See the docstring of `pipeline.py` (copied below). No discretion, no overrides.
```
Industry momentum (Moskowitz & Grinblatt 1999). The derivatives researcher, 2026-10-30.
Paper: 20 value-weighted industries; long top-3 / short bottom-3 by past 6-month return, hold 6 months (overlapping
portfolios), no skip month in the headline spec.
Desk versions (same engine / costs / reporting as the other two replications):
  A) Sector ETFs: 11 SPDR sector ETFs (XLC from 2018-06, XLRE from 2015-10; an ETF enters once it has 6m of history).
     imom_etf_ls    (PRIMARY): top-3 minus bottom-3 by past form_months return, held hold_months via overlapping
                      monthly cohorts (paper's J=6/K=6); equal weight, dollar-neutral
     imom_etf_ls_1m : same ranking, rebalanced monthly (K=1)
     imom_etf_long  : long-only top-3, rebalanced fully every month (1-month hold, no cohorts; excess of rf)
  B) Stock level (GICS sector portfolios of PIT S&P 500 members, EW within sector; trade the member stocks).
     Requires point-in-time industry codes for former members; gated by coverage (see run_all.py). The data owner's
     universe.parquet has GICS only for current members (as of 2026-10-30) -> blocked unless forced as a diagnostic.
  C) Public pre/post-2016 check: FF 49 industries (VW), J=6/K=6, top-5/bottom-5 (~10% each side), monthly from
     1926 -> splits pre-2016 vs 2016+ (the data owner's data starts 2016).
```
Execution: signal at the close of the last session of each month; market-on-open fill at the next session's open; costs TCA owner v1.1 max validator floor; borrow 1.00%/yr; book $100,000; 2x stress doubles costs and borrow. Primary (pre-specified, paper-faithful) book: **imom_etf_ls**; secondary books: imom_etf_long, imom_etf_ls_1m.

## Headline (base parameters, next-open fills, full desk sample)

| book | start | net SR | gross SR | net SR 2x | net ann | t (NW) | maxDD | alpha vs SPY (ann, t) | beta SPY | FF3+UMD alpha (ann, t) | WF-OOS SR (yrs) | DSR fam (N) | PBO grid |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| imom_etf_ls | 2017-02-02 | 0.02 | 0.12 | -0.08 | 0.2% | 0.05 | -24.3% | 0.1% (0.02) | 0.01 | -3.2% (-1.10) | 0.22 (7.1) | 0.01 (48) | 0.62 |
| imom_etf_long | 2016-08-30 | 0.45 | 0.48 | 0.42 | 8.1% | 1.61 | -31.6% | -3.4% (-1.17) | 0.87 | -4.9% (-1.78) | 0.72 (7.1) | 0.18 (48) | 0.28 |
| imom_etf_ls_1m | 2016-08-30 | -0.33 | -0.19 | -0.46 | -5.2% | -1.07 | -49.9% | -4.6% (-0.94) | -0.05 | -7.4% (-1.76) | 0.32 (7.1) | 0.00 (48) | 0.25 |

![equity curve](equity_curve.png)

## STANDARD.md checklist for the primary book (imom_etf_ls)

| requirement | status | evidence |
|---|---|---|
| §1 artefacts: rules, one-command code, trial log + TxN matrix, report/equity curve/trade list | MET | files listed above |
| §2 PIT universe incl. delisted names | MET (with caveat) | PIT S&P 500 membership incl. 220 former members; ticker-reuse intervals (SNDK, AA, Q) excluded. Delisting returns only partly available: 0 held positions hit a delisting; base = cash at last close; conservative-delisting SR 0.02, adverse 0.02 (see Data-affected caveats) |
| §2 SIP volume, adjusted total-return prices | MET | SIP; ret_total_best; 12 suspect corporate-action days zeroed (results/suspect_returns.csv); no-clean SR 0.02 |
| §2 no look-ahead / next-bar open fills | MET | signal at close t, fill at open t+1. Next-close alt SR 0.04 |
| §2 history >= 10 years | NOT MET | bars 2016-01..2026-10 (10.8y) but lookbacks leave 9.7y of strategy returns |
| §3 OOS: walk-forward >= 5 folds spanning >= 3y, embargo >= 1 rebalance | MET | 8 annual folds, 7.1y OOS, 21-session embargo; selection over the +/-20% grid. Caveat: the period was not untouched (v1 runs at 01:21 SGT and turn-1 runs on 2020+ IEX data are in the trial log) |
| §3 >= 30 independent OOS rebalance periods | MET | 86 OOS months |
| §4 OOS Sharpe net > 0.5 | NOT MET | WF-OOS net SR 0.22; full-sample net SR 0.02 |
| §4/§5 Sharpe > 0 at 2x costs | NOT MET | full -0.08, WF-OOS 0.14 |
| §4 DSR >= 0.95 | NOT MET | family N=48: DSR 0.012, SR0 0.74 ann; all-derivatives-researcher N=184: DSR 0.001, SR0 1.06; T=2448, skew -0.50, kurt 9.07 |
| §4 t-stat >= 2.8 (replication of published anomaly; NW) | NOT MET | t_NW 0.05 (iid 0.05) |
| §4 PBO < 0.20 (<= 0.05 for PASS) | NOT MET | book grid PBO 0.62 (N=9); whole family PBO 0.22 (N=27). N~11 per grid -> weakly informative |
| §5 costs >= validator minimums; borrow >= 1%/yr; exclude unborrowable | MET (borrow caveat) | avg 6.5 bps/side (TCA-owner-only 6.0); borrow 1%/yr; no PIT borrow history exists, so unborrowable names cannot be excluded at signal time |
| §6 post-publication haircut | computed | expected SR for sizing = min(WF-OOS 0.22, 0.40 x 0.51) = 0.20 (set at run time: FF49 VW J6/K6 top5-bot5, 1963-07..1995-07 (MG's sample end), public proxy) |
| §7 no year > 40% of PnL | NOT MET | max year share 924% (n/a if total PnL <= 0) |
| §7 no regime Sharpe < -0.5 | MET | worst regime SR -0.30 |
| §7 +/-20% neighbourhood: SR > 0 and >= 50% of base | NOT MET | 7/9 configs pass on full-sample net SR; 8/9 on 2022+ net SR |
| §7 legs reported; correlation to book | MET (book history 1 day) | long leg gross SR 0.69, short leg gross SR -0.54; desk book has 1 day of history, so correlations are vs SPY/FF factors and the validator's validation backtests |
| §8 trade size <= 1% of 20d ADV | MET | max 0.0190% at $100,000; at 10x book max 0.190% |
| §8 break-even cost >= 2x assumed | MET | break-even 23.8 bps/side vs assumed 6.5 |

**Self-assessed verdict: FAIL** (8 requirement(s) not met: §2 history >= 10 years; §4 OOS Sharpe net > 0.5; §4/§5 Sharpe > 0 at 2x costs; §4 DSR >= 0.95; §4 t-stat >= 2.8 (replication of published anomaly; NW); §4 PBO < 0.20 (<= 0.05 for PASS); §7 no year > 40% of PnL; §7 +/-20% neighbourhood: SR > 0 and >= 50% of base). A FAIL is a verdict on evidence.

## Details per book

### imom_etf_ls

- Net {"start": "2017-02-02", "end": "2026-10-28", "T": 2448, "ann_ret": 0.002, "ann_vol": 0.1268, "sharpe": 0.016, "t_nw": 0.053, "t_iid": 0.0499, "max_dd": -0.2435, "skew": -0.4952, "kurt": 9.072}
- Gross SR 0.12, 2x-cost SR -0.08; long leg gross SR 0.69 (ann 10.1%), short leg gross SR -0.54 (ann -8.6%).
- Market: {"alpha_ann_vs_spy": 0.001, "alpha_t_nw_vs_spy": 0.022, "beta_spy": 0.009, "beta_t_nw": 0.335, "beta_neutral_test": "beta within +/-0.1 and |t|<2", "alpha_sharpe_vs_spy": 0.007, "alpha_ann_ff4": -0.032, "alpha_t_nw_ff4": -1.101, "load_Mkt-RF": 0.055, "load_SMB": -0.038, "load_HML": -0.016, "load_UMD": 0.49}
- Gross-return beta vs SPY 0.01, gross alpha vs SPY 1.3% (t 0.35).
- Turnover/costs: {"traded_per_yr_x_nav": 6.148, "avg_gross_exposure": 1.699, "oneway_turnover_per_yr_of_gross": 1.809, "avg_holding_months": 6.633, "gross_ret_per_unit_traded_bps": 23.833, "breakeven_cost_bps_per_side": 23.833, "assumed_avg_cost_bps_per_side": 6.497, "tomas_only_avg_cost_bps": 6.043, "breakeven_over_assumed": 3.669, "cost_drag_ann": 0.004, "borrow_drag_ann": 0.009, "avg_long_mv": 0.849, "avg_short_mv": 0.85}
- Capacity: {"book_usd": 100000.0, "max_participation": 0.00019, "p99_participation": 8e-05, "share_trades_over_1pct_adv": 0.0, "max_participation_at_10x_book": 0.0019, "share_over_1pct_at_10x": 0.0}
- Walk-forward: SR 0.22, t_NW 0.66, folds 8, picks ['topn_m20', 'topn_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20', 'all_m20'], 2x SR 0.14
- DSR (family N=48): 0.012; DSR (all derivatives researcher trials N=184): 0.001
- PBO grid 0.62 (N=9), family 0.22 (N=27)
- Alt trials: next-close fill SR 0.04; no-clean data SR 0.02; delisting returns table/conservative/adverse SR 0.02 / 0.02 / 0.02
- Delisting exits while held: 0
- Correlations: {"SPY": 0.01, "FF_Mkt-RF": 0.02, "FF_SMB": -0.16, "FF_HML": -0.24, "FF_UMD": 0.72, "validation_backtest_MOM_monthly_LS": 0.47, "validation_backtest_PEAD_raw_LS": -0.06, "validation_backtest_PEAD_trend_LS": 0.04, "validation_backtest_MOM_bracket_LS": 0.39}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2017 | -0.043 |    -0.042 |   -0.794 | 230.000 |               -2.135 |
|   2018 | -0.032 |    -0.026 |   -0.233 | 251.000 |               -1.328 |
|   2019 | -0.004 |     0.000 |    0.003 | 252.000 |                0.015 |
|   2020 |  0.126 |     0.145 |    0.634 | 253.000 |                7.375 |
|   2021 | -0.070 |    -0.065 |   -0.537 | 252.000 |               -3.309 |
|   2022 |  0.187 |     0.182 |    1.242 | 251.000 |                9.237 |
|   2023 | -0.137 |    -0.140 |   -1.119 | 250.000 |               -7.102 |
|   2024 |  0.054 |     0.057 |    0.575 | 252.000 |                2.894 |
|   2025 | -0.024 |    -0.021 |   -0.239 | 250.000 |               -1.045 |
|   2026 | -0.073 |    -0.071 |   -0.790 | 207.000 |               -3.603 |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2044 |     -0.00 |    -0.01 |
| SPY<200dma  |    404 |      0.02 |     0.11 |
| VIX>median  |   1222 |      0.03 |     0.22 |
| VIX<=median |   1225 |     -0.03 |    -0.30 |
| VIX>25      |    363 |      0.11 |     0.60 |
| VIX<=25     |   2084 |     -0.02 |    -0.14 |

+/-20% neighbourhood (net SR):

| param_tag       |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:----------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base            |          0.02 |              0.01 |            -0.08 | True      | True          |
| form_months_m20 |          0.04 |              0.02 |            -0.06 | True      | True          |
| form_months_p20 |          0.17 |              0.37 |             0.08 | True      | True          |
| topn_m20        |          0.17 |              0.23 |             0.08 | True      | True          |
| topn_p20        |         -0.04 |              0.01 |            -0.15 | False     | True          |
| hold_months_m20 |         -0.04 |             -0.15 |            -0.14 | False     | False         |
| hold_months_p20 |          0.09 |              0.20 |            -0.00 | True      | True          |
| all_m20         |          0.12 |              0.02 |             0.02 | True      | True          |
| all_p20         |          0.11 |              0.30 |             0.02 | True      | True          |

### imom_etf_long

- Net {"start": "2016-08-30", "end": "2026-10-28", "T": 2555, "ann_ret": 0.0808, "ann_vol": 0.1796, "sharpe": 0.4501, "t_nw": 1.6128, "t_iid": 1.4332, "max_dd": -0.3162, "skew": -0.5413, "kurt": 15.4471}
- Gross SR 0.48, 2x-cost SR 0.42; long leg gross SR 0.48 (ann 8.6%), short leg gross SR n/a (ann n/a).
- Market: {"alpha_ann_vs_spy": -0.034, "alpha_t_nw_vs_spy": -1.169, "beta_spy": 0.874, "beta_t_nw": 31.457, "beta_neutral_test": "NOT beta-neutral", "alpha_sharpe_vs_spy": -0.366, "alpha_ann_ff4": -0.049, "alpha_t_nw_ff4": -1.783, "load_Mkt-RF": 0.882, "load_SMB": -0.114, "load_HML": 0.219, "load_UMD": 0.183}
- Gross-return beta vs SPY 0.87, gross alpha vs SPY -2.9% (t -0.99).
- Turnover/costs: {"traded_per_yr_x_nav": 7.68, "avg_gross_exposure": 1.0, "oneway_turnover_per_yr_of_gross": 3.84, "avg_holding_months": 3.125, "gross_ret_per_unit_traded_bps": 111.943, "breakeven_cost_bps_per_side": 111.943, "assumed_avg_cost_bps_per_side": 6.823, "tomas_only_avg_cost_bps": 6.507, "breakeven_over_assumed": 16.406, "cost_drag_ann": 0.005, "borrow_drag_ann": 0.0, "avg_long_mv": 1.0, "avg_short_mv": 0.0}
- Capacity: {"book_usd": 100000.0, "max_participation": 0.01765, "p99_participation": 0.00026, "share_trades_over_1pct_adv": 0.00413, "max_participation_at_10x_book": 0.1765, "share_over_1pct_at_10x": 0.00413}
- Walk-forward: SR 0.72, t_NW 2.17, folds 8, picks ['form_months_p20', 'all_p20', 'form_months_p20', 'all_p20', 'form_months_p20', 'form_months_p20', 'form_months_p20', 'all_p20'], 2x SR 0.70
- DSR (family N=48): 0.178; DSR (all derivatives researcher trials N=184): 0.028
- PBO grid 0.28 (N=9), family 0.22 (N=27)
- Alt trials: next-close fill SR 0.45; no-clean data SR 0.45; delisting returns table/conservative/adverse SR 0.45 / 0.45 / 0.45
- Delisting exits while held: 0
- Correlations: {"SPY": 0.86, "FF_Mkt-RF": 0.86, "FF_SMB": 0.11, "FF_HML": 0.02, "FF_UMD": 0.07, "validation_backtest_MOM_monthly_LS": 0.22, "validation_backtest_PEAD_raw_LS": -0.36, "validation_backtest_PEAD_trend_LS": -0.29, "validation_backtest_MOM_bracket_LS": 0.16}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2016 | -0.077 |    -0.076 |   -1.398 |  86.000 |               -0.093 |
|   2017 |  0.142 |     0.136 |    1.686 | 251.000 |                0.166 |
|   2018 | -0.063 |    -0.050 |   -0.284 | 251.000 |               -0.061 |
|   2019 |  0.081 |     0.086 |    0.698 | 252.000 |                0.105 |
|   2020 |  0.237 |     0.267 |    0.811 | 253.000 |                0.326 |
|   2021 |  0.208 |     0.204 |    1.176 | 252.000 |                0.249 |
|   2022 |  0.022 |     0.042 |    0.210 | 251.000 |                0.051 |
|   2023 |  0.094 |     0.103 |    0.643 | 250.000 |                0.126 |
|   2024 |  0.100 |     0.102 |    0.849 | 252.000 |                0.125 |
|   2025 | -0.037 |    -0.020 |   -0.104 | 250.000 |               -0.024 |
|   2026 |  0.019 |     0.024 |    0.248 | 207.000 |                0.030 |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2117 |      0.07 |     0.49 |
| SPY<200dma  |    438 |      0.13 |     0.44 |
| VIX>median  |   1275 |      0.15 |     0.66 |
| VIX<=median |   1279 |      0.01 |     0.12 |
| VIX>25      |    363 |      0.31 |     0.95 |
| VIX<=25     |   2191 |      0.04 |     0.31 |

+/-20% neighbourhood (net SR):

| param_tag       |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:----------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base            |          0.45 |              0.32 |             0.42 | True      | True          |
| form_months_m20 |          0.56 |              0.41 |             0.53 | True      | True          |
| form_months_p20 |          0.68 |              0.44 |             0.66 | True      | True          |
| topn_m20        |          0.36 |              0.27 |             0.33 | True      | True          |
| topn_p20        |          0.58 |              0.42 |             0.56 | True      | True          |
| hold_months_m20 |          0.45 |              0.32 |             0.42 | True      | True          |
| hold_months_p20 |          0.45 |              0.32 |             0.42 | True      | True          |
| all_m20         |          0.50 |              0.41 |             0.47 | True      | True          |
| all_p20         |          0.73 |              0.53 |             0.71 | True      | True          |

### imom_etf_ls_1m

- Net {"start": "2016-08-30", "end": "2026-10-28", "T": 2555, "ann_ret": -0.0523, "ann_vol": 0.1594, "sharpe": -0.3283, "t_nw": -1.0707, "t_iid": -1.0453, "max_dd": -0.4994, "skew": -0.2176, "kurt": 5.7451}
- Gross SR -0.19, 2x-cost SR -0.46; long leg gross SR 0.49 (ann 8.5%), short leg gross SR -0.61 (ann -11.6%).
- Market: {"alpha_ann_vs_spy": -0.046, "alpha_t_nw_vs_spy": -0.937, "beta_spy": -0.048, "beta_t_nw": -1.404, "beta_neutral_test": "beta within +/-0.1 and |t|<2", "alpha_sharpe_vs_spy": -0.289, "alpha_ann_ff4": -0.074, "alpha_t_nw_ff4": -1.759, "load_Mkt-RF": 0.007, "load_SMB": -0.051, "load_HML": 0.016, "load_UMD": 0.53}
- Gross-return beta vs SPY -0.05, gross alpha vs SPY -2.5% (t -0.50).
- Turnover/costs: {"traded_per_yr_x_nav": 16.332, "avg_gross_exposure": 2.017, "oneway_turnover_per_yr_of_gross": 4.049, "avg_holding_months": 2.963, "gross_ret_per_unit_traded_bps": -18.869, "breakeven_cost_bps_per_side": -18.869, "assumed_avg_cost_bps_per_side": 6.935, "tomas_only_avg_cost_bps": 6.648, "breakeven_over_assumed": -2.721, "cost_drag_ann": 0.011, "borrow_drag_ann": 0.01, "avg_long_mv": 1.006, "avg_short_mv": 1.01}
- Capacity: {"book_usd": 100000.0, "max_participation": 0.01776, "p99_participation": 0.00039, "share_trades_over_1pct_adv": 0.0021, "max_participation_at_10x_book": 0.17757, "share_over_1pct_at_10x": 0.0021}
- Walk-forward: SR 0.32, t_NW 0.95, folds 8, picks ['form_months_p20', 'form_months_p20', 'form_months_p20', 'form_months_p20', 'form_months_p20', 'form_months_p20', 'form_months_p20', 'form_months_p20'], 2x SR 0.21
- DSR (family N=48): 0.000; DSR (all derivatives researcher trials N=184): 0.000
- PBO grid 0.25 (N=9), family 0.22 (N=27)
- Alt trials: next-close fill SR -0.31; no-clean data SR -0.33; delisting returns table/conservative/adverse SR -0.33 / -0.33 / -0.33
- Delisting exits while held: 0
- Correlations: {"SPY": -0.05, "FF_Mkt-RF": -0.05, "FF_SMB": -0.16, "FF_HML": -0.16, "FF_UMD": 0.6, "validation_backtest_MOM_monthly_LS": 0.54, "validation_backtest_PEAD_raw_LS": 0.03, "validation_backtest_PEAD_trend_LS": 0.14, "validation_backtest_MOM_bracket_LS": 0.45}

Calendar years:

|   date |    ret |   pnl_sum |   sharpe |    days |   share_of_total_pnl |
|-------:|-------:|----------:|---------:|--------:|---------------------:|
|   2016 | -0.182 |    -0.197 |   -3.813 |  86.000 |                  nan |
|   2017 | -0.065 |    -0.063 |   -0.702 | 251.000 |                  nan |
|   2018 |  0.013 |     0.022 |    0.164 | 251.000 |                  nan |
|   2019 | -0.166 |    -0.174 |   -1.375 | 252.000 |                  nan |
|   2020 |  0.255 |     0.258 |    1.033 | 253.000 |                  nan |
|   2021 | -0.068 |    -0.060 |   -0.415 | 252.000 |                  nan |
|   2022 |  0.209 |     0.211 |    1.015 | 251.000 |                  nan |
|   2023 | -0.059 |    -0.049 |   -0.318 | 250.000 |                  nan |
|   2024 | -0.069 |    -0.064 |   -0.522 | 252.000 |                  nan |
|   2025 | -0.190 |    -0.202 |   -1.630 | 250.000 |                  nan |
|   2026 | -0.203 |    -0.213 |   -1.442 | 207.000 |                  nan |

Regimes (labels lagged 1 day):

| regime      |   days |   ann_ret |   sharpe |
|:------------|-------:|----------:|---------:|
| SPY>200dma  |   2117 |     -0.05 |    -0.36 |
| SPY<200dma  |    438 |     -0.05 |    -0.25 |
| VIX>median  |   1275 |      0.00 |     0.02 |
| VIX<=median |   1279 |     -0.11 |    -0.87 |
| VIX>25      |    363 |      0.16 |     0.69 |
| VIX<=25     |   2191 |     -0.09 |    -0.62 |

+/-20% neighbourhood (net SR):

| param_tag       |   sr_net_full |   sr_net_2022plus |   sr_net_2x_full | ok_full   | ok_2022plus   |
|:----------------|--------------:|------------------:|-----------------:|:----------|:--------------|
| base            |         -0.33 |             -0.41 |            -0.46 | False     | False         |
| form_months_m20 |         -0.19 |             -0.11 |            -0.33 | False     | False         |
| form_months_p20 |          0.09 |              0.04 |            -0.04 | False     | False         |
| topn_m20        |         -0.22 |             -0.19 |            -0.34 | False     | False         |
| topn_p20        |         -0.34 |             -0.38 |            -0.48 | False     | False         |
| hold_months_m20 |         -0.33 |             -0.41 |            -0.46 | False     | False         |
| hold_months_p20 |         -0.33 |             -0.41 |            -0.46 | False     | False         |
| all_m20         |         -0.16 |             -0.15 |            -0.28 | False     | False         |
| all_p20         |          0.06 |              0.15 |            -0.08 | False     | False         |

### Public pre/post-2016 check (gross; desk data starts 2016)

| series                            | window                     | start      | end        |    n |   mean_ann |   sharpe_ann |   t_stat |   max_dd |
|:----------------------------------|:---------------------------|:-----------|:-----------|-----:|-----------:|-------------:|---------:|---------:|
| FF49 VW, J6/K6, top5-bot5 (gross) | in_sample_1963-07..1995-07 | 1963-07-31 | 1995-07-31 |  385 |      0.080 |        0.510 |    2.886 |   -0.336 |
| FF49 VW, J6/K6, top5-bot5 (gross) | pre-2016 (1927..2015)      | 1927-06-30 | 2015-12-31 | 1063 |      0.072 |        0.403 |    3.791 |   -0.826 |
| FF49 VW, J6/K6, top5-bot5 (gross) | post-pub 1999-08..2015     | 1999-08-31 | 2015-12-31 |  197 |      0.084 |        0.387 |    1.568 |   -0.568 |
| FF49 VW, J6/K6, top5-bot5 (gross) | 2016+                      | 2016-01-31 | 2026-09-30 |  129 |      0.043 |        0.283 |    0.927 |   -0.311 |

Stock-level version: **BLOCKED**: GICS codes cover 0% of former S&P 500 members (need >=95%, point-in-time). Current-only GICS would re-introduce survivorship bias. Code is ready (`build_targets_stock`); it runs automatically when PIT codes land (or `--force-stock-imom` for a labelled diagnostic).

## Data-affected caveats (read before the numbers)

**Earnings timing: none of the three strategies (residual momentum, BAB / low vol, industry momentum) uses earnings dates, earnings surprises or announcement timing.** The known earnings defects in the store (intraday earnings dated a day late; earnings and predecessor history missing for many former members; see validation/backtests/pead_long_pit/data_issues.json) therefore do not enter any signal here. The other defects do, as below.

### 1. Missing delisting returns (material for long books)

The data owner's `data/universe/delisting_returns.parquet` has terminal returns only for deals matched in Alpaca's corporate-action feed (which starts 2020-04). Of the 120 stocks whose bars end before the sample end, 47 have a terminal return and 73 do not (they cannot be told apart as merger vs performance delisting from the data available, so they are treated as performance-related in the stress). Base runs treat a held position whose bars stop as cash at the last close (0%). Sensitivity (base params, next-open fills, each logged as a data_alt trial):
- **table**: matched terminal return where known, else 0%;
- **conservative**: matched terminal return where known, else **-30% on both legs** (the validator's suggested assumption; shorts gain);
- **adverse**: matched where known, else -30% on longs and **+30% on shorts** (takeover-premium case; worst for every book).

| book | delisting events while held (long / short) | net SR base | table | conservative | adverse | net ann base | ann conservative | ann adverse |
|---|---|---|---|---|---|---|---|---|
| imom_etf_ls | 0 (0 / 0) | 0.02 | 0.02 | 0.02 | 0.02 | 0.20% | 0.20% | 0.20% |
| imom_etf_long | 0 (0 / 0) | 0.45 | 0.45 | 0.45 | 0.45 | 8.08% | 8.08% | 8.08% |
| imom_etf_ls_1m | 0 (0 / 0) | -0.33 | -0.33 | -0.33 | -0.33 | -5.23% | -5.23% | -5.23% |

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
- PIT GICS codes for former members: 0% coverage, so stock-level industry momentum is blocked. Industry momentum here is the 11 sector-ETF version, so items 1-3 do not affect it (ETFs have full bars and no delistings).
- The store is still being written (symbol count changed 772 -> 774 during the sprint); results are tied to the file mtimes above.
