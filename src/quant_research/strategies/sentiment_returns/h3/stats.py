"""One-sided Newey-West test, sector-demeaned IC, per-variant summary and the DEV gate."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats as _st  # type: ignore[import-untyped]  # scipy ships no py.typed; scipy-stubs not in qr-venv

from ..h2c.stats import nw_t
from .config import H3Params


def one_sided(x: Sequence[float] | npt.NDArray[np.float64], lag: int) -> dict[str, Any]:
    """NW t of the mean and one-sided Student-t p with ``df = T - 1``; None values when T < 3 or x is constant."""
    a = np.asarray(x, float)
    T = len(a)
    if T < 3 or np.allclose(a, a.mean()):
        return dict(nw_t=None, p_one_sided=None, df=T - 1)
    t = nw_t(a, lag)
    return dict(nw_t=float(t), p_one_sided=float(1 - _st.t.cdf(t, df=T - 1)), df=T - 1)


def sector_ic(names: Sequence[str], S: Mapping[str, float], y: Mapping[str, float], sector: Mapping[str, str | None],
              p: H3Params) -> float | None:
    """Sector-neutral IC. The method is the configurable ``sector_ic_method``; ``demeaned_spearman`` demeans score and
    target within sector and takes the Spearman correlation. None with fewer than ``min_names`` sectored names."""
    method = p.require("sector_ic_method")
    if method != "demeaned_spearman":
        raise ValueError(method)
    df = pd.DataFrame(dict(S=[S[s] for s in names], y=[y[s] for s in names], sec=[sector.get(s) for s in names]))
    df = df[df.sec.notna() & (df.sec != "")]
    if len(df) < p.min_names:
        return None
    df["S"] -= df.groupby("sec").S.transform("mean")
    df["y"] -= df.groupby("sec").y.transform("mean")
    return float(_st.spearmanr(df.S, df.y).statistic)


def summarise(weeks: Sequence[Mapping[str, Any]], book: Sequence[Mapping[str, Any]], term: float,
              p: H3Params) -> dict[str, Any]:
    """Summary of one variant: IC stats over scored weeks, net L/S stats, turnover, breakeven and holding period.
    ``weeks`` rows carry ``scored``, ``ic`` and optional ``ic_sec``."""
    ics = [w["ic"] for w in weeks if w["scored"]]
    secs: list[float] = [s for w in weeks if w["scored"] and (s := w.get("ic_sec")) is not None]
    B = pd.DataFrame(list(book))
    net = B["net"].to_numpy(float)
    ic_st = one_sided(ics, p.nw_lag) if ics else {}
    net_st = one_sided(net, p.nw_lag)
    gm, tm = float(B["gross"].mean()), float(B["traded"].mean())
    liq = net.copy()
    liq[-1] -= p.cost_side * term
    entries = held = 0
    prev: set[str] = set()
    for bk in book:
        cur = set(bk["longs"]) | {"-" + s for s in bk["shorts"]}
        entries += len(cur - prev)
        held += len(cur)
        prev = cur
    return dict(weeks_in_series=len(B), scored_weeks=len(ics), mean_ic=(float(np.mean(ics)) if ics else None),
                ic_nw_t=ic_st.get("nw_t"), ic_p_one_sided=ic_st.get("p_one_sided"), ic_df=ic_st.get("df"),
                ls_gross_mean=gm, ls_net_mean=float(B["net"].mean()), ls_net_sens_mean=float(B["net_sens"].mean()),
                ls_net_nw_t=net_st["nw_t"], ls_net_p_one_sided=net_st["p_one_sided"],
                ls_betaadj_gross_mean=float(B["betaadj"].mean()),
                ls_betaadj_net_mean=float((B["betaadj"] - p.cost_side * B["traded"]).mean()),
                ls_net_with_liquidation_mean=float(liq.mean()), terminal_liquidation_weight=term,
                mean_traded_weight=tm, mean_one_way_turnover=tm / 2,
                breakeven_cost_per_side_bps=(gm / tm * 1e4 if tm > 0 else None),
                avg_holding_weeks=(held / entries if entries else None), flat_weeks=int(B["flat"].sum()),
                forced_exits=int(B["forced_exits"].sum()), mean_n_long=float(B["n_long"].mean()),
                mean_n_short=float(B["n_short"].mean()),
                sector_ic_mean=(float(np.mean(secs)) if secs else None), sector_ic_weeks=len(secs))


def dev_gate(summary: Mapping[str, Any]) -> str:
    """PASS iff mean IC > 0 and mean net L/S at ``cost_side`` > 0; otherwise FAIL."""
    mic = summary.get("mean_ic")
    return "PASS" if (mic is not None and mic > 0 and summary["ls_net_mean"] > 0) else "FAIL"


def combined_gate(by_reading: Mapping[str, Mapping[str, Any]]) -> str:
    """PASS only if every reading (e.g. UTC and ET) passes ``dev_gate``."""
    return "PASS" if by_reading and all(dev_gate(s) == "PASS" for s in by_reading.values()) else "FAIL"
