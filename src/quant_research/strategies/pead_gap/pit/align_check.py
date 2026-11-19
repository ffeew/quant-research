"""Earnings timing alignment diagnostic (no returns used): median |overnight gap| on the announce day (d)
vs the next session (d+1), and share of |gap|>4%, by timing class. Writes align_check.csv."""

from __future__ import annotations

import sys
from typing import cast

import pandas as pd

sys.path.insert(0, ".")
from quant_research.strategies.pead_gap.pit.core import GAP, NT, cal, col, ev

ci = {d: i for i, d in enumerate(cal)}
G = GAP.abs()
rows = []
for r in ev.itertuples():
    if r.symbol not in col or r.ad not in ci:
        continue
    i = ci[cast(pd.Timestamp, r.ad)]
    if i + 1 >= NT:
        continue
    g0 = G.iat[i, col[r.symbol]]
    g1 = G.iat[i + 1, col[r.symbol]]
    rows.append(dict(timing=r.timing, source=r.source, g_d=g0, g_d1=g1))
df = pd.DataFrame(rows).dropna()
out = (
    df.groupby(["source", "timing"])
    .agg(
        n=("g_d", "size"),
        med_absgap_d_bps=("g_d", lambda x: round(x.median() * 1e4, 1)),
        med_absgap_d1_bps=("g_d1", lambda x: round(x.median() * 1e4, 1)),
        share_gt4pct_d=("g_d", lambda x: round((x > 0.04).mean(), 3)),
        share_gt4pct_d1=("g_d1", lambda x: round((x > 0.04).mean(), 3)),
        share_d_bigger=("g_d", lambda x: None),
    )
    .reset_index()
)
out["share_d_bigger"] = df.assign(b=df.g_d > df.g_d1).groupby(["source", "timing"]).b.mean().round(3).values
out.to_csv("align_check.csv", index=False)
print(out.to_string())
