"""Uniform reporting for all desk replications (the derivatives researcher). Gross/net Sharpe, t, maxDD, turnover, break-even,
TCA owner section-6 flag, avg cost bps by liquidity bucket, sub-period splits."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .engine import monthly
from .stats import perf

# Desk data starts 2016-01, so "pre-2016" cannot be computed on desk data; it comes from public proxies
# (post_pub_checks.py). On desk data we split the post-2016 sample in two halves.
DESK_WINDOWS = {"full": (None, None), "2016-2020": (None, "2020-12-31"), "2021-2026": ("2021-01-01", None)}


def _win[FrameT: (pd.Series, pd.DataFrame)](s: FrameT, a: str | None, b: str | None) -> FrameT:
    if a:
        s = s[s.index >= a]
    if b:
        s = s[s.index <= b]
    return s


def flag(net_base: float, net_2x: float, gross: float, cost_drag: float) -> str:
    if not np.isfinite(net_base) or net_base <= 0:
        return "FAIL"
    if net_2x <= 0 or (gross > 0 and cost_drag > 0.5 * gross):
        return "WARN"
    return "PASS"


def summarize(
    strategy: str, variant: str, daily: pd.DataFrame, trades: pd.DataFrame, meta: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    g_m = monthly(daily, 0, 0)  # type: ignore[arg-type, call-arg]  # legacy (daily, cost, borrow) call; monthly takes a column name
    n_m = monthly(daily, 1, 1)  # type: ignore[arg-type, call-arg]  # legacy (daily, cost, borrow) call; monthly takes a column name
    s_m = monthly(daily, 2, 2)  # type: ignore[arg-type, call-arg]  # stress: 2x costs, borrow 50bps
    # drop first (partial) month
    g_m, n_m, s_m = g_m.iloc[1:], n_m.iloc[1:], s_m.iloc[1:]
    for wname, (a, b) in DESK_WINDOWS.items():
        g, n, s = _win(g_m, a, b), _win(n_m, a, b), _win(s_m, a, b)
        dd = _win(daily, a, b)
        if len(g) < 6:
            rows.append(
                {"strategy": strategy, "variant": variant, "window": wname, "n_months": len(g), "note": "insufficient"}
            )
            continue
        pg, pn, ps = perf(g), perf(n), perf(s)
        yrs = len(dd) / 252.0
        traded_ann = dd.traded.sum() / yrs
        gross_book = (dd.long_mv + dd.short_mv).replace(0, np.nan).mean()
        reb = dd[dd.traded > 0]
        oneway_mo = (reb.traded / (2 * gross_book)).mean() if len(reb) else np.nan
        cost_ann = dd.cost.sum() / yrs
        borrow_ann = dd.borrow.sum() / yrs
        tr = trades[(trades.date >= dd.index[0]) & (trades.date <= dd.index[-1])] if len(trades) else trades
        bk = (
            tr.assign(wb=tr.abs_dw * tr.bps)
            .groupby("bucket")
            .apply(lambda x: x.wb.sum() / x.abs_dw.sum(), include_groups=False)  # type: ignore[call-overload]  # pandas-stubs GroupBy.apply omits include_groups
            if len(tr)
            else pd.Series(dtype=float)
        )
        rows.append(
            {
                "strategy": strategy,
                "variant": variant,
                "window": wname,
                "start": pg["start"],
                "end": pg["end"],
                "n_months": pg["n"],
                "gross_ann": pg["mean_ann"],
                "net_ann": pn["mean_ann"],
                "net2x_ann": ps["mean_ann"],
                "vol_ann": pg["vol_ann"],
                "sharpe_gross": pg["sharpe_ann"],
                "sharpe_net": pn["sharpe_ann"],
                "sharpe_net2x": ps["sharpe_ann"],
                "t_gross": pg["t_stat"],
                "t_net": pn["t_stat"],
                "maxdd_gross": pg["max_dd"],
                "maxdd_net": pn["max_dd"],
                "turnover_oneway_per_rebal": oneway_mo,
                "traded_per_yr_x_nav": traded_ann,
                "cost_drag_ann": cost_ann,
                "borrow_drag_ann": borrow_ann,
                "avg_cost_bps": (tr.abs_dw * tr.bps).sum() / tr.abs_dw.sum() if len(tr) else np.nan,
                "cost_bps_by_bucket": ";".join(f"{k}:{v:.1f}" for k, v in bk.items()),
                "breakeven_cost_bps": pg["mean_ann"] / traded_ann * 1e4 if traded_ann > 0 else np.nan,
                "avg_long_mv": dd.long_mv.mean(),
                "avg_short_mv": dd.short_mv.mean(),
                "costs_flag": flag(pn["mean_ann"], ps["mean_ann"], pg["mean_ann"], cost_ann + borrow_ann),
                **meta,
            }
        )
    return rows


def monthly_frame(daily: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gross": monthly(daily, 0, 0),  # type: ignore[arg-type, call-arg]  # legacy (daily, cost, borrow) call; monthly takes a column name
            "net": monthly(daily, 1, 1),  # type: ignore[arg-type, call-arg]  # legacy (daily, cost, borrow) call; monthly takes a column name
            "net_stress": monthly(daily, 2, 2),  # type: ignore[arg-type, call-arg]  # legacy (daily, cost, borrow) call; monthly takes a column name
            "traded": daily.traded.groupby(pd.Grouper(freq="ME")).sum(),
        }
    ).iloc[1:]
