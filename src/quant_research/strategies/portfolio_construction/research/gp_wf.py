"""Garleanu-Pedersen (2013) partial trading: walk-forward test (research only; no look-ahead).

Part A: risk portfolios (MV-LW, HRP from riskmodels_wf.py), trade rate tau in {1, .732, .5, .2965, .1}.
Part B: a long/short signal book (MOM_12_1, RS63, TREND, REV5; PEAD omitted: no earnings history in the
        bar files), full rebalance vs partial trading (tau only) vs full GP (aim multipliers + tau).
Costs: flat 10 bps one-way AND the tca/baseline_report.md §5 per-name model (riskmodels_wf.tca_costs),
       plus 25 bps/yr borrow on short MV (tca/cost_model.md §4 ASSUMPTION) in Part B.
GP scalar mapping (Prop. 2 under Lambda = lambda*Sigma, rho = 0): ell = lambda/gamma,
   a/gamma = (-ell + sqrt(ell^2 + 4 ell)) / 2,  tau = (a/gamma)/ell.  Aim (Prop. 4): factor k scaled by 1/(1 + phi_k a/gamma).
"""
from __future__ import annotations

from typing import Any, cast

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import json, math, sys
import numpy as np, pandas as pd
sys.path.insert(0, f"{_QR.DESK_DIR}/portfolio/research")
from quant_research.strategies.portfolio_construction.research import riskmodels_wf as rw

def gp(ell: float, rho: float = 0.0) -> Any:
    b = (1 - rho) + ell * rho
    ag = (-b + math.sqrt(b * b + 4 * ell * (1 - rho) ** 2)) / (2 * (1 - rho))
    return ag, ag / ell

TAUS = [1.0, gp(0.5)[1], gp(2)[1], gp(8)[1], 0.1]

def te_ann(x: Any) -> Any: return float(x.std() * math.sqrt(252))

def part_a(src: str, allow_retired: bool = False) -> Any:
    fr, _ = rw.load_closes(src, fields=("c", "v"), allow_retired=allow_retired)
    C = fr["c"]
    R = C.pct_change().iloc[1:]
    tca, _ = rw.tca_costs(C, fr["v"], src)
    out: list[Any] = []
    cache: dict[Any, Any] = {}
    for m in ["MV-LW", "HRP"]:
        base = None
        for tau in TAUS:
            r10 = rw.simulate(R, 120, 5, [m], tau={m: tau}, cache=cache)[m]
            rt = rw.simulate(R, 120, 5, [m], tc=tca, tau={m: tau}, cache=cache)[m]
            gross = r10["ret"] + pd.Series(0.0, r10["ret"].index)  # net of 10bp; rebuild gross below
            yrs = len(r10["ret"]) / 252
            s10, st = rw.stats(r10["ret"]), rw.stats(rt["ret"])
            if base is None:
                base = rt["ret"]
            out.append(dict(src=src, method=m, tau=round(tau, 4), turnover_ann=float(r10["turn"].sum() / yrs),
                            cost_bp_10=float(r10["cost"][1:].sum() / yrs * 1e4), cost_bp_tca=float(rt["cost"][1:].sum() / yrs * 1e4),
                            vol=s10["ann_vol"], sr_10=s10["sharpe"], sr_tca=st["sharpe"], ret_tca=st["ann_ret"],
                            te_to_target=te_ann(r10["te"]), te_to_full=te_ann(rt["ret"] - base),
                            oos=f"{r10['ret'].index[0].date()}..{r10['ret'].index[-1].date()}"))
    return out

def zs(df: pd.DataFrame) -> Any:
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0).clip(-3, 3)

def spearman_ac(S: pd.DataFrame, lag: int = 5) -> Any:
    rk = S.rank(axis=1)
    a, b = rk, rk.shift(lag)
    a = a.sub(a.mean(axis=1), axis=0)
    b = b.sub(b.mean(axis=1), axis=0)
    return (a * b).sum(axis=1) / np.sqrt((a * a).sum(axis=1) * (b * b).sum(axis=1))

def part_b(src: str, gross: float = 0.58, cap: float = 0.095, borrow_yr: float = 0.0025, allow_retired: bool = False) -> Any:
    fr, _ = rw.load_closes(src, fields=("c", "v"), allow_retired=allow_retired)
    C = fr["c"]
    R = C.pct_change()
    tca, _ = rw.tca_costs(C, fr["v"], src)
    sig = {"MOM_12_1": C.shift(21) / C.shift(252) - 1, "RS63": C / C.shift(63) - 1,
           "TREND": C / C.rolling(200).mean() - 1, "REV5": -(C / C.shift(5) - 1)}
    Z = {k: zs(v) for k, v in sig.items()}
    phi = {k: (1 - spearman_ac(v).rolling(120, min_periods=60).mean()).clip(0, 1) for k, v in sig.items()}
    vol = R.rolling(60).std()
    dates = C.index
    T = len(dates)
    first_phi = max(dates.get_loc(phi[k].first_valid_index()) for k in phi)
    start = max(254, first_phi)   # common start for all variants: every signal and phi_k available (no look-ahead)
    def target(t: Any, mult: Any) -> Any:
        zc = sum(mult[k] * Z[k].iloc[t].fillna(0) for k in Z) / sum(mult.values())
        x = zc / vol.iloc[t].replace(0, np.nan)
        x = (x - x.mean()).fillna(0)
        w = x / x.abs().sum() * gross
        for _ in range(20):
            w = w.clip(-cap, cap)
            w = w - w.mean() * (w != 0)
        return w.clip(-cap, cap).values
    variants = [("full", 1.0, None)] + [(f"partial tau={t:.3f}", t, None) for t in (gp(2)[1], gp(8)[1], 0.1)] + \
               [(f"GP ell={e}", gp(e)[1], gp(e)[0]) for e in (0.5, 2, 8)]
    Rv = R.values
    res = {}
    for name, tau, ag in variants:
        w = np.zeros(C.shape[1])
        started = False
        rets, grs, turns, costs, shorts = [], [], [], [], []
        for t in range(start, T - 1):
            c = 0.0
            if (t - start) % 5 == 0:
                mult = {k: 1.0 if ag is None else 1 / (1 + float(phi[k].iloc[t]) * ag) for k in Z}
                tgt = target(t, mult)
                new = tgt if not started else w + tau * (tgt - w)
                d = np.abs(new - w)
                if started:
                    turns.append(d.sum())
                    c = float(d @ tca)
                w = new
                started = True
            r = np.nan_to_num(Rv[t + 1])
            g = float(w @ r)
            b = borrow_yr / 360 * (1.4) * float(-w[w < 0].sum())   # ~7/5 calendar/trading days
            rets.append(g - c - b)
            grs.append(g)
            costs.append(c + b)
            shorts.append(-w[w < 0].sum())
            w = w * (1 + r)   # drift (equity-normalised approx.: no rescale for L/S book)
        idx = dates[start + 1:]
        res[name] = dict(net=pd.Series(rets, idx), gross=pd.Series(grs, idx), turn=np.array(turns), cost=np.array(costs))
    yrs = len(cast(pd.Series, res["full"]["net"])) / 252
    full = cast(pd.Series, res["full"]["gross"])
    out = []
    for name, v in res.items():
        net = cast(pd.Series, v["net"])
        gross_s = cast(pd.Series, v["gross"])
        sn, sg = rw.stats(net), rw.stats(gross_s)
        turn = cast(np.ndarray, v["turn"])
        cost_a = cast(np.ndarray, v["cost"])
        out.append(dict(src=src, variant=name, turnover_ann=float(turn.sum() / yrs), cost_bp_ann=float(cost_a.sum() / yrs * 1e4),
                        gross_ret=sg["ann_ret"], net_ret=sn["ann_ret"], vol=sn["ann_vol"], sr_gross=sg["sharpe"], sr_net=sn["sharpe"],
                        max_dd=sn["max_dd"],                         te_to_full=te_ann(gross_s - full),
                        oos=f"{net.index[0].date()}..{net.index[-1].date()}"))
    phis = {k: float(phi[k].dropna().mean()) for k in phi}
    return out, phis

if __name__ == "__main__":
    # DESK_RULES #5: default = Dmitri's store via desk_data_client. `--retired` reproduces the pre-rule-5 run
    # (statarb audit copy + data.json) for audit only. New output never overwrites the retired-source file out/gp_wf.json.
    retired = "--retired" in sys.argv
    if retired:
        A = part_a("statarb", True) + part_a("datajson", True)
        B, phis = part_b("statarb", allow_retired=True)
        out = "gp_wf_retired_rerun.json"
    else:
        A = part_a("store")
        B, phis = part_b("store")
        out = "gp_wf_store.json"
    json.dump(dict(data_source="RETIRED (audit)" if retired else "Dmitri's store via desk_data_client", taus=TAUS, gp_map={e: gp(e) for e in (0.5, 2, 8)},
                   partA=A, partB=B, phi_mean=phis), open(f"{_QR.DESK_DIR}/portfolio/research/out/{out}", "x"), indent=1, default=float)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(A).round(4).to_string())
    print(pd.DataFrame(B).round(4).to_string())
    print(phis)
