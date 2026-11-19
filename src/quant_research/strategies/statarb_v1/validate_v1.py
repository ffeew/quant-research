"""Judge every v1 trial against $QR_DESK_DIR/validation/STANDARD.md v1.0. Reads ../results/v1/{trial_meta.csv,daily/}.
Writes: trial_log.csv (all trials incl. prior ones), returns_matrix_net_std.parquet (T x N), metrics_all.csv,
validation_passfail.csv, factor_regressions.csv, blitz_decay.csv, regime_<pick>.csv, pbo.json, dsr.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from quant_research.strategies.statarb_v1 import config as CFG
from quant_research.strategies.statarb_v1.statarb import validation as V
from quant_research.strategies.statarb_v1.statarb.data import CIO

R = Path(__file__).resolve().parents[1] / "results" / (sys.argv[1] if len(sys.argv) > 1 else "v1")
HOLD = pd.Timestamp("2022-02-01")  # holdout eval start: 2022-01-01 split + ~21-trading-day / 1-rebalance embargo
DEV_END = pd.Timestamp("2021-12-31")
meta = pd.read_csv(R / "trial_meta.csv")
D = {t: pd.read_parquet(R / "daily" / f"{t.replace('/', '-')}.parquet") for t in meta.trial}
SC = list(CFG.SCENARIOS)
ff = V.load_ff_daily()


def active_start(d: pd.DataFrame) -> pd.Timestamp:
    a = d.index[d.gross_exposure > 0]
    return cast(pd.Timestamp, a[0])


def sh(r: pd.Series) -> float:
    r = r.dropna()
    return r.mean() / r.std() * np.sqrt(252) if len(r) > 20 and r.std() > 0 else np.nan


def mdd(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return cast(float, (eq / eq.cummax() - 1).min())


rows = []
for _, m in meta.iterrows():
    d = D[m.trial]
    s = active_start(d)
    per = {"dev": d.loc[s:DEV_END], "holdout": d.loc[HOLD:], "full": d.loc[s:]}
    row = {"trial": m.trial, "family": m.family, "exec": m.exec, "replication": m.replication, "active_from": s.date()}
    for pn, x in per.items():
        row[f"{pn}_gross_sharpe"] = sh(x.gross)
        row[f"{pn}_gross_ann"] = x.gross.mean() * 252
        for sc in SC:
            row[f"{pn}_net_sharpe_{sc}"] = sh(x[f"net_{sc}"])
        row[f"{pn}_net_ann_std"] = x.net_std.mean() * 252
        row[f"{pn}_net_vol_std"] = x.net_std.std() * np.sqrt(252)
        row[f"{pn}_maxdd_std"] = mdd(x.net_std)
        row[f"{pn}_maxdd_tca_base"] = mdd(x.net_tca_base)
        row[f"{pn}_annual_turnover"] = x.turnover.mean() * 252
        tv = x.turnover.sum()
        row[f"{pn}_gross_edge_bps_per$traded"] = x.gross.sum() / tv * 1e4 if tv else np.nan
        row[f"{pn}_cost_bps_per$traded_std"] = x.tcost_std.sum() / tv * 1e4 if tv else np.nan
        row[f"{pn}_cost_bps_per$traded_tca"] = x.tcost_tca_base.sum() / tv * 1e4 if tv else np.nan
        nz = x.net_std[x.gross != 0]
        row[f"{pn}_hit_rate_days"] = (nz > 0).mean() if len(nz) else np.nan
        row[f"{pn}_new_positions"] = int(x.opens.sum())
        row[f"{pn}_rebalance_days"] = int((x.turnover > 1e-6).sum())
        row[f"{pn}_long_leg_gross_ann"] = x.long_gross.mean() * 252
        row[f"{pn}_short_leg_gross_ann"] = x.short_gross.mean() * 252
    row["holdout_nw_t_net_std"] = V.nw_t(per["holdout"].net_std)
    row["full_nw_t_net_std"] = V.nw_t(per["full"].net_std)
    row["full_nw_t_net_tca_base"] = V.nw_t(per["full"].net_tca_base)
    row["full_nw_t_gross"] = V.nw_t(per["full"].gross)
    # break-even one-way cost (bps per $ traded) in holdout vs assumed (std floor)
    row["holdout_breakeven_over_assumed_std"] = (
        row["holdout_gross_edge_bps_per$traded"] / row["holdout_cost_bps_per$traded_std"]
        if row["holdout_cost_bps_per$traded_std"]
        else np.nan
    )
    row["holdout_avg_hold_days"] = (
        2 * per["holdout"].gross_exposure.mean() / per["holdout"].turnover.mean()
        if per["holdout"].turnover.mean() > 0
        else np.nan
    )
    for k in ("cap_1pctADV_$", "cap_5pctADV_$", "pair_round_trips_holdout"):
        row[k] = m.get(k)
    rows.append(row)
M = pd.DataFrame(rows)

# ---- trial count for DSR (pairs: each config = 1 trial; the 273,344 pair tests inside it are one family) ----
n_prior = sum(n for _, n in CFG.PRIOR_TRIALS)
N = len(M) + n_prior
# ---- DSR on holdout net (std costs) daily returns; V[SR] across all v1 trials' holdout daily SRs ----
hsr = np.array([D[t].loc[HOLD:].net_std.mean() / D[t].loc[HOLD:].net_std.std() for t in M.trial])
hsr_g = np.array([D[t].loc[HOLD:].gross.mean() / D[t].loc[HOLD:].gross.std() for t in M.trial])
T_h = len(D[M.trial.iloc[0]].loc[HOLD:])
# V[SR] choices: (a) across net trial SRs (inflated by cost-dominated losers), (b) across gross trial SRs,
# (c) pure-noise 1/T. Verdict uses the MOST LENIENT (smallest SR0) so a FAIL cannot be an artefact of this choice.
var_opts = {"net_trials": np.nanvar(hsr, ddof=1), "gross_trials": np.nanvar(hsr_g, ddof=1), "null_1_over_T": 1.0 / T_h}
sr0_opts = {k: V.expected_max_sr(v, N) for k, v in var_opts.items()}
var_choice = min(sr0_opts, key=lambda k: float(sr0_opts[k]))
var_sr, sr0 = var_opts[var_choice], sr0_opts[var_choice]
dsr_rows = []
for t in M.trial:
    o = V.dsr(D[t].loc[HOLD:].net_std, sr0)
    o["trial"] = t
    dsr_rows.append(o)
DS = pd.DataFrame(dsr_rows).set_index("trial")
M = M.merge(DS[["DSR", "SR_daily", "skew", "kurtosis", "T"]].add_prefix("holdout_"), left_on="trial", right_index=True)
dsr_info = {
    "V_SR_options": var_opts,
    "SR0_daily_options": sr0_opts,
    "SR0_ann_options": {k: v * np.sqrt(252) for k, v in sr0_opts.items()},
    "V_SR_used": var_choice,
    "N_trials_total": N,
    "N_v1_logged": len(M),
    "N_prior_logged": n_prior,
    "var_SR_daily_across_trials": var_sr,
    "SR0_daily": sr0,
    "SR0_annualised": sr0 * np.sqrt(252),
    "sample": f"holdout {HOLD.date()}..end, net under STANDARD cost floor",
    "note": "Pairs: each pairs config counts as ONE trial (the 273,344 EG tests are one family, BH-controlled inside).",
}
# DSR sensitivity: what if only v1 trials counted
dsr_info["SR0_annualised_if_N_v1_only"] = V.expected_max_sr(var_sr, len(M)) * np.sqrt(252)

# ---- PBO via CSCV, S=16, on the full T x N matrix of net (std) daily returns over the common active range ----
Mat = pd.DataFrame({t: D[t].net_std for t in M.trial})
start = max(active_start(D[t]) for t in M.trial)
Mat_c = Mat.loc[start:]
Mat.to_parquet(R / "returns_matrix_net_std.parquet")
pd.DataFrame({t: D[t].gross for t in M.trial}).to_parquet(R / "returns_matrix_gross.parquet")
pbo: dict[str, Any] = {"all_trials": V.pbo_cscv(Mat_c, 16), "common_range_start": str(start.date())}
for fam, g in M.groupby("family"):
    if len(g) >= 4:
        pbo[f"family:{fam}"] = V.pbo_cscv(Mat_c[g.trial.tolist()], 16)
pbo["all_trials_tca_base"] = V.pbo_cscv(pd.DataFrame({t: D[t].net_tca_base for t in M.trial}).loc[start:], 16)
PBO_ALL = pbo["all_trials"]["PBO"]
json.dump(pbo, open(R / "pbo.json", "w"), indent=1, default=float)
json.dump(dsr_info, open(R / "dsr.json", "w"), indent=1, default=float)

# ---- factor regressions (daily FF3+Mom+ST_Rev, HAC) ----
fr = []
for t in M.trial:
    d = D[t]
    s = active_start(d)
    for pn, x in {"dev": d.loc[s:DEV_END], "holdout": d.loc[HOLD:]}.items():
        for col in ("gross", "net_std"):
            o = V.factor_regression(x[col], ff)
            o.update(trial=t, period=pn, series=col)
            fr.append(o)
FR = pd.DataFrame(fr)
FR.to_csv(R / "factor_regressions_daily.csv", index=False)


# ---- Blitz: monthly decay table on monthly factors ----
def load_ff_monthly() -> pd.DataFrame:
    out = []
    for f, cols in [
        ("ff3_monthly", ["Mkt-RF", "SMB", "HML", "RF"]),
        ("mom_monthly", ["Mom"]),
        ("st_rev_monthly", ["ST_Rev"]),
    ]:
        d = pd.read_parquet(CIO / "factors/ken_french" / f"{f}.parquet")
        d["date"] = pd.PeriodIndex(pd.to_datetime(d["date"].astype(str), format="mixed"), freq="M")
        out.append(d.set_index("date")[cols])
    return pd.concat(out, axis=1).dropna()


ffm = load_ff_monthly()
bl = []
for t in M.trial[M.family == "Blitz_FF3"]:
    d = D[t]
    s = active_start(d)
    mo = (1 + d[["gross", "net_std", "net_tca_base"]]).groupby(
        cast(pd.DatetimeIndex, d.index).to_period("M")
    ).prod() - 1
    for pn, x in {
        "dev": mo.loc[s.to_period("M") : "2021-12"],
        "holdout": mo.loc["2022-02":"2026-09"],
        "full": mo.loc[s.to_period("M") : "2026-09"],
    }.items():
        for col in ("gross", "net_std"):
            r = x[col]
            o = {
                "trial": t,
                "period": pn,
                "series": col,
                "months": len(r),
                "mean_monthly": r.mean(),
                "ann_mean": r.mean() * 12,
                "sharpe_monthly_ann": r.mean() / r.std() * np.sqrt(12),
                "nw_t_mean": V.nw_t(r, lags=3),
            }
            for cols, tag in [
                (("Mkt-RF", "SMB", "HML"), "FF3"),
                (("Mkt-RF", "SMB", "HML", "Mom", "ST_Rev"), "FF3+Mom+STRev"),
            ]:
                xx = ffm[list(cols)].reindex(r.index)
                dd = pd.concat([r.rename("r"), xx], axis=1).dropna()
                import statsmodels.api as sm

                mm = sm.OLS(dd.r, sm.add_constant(dd[list(cols)])).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
                o[f"{tag}_alpha_monthly"] = mm.params["const"]
                o[f"{tag}_alpha_t"] = mm.tvalues["const"]
                o[f"{tag}_r2"] = mm.rsquared
                for c in cols:
                    o[f"{tag}_b_{c}"] = mm.params[c]
                    o[f"{tag}_t_{c}"] = mm.tvalues[c]
            bl.append(o)
pd.DataFrame(bl).to_csv(R / "blitz_decay_monthly.csv", index=False)

# ---- pass / fail per criterion (verdict uses STANDARD cost floor; TCA-cost columns informative) ----
pf = []
for _, r in M.iterrows():
    hurdle = 2.8 if r.replication else 3.0
    # STANDARD s3: pairs = time-series/event signal -> >=100 OOS round trips; AL = >=100 OOS position opens;
    # cross-sectional (b, c daily; Blitz monthly) -> >=30 independent OOS rebalance periods (Blitz: months)
    if r.family == "a_pairs_EG":
        trades_ok = (r.pair_round_trips_holdout or 0) >= 100
    elif r.family.startswith("AL_"):
        trades_ok = r.holdout_new_positions >= 100
    elif r.family == "Blitz_FF3":
        trades_ok = len(pd.period_range("2022-02", "2026-10", freq="M")) >= 30 and r.holdout_rebalance_days >= 30
    else:
        trades_ok = r.holdout_rebalance_days >= 30
    crit: dict[str, Any] = {
        "trial": r.trial,
        "family": r.family,
        "exec": r.exec,
        "t_hurdle": hurdle,
        "holdout_net_sharpe_std": r.holdout_net_sharpe_std,
        "C1_net_sharpe>0.5": r.holdout_net_sharpe_std > 0.5,
        "holdout_net_sharpe_std_2x": r.holdout_net_sharpe_std_2x,
        "C2_2x_costs_sharpe>0": r.holdout_net_sharpe_std_2x > 0,
        "full_nw_t_net_std": r.full_nw_t_net_std,
        "C3_t>=hurdle": r.full_nw_t_net_std >= hurdle,
        "holdout_DSR": r.holdout_DSR,
        "C4_DSR>=0.95": r.holdout_DSR >= 0.95,
        "PBO_all_trials": PBO_ALL,
        "C5_PBO<0.20": PBO_ALL < 0.20,
        "C6_OOS_trades_ok": bool(trades_ok),
        "breakeven/assumed_cost": r.holdout_breakeven_over_assumed_std,
        "C7_breakeven>=2x_cost": r.holdout_breakeven_over_assumed_std >= 2,
        "info_holdout_net_sharpe_tca_base": r.holdout_net_sharpe_tca_base,
        "info_holdout_net_sharpe_tca_2x": r.holdout_net_sharpe_tca_2x,
        "info_holdout_gross_sharpe": r.holdout_gross_sharpe,
    }
    crit["hard_bars_passed"] = sum(bool(crit[k]) for k in crit if k.startswith("C"))
    crit["VERDICT"] = "PASS-candidate" if crit["hard_bars_passed"] == 7 else "FAIL"
    pf.append(crit)
PF = pd.DataFrame(pf)
# pre-registered selection: best DEV net Sharpe (std), open_t1, per family
picks = M[M.exec == "open_t1"].sort_values("dev_net_sharpe_std", ascending=False).groupby("family").head(1)
PF["preregistered_pick"] = PF.trial.isin(picks.trial)
PF.to_csv(R / "validation_passfail.csv", index=False)
M.insert(0, "label", CFG.LABEL)
M.to_csv(R / "metrics_all.csv", index=False)

# ---- trial log (STANDARD s1.3) ----
TL = M[
    [
        "trial",
        "family",
        "exec",
        "dev_net_sharpe_std",
        "holdout_net_sharpe_std",
        "dev_net_sharpe_tca_base",
        "holdout_net_sharpe_tca_base",
    ]
].merge(meta[["trial", "params", "buffer"]], on="trial")
TL["date_run"] = "2026-10-30"
TL["dataset"] = "cio_data adjusted (final), PIT S&P500, jump filter (split-ratio>=2:1, |r|>40%)"
TL["cost_settings"] = "; ".join(f"{k}={v}" for k, v in CFG.SCENARIOS.items())
prior = pd.DataFrame(
    [
        {
            "trial": d,
            "family": "prior (pre-v1)",
            "n_trials": n,
            "date_run": "2026-10-29/30",
            "dataset": "IEX data.json fallback" if d.startswith("IEX") else "cio_data pre-final build",
        }
        for d, n in CFG.PRIOR_TRIALS
    ]
)
pd.concat([TL.assign(n_trials=1), prior]).to_csv(R / "trial_log.csv", index=False)

# ---- regime / stability for the pre-registered picks (STANDARD s7) ----
vix = pd.read_csv(
    Path(__file__).resolve().parents[1] / "data_ext" / "VIXCLS_fred.csv", parse_dates=["observation_date"], index_col=0
)["VIXCLS"]
spy_bars = pd.read_parquet(CIO / "bars/daily/adjusted/SPY.parquet", columns=["session_date", "close"])
spy = pd.Series(spy_bars.close.values, index=pd.to_datetime(spy_bars.session_date))
above = spy > spy.rolling(200).mean()
for t in picks.trial:
    d = D[t]
    s = active_start(d)
    x = d.loc[s:]
    v = vix.reindex(x.index).ffill()
    a = above.reindex(x.index).ffill()
    vm = v.loc[:DEV_END].median()
    grp = {
        "year": cast(pd.DatetimeIndex, x.index).year.astype(str),
        "SPY>200dma": np.where(a, "above", "below"),
        "VIX_vs_dev_median": np.where(v > vm, "high", "low"),
        "VIX>25": np.where(v > 25, "yes", "no"),
    }
    out = []
    for gname, labels in grp.items():
        for k, xx in x.groupby(labels):  # type: ignore[call-overload]  # aligned year/regime labels
            out.append(
                {
                    "split": gname,
                    "bucket": k,
                    "days": len(xx),
                    "gross_sharpe": sh(xx.gross),
                    "net_sharpe_std": sh(xx.net_std),
                    "net_pnl_std": xx.net_std.sum(),
                    "gross_pnl": xx.gross.sum(),
                }
            )
    regime = pd.DataFrame(out)
    tot = x.gross.sum()
    regime["share_of_total_gross_pnl"] = regime.gross_pnl / tot if tot else np.nan
    regime.to_csv(R / f"regime_{t.replace('/', '-')}.csv", index=False)
print(json.dumps(dsr_info, default=float, indent=0))
print(json.dumps(pbo, default=float, indent=0))
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(PF.drop(columns=["PBO_all_trials"]).round(3).to_string())
print(picks[["trial", "dev_net_sharpe_std", "holdout_net_sharpe_std", "holdout_gross_sharpe"]])
