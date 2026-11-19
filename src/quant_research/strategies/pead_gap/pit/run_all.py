"""One command: $QR_DATA_DIR/.venv/bin/python run_all.py  -> all CSV/JSON outputs in this folder."""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from collections.abc import Callable
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

sys.path.insert(0, ".")
from statistics import NormalDist

from quant_research.strategies.pead_gap.pit.core import (
    ABOVE,
    FIRST,
    MEMB,
    NT,
    OOS0,
    RV21,
    SPLIT,
    SPY_UP,
    SPYRET,
    SYMS,
    Ca,
    D,
    cal,
    candidates,
    col,
    costs,
    coverage_mask,
    curve_stats,
    daily_curve,
    dl,
    earn_days,
    earn_window_mask,
    ev,
    nw_t,
    run_signals,
    sim,
    trade_stats,
    uni,
)

Z = NormalDist()
EG = 0.5772156649
rng = np.random.default_rng(20261030)
T0 = time.time()


def log(*a: object) -> None:
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


PRIOR = cast(list[str], json.load(open(f"{_QR.DESK_DIR}/validation/backtests/data/bars_sip.json"))["U"])
U117 = [("MRSH" if s == "MMC" else s) for s in PRIOR]  # MMC renamed MRSH; same entity in new store
assert all(s in col for s in U117)

EARN = earn_days("aligned")
EARN_STRICT = earn_days("strict")


def setmask(S: set[tuple[Any, Any]]) -> pd.DataFrame:
    M = np.zeros((NT, len(SYMS)), bool)
    ci = {d: i for i, d in enumerate(cal)}
    for s, d in S:
        if s in col and d in ci:
            M[ci[d], col[s]] = True
    return pd.DataFrame(M, index=cal, columns=SYMS)


EM = setmask(EARN)
EMS = setmask(EARN_STRICT)
EWIN = earn_window_mask(2)
COV = coverage_mask(135)
NONEARN = (~EWIN) & COV
log("masks built")


# ---------------- variants ----------------
class _Center(TypedDict):
    gap: float
    vr: float
    atrk: float


CENTER: _Center = {"gap": 0.04, "vr": 1.8, "atrk": 2.0}


def make(run: str, gap: float, vr: float, atrk: float, delist_mode: str = "table") -> list[dict[str, Any]]:
    if run == "R1_PIT_all":
        c = candidates(gap, vr, "pit")
    elif run == "R2_PIT_earn":
        c = candidates(gap, vr, "pit", EM)
    elif run == "R2s_PIT_earn_strict":
        c = candidates(gap, vr, "pit", EMS)
    elif run == "R3_PIT_nonearn":
        c = candidates(gap, vr, "pit", NONEARN)
    elif run == "R5_U117":
        c = candidates(gap, vr, "all", syms=U117)
    else:
        raise ValueError(run)
    return run_signals(c, atrk, delist_mode)


MAIN = ["R1_PIT_all", "R2_PIT_earn", "R3_PIT_nonearn", "R5_U117"]
trades: dict[str, list[dict[str, Any]]] = {r: make(r, **CENTER) for r in MAIN}
trades["R2s_PIT_earn_strict"] = make("R2s_PIT_earn_strict", **CENTER)
trades["R1_PIT_all_bankrupt100"] = make("R1_PIT_all", **CENTER, delist_mode="bankrupt100")
log("main trades", {k: len(v) for k, v in trades.items()})

# ---------------- factors ----------------
ff = pd.read_parquet(D + "factors/ken_french/ff3_daily.parquet")[["date", "Mkt-RF", "SMB", "HML", "RF"]]
mo = pd.read_parquet(D + "factors/ken_french/mom_daily.parquet")[["date", "Mom"]]
FF = ff.merge(mo, on="date")
FF["date"] = pd.to_datetime(FF["date"])
FF = FF.set_index("date")
FCOLS = ["Mkt-RF", "SMB", "HML", "Mom"]

PER: dict[str, Callable[[dict[str, Any]], bool]] = {
    "IS": (lambda t: bool(t["sig"] <= SPLIT)),
    "OOS": (lambda t: bool(t["sig"] >= OOS0)),
    "FULL": (lambda t: True),
}


def per_curve(tr_: list[dict[str, Any]], per: str, key: str) -> tuple[list[dict[str, Any]], pd.Series]:
    sel = [t for t in tr_ if PER[per](t)]
    p = daily_curve(sel, key)
    if per == "IS":
        end = max([cal[t["j"]] for t in sel], default=SPLIT)
        p = p.loc[cal[FIRST] : max(end, SPLIT)]
    elif per == "OOS":
        p = p.loc[OOS0:]
    else:
        p = p.loc[cal[FIRST] :]
    return sel, p


def reg_stats(p: pd.Series) -> dict[str, Any]:
    x = cast(np.ndarray, SPYRET.reindex(p.index).fillna(0).values)
    b, _t = nw_t(p.values, x[:, None])
    beta = b[1] / 100  # R per 1% SPY move
    f = FF.reindex(p.index).dropna()
    y = p.loc[f.index].values
    bf, tf = nw_t(y, cast(np.ndarray, f[FCOLS].values))
    _, tm = nw_t(p.values)
    return dict(
        beta_spy=round(float(beta), 3),
        ff_alpha_R_day=round(float(bf[0]), 4),
        ff_alpha_t=round(float(tf[0]), 2),
        ff_betas=dict(zip(FCOLS, [round(float(v), 2) for v in bf[1:]])),
        nw_t_mean=round(float(tm[0]), 2),
        ff_end=str(f.index[-1].date()),
    )


def full_summary(name: str, tr_: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for per in ("IS", "OOS", "FULL"):
        for key in ("R_1x", "R_2x", "R_flat5"):
            sel, p = per_curve(tr_, per, key)
            rows.append(
                dict(variant=name, period=per, costs=key[2:], **trade_stats(sel, key), **curve_stats(p), **reg_stats(p))
            )
    return rows


summary: list[dict[str, Any]] = []
for r, tr_ in trades.items():
    summary += full_summary(r, tr_)
log("summaries")

# ---------------- by year / regime ----------------
yearly: list[dict[str, Any]] = []
regime: list[dict[str, Any]] = []
for r in MAIN:
    tr_ = trades[r]
    p = daily_curve(tr_, "R_1x").loc[cal[FIRST] :]
    tot = p.sum()
    for y in range(2017, 2027):
        ty = [t for t in tr_ if t["sig"].year == y]
        py = p[cast(pd.DatetimeIndex, p.index).year == y]
        yearly.append(
            dict(
                variant=r,
                year=y,
                **trade_stats(ty, "R_1x"),
                sharpe=curve_stats(py)["sharpe"],
                pnl_R=round(float(py.sum()), 1),
                share_of_total_pnl=round(float(py.sum() / tot), 3),
            )
        )
    lagged = {
        "SPY>200": SPY_UP.shift(1).fillna(False).astype(bool),
        "SPY<200": ~SPY_UP.shift(1).fillna(True).astype(bool),
        "RVproxy>median": (RV21.loc[cal[FIRST] :].median() < RV21).shift(1).fillna(False).astype(bool),
        "RVproxy<=median": (RV21.loc[cal[FIRST] :].median() >= RV21).shift(1).fillna(False).astype(bool),
        "RVproxy>25%": (RV21 > 0.25).shift(1).fillna(False).astype(bool),
    }
    for per in ("IS", "OOS", "FULL"):
        sel, pp = per_curve(tr_, per, "R_1x")
        for reg_name, m in lagged.items():
            mm = m.reindex(pp.index).fillna(False).astype(bool)
            sig_state = m.shift(-1).fillna(False)  # state at signal close
            tg = [t for t in sel if bool(sig_state.iat[t["i_sig"]])]
            regime.append(
                dict(
                    variant=r,
                    period=per,
                    regime=reg_name,
                    **trade_stats(tg, "R_1x"),
                    days=int(mm.sum()),
                    sharpe_on_regime_days=curve_stats(pp[mm])["sharpe"] if mm.sum() > 20 else None,
                )
            )
pd.DataFrame(yearly).to_csv("by_year.csv", index=False)
pd.DataFrame(regime).to_csv("by_regime.csv", index=False)
log("year/regime")

# ---------------- benchmarks: same exits, eligible = (PIT member or U117) & above 50/200 ----------------
ELIG_PIT = (ABOVE & MEMB).values
ELIG_117 = (ABOVE & pd.DataFrame(np.isin(SYMS, U117)[None, :].repeat(NT, 0), index=cal, columns=SYMS)).values
pool_cache: dict[tuple[int, str], list[dict[str, Any]]] = {}


def pool(i: int, which: str) -> list[dict[str, Any]]:
    k = (i, which)
    if k not in pool_cache:
        E_ = ELIG_PIT if which == "pit" else ELIG_117
        out = []
        for jj in np.where(E_[i])[0]:
            t = sim(SYMS[jj], i)
            if t:
                out.append(costs(t))
        pool_cache[k] = out
    return pool_cache[k]


# (a) all-eligible every 5th session
bench_rows: list[dict[str, Any]] = []
for which, nm in (("pit", "BENCH_all_eligible_5d_PIT"), ("u117", "BENCH_all_eligible_5d_U117")):
    btr = [t for i in range(FIRST, NT - 1, 5) for t in pool(i, which)]
    trades[nm] = btr
    bench_rows += full_summary(nm, btr)
    log("bench", nm, len(btr))
# (b) date-matched excess & (c) random matched entries
matched: list[dict[str, Any]] = []
rand_rows: list[dict[str, Any]] = []
for r in [*MAIN, "R2s_PIT_earn_strict"]:
    which = "u117" if r == "R5_U117" else "pit"
    for per in ("IS", "OOS", "FULL"):
        sel = [t for t in trades[r] if PER[per](t)]
        bydate: dict[Any, list[Any]] = {}
        for t in sel:
            pl = pool(t["i_sig"], which)
            m = np.mean([q["R_1x"] for q in pl])
            bydate.setdefault(t["i_sig"], []).append(t["R_1x"] - m)
        ex = np.array([np.mean(v) for v in bydate.values()])
        allex = np.concatenate([np.array(v) for v in bydate.values()])
        matched.append(
            dict(
                variant=r,
                period=per,
                n_trades=len(sel),
                n_dates=len(ex),
                mean_excess_R=round(float(allex.mean()), 4),
                t_date_clustered=round(float(ex.mean() / (ex.std(ddof=1) / math.sqrt(len(ex)))), 2),
            )
        )
        if per == "FULL":
            continue
        _, preal = per_curve(trades[r], per, "R_1x")
        real_sr = curve_stats(preal)["sharpe"]
        real_exp = float(np.mean([t["R_1x"] for t in sel]))
        sr_draws: list[Any] = []
        exp_draws: list[Any] = []
        for _rep in range(200):
            pick = []
            for t in sel:
                pl = pool(t["i_sig"], which)
                pick.append(pl[rng.integers(len(pl))])
            _, pr = per_curve(pick, per, "R_1x")
            sr_draws.append(curve_stats(pr)["sharpe"])
            exp_draws.append(np.mean([q["R_1x"] for q in pick]))
        srs, exps = np.array(sr_draws), np.array(exp_draws)
        rand_rows.append(
            dict(
                variant=r,
                period=per,
                real_sharpe=real_sr,
                rand_sharpe_mean=round(float(srs.mean()), 3),
                rand_sharpe_p95=round(float(np.percentile(srs, 95)), 3),
                p_sharpe=round(float((srs >= real_sr).mean()), 3),
                real_exp_R=round(real_exp, 4),
                rand_exp_mean=round(float(exps.mean()), 4),
                p_exp=round(float((exps >= real_exp).mean()), 3),
            )
        )
    log("matched/random", r)
pd.DataFrame(matched).to_csv("benchmark_date_matched.csv", index=False)
pd.DataFrame(rand_rows).to_csv("benchmark_random_matched.csv", index=False)
summary += bench_rows
S = pd.DataFrame(summary)
S.drop(columns=["ff_betas"]).assign(ff_betas=S.ff_betas.astype(str)).to_csv("summary.csv", index=False)

# ---------------- parameter sweep (+-20%, one-at-a-time and joint) ----------------
grid = list(itertools.product([0.032, 0.04, 0.048], [1.44, 1.8, 2.16], [1.6, 2.0, 2.4]))
sweep: list[dict[str, Any]] = []
curves_trials: dict[str, pd.Series] = {}
for r in ["R1_PIT_all", "R2_PIT_earn", "R3_PIT_nonearn"]:
    for gap, vr, atr in grid:
        tr_ = trades[r] if (gap, vr, atr) == (0.04, 1.8, 2.0) else make(r, gap, vr, atr)
        name = f"{r}|gap{gap}|vr{vr}|atr{atr}"
        row: dict[str, Any] = dict(
            variant=r,
            gap=gap,
            vr=vr,
            atrk=atr,
            center=(gap, vr, atr) == (0.04, 1.8, 2.0),
            one_at_a_time=sum([gap != 0.04, vr != 1.8, atr != 2.0]) <= 1,
        )
        for per in ("IS", "OOS"):
            sel, p = per_curve(tr_, per, "R_1x")
            cs = curve_stats(p)
            ts = trade_stats(sel, "R_1x")
            row.update(
                {
                    f"{per}_n": ts["n"],
                    f"{per}_exp_R": ts.get("exp_R"),
                    f"{per}_sharpe": cs["sharpe"],
                    f"{per}_sr_d": cs["sr_d"],
                }
            )
        curves_trials[name] = daily_curve(tr_, "R_1x").loc[cal[FIRST] :]
        sweep.append(row)
    log("sweep", r)
SW = pd.DataFrame(sweep)
SW.to_csv("sweep.csv", index=False)
stab: list[dict[str, Any]] = []
for var_name, grp in SW.groupby("variant"):
    center_row = grp[grp.center].iloc[0]
    for lab, sub in (("one_at_a_time", grp[grp.one_at_a_time & ~grp.center]), ("joint_all27", grp[~grp.center])):
        stab.append(
            dict(
                variant=var_name,
                set=lab,
                n=len(sub),
                center_OOS_sharpe=center_row.OOS_sharpe,
                min_OOS_sharpe=sub.OOS_sharpe.min(),
                max_OOS_sharpe=sub.OOS_sharpe.max(),
                all_gt0=bool((sub.OOS_sharpe > 0).all()),
                all_ge_50pct_center=bool((sub.OOS_sharpe >= 0.5 * center_row.OOS_sharpe).all()),
                n_fail_50pct=int((sub.OOS_sharpe < 0.5 * center_row.OOS_sharpe).sum()),
            )
        )
pd.DataFrame(stab).to_csv("sweep_stability.csv", index=False)

# ---------------- trial log, T x N matrix ----------------
for r in ["R5_U117", "R2s_PIT_earn_strict"]:
    curves_trials[f"{r}|gap0.04|vr1.8|atr2.0"] = daily_curve(trades[r], "R_1x").loc[cal[FIRST] :]
old = pd.read_csv(f"{_QR.DESK_DIR}/validation/backtests/daily_pnl_R_all_variants.csv", index_col=0, parse_dates=True)
old_sum = pd.read_csv(f"{_QR.DESK_DIR}/validation/backtests/results_summary.csv")
M_new = pd.DataFrame(curves_trials)
M_old = old.reindex(M_new.index).fillna(0.0)
M_old.columns = [f"PRIOR|{c}" for c in M_old.columns]
M = pd.concat([M_old, M_new], axis=1)
M.to_csv("daily_pnl_matrix_all_trials.csv")
tl: list[dict[str, Any]] = []
for c in M_old.columns:
    v = c.split("|")[1]
    o = old_sum[(old_sum.variant == v)].set_index("period")
    tl.append(
        dict(
            trial=c,
            date_run="2026-10-30 (prior study)",
            universe="117 survivor names",
            costs="flat 5bps",
            IS_sharpe=o.loc["IS", "sharpe_ann"],
            OOS_sharpe=o.loc["OOS", "sharpe_ann"],
            OOS_sr_d=o.loc["OOS", "sr_daily"],
        )
    )
for _idx, rw in SW.iterrows():
    tl.append(
        dict(
            trial=f"{rw.variant}|gap{rw.gap}|vr{rw.vr}|atr{rw.atrk}",
            date_run="2026-10-30",
            universe="PIT S&P 500",
            costs="TCA owner v1.1",
            IS_sharpe=rw.IS_sharpe,
            OOS_sharpe=rw.OOS_sharpe,
            OOS_sr_d=rw.OOS_sr_d,
        )
    )
for r in ["R5_U117", "R2s_PIT_earn_strict"]:
    s1 = S[(S.variant == r) & (S.costs == "1x")].set_index("period")
    tl.append(
        dict(
            trial=f"{r}|gap0.04|vr1.8|atr2.0",
            date_run="2026-10-30",
            universe="117 names" if r == "R5_U117" else "PIT S&P 500",
            costs="TCA owner v1.1",
            IS_sharpe=s1.loc["IS", "sharpe"],
            OOS_sharpe=s1.loc["OOS", "sharpe"],
            OOS_sr_d=s1.loc["OOS", "sr_d"],
        )
    )
TL = pd.DataFrame(tl)
TL.to_csv("trial_log.csv", index=False)
N = len(TL)
log("trials", N)

# ---------------- DSR (cumulative N) ----------------
var_sr = float(TL.OOS_sr_d.astype(float).var(ddof=1))
sr0 = math.sqrt(var_sr) * ((1 - EG) * Z.inv_cdf(1 - 1 / N) + EG * Z.inv_cdf(1 - 1 / (N * math.e)))
dsr_rows: list[dict[str, Any]] = []
for r in [*MAIN, "R2s_PIT_earn_strict"]:
    for key in ("1x", "2x"):
        b = S[(S.variant == r) & (S.period == "OOS") & (S.costs == key)].iloc[0]
        sr, T, sk, ku = b["sr_d"], b["days"], b["skew"], b["kurt"]
        den = math.sqrt(1 - sk * sr + (ku - 1) / 4 * sr**2)
        dsr_rows.append(
            dict(
                variant=r,
                costs=key,
                N=N,
                T=int(T),
                sr_ann=round(sr * math.sqrt(252), 3),
                skew=round(sk, 2),
                kurt=round(ku, 2),
                var_trial_sr_d=var_sr,
                sr0_ann=round(sr0 * math.sqrt(252), 3),
                PSR0=round(Z.cdf(sr * math.sqrt(T - 1) / den), 4),
                DSR=round(Z.cdf((sr - sr0) * math.sqrt(T - 1) / den), 4),
            )
        )
pd.DataFrame(dsr_rows).to_csv("dsr.csv", index=False)


# ---------------- PBO via CSCV, S=16 ----------------
def pbo(Mx: pd.DataFrame, S_: int = 16) -> dict[str, Any]:
    X = cast(np.ndarray, Mx.values)
    T_ = len(X) - len(X) % S_
    X = X[-T_:]
    blocks = np.array_split(np.arange(T_), S_)
    s1 = np.array([X[b].sum(0) for b in blocks])
    s2 = np.array([(X[b] ** 2).sum(0) for b in blocks])
    n = np.array([len(b) for b in blocks])
    lam_vals: list[float] = []
    for comb in itertools.combinations(range(S_), S_ // 2):
        ii = np.zeros(S_, bool)
        ii[list(comb)] = True

        def sr(m: np.ndarray) -> np.ndarray:
            nn = n[m].sum()
            mu = s1[m].sum(0) / nn
            var = s2[m].sum(0) / nn - mu**2
            return cast(np.ndarray, mu / np.sqrt(np.where(var > 0, var, np.nan)))

        a, o = sr(ii), sr(~ii)
        best = np.nanargmax(a)
        rank = (np.nansum(o < o[best]) + 1) / (np.sum(~np.isnan(o)) + 1)
        lam_vals.append(math.log(rank / (1 - rank)))
    lam = np.array(lam_vals)
    return dict(
        S=S_,
        combos=len(lam),
        N=Mx.shape[1],
        T=T_,
        PBO=round(float((lam <= 0).mean()), 4),
        median_logit=round(float(np.median(lam)), 3),
    )


PBO = {
    "all_trials": pbo(M),
    "new_trials_only": pbo(M_new),
    "new_PIT_long_only_sweep": pbo(M_new[[c for c in M_new if cast(str, c).startswith(("R1", "R2_", "R3"))]]),
}
json.dump(PBO, open("pbo.json", "w"), indent=1)
log("pbo", PBO)

# ---------------- costs / capacity / turnover ----------------
cap: list[dict[str, Any]] = []
for r in MAIN:
    tr_ = trades[r]
    Rg = np.array([t["R_gross"] for t in tr_])
    u = np.array([(t["E"] + t["X"]) / t["D"] * 1e-4 for t in tr_])
    avg_side = np.array([(t["c_in_bps"] * t["E"] + t["c_out_bps"] * t["X"]) / (t["E"] + t["X"]) for t in tr_])
    adv = np.array([t["adv_usd"] for t in tr_])
    days = np.array([t["days"] for t in tr_])
    yrs = (cal[-1] - cal[FIRST]).days / 365.25
    cap.append(
        dict(
            variant=r,
            trades=len(tr_),
            trades_per_year=round(len(tr_) / yrs, 1),
            avg_hold_days=round(float(days.mean()), 1),
            avg_cost_bps_per_side=round(float(avg_side.mean()), 2),
            breakeven_bps_per_side=round(float(Rg.mean() / u.mean()), 1),
            breakeven_over_assumed=round(float(Rg.mean() / u.mean() / avg_side.mean()), 2),
            adv_usd_p5=round(float(np.nanpercentile(adv, 5)) / 1e6, 1),
            adv_usd_median=round(float(np.nanmedian(adv)) / 1e6, 1),
            clip_at_1pct_adv_p5_usd=round(float(np.nanpercentile(adv, 5)) * 0.01),
            max_concurrent=int(pd.Series([1] * len(tr_)).groupby([0] * len(tr_)).size().iloc[0]) if False else None,
            bucket_mix=dict(pd.Series([t["bucket"].split(" ")[0] for t in tr_]).value_counts()),
        )
    )
    conc = np.zeros(NT)
    for t in tr_:
        conc[t["i"] : t["j"] + 1] += 1
    cap[-1]["max_concurrent"] = int(conc.max())
    cap[-1]["avg_concurrent"] = round(float(conc[FIRST:].mean()), 1)
pd.DataFrame(cap).to_csv("costs_capacity.csv", index=False)

# ---------------- trades out ----------------
keep = [
    "sym",
    "sig",
    "i_sig",
    "i",
    "j",
    "E",
    "X",
    "X_bar",
    "D",
    "why",
    "ven",
    "term",
    "term_flag",
    "days",
    "R_gross",
    "bucket",
    "adv_usd",
    "c_in_bps",
    "c_out_bps",
    "cost_R_1x",
    "R_1x",
    "R_2x",
    "R_flat5",
    "regime",
]
pd.concat(
    [
        pd.DataFrame(trades[r])[keep].assign(variant=r, entry=lambda d: cal[d.i].date, exit=lambda d: cal[d.j].date)
        for r in [*MAIN, "R2s_PIT_earn_strict", "R1_PIT_all_bankrupt100"]
    ]
).to_csv("trades_main.csv", index=False)

# ---------------- data issues ----------------
issues: dict[str, Any] = {}
mb = MEMB.values
hasbar = ~np.isnan(Ca)
yr = cal.year
issues["member_days_without_bars_by_year"] = {int(y): int((mb & ~hasbar)[yr == y].sum()) for y in range(2016, 2027)}
issues["members_without_bars_symbols"] = sorted({SYMS[j] for j in np.where((mb & ~hasbar).any(0))[0]})
cm = COV.values
issues["share_member_days_with_earnings_coverage_by_year"] = {
    int(y): round(float((mb & cm & hasbar)[yr == y].sum() / max(1, (mb & hasbar)[yr == y].sum())), 3)
    for y in range(2017, 2027)
}
role = uni.role.reindex(SYMS).values
issues["former_members_with_any_earnings_event"] = int(
    len(set(ev.symbol) & set(uni.index[uni.role == "sp500_former_since_2016"]))
)
issues["former_members_total"] = int((uni.role == "sp500_former_since_2016").sum())
issues["delisting_returns_rows"] = int(len(dl))
issues["delisting_reason_counts"] = dl.reason.value_counts().to_dict()
issues["during_mkt_events"] = int((ev.timing == "DURING_MKT").sum())
issues["trades_hitting_delisting"] = {
    r: [
        dict(sym=t["sym"], sig=str(t["sig"].date()), term=t["term"], flag=t["term_flag"], R_1x=round(t["R_1x"], 3))
        for t in trades[r]
        if t["why"] == "delisted"
    ]
    for r in [*MAIN, "R1_PIT_all_bankrupt100"]
}
issues["pit_candidates_lost_to_missing_bars"] = "see member_days_without_bars_by_year"
json.dump(issues, open("data_issues.json", "w"), indent=1, default=str)
log("done")
