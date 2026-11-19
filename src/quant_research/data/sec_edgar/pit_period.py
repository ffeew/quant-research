"""Point-in-time fiscal-period labelling for 8-K EX-99 EPS rows (SPEC §4a, 2026-11-06).

The earlier label (eps8k_extract.assign_fiscal_period) picked the latest XBRL quarter end within 100 days before
acceptance from the FULL XBRL table, i.e. it depended on 10-Q/10-K filings that were not yet public at the 8-K
acceptance tau (ex-post selection: an 8-K got a period only if a later 3-month XBRL value existed). Replaced by:

1. text label: 'quarter ended <date>' parsed from the 8-K itself (public at tau), if tau-100d <= date < tau.date;
2. else PIT roll-forward: the latest XBRL period_end whose knowledge_et_eff <= tau (public at tau), advanced by
   k = 1..4 quarters (3 calendar months if that period_end is a month-end, else 91 days), taking the latest
   candidate with tau-100d <= candidate < tau.date;
3. canonical snap: if an XBRL period_end for the same CIK lies within +-7 days of the PIT label, the date is
   replaced by that XBRL date (date canonicalisation only, so 52/53-week calendars join; it can neither add nor
   remove an event, because inclusion was decided in steps 1-2 from tau-public information). Flagged.
The ex-post label is kept only as a QA comparison column (fiscal_period_expost); it never enters SUE.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd


def _parse(t: object) -> Any:
    if not isinstance(t, str):
        return pd.NaT
    try:
        return pd.Timestamp(t.replace(".", "")).normalize()
    except Exception:
        return pd.NaT


def _roll(pe0: pd.Timestamp, k: int) -> pd.Timestamp:
    pe0 = pd.Timestamp(pe0)
    if pe0.is_month_end:
        return (pe0 + pd.DateOffset(months=3 * k)) + pd.offsets.MonthEnd(0)
    return pe0 + pd.Timedelta(days=91 * k)


def assign_fiscal_period_pit(df: pd.DataFrame, xq: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    acc = pd.to_datetime(df.acceptance_et)
    g = {
        int(cast(int, c)): d.sort_values("period_end")[["period_end", "knowledge_et_eff"]].to_numpy()
        for c, d in xq.groupby("cik")
    }
    labels: list[Any] = []
    srcs: list[str] = []
    snapped: list[bool] = []
    for c, raw_a, t in zip(df.cik, acc, df.get("period_text", pd.Series([None] * len(df), index=df.index))):
        a = cast(Any, raw_a)  # acceptance may be NaT
        if pd.isna(a):
            labels.append(pd.NaT)
            srcs.append("no_acceptance")
            snapped.append(False)
            continue
        day = a.normalize()
        lo = day - pd.Timedelta(days=100)
        val: Any = pd.NaT
        src = "none"
        d = _parse(t)
        if pd.notna(d) and lo <= d < day:
            val, src = d, "text"
        arr = g.get(int(c))
        if pd.isna(val) and arr is not None and len(arr):
            known = arr[(pd.to_datetime(arr[:, 1]) <= a) & (pd.to_datetime(arr[:, 0]) < day)]
            if len(known):
                pe0 = pd.Timestamp(known[:, 0].max())
                cands = [pe0] + [_roll(pe0, k) for k in range(1, 5)]
                cands = [x for x in cands if lo <= x < day]
                if cands:
                    val, src = max(cands), ("pit_known_xbrl" if max(cands) == pe0 else "pit_rollforward")
        sn = False
        if pd.notna(val) and arr is not None and len(arr):
            pes = pd.to_datetime(arr[:, 0])
            dd = np.abs((pes - val).days)
            j = int(np.argmin(dd))
            if dd[j] <= 7 and pes[j] != val:
                val, sn = pd.Timestamp(pes[j]), True
        labels.append(val)
        srcs.append(src)
        snapped.append(sn)
    df["fiscal_period"] = pd.to_datetime(pd.Series(labels, index=df.index))
    df["fiscal_period_src"] = srcs
    df["fiscal_period_snapped"] = snapped
    return df
