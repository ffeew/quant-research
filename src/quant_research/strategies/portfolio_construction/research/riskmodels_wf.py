from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

#!/usr/bin/env python3
"""
Walk-forward head-to-head of risk-based allocators (no look-ahead), research only. Places no orders.
  (a) IV     inverse-vol  w ∝ 1/σ_i (sample vol over lookback)
  (b) MV-S   long-only min-variance, sample covariance, sum w = 1, w_i ≤ 10%
  (c) MV-LW  same optimiser, Ledoit-Wolf (2004) constant-correlation shrinkage with the OPTIMAL intensity δ*
             (own implementation of the 'Honey' paper's Appendix B / Ledoit's covCor.m; NOT sklearn's LedoitWolf,
              which shrinks to a scaled identity - a different target)
  (c') MV-CC50 same optimiser, fixed δ = 0.5 to constant correlation (what construct.py uses today)
  (d) HRP    López de Prado (2016): correlation distance, single linkage, quasi-diagonalisation, recursive bisection
             with inverse-variance cluster weights, on the sample covariance (as in the paper)
Rebalance at the close of day t using returns up to and including t; hold from t+1 (close-to-close).
Cost: 10 bps one-way on |w_target - w_drifted| (initial build from cash counted in cost, excluded from turnover stats).
Forecast vol = sqrt(w' Σ̂ w) of each method's own risk model (IV and HRP: sample Σ).  Bias stat = std(r_t / σ̂_t).
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import json, math, sys, argparse
import numpy as np, pandas as pd, cvxpy as _cvxpy

cp: Any = _cvxpy  # cvxpy atoms are attached by star-import and are invisible to mypy
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import squareform

NON_ALPHA = {"SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "TLT", "HYG", "GLD", "SLV"}
SECTOR_ETF = {"XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY", "SMH"}
CRYPTO = {"BTC/USD", "ETH/USD", "SOL/USD"}
CUTOFF = "2026-10-29"   # 2026-10-29 bar is partial at run time (market open)
# Data-provenance rule (2026-10-30): history ONLY from the shared store, via $QR_DATA_DIR/lib/desk_data_client.py.
# src="store" (default) = desk universe (construct.DESK_UNIVERSE, alpha names only) from bars/daily/adjusted (SIP, adjustment=all),
# allow_api=False (history only; no live calls in research). "datajson"/"statarb" are RETIRED sources kept only so earlier
# outputs can be reproduced/audited: they raise unless allow_retired=True (CLI --allow_retired). statarb -> the derivatives researcher's audit copy.
RETIRED = {"datajson": f"{_QR.DESK_DIR}/data.json", "statarb": f"{_QR.DESK_DIR}/statarb/data/_deprecated/daily_bars.json"}
STORE_START = "2016-01-01"

def _load_store(fields: tuple[str, ...], start: str = STORE_START) -> Any:
    sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
    sys.path.insert(0, f"{_QR.DESK_DIR}/portfolio")
    from quant_research.data.client import desk_data_client as ddc
    from quant_research.strategies.portfolio_construction.construct import DESK_UNIVERSE
    syms = [s for s in DESK_UNIVERSE if s not in CRYPTO and s not in NON_ALPHA and s not in SECTOR_ETF]
    df = ddc.get_daily_bars(syms, start, (pd.Timestamp(CUTOFF) - pd.Timedelta(days=1)).date(), adjustment="all", allow_api=False)
    df = df[df["session_date"].astype(str) < CUTOFF].copy()
    df["session_date"] = pd.to_datetime(df["session_date"])
    if "zero_volume" in df:
        df.loc[df["zero_volume"].fillna(False).astype(bool), ["close", "volume"]] = np.nan
    col = {"c": "close", "v": "volume", "o": "open", "h": "high", "l": "low"}
    return {f: df.pivot(index="session_date", columns="symbol", values=col[f]).sort_index() for f in fields}

def load_closes(src: str = "store", fields: tuple[str, ...] = ("c",), allow_retired: bool = False, start: str = STORE_START) -> Any:
    if src == "store":
        frames = _load_store(fields, start)
        C = frames["c"]
        keep_dates = C.index[C.notna().mean(1) >= 0.5]
        C = C.loc[keep_dates]
        full = C.columns[C.notna().mean() >= 0.99]
        return {f: frames[f].loc[keep_dates, full].ffill() for f in fields}, sorted(set(C.columns) - set(full))
    if not allow_retired:
        raise SystemExit(f"src={src!r} is a RETIRED data source (DESK_RULES #5); use src='store', or --allow_retired for audit reproduction only")
    path = RETIRED[src]
    d = json.load(open(path))
    out: dict[str, dict[str, Any]] = {f: {} for f in fields}
    for s, b in d["bars"].items():
        if s in CRYPTO or s in NON_ALPHA or s in SECTOR_ETF:
            continue
        b = [x for x in b if x["t"][:10] < CUTOFF]
        idx = pd.to_datetime([x["t"][:10] for x in b])
        for f in fields:
            out[f][s] = pd.Series([x[f] for x in b], idx)
    frames = {f: pd.DataFrame(v).sort_index() for f, v in out.items()}
    C = frames["c"]
    keep_dates = C.index[C.notna().mean(1) >= 0.5]   # drop stray dates where most names have no bar
    C = C.loc[keep_dates]
    full = C.columns[C.notna().mean() >= 0.99]       # fixed universe: >=99% coverage over the sample
    # remaining isolated gaps (IEX no-print days) are forward-filled = 0 return that day
    return {f: frames[f].loc[keep_dates, full].ffill() for f in fields}, sorted(set(C.columns) - set(full))

# ---------- risk models ----------
def lw_cc(X: np.ndarray) -> Any:
    """Ledoit & Wolf (2004) shrinkage to constant correlation; returns (Σ, δ*). X: T×N returns."""
    T, N = X.shape
    X = X - X.mean(0)
    S = X.T @ X / T
    var = np.diag(S)
    sd = np.sqrt(var)
    rbar = ((S / np.outer(sd, sd)).sum() - N) / (N * (N - 1))
    F = rbar * np.outer(sd, sd)
    np.fill_diagonal(F, var)
    Y = X ** 2
    phiMat = Y.T @ Y / T - 2 * (X.T @ X) * S / T + S ** 2
    phi = phiMat.sum()
    term1 = (X ** 3).T @ X / T
    help_ = X.T @ X / T
    hd = np.diag(help_)
    term2 = hd[:, None] * S
    term3 = help_ * var[None, :]
    term4 = var[:, None] * S
    theta = term1 - term2 - term3 + term4
    np.fill_diagonal(theta, 0)
    rho = np.diag(phiMat).sum() + rbar * ((1 / sd)[:, None] * sd[None, :] * theta).sum()
    gamma = np.linalg.norm(S - F, "fro") ** 2
    kappa = (phi - rho) / gamma
    d = max(0.0, min(1.0, kappa / T))
    return d * F + (1 - d) * S, d

def cc_fixed(X: np.ndarray, d: float = 0.5) -> Any:
    S = np.cov(X, rowvar=False, bias=True)
    sd = np.sqrt(np.diag(S))
    N = len(sd)
    rbar = ((S / np.outer(sd, sd)).sum() - N) / (N * (N - 1))
    F = rbar * np.outer(sd, sd)
    np.fill_diagonal(F, sd ** 2)
    return d * F + (1 - d) * S

def minvar(Sig: np.ndarray, cap: float = 0.10) -> Any:
    n = len(Sig)
    w = cp.Variable(n)
    P = cp.psd_wrap((Sig + Sig.T) / 2 * 1e4)
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, P)), [cp.sum(w) == 1, w >= 0, w <= cap])
    prob.solve(solver="CLARABEL")
    v = np.clip(np.array(w.value).ravel(), 0, None)
    return v / v.sum()

def hrp(Sig: np.ndarray) -> Any:
    sd = np.sqrt(np.diag(Sig))
    corr = np.clip(Sig / np.outer(sd, sd), -1, 1)
    dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
    # as in the paper's snippet: linkage on the Euclidean distance between columns of the distance matrix
    link = sch.linkage(dist, "single")
    order = list(sch.leaves_list(link))
    w = pd.Series(1.0, index=order)
    clusters = [order]
    def cvar(ix: Any) -> Any:
        c = Sig[np.ix_(ix, ix)]
        iv = 1 / np.diag(c)
        iv /= iv.sum()
        return iv @ c @ iv
    while clusters:
        clusters = [c[j:k] for c in clusters for j, k in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for i in range(0, len(clusters), 2):
            c0, c1 = clusters[i], clusters[i + 1]
            v0, v1 = cvar(c0), cvar(c1)
            al = 1 - v0 / (v0 + v1)
            w[cast(Any, c0)] *= al
            w[cast(Any, c1)] *= 1 - al
    out = np.zeros(len(sd))
    out[cast(Any, w.index.values)] = cast(Any, w.values)
    return out

def weights(method: str, X: np.ndarray) -> Any:
    S = np.cov(X, rowvar=False, bias=True)
    if method == "IV":
        v = 1 / np.sqrt(np.diag(S))
        return v / v.sum(), S, None
    if method == "MV-S":
        return minvar(S), S, None
    if method == "MV-LW":
        L, d = lw_cc(X)
        return minvar(L), L, d
    if method == "MV-CC50":
        L = cc_fixed(X)
        return minvar(L), L, 0.5
    if method == "HRP":
        return hrp(S), S, None
    raise ValueError(method)

# ---------- TCA cost model (tca/baseline_report.md §5), per side, in fraction of notional ----------
def tca_costs(C: pd.DataFrame, V: pd.DataFrame, src: str, equity: float = 100_000.0, k: float = 0.75, clip: float = 0.01, haircut_bps: float = 2.0, hs_default: float = 2.75) -> Any:
    """HS (measured pilot half-spread if available, else L1 default 2.75) + k*sigma*sqrt(Q/ADV) + H.
    Q = clip*equity; sigma = median 20d daily vol over the sample; ADV = median 20d $ADV (store: SIP, x1.0; retired IEX
    sources: x SIP/IEX ratio 21.6 measured on the 5 pilot names). Impact is < 0.1 bps at these sizes, so the use of
    full-sample medians for sigma/ADV (a mild look-ahead) is immaterial; HS + H dominate."""
    import csv
    hs: dict[str, Any] = {}
    for r in csv.DictReader(open(f"{_QR.DESK_DIR}/tca/fills_20261030.csv")):
        if r.get("half_spread_bps"):
            hs.setdefault(r["symbol"], []).append(float(r["half_spread_bps"]))
    hs = {s: float(np.mean(v)) for s, v in hs.items()}
    R = C.pct_change()
    sig = R.rolling(20).std().median()
    adv = ((C * V).rolling(20).mean().median() * 21.6) if V is not None else pd.Series(2e9, C.columns)
    bps = np.array([hs.get(s, hs_default) + k * sig[s] * math.sqrt(clip * equity / adv[s]) * 1e4 + haircut_bps for s in C.columns])
    meta = dict(formula="HS + k*sigma*sqrt(Q/ADV) + H", k=k, Q=f"{clip:.0%} of ${equity:.0f}", H_bps=haircut_bps,
                hs_measured={s: round(hs[s], 2) for s in C.columns if s in hs}, hs_default=hs_default,
                per_side_bps_min_med_max=[round(float(bps.min()), 2), round(float(np.median(bps)), 2), round(float(bps.max()), 2)])
    return bps / 1e4, meta

# ---------- simulator ----------
def simulate(R: pd.DataFrame, lookback: int, step: int, methods: list[str], tc: Any = 10e-4, tau: Any = None, cache: dict[Any, Any] | None = None) -> Any:
    """R: daily returns DataFrame. tau: dict method->trade rate (GP partial trading) else full rebalance."""
    dates = R.index
    Rv = R.values
    T, N = Rv.shape
    res = {}
    for m in methods:
        rate = (tau or {}).get(m, 1.0)
        w = np.zeros(N)
        wt_hold = None
        started = False
        rets, fc, turn_list, cost_list, deltas, te = [], [], [], [], [], []
        sig_fc = np.nan
        for t in range(lookback, T - 1):
            if (t - lookback) % step == 0:
                key = (m, t)
                if cache is not None and key in cache:
                    tgt, Sig, d = cache[key]
                else:
                    tgt, Sig, d = weights(m, Rv[t - lookback + 1: t + 1])
                    if cache is not None:
                        cache[key] = (tgt, Sig, d)
                new = tgt if not started else w + rate * (tgt - w)
                tr = np.abs(new - w).sum()
                cost = float(np.abs(new - w) @ tc) if np.ndim(tc) else tc * tr
                if started:
                    turn_list.append(tr)
                cost_list.append(cost)
                w = new
                started = True
                wt_hold = tgt.copy()
                sig_fc = math.sqrt(w @ Sig @ w)
                if d is not None:
                    deltas.append(d)
            else:
                cost = 0.0
            r = Rv[t + 1]
            pr = float(w @ r) - cost
            pt = float(wt_hold @ r)
            rets.append(pr)
            fc.append(sig_fc)
            te.append(float(w @ r) - pt)
            g = w * (1 + r)
            w = g / (1 + w @ r)                      # drift
            g2 = wt_hold * (1 + r)
            wt_hold = g2 / (1 + wt_hold @ r)
        idx = dates[lookback + 1:]
        res[m] = dict(ret=pd.Series(rets, idx), fc=pd.Series(fc, idx), turn=np.array(turn_list),
                      cost=np.array(cost_list), delta=np.array(deltas), te=pd.Series(te, idx))
    return res

def stats(r: Any, fc: Any = None) -> Any:
    v = r.std() * math.sqrt(252)
    mu = r.mean() * 252
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    out = dict(ann_ret=mu, ann_vol=v, sharpe=mu / v if v > 0 else np.nan, max_dd=dd)
    if fc is not None:
        out["fc_vol"] = fc.mean() * math.sqrt(252)
        out["real_over_fc"] = v / out["fc_vol"]
        out["bias_stat"] = float((r / fc).std())
    return out

def stationary_bootstrap(n: int, mean_block: int, rng: Any) -> Any:
    idx = np.empty(n, dtype=int)
    i = rng.integers(n)
    for k in range(n):
        idx[k] = i
        i = rng.integers(n) if rng.random() < 1 / mean_block else (i + 1) % n
    return idx

def bootstrap(res: dict[str, Any], methods: list[str], B: int = 2000, block: int = 10, seed: int = 7, ref: str = "MV-LW") -> Any:
    rng = np.random.default_rng(seed)
    Rm = pd.DataFrame({m: res[m]["ret"] for m in methods})
    Fm = pd.DataFrame({m: res[m]["fc"] for m in methods})
    n = len(Rm)
    out: dict[str, dict[str, list[float]]] = {m: {"vol": [], "sharpe": [], "bias": []} for m in methods}
    diffs: dict[str, dict[str, list[float]]] = {m: {"dvol": [], "dsharpe": []} for m in methods if m != ref}
    for _ in range(B):
        ix = stationary_bootstrap(n, block, rng)
        rb = Rm.values[ix]
        fb = Fm.values[ix]
        vol = rb.std(0) * math.sqrt(252)
        sh = rb.mean(0) * 252 / vol
        bias = (rb / fb).std(0)
        for j, m in enumerate(methods):
            out[m]["vol"].append(vol[j])
            out[m]["sharpe"].append(sh[j])
            out[m]["bias"].append(bias[j])
        jr = methods.index(ref)
        for j, m in enumerate(methods):
            if m == ref:
                continue
            diffs[m]["dvol"].append(vol[j] - vol[jr])
            diffs[m]["dsharpe"].append(sh[j] - sh[jr])
    q: Callable[[Any], tuple[float, float]] = lambda a: (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))
    ci = {m: {k: q(v) for k, v in d.items()} for m, d in out.items()}
    dci = {m: {k: q(v) | (dict(p_gt0=float(np.mean(np.array(v) > 0))),) if False else (q(v)[0], q(v)[1], float(np.mean(np.array(v) > 0))) for k, v in d.items()} for m, d in diffs.items()}
    return ci, dci

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="store", choices=["store", "datajson", "statarb"])
    ap.add_argument("--allow_retired", action="store_true", help="audit reproduction of pre-rule-5 outputs only")
    ap.add_argument("--start", default=STORE_START)
    ap.add_argument("--lookback", type=int, default=120)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    fr, dropped = load_closes(a.src, fields=("c", "v"), allow_retired=a.allow_retired, start=a.start)
    C = fr["c"]
    R = C.pct_change(fill_method=None).iloc[1:]
    jumps = [(str(d.date()), s, round(float(v), 3)) for (d, s), v in R.stack().items() if abs(v) > 0.3]
    methods = ["IV", "MV-S", "MV-LW", "MV-CC50", "HRP"]
    cache: dict[Any, Any] = {}
    res = simulate(R, a.lookback, a.step, methods, cache=cache)
    tca_vec, tca_meta = tca_costs(C, fr.get("v"), a.src)
    res_tca = simulate(R, a.lookback, a.step, methods, tc=tca_vec, cache=cache)
    oos_days = len(res["IV"]["ret"])
    yrs = oos_days / 252
    table = {}
    for m in methods:
        s = stats(res[m]["ret"], res[m]["fc"])
        s["turnover_ann_oneway"] = float(res[m]["turn"].sum() / yrs)
        s["avg_turn_per_rebal"] = float(res[m]["turn"].mean())
        s["cost_drag_ann"] = float(res[m]["cost"][1:].sum() / yrs)
        st = stats(res_tca[m]["ret"])
        s["tca_ann_ret"], s["tca_sharpe"], s["tca_cost_drag_ann"] = st["ann_ret"], st["sharpe"], float(res_tca[m]["cost"][1:].sum() / yrs)
        s["lw_delta_mean"] = float(res[m]["delta"].mean()) if len(res[m]["delta"]) else None
        s["lw_delta_range"] = (float(res[m]["delta"].min()), float(res[m]["delta"].max())) if len(res[m]["delta"]) else None
        table[m] = s
    ci, dci = bootstrap(res, methods, B=a.boot)
    meta = dict(src=a.src, data_provenance=("shared store via desk_data_client (data-provenance rule)" if a.src == "store" else "RETIRED source (audit reproduction)"), universe_n=C.shape[1], dropped_incomplete=dropped, first_bar=str(C.index[0].date()), last_bar=str(C.index[-1].date()),
                lookback=a.lookback, step=a.step, oos_start=str(res["IV"]["ret"].index[0].date()), oos_end=str(res["IV"]["ret"].index[-1].date()),
                oos_days=oos_days, n_rebal=int(len(res["IV"]["cost"])), tc_bps_oneway=10, big_moves_gt30pct=jumps,
                tca_cost_model=tca_meta, bootstrap=dict(type="stationary (Politis-Romano), joint across methods", mean_block_days=10, reps=a.boot))
    json.dump(dict(meta=meta, table=table, ci95=ci, diff_vs_MV_LW_ci95_pgt0=dci), open(a.out, "w"), indent=1, default=float)
    pd.DataFrame({m: res[m]["ret"] for m in methods}).to_csv(a.out.replace(".json", "_daily.csv"))
    print(json.dumps(meta, default=str))
    print(pd.DataFrame(table).T.round(4).to_string())
    print(json.dumps(ci, indent=0))
    print(json.dumps(dci, indent=0))
