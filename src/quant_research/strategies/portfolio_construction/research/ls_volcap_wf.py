from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, cast

#!/usr/bin/env python3
"""
Walk-forward of the SHADOW-CONSTRUCTION long/short book (shadow_fallback_composite_v1 method) on the data owner's SIP data,
to re-estimate the risk-forecast inflation k for the 6% book vol cap. Research only; places no orders.

Data (read-only, $QR_DATA_DIR): bars/daily/adjusted (O/H/L/C/V, zero_volume masked), total_return
(ret_total_best), universe/sp500_membership (PIT intervals), universe/universe.parquet (GICS - CURRENT, not PIT),
universe/delisting_returns (terminal returns where matched).

Each weekly rebalance date t (close of t, hold from t+1, no look-ahead):
  universe  = PIT S&P 500 members on t with 120 complete daily returns and a price on t, top N by trailing 63d median
              $ volume (N=100, ~ the desk's data.json universe size), plus SPY as the hedge instrument;
  signals   = MOM_12_1, RS63, TREND, REV5, PEAD (construct.py definitions), cross-sectional z (clip +-3);
              fallback weights as in the live shadow book (MOM_12_1, TREND, REV5, PEAD = 0.25; RS63 = 0) [--all5: 0.2 each];
  sleeve m  = min(1, sigma_target / sigma_hat_126d) per sleeve from lagged unit-gross sleeve proxies over all PIT members;
              sigma_target = EXPANDING (PIT) full-history proxy vol (min 252 obs), not the full-sample value;
  composite = sum sw*m*Z / std(sum sw*Z), clip +-3; alpha_i = 0.02 * sigma_i(5d) * comp_i (fallback IC floor);
  optimiser = max alpha'w - tc|w - w_drift| - borrow*short   s.t. |w_i| <= min(9.5%, 0.95%/stop%_i) (stop = 2xATR14),
              sum|w| <= 58%, |beta'w| <= 0.01 (120d Blume beta vs SPY), k^2 * w' Sigma_LW w * 252 <= 6%^2,
              sector gross <= 20% / |net| <= 10% (current GICS; names without GICS are unconstrained by sector);
  costs     = 10 bp one-way flat + 25 bp/yr borrow on shorts.
NOT simulated: panic flag, drawdown breakers, stops being hit, 1% min-position, no-trade band, share rounding.
Forecast = sqrt(w' Sigma_LW w) at the rebalance (raw, k NOT applied); bias = std(r_t / sigma_hat_t,daily).
DESK_RULES #5 provenance: history only, read-only from the data owner's store files (bulk pd.read_parquet of the partitioned store; no
API/HTTP, no live calls, no data.json). desk_data_client.get_daily_bars is the per-symbol equivalent for bars; the bulk read is
kept because the client has no total_return / membership / delisting accessors. PROVISIONAL until the data owner's defect fixes land.
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, os, json, math, argparse, time
import numpy as np, pandas as pd, cvxpy as _cvxpy

cp: Any = _cvxpy  # cvxpy atoms are attached by star-import and are invisible to mypy
sys.path.insert(0, f"{_QR.DESK_DIR}/portfolio")
sys.path.insert(0, f"{_QR.DESK_DIR}/portfolio/research")
from quant_research.strategies.portfolio_construction.construct import shrunk_cov
from quant_research.strategies.portfolio_construction.research.riskmodels_wf import stationary_bootstrap
D = f"{_QR.DATA_DIR}"
SLEEVE_OF = {"MOM_12_1": "momentum", "RS63": "momentum", "TREND": "trend", "REV5": "reversal", "PEAD": "event"}

def load() -> tuple[Any, ...]:
    adj = pd.read_parquet(f"{D}/bars/daily/adjusted", columns=["symbol", "session_date", "open", "high", "low", "close", "volume", "zero_volume"])
    adj["session_date"] = pd.to_datetime(adj["session_date"])
    adj.loc[adj.zero_volume, ["open", "high", "low", "close", "volume"]] = np.nan
    P = {f: adj.pivot(index="session_date", columns="symbol", values=f).sort_index() for f in ["open", "high", "low", "close", "volume"]}
    tr = pd.read_parquet(f"{D}/bars/daily/total_return/daily_total_return.parquet", columns=["symbol", "session_date", "ret_total_best", "ret_total"])
    tr["session_date"] = pd.to_datetime(tr["session_date"])
    tr["r"] = tr["ret_total_best"].fillna(tr["ret_total"])
    R = tr.pivot(index="session_date", columns="symbol", values="r").reindex(P["close"].index)
    R = R.where(P["close"].notna())                                  # mask zero-volume placeholder rows
    mem = pd.read_parquet(f"{D}/universe/sp500_membership.parquet")
    uni = pd.read_parquet(f"{D}/universe/universe.parquet")
    dl = pd.read_parquet(f"{D}/universe/delisting_returns.parquet")
    return P, R, mem, uni, dl

def member_mask(mem: pd.DataFrame, idx: Any, cols: Any) -> Any:
    M = pd.DataFrame(False, index=idx, columns=cols)
    for _, r in mem.iterrows():
        if r.symbol not in M.columns:
            continue
        s = pd.Timestamp(r.start_date_filled)
        e = pd.Timestamp(r.end_date) if r.end_date is not None and not pd.isna(r.end_date) else None
        sel = (idx >= s) & ((idx < e) if e is not None else True)
        M.loc[sel, r.symbol] = True
    return M

def xs_z(X: pd.DataFrame, mask: pd.DataFrame) -> Any:
    X = X.where(mask)
    mu = X.mean(axis=1)
    sd = X.std(axis=1)
    return X.sub(mu, axis=0).div(sd.replace(0, np.nan), axis=0).clip(-3, 3)

def main() -> Any:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--lookback", type=int, default=120)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--ks", default="1.0,1.25")
    ap.add_argument("--cap", type=float, default=0.06)
    ap.add_argument("--tc", type=float, default=10e-4)
    ap.add_argument("--all5", action="store_true")
    ap.add_argument("--exclude_defects", action="store_true", help="drop every symbol in validator data_issues.json members_without_bars_symbols (+SNDK) - sensitivity")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    P, R, mem, uni, dl = load()
    C, O, H, L, V = P["close"], P["open"], P["high"], P["low"], P["volume"]
    idx = C.index
    spy = C["SPY"]
    roles = uni.set_index("symbol")["role"]
    gics = uni.set_index("symbol")["gics_sector"]
    stocks = [s for s in C.columns if roles.get(s) in ("sp500_current", "sp500_former_since_2016")]
    issues = json.load(open(f"{_QR.DESK_DIR}/validation/backtests/pead_long_pit/data_issues.json"))
    DEFECT = set(issues["members_without_bars_symbols"]) | {"SNDK"}          # Validator 2026-10-30 (read-only)
    FORMER = {s for s in stocks if roles.get(s) == "sp500_former_since_2016"}
    if a.exclude_defects:
        stocks = [s for s in stocks if s not in DEFECT]
    M = member_mask(mem, idx, stocks)
    # delisting terminal returns (matched only) on the session after the last bar
    term = {}
    for _, r in dl.iterrows():
        if pd.notna(r.terminal_return) and r.symbol in R.columns:
            last = pd.Timestamp(r.last_session)
            nxt = idx[idx > last]
            if len(nxt):
                R.loc[nxt[0], r.symbol] = r.terminal_return
                term[r.symbol] = (str(nxt[0].date()), float(r.terminal_return))
    # signals (construct.py definitions)
    sig = {}
    sig["MOM_12_1"] = C.shift(21) / C.shift(252) - 1
    sig["RS63"] = (C / C.shift(63) - 1).sub(spy / spy.shift(63) - 1, axis=0)
    sig["TREND"] = C / C.rolling(200, min_periods=200).mean() - 1
    sig["REV5"] = -(C / C.shift(5) - 1)
    gap = O / C.shift(1) - 1
    vr = V / V.shift(1).rolling(20).mean()
    sig["PEAD"] = gap.where((gap.abs() > 0.04) & (vr > 1.8)).ffill(limit=14).fillna(0.0).where(C.notna())
    sw = {"MOM_12_1": 0.25, "RS63": 0.0, "TREND": 0.25, "REV5": 0.25, "PEAD": 0.25} if not a.all5 else {k: 0.2 for k in SLEEVE_OF}
    Ms = M & C[stocks].notna()
    Z = {k: xs_z(sig[k][stocks], Ms) for k in sig}
    # sleeve proxies over all PIT members, lagged, unit gross; expanding sigma_target (PIT)
    Rs = R[stocks]
    mvals = {}
    for sl in sorted(set(SLEEVE_OF.values())):
        ks = [k for k in SLEEVE_OF if SLEEVE_OF[k] == sl]
        Zs = sum(Z[k].fillna(0) for k in ks) / len(ks)
        Zs = Zs.where(Ms)
        W = Zs.sub(Zs.mean(axis=1), axis=0)
        W = W.div(W.abs().sum(axis=1).replace(0, np.nan), axis=0)
        pr = (W.shift(1) * Rs).sum(axis=1, min_count=1)
        pr = pr[W.shift(1).abs().sum(axis=1) > 0]
        vol126 = pr.rolling(126).std() * math.sqrt(252)
        tgt = pr.expanding(252).std() * math.sqrt(252)
        mvals[sl] = (tgt / vol126).clip(upper=1.0).reindex(idx)
    # risk inputs
    tr_ = pd.concat([H - L, (H - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1, keys=["a", "b", "c"]).T.groupby(level=1).max().T
    atr = tr_.rolling(14).mean()
    dvol = (C * V).rolling(63, min_periods=40).median()
    sd5 = R.rolling(120).std() * math.sqrt(5)
    k_grid = [float(x) for x in a.ks.split(",")]
    start = 252 + 5   # warm-up: 252d for MOM_12_1 / proxies
    rebal = list(range(start, len(idx) - 1, a.step))
    res = {}
    diag_rows = []
    for k in k_grid:
        w_prev = pd.Series(dtype=float)
        rets, fcs, dates = [], [], []
        binds = []
        gross_l = []
        nsk = []
        sigs = []
        expo = []
        for j, t in enumerate(rebal):
            d = idx[t]
            win = R.iloc[t - a.lookback + 1: t + 1]
            elig = [s for s in stocks if Ms.at[d, s] and win[s].notna().all() and pd.notna(dvol.at[d, s]) and pd.notna(atr.at[d, s])]
            top = list(dvol.loc[d, elig].sort_values(ascending=False).index[: a.n])
            univ = top + ["SPY"]
            X = win[univ]
            Sig_d, rbar, delta = shrunk_cov(X, "lw")
            beta = 0.67 * (X.apply(lambda x: x.cov(X["SPY"])) / X["SPY"].var()).values + 0.33
            base = sum(sw[q] * Z[q].loc[d, top].fillna(0) for q in sw)
            comp_s = sum(sw[q] * (mvals[SLEEVE_OF[q]].at[d] if pd.notna(mvals[SLEEVE_OF[q]].at[d]) else 1.0) * Z[q].loc[d, top].fillna(0) for q in sw)
            sdb = base.std()
            comp = ((comp_s - base.mean()) / sdb).clip(-3, 3) if sdb > 0 else comp_s * 0
            alpha = np.array([0.02 * sd5.at[d, s] * comp[s] for s in top] + [0.0])
            px = C.loc[d, univ].values
            stop = (2 * atr.loc[d, univ].values / px)
            capv = np.minimum(0.095, 0.0095 / stop)
            w0 = w_prev.reindex(univ).fillna(0).values
            n = len(univ)
            w = cp.Variable(n)
            cons = [cp.abs(w) <= capv, cp.norm1(w) <= 0.58, cp.abs(beta @ w) <= 0.01,
                    cp.quad_form(w, cp.psd_wrap(Sig_d * 252 * k * k)) <= a.cap ** 2]
            secs: dict[Any, Any] = {}
            for i, s in enumerate(top):
                g = gics.get(s)
                if isinstance(g, str) and g:
                    secs.setdefault(g, []).append(i)
            for g, ii in secs.items():
                cons += [cp.norm1(w[ii]) <= 0.20, cp.abs(cp.sum(w[ii])) <= 0.10]
            borrow = 0.0025 * a.step / 252
            prob = cp.Problem(cp.Maximize(alpha @ w - a.tc * cp.norm1(w - w0) - borrow * cp.sum(cp.neg(w))), cons)
            try:
                prob.solve(solver="CLARABEL")
            except Exception:
                prob.solve(solver="SCS")
            wv = np.array(w.value).ravel() if w.value is not None else w0
            wv[np.abs(wv) < 1e-6] = 0.0
            cost = a.tc * np.abs(cast(np.ndarray, wv) - cast(np.ndarray, w0)).sum()
            fc = math.sqrt(max(wv @ Sig_d @ wv, 0))                  # daily, raw (k not applied)
            ws_ = pd.Series(wv, univ)
            gsum = ws_.abs().sum() or 1.0
            expo.append(dict(date=str(d.date()), univ_former=sum(x in FORMER for x in top), univ_defect=sum(x in DEFECT for x in top),
                             g_former=float(ws_[[x for x in top if x in FORMER]].abs().sum() / gsum), g_defect=float(ws_[[x for x in top if x in DEFECT]].abs().sum() / gsum),
                             sndk=float(ws_.get("SNDK", 0.0)), defect_names=[x for x in top if x in DEFECT and abs(ws_[x]) > 1e-6]))
            binds.append(k * fc * math.sqrt(252) >= a.cap * 0.995)
            gross_l.append(np.abs(wv).sum())
            sigs.append(fc * math.sqrt(252))
            # hold until next rebalance with drift; names with no return (delisted, unmatched) -> 0 return, then dropped
            wcur = pd.Series(wv, univ)
            t_end = rebal[j + 1] if j + 1 < len(rebal) else min(t + a.step, len(idx) - 1)
            for u in range(t + 1, t_end + 1):
                r = R.iloc[u].reindex(wcur.index)
                miss = r.isna() & (wcur != 0)
                if miss.any():
                    nsk.append((str(idx[u].date()), list(wcur[miss].index), [round(x, 4) for x in wcur[miss].values]))
                r = r.fillna(0.0)
                pr = float((wcur * r).sum()) - (cost if u == t + 1 else 0.0)
                rets.append(pr)
                fcs.append(fc)
                dates.append(idx[u])
                wcur = wcur * (1 + r) / (1 + float((wcur * r).sum()))
                wcur[miss] = 0.0
            w_prev = wcur
            if k == k_grid[0]:
                diag_rows.append(dict(date=str(d.date()), n=len(top), delta=delta, rbar=rbar))
        res[k] = dict(expo=expo, ret=pd.Series(rets, dates), fc=pd.Series(fcs, dates), bind=np.array(binds), gross=np.array(gross_l), sig=np.array(sigs), missing=nsk)
        print(f"k={k} done {time.time()-t0:.0f}s", flush=True)
    # stats + bootstrap
    Rm = pd.DataFrame({k: res[k]["ret"] for k in k_grid})
    Fm = pd.DataFrame({k: res[k]["fc"] for k in k_grid})
    rng = np.random.default_rng(7)
    nobs = len(Rm)
    bv: dict[float, list[float]] = {k: [] for k in k_grid}
    bb: dict[float, list[float]] = {k: [] for k in k_grid}
    br: dict[float, list[float]] = {k: [] for k in k_grid}
    for _ in range(a.boot):
        ix = stationary_bootstrap(nobs, 10, rng)
        rb = Rm.values[ix]
        fb = Fm.values[ix]
        v = rb.std(0) * math.sqrt(252)
        b = (rb / fb).std(0)
        rr = v / (fb.mean(0) * math.sqrt(252))
        for j, k in enumerate(k_grid):
            bv[k].append(v[j])
            bb[k].append(b[j])
            br[k].append(rr[j])
    q: Callable[[Any], list[float]] = lambda x: [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]
    table = {}
    for k in k_grid:
        r = cast(pd.Series, res[k]["ret"])
        f = cast(pd.Series, res[k]["fc"])
        bind = cast(pd.Series, res[k]["bind"])
        gross_s = cast(pd.Series, res[k]["gross"])
        expo = cast(list[dict[str, Any]], res[k]["expo"])
        rv = float(r.std() * math.sqrt(252))
        year_stats: Callable[[pd.DataFrame], pd.Series] = lambda g: pd.Series(dict(
            realised=g.r.std() * math.sqrt(252), fc_raw=g.f.mean() * math.sqrt(252), bias=(g.r / g.f).std(), days=len(g)))
        yr = pd.DataFrame({"r": r, "f": f}).groupby(cast(pd.DatetimeIndex, r.index).year).apply(year_stats)
        table[str(k)] = dict(k=k, realised_vol=rv, realised_vol_ci95=q(bv[k]), ex_ante_raw_mean=float(f.mean() * math.sqrt(252)),
                             ex_ante_inflated_mean=float(k * f.mean() * math.sqrt(252)),
                             realised_over_cap=rv / a.cap, realised_over_raw_forecast=rv / float(f.mean() * math.sqrt(252)),
                             realised_over_raw_forecast_ci95=q(br[k]), bias_stat=float((r / f).std()), bias_ci95=q(bb[k]),
                             share_rebal_cap_binding=float(bind.mean()), gross_mean=float(gross_s.mean()),
                             ann_ret=float(r.mean() * 252), sharpe=float(r.mean() * 252 / rv), max_dd=float(((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()),
                             share_63d_windows_above_cap=float(((r.rolling(63).std() * math.sqrt(252)).dropna() > a.cap).mean()),
                             by_year={int(cast(Any, y)): {kk: round(float(vv), 4) for kk, vv in row.items()} for y, row in yr.iterrows()},
                             held_names_without_return=res[k]["missing"],
                             exposure=dict(mean_univ_former=float(np.mean([e["univ_former"] for e in expo])),
                                           mean_univ_defect=float(np.mean([e["univ_defect"] for e in expo])),
                                           share_gross_former_mean=float(np.mean([e["g_former"] for e in expo])),
                                           share_gross_defect_mean=float(np.mean([e["g_defect"] for e in expo])),
                                           rebal_with_defect_position=int(sum(1 for e in expo if e["defect_names"])),
                                           defect_names_held=sorted({x for e in expo for x in cast(Iterable[Any], e["defect_names"])}),
                                           sndk_ever_in_book=bool(any(abs(cast(float, e["sndk"])) > 1e-6 for e in expo))))
    dg = pd.DataFrame(diag_rows)
    meta = dict(status="PROVISIONAL - data defects pending the data owner's fixes (validator validation/backtests/pead_long_pit/data_issues.json)", exclude_defects=a.exclude_defects, data_span=[str(idx[0].date()), str(idx[-1].date())], data_years=round((idx[-1] - idx[0]).days / 365.25, 2),
                oos_start=str(Rm.index[0].date()), oos_end=str(Rm.index[-1].date()), oos_days=nobs, oos_years=round(nobs / 252, 2),
                n_rebal=len(rebal), universe_rule=f"PIT S&P 500 members, 120 complete returns, top {a.n} by 63d median $ volume, + SPY hedge",
                signal_weights=sw, lw_delta_mean=float(dg.delta.mean()), lw_delta_range=[float(dg.delta.min()), float(dg.delta.max())],
                avg_corr_mean=float(dg.rbar.mean()), tc_bps=a.tc * 1e4, cap=a.cap, step=a.step, lookback=a.lookback,
                distinct_names_traded=None, terminal_returns_applied=len(term),
                bootstrap=dict(type="stationary", block=10, reps=a.boot), runtime_s=round(time.time() - t0))
    json.dump(dict(meta=meta, table=table), open(a.out, "w"), indent=1, default=str)
    Rm.assign(**{f"fc_{k}": Fm[k] for k in k_grid}).to_csv(a.out.replace(".json", "_daily.csv"))
    print(json.dumps(meta, default=str))
    for k in k_grid:
        row = table[str(k)]
        print(k, {x: row[x] for x in row if x not in ("by_year", "held_names_without_return")})
        print("exposure", row["exposure"])
        print(pd.DataFrame(row["by_year"]).T.round(4).to_string())
        print("missing:", row["held_names_without_return"][:20])

if __name__ == "__main__":
    main()
