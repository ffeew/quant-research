"""Weekly long/short book: 80/60 band (or plain quintile), equal weights within legs, drift, turnover, costs."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from .config import H3Params

Weights = dict[str, float]


def band_step(pos: int, u: float, p: H3Params) -> int:
    """Next position in {+1, 0, -1} from current ``pos`` and percentile ``u``: enter at ``long_in`` / ``short_in``,
    hold while inside ``long_hold`` / ``short_hold``, and flip directly at the opposite entry bar."""
    if pos == 1:
        return -1 if u <= p.short_in else (0 if u < p.long_hold else 1)
    if pos == -1:
        return 1 if u >= p.long_in else (0 if u > p.short_hold else -1)
    return 1 if u >= p.long_in else (-1 if u <= p.short_in else 0)


def target_weights(state: Mapping[str, int], p: H3Params) -> tuple[Weights, bool]:
    """Equal weight +1/n_long and -1/n_short. If either leg has fewer than ``min_leg`` names the whole book is flat."""
    L = [s for s, x in state.items() if x == 1]
    S = [s for s, x in state.items() if x == -1]
    if len(L) < p.min_leg or len(S) < p.min_leg:
        return {}, True
    w = {s: 1.0 / len(L) for s in L}
    w.update({s: -1.0 / len(S) for s in S})
    return w, False


def traded_weight(w_new: Mapping[str, float], w_drift: Mapping[str, float]) -> float:
    """Sum of absolute weight changes over both legs."""
    return float(sum(abs(w_new.get(s, 0.0) - w_drift.get(s, 0.0)) for s in set(w_new) | set(w_drift)))


def drift(w: Mapping[str, float], r: Mapping[str, float], p: H3Params) -> Weights:
    """Weights after one week of returns. With ``drift_renormalise_legs`` each leg is rescaled back to +1 / -1;
    otherwise weights grow by ``1 + r`` without rescaling. The choice is a required configurable parameter."""
    renorm = p.require("drift_renormalise_legs")
    out: Weights = {}
    for sign in (1, -1):
        leg = {s: abs(x) for s, x in w.items() if np.sign(x) == sign}
        if not leg:
            continue
        tot = sum(x * (1 + r[s]) for s, x in leg.items()) if renorm else 1.0
        for s, x in leg.items():
            out[s] = sign * x * (1 + r[s]) / tot
    return out


def leg_return(w: Mapping[str, float], r: Mapping[str, float]) -> float:
    lo = sum(x * r[s] for s, x in w.items() if x > 0)
    sh = sum(-x * r[s] for s, x in w.items() if x < 0)
    return float(lo - sh)


def run_book(weeks: Sequence[Mapping[str, Any]], p: H3Params, mode: str = "band") -> tuple[list[dict[str, Any]], float]:
    """Run the book from flat. Each week is ``dict(dec, qual={sym: (S, u)}, scored, r={sym: raw}, y={sym: beta-adj})``.
    Names missing from ``qual`` are force-exited. Returns ``(rows, terminal_liquidation_weight)``.
    Whether band memory is cleared while the book is flat is the configurable ``flat_clears_band_memory``."""
    if mode not in ("band", "quintile"):
        raise ValueError(f"mode {mode!r}")
    clear = p.require("flat_clears_band_memory") if mode == "band" else True
    state: dict[str, int] = {}
    w_d: Weights = {}
    w: Weights = {}
    out = []
    for wk in weeks:
        q = wk["qual"]
        forced = [s for s in state if s not in q]
        for s in forced:
            state.pop(s)
        if wk["scored"]:
            if mode == "band":
                state = {s: x for s, (_, u) in q.items() if (x := band_step(state.get(s, 0), u, p))}
            else:
                o = sorted(q, key=lambda s: (q[s][0], s))
                k = len(o) // p.quantile_div
                state = {s: -1 for s in o[:k]}
                state.update({s: 1 for s in o[len(o) - k:]})
        w, flat = target_weights(state, p)
        if flat and clear:
            state = {}
        tw = traded_weight(w, w_d)
        g = leg_return(w, wk["r"]) if w else 0.0
        b = leg_return(w, wk["y"]) if w else 0.0
        out.append(dict(dec=wk["dec"], scored=wk["scored"], flat=flat, forced_exits=len(forced),
                        n_long=sum(1 for x in w.values() if x > 0), n_short=sum(1 for x in w.values() if x < 0),
                        traded=tw, gross=g, betaadj=b, net=g - p.cost_side * tw, net_sens=g - p.cost_side_sens * tw,
                        longs=sorted(s for s, x in w.items() if x > 0), shorts=sorted(s for s, x in w.items() if x < 0)))
        w_d = drift(w, wk["r"], p) if w else {}
    return out, float(sum(abs(x) for x in w_d.values()))


def trade_list(names: Iterable[str], p: H3Params) -> list[str]:
    """Names for any trade-list output, with research-only symbols removed."""
    ro = set(p.research_only)
    return [s for s in names if s not in ro]
