"""Industry momentum (Moskowitz & Grinblatt 1999). Dave, 2026-10-30.
Paper: 20 value-weighted industries; long top-3 / short bottom-3 by past 6-month return, hold 6 months (overlapping
portfolios), no skip month in the headline spec.
Desk versions (same engine / costs / reporting as the other two replications):
  A) Sector ETFs: 11 SPDR sector ETFs (XLC from 2018-06, XLRE from 2015-10; an ETF enters once it has 6m of history).
     imom_etf_ls    (PRIMARY): top-3 minus bottom-3 by past form_months return, held hold_months via overlapping
                      monthly cohorts (paper's J=6/K=6); equal weight, dollar-neutral
     imom_etf_ls_1m : same ranking, rebalanced monthly (K=1)
     imom_etf_long  : long-only top-3, rebalanced fully every month (1-month hold, no cohorts; excess of rf)
  B) Stock level (GICS sector portfolios of PIT S&P 500 members, EW within sector; trade the member stocks).
     Requires point-in-time industry codes for former members; gated by coverage (see run_all.py). Dmitri's
     universe.parquet has GICS only for current members (as of 2026-10-30) -> blocked unless forced as a diagnostic.
  C) Public pre/post-2016 check: FF 49 industries (VW), J=6/K=6, top-5/bottom-5 (~10% each side), monthly from
     1926 -> splits pre-2016 vs 2016+ (Dmitri's data starts 2016)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

BASE = {"form_months": 6, "topn": 3, "hold_months": 6}


class ImomParams(TypedDict):
    form_months: int
    topn: int
    hold_months: int


def _cum(R: pd.DataFrame, t: pd.Timestamp, months: int, cols: Sequence[str]) -> pd.Series:
    idx = R.index
    e = idx.searchsorted(t, side="right")
    s = idx.searchsorted(t - pd.DateOffset(months=months), side="right")
    w = R.iloc[s:e][cols]
    ok = w.notna().sum() >= 0.9 * len(w)
    return ((1 + w.fillna(0)).prod() - 1)[ok]


def _overlap(cohorts: list[pd.Series], K: int) -> pd.Series:
    return pd.concat(cohorts[-K:], axis=1).fillna(0).sum(axis=1) / K


def build_targets_etf(
    panel: dict[str, pd.DataFrame],
    ctx: dict[str, Any],
    etfs: Sequence[str],
    p: ImomParams | None = None,
) -> dict[str, dict[pd.Timestamp, pd.Series]]:
    """Codified rules: universe = SPDR sector ETFs with >= form_months of bars at t; rank by total return over
    (t - form_months, t] (no skip month, as in MG's headline J/K tables); long top `topn`, short bottom `topn`, EW.
    imom_etf_ls: hold_months overlapping monthly cohorts (MG J=6/K=6); imom_etf_ls_1m: rebalance fully monthly;
    imom_etf_long: long-only top `topn`, 1m hold (excess of rf). Monthly signal at last session; fill next open."""
    p = cast(ImomParams, {**BASE, **(p or {})})
    R = panel["ret"]
    etf_names = [e for e in etfs if e in R.columns]
    out: dict[str, dict[pd.Timestamp, pd.Series]] = {k: {} for k in ["imom_etf_ls", "imom_etf_ls_1m", "imom_etf_long"]}
    cohorts: list[pd.Series] = []
    N = p["topn"]
    for t in ctx["month_ends"]:
        avail = [e for e in etf_names if R[e].loc[:t].notna().sum() >= 21 * p["form_months"]]
        if len(avail) < 2 * N + 1:
            continue
        r = _cum(R, t, p["form_months"], avail).sort_values()
        lo, hi = r.index[:N], r.index[-N:]
        ls = pd.concat([pd.Series(1 / N, hi), pd.Series(-1 / N, lo)])
        out["imom_etf_ls_1m"][t] = ls
        cohorts.append(ls)
        if len(cohorts) >= p["hold_months"]:
            out["imom_etf_ls"][t] = _overlap(cohorts, p["hold_months"])
        out["imom_etf_long"][t] = pd.Series(1 / N, hi)
    return out


def build_targets_stock(
    panel: dict[str, pd.DataFrame], ctx: dict[str, Any], gics: pd.Series, p: ImomParams | None = None
) -> dict[str, dict[pd.Timestamp, pd.Series]]:
    """Stock-level: sector = EW of PIT member stocks with a GICS code; rank sectors as above; trade the member stocks
    (EW within sector, 1/topn per sector). Requires point-in-time codes; current-only codes = DIAGNOSTIC."""
    p = cast(ImomParams, {**BASE, **(p or {})})
    R = panel["ret"]
    N = p["topn"]
    out: dict[str, dict[pd.Timestamp, pd.Series]] = {k: {} for k in ["imom_stk_ls", "imom_stk_ls_1m", "imom_stk_long"]}
    cohorts: list[pd.Series] = []
    for t in ctx["month_ends"]:
        mem = [s for s in ctx["members_at"](t) if s in R.columns and s in gics.index]
        if len(mem) < 100:
            continue
        r6 = _cum(R, t, p["form_months"], mem)
        g = gics.reindex(r6.index)
        ind = r6.groupby(g).mean()[r6.groupby(g).size() >= 5].sort_values()
        if len(ind) < 2 * N + 1:
            continue

        def book(secs: pd.Index, sign: int) -> pd.Series:
            return pd.concat([pd.Series(sign / N / (g == s).sum(), g.index[g == s]) for s in secs])

        ls = pd.concat([book(ind.index[-N:], 1), book(ind.index[:N], -1)])
        out["imom_stk_ls_1m"][t] = ls
        cohorts.append(ls)
        if len(cohorts) >= p["hold_months"]:
            out["imom_stk_ls"][t] = _overlap(cohorts, p["hold_months"])
        out["imom_stk_long"][t] = book(ind.index[-N:], 1)
    return out


def public_check() -> tuple[pd.DataFrame, pd.Series]:
    """FF49 VW industries, J=6/K=6 overlapping, top5-bottom5; pre-2016 vs 2016+. Gross only (no cost model for
    industry portfolios of unknown constituents)."""
    import sys

    sys.path.insert(0, f"{_QR.DESK_DIR}/research/replication")
    from quant_research.backtest.stats import perf
    from quant_research.data.public_data import ind49_vw_monthly

    ind = ind49_vw_monthly()
    ind = ind.where(ind > -0.99)  # FF missing code -99.99 (already /100 by the loader)
    cum6 = (1 + ind).rolling(6).apply(np.prod, raw=True) - 1
    legs: list[tuple[pd.Index, pd.Index] | None] = []
    for i in range(len(ind) - 1):
        p = cum6.iloc[i].dropna()
        if len(p) < 20:
            legs.append(None)
            continue
        p = p.sort_values()
        legs.append((p.index[-5:], p.index[:5]))
    rets: dict[Any, float] = {}
    for i in range(6, len(ind)):
        rs = []
        for k in range(1, 7):
            L = legs[i - k] if i - k < len(legs) else None
            if L is None:
                continue
            nxt = ind.iloc[i]
            rs.append(nxt[L[0]].mean() - nxt[L[1]].mean())
        if len(rs) == 6:
            rets[ind.index[i]] = np.mean(rs)
    r = pd.Series(rets).sort_index()
    rows: list[dict[str, Any]] = []
    for name, a, b in [
        ("in_sample_1963-07..1995-07", "1963-07-01", "1995-07-31"),
        ("pre-2016 (1927..2015)", None, "2015-12-31"),
        ("post-pub 1999-08..2015", "1999-08-01", "2015-12-31"),
        ("2016+", "2016-01-01", None),
    ]:
        s = r.copy()
        if a:
            s = s[s.index >= a]
        if b:
            s = s[s.index <= b]
        rows.append({"series": "FF49 VW, J6/K6, top5-bot5 (gross)", "window": name, **perf(s)})
    return pd.DataFrame(rows), r
