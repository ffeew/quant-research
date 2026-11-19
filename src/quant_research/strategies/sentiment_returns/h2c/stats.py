"""Newey-West t, per-quarter long/short metrics and the G0/G1/G2 gates."""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import stats as _st  # type: ignore[import-untyped]  # scipy ships no py.typed; scipy-stubs not in qr-venv

from .config import H2CParams, Partition


def nw_t(x: Sequence[float] | npt.NDArray[np.float64], lag: int) -> float:
    """t-stat of the mean with a Bartlett-kernel Newey-West long-run variance."""
    a = np.asarray(x, float)
    T = len(a)
    u = a - a.mean()
    lrv = (u @ u) / T
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        lrv += 2 * w * (u[k:] @ u[:-k]) / T
    return float(a.mean() / np.sqrt(lrv / T))


def quarter_metrics(
    events: Sequence[dict[str, Any]], quarter: str, ret_start: dict[int, str], p: H2CParams
) -> dict[str, Any] | None:
    """Metrics for one quarter's included events: Spearman IC of surprise vs target, top-minus-bottom quintile
    L/S (raw and beta-adjusted), hedge notional, costs and borrow. ``ret_start`` maps id(event) -> the ISO session
    where the return window starts (for borrow days). Returns None if no events."""
    g = list(events)
    if not g:
        return None
    n = len(g)
    k = n // p.quantile_div
    o = sorted(g, key=lambda e: (e["surprise"], e["symbol"], e["label"]))
    sh, lo = o[:k], o[-k:]
    ic = float(_st.spearmanr([e["surprise"] for e in g], [e["target"] for e in g]).statistic)
    hedge = float(abs(np.mean([e["beta"] for e in lo]) - np.mean([e["beta"] for e in sh])))
    days = float(np.mean([(dt.date.fromisoformat(e["ret_end"]) - dt.date.fromisoformat(ret_start[id(e)])).days for e in sh]))
    ls_b = float(np.mean([e["target"] for e in lo]) - np.mean([e["target"] for e in sh]))
    ls_r = float(np.mean([e["ret_raw"] for e in lo]) - np.mean([e["ret_raw"] for e in sh]))
    turnover = 4 + 2 * hedge
    c10, c20, bor = p.cost_side * turnover, p.cost_side_sens * turnover, p.borrow * days / 365
    return dict(quarter=quarter, n=n, k=k, n_symbols=len({e["symbol"] for e in g}), ic=ic, ls_raw=ls_r, ls_badj=ls_b,
                hedge_notional=hedge, cost10=c10, cost20=c20, borrow=bor, net10_badj=ls_b - c10,
                net20_badj=ls_b - c20, net10_badj_borrow=ls_b - c10 - bor, turnover_units=turnover)


def summarize(periods: Sequence[dict[str, Any]], qn: dict[str, int], part: Partition, p: H2CParams) -> dict[str, Any]:
    """Common summary: G0 coverage plus mean IC, NW t, one-sided p and mean L/S figures (when >= 2 periods)."""
    T = len(periods)
    q20 = sum(1 for q in part.scored_quarters if qn.get(q, 0) >= p.q_min_events)
    res: dict[str, Any] = dict(periods=T, df=T - 1, g0_quarters_ge20=q20, g0_required=part.g0_min_quarters,
                               G0_pass=bool(q20 >= part.g0_min_quarters))
    if T >= 2:
        ics = np.array([x["ic"] for x in periods], float)
        t = nw_t(ics, p.nw_lag)

        def mn(k: str) -> float:
            return float(np.mean([x[k] for x in periods]))

        res.update(mean_ic=float(ics.mean()), ic_sd=float(ics.std(ddof=1)), nw_lag=p.nw_lag, nw_t=t,
                   p_one_sided=float(1 - _st.t.cdf(t, df=T - 1)), ls_badj_mean=mn("ls_badj"), ls_raw_mean=mn("ls_raw"),
                   net10_badj_mean=mn("net10_badj"), net20_badj_mean=mn("net20_badj"),
                   net10_badj_borrow_mean=mn("net10_badj_borrow"),
                   breakeven_cost_per_side=mn("ls_badj") / mn("turnover_units"))
    return res


def evaluate_g1(periods: Sequence[dict[str, Any]], qn: dict[str, int], part: Partition, p: H2CParams) -> dict[str, Any]:
    """DEV gate: G0 and G1 (mean IC > 0, NW t >= g1_min_t, mean net L/S at cost_side > 0)."""
    res = summarize(periods, qn, part, p)
    if res["periods"] >= 2:
        res["G1"] = dict(i=bool(res["mean_ic"] > 0), ii=bool(res["nw_t"] >= p.g1_min_t),
                         iii=bool(res["net10_badj_mean"] > 0))
        res["G1_pass"] = bool(res["G0_pass"] and all(res["G1"].values()))
    else:
        res["G1_pass"] = False
    res["verdict"] = "PASS (G0+G1)" if res["G1_pass"] else "FAIL"
    return res


def evaluate_g2(
    periods: Sequence[dict[str, Any]], qn: dict[str, int], part: Partition, p: H2CParams, dev_mean_ic: float
) -> dict[str, Any]:
    """Holdout gate: G0 and G2 (i) mean IC > 0; (ii) one-sided p <= g2_alpha; (iii) mean IC >= g2_ic_frac x the
    frozen DEV mean IC; (iv) mean net L/S > 0 at cost_side, both before and after borrow. Any fail -> FAIL."""
    res = summarize(periods, qn, part, p)
    res.update(dev_mean_ic_frozen=float(dev_mean_ic), g2_iii_threshold=p.g2_ic_frac * float(dev_mean_ic),
               g2_alpha=p.g2_alpha)
    if res["periods"] >= 2:
        res["G2"] = dict(i=bool(res["mean_ic"] > 0), ii=bool(res["p_one_sided"] <= p.g2_alpha),
                         iii=bool(res["mean_ic"] >= p.g2_ic_frac * float(dev_mean_ic)),
                         iv=bool(res["net10_badj_mean"] > 0 and res["net10_badj_borrow_mean"] > 0),
                         iv_net10=bool(res["net10_badj_mean"] > 0),
                         iv_net10_borrow=bool(res["net10_badj_borrow_mean"] > 0))
        res["G2_pass"] = bool(res["G0_pass"] and all(res["G2"][k] for k in ("i", "ii", "iii", "iv")))
    else:
        res["G2"] = dict(i=False, ii=False, iii=False, iv=False, iv_net10=False, iv_net10_borrow=False)
        res["G2_pass"] = False
    res["verdict"] = "PASS (G0+G2)" if res["G2_pass"] else "FAIL"
    return res
