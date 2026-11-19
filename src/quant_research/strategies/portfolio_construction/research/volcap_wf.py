from __future__ import annotations

from collections.abc import Callable
from typing import Any

#!/usr/bin/env python3
"""
Walk-forward check: realised vs targeted vol of the MV-LW book under a 6% ex-ante vol CAP,
risk-forecast inflation k = 1.0 vs 1.25. Research only; places no orders.
Setup = riskmodels_wf.py (same loader, universe, L=120 lookback, weekly step, 10 bps one-way, close-to-close, no look-ahead).
Book: long-only min-variance on the LW(2004) constant-correlation shrunk covariance (sum w = 1, w_i <= 10%),
then scaled by c = min(1, cap / (k * sigma_hat_ann)), remainder in cash (0 return; no leverage).
sigma_hat_ann = sqrt(w' Sigma_LW w * 252) at rebalance. Realised vol = std(daily OOS returns)*sqrt(252).
CIs: stationary bootstrap (Politis-Romano), mean block 10 days, 2000 reps, joint across k.
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, json, math, argparse
import numpy as np, pandas as pd
sys.path.insert(0, f"{_QR.DESK_DIR}/portfolio/research")
from quant_research.strategies.portfolio_construction.research.riskmodels_wf import load_closes, lw_cc, minvar, stationary_bootstrap

def run(R: pd.DataFrame, lookback: int, step: int, cap: float, ks: list[float], tc: float = 10e-4) -> Any:
    Rv = R.values
    T, N = Rv.shape
    out = {}
    cache = {}
    for k in ks:
        w = np.zeros(N)
        started = False
        rets, fc, cs, ex_inf = [], [], [], []
        for t in range(lookback, T - 1):
            cost = 0.0
            if (t - lookback) % step == 0:
                if t not in cache:
                    L, d = lw_cc(Rv[t - lookback + 1: t + 1])
                    cache[t] = (minvar(L), L, d)
                wm, L, d = cache[t]
                sig = math.sqrt(wm @ L @ wm * 252)
                c = min(1.0, cap / (k * sig))
                new = c * wm
                cost = tc * np.abs(new - w).sum()
                w = new
                started = True
                fc_raw = math.sqrt(w @ L @ w * 252)
                cs.append(c)
            r = Rv[t + 1]
            pr = float(w @ r) - cost
            rets.append(pr)
            fc.append(fc_raw)
            ex_inf.append(k * fc_raw)
            g = w * (1 + r)
            w = g / (1 + w @ r)
        idx = R.index[lookback + 1:]
        out[k] = dict(ret=pd.Series(rets, idx), fc=pd.Series(fc, idx), fc_inf=pd.Series(ex_inf, idx), c=np.array(cs),
                      delta=np.array([cache[t][2] for t in sorted(cache)]))
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=["store", "datajson", "statarb"], default="store")   # DESK_RULES #5: store via desk_data_client
    ap.add_argument("--allow_retired", action="store_true", help="audit reproduction of pre-rule-5 outputs only")
    ap.add_argument("--lookback", type=int, default=120)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--cap", type=float, default=0.06)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    fr, dropped = load_closes(a.src, allow_retired=a.allow_retired)
    C = fr["c"]
    R = C.pct_change(fill_method=None).iloc[1:]
    ks = [1.0, 1.25]
    res = run(R, a.lookback, a.step, a.cap, ks)
    Rm = pd.DataFrame({k: res[k]["ret"] for k in ks})
    Fm = pd.DataFrame({k: res[k]["fc"] for k in ks}) / math.sqrt(252)   # daily forecast vol
    rng = np.random.default_rng(7)
    n = len(Rm)
    bv: dict[Any, list[float]] = {k: [] for k in ks}
    bb: dict[Any, list[float]] = {k: [] for k in ks}
    bd = []
    for _ in range(a.boot):
        ix = stationary_bootstrap(n, 10, rng)
        rb = Rm.values[ix]
        fb = Fm.values[ix]
        v = rb.std(0) * math.sqrt(252)
        b = (rb / fb).std(0)
        for j, k in enumerate(ks):
            bv[k].append(v[j])
            bb[k].append(b[j])
        bd.append(v[1] - v[0])
    q: Callable[[Any], list[float]] = lambda x: [round(float(np.percentile(x, 2.5)), 5), round(float(np.percentile(x, 97.5)), 5)]
    table = {}
    for k in ks:
        r = res[k]["ret"]
        rv = float(r.std() * math.sqrt(252))
        roll = r.rolling(63).std() * math.sqrt(252)
        table[str(k)] = dict(risk_inflation=k, cap=a.cap, realised_vol=rv, realised_vol_ci95=q(bv[k]),
                             ex_ante_raw_mean=float(res[k]["fc"].mean()), ex_ante_inflated_mean=float(res[k]["fc_inf"].mean()),
                             realised_over_cap=rv / a.cap, bias_stat_raw=float((r / (res[k]["fc"] / math.sqrt(252))).std()),
                             bias_ci95=q(bb[k]), mean_scale_c=float(res[k]["c"].mean()), min_scale_c=float(res[k]["c"].min()),
                             max_scale_c=float(res[k]["c"].max()),
                             ann_ret=float(r.mean() * 252), sharpe=float(r.mean() * 252 / rv),
                             share_63d_windows_above_cap=float((roll.dropna() > a.cap).mean()),
                             rolling63_vol_min_med_max=[float(roll.min()), float(roll.median()), float(roll.max())])
    meta = dict(src=a.src, universe_n=C.shape[1], lookback=a.lookback, step=a.step, oos_start=str(Rm.index[0].date()),
                oos_end=str(Rm.index[-1].date()), oos_days=n, n_rebal=int(len(res[1.0]["c"])), tc_bps=10,
                lw_delta_mean=float(res[1.0]["delta"].mean()), lw_delta_range=[float(res[1.0]["delta"].min()), float(res[1.0]["delta"].max())],
                bootstrap=dict(type="stationary", block=10, reps=a.boot), dvol_k125_minus_k1_ci95=q(bd))
    json.dump(dict(meta=meta, table=table), open(a.out, "w"), indent=1)
    Rm.to_csv(a.out.replace(".json", "_daily.csv"))
    print(json.dumps(meta))
    print(pd.DataFrame(table).T.to_string())
