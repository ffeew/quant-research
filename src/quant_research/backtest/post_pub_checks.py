"""Post-publication sanity checks on PUBLIC long-short factor series (not our desk data). The derivatives researcher, 2026-10-30.
Splits each factor into the original paper's in-sample window and the post-publication window.
Factors are close proxies, NOT exact paper constructions (see notes column).
Output: post_pub_checks.csv
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.backtest.stats import perf
from quant_research.data import public_data as P

rows: list[dict[str, Any]] = []


def add(
    name: str,
    s: pd.Series,
    insample: tuple[str, str | None],
    postpub: tuple[str, str | None],
    note: str,
) -> None:
    for label, (a, b) in [("in_sample", insample), ("post_publication", postpub)]:
        d = perf(s.loc[a:b])
        d.update(factor=name, window=label, note=note)
        rows.append(d)
    d = perf(s.loc["2016-01-01":])
    d.update(factor=name, window="since_2016", note=note)
    rows.append(d)


umd = P.umd_monthly()["Mom"]
add(
    "UMD (Ken French 12-2 momentum, VW 2x3)",
    umd,
    ("1965-01", "1989-12"),
    ("1993-04", None),
    "Proxy for Jegadeesh-Titman 1993 (in-sample 1965-1989, published Mar 1993).",
)
st = P.strev_monthly()["ST_Rev"]
add(
    "ST_Rev (Ken French 1-month reversal, VW 2x3)",
    st,
    ("1934-01", "1987-12"),
    ("1990-08", None),
    "Proxy for Jegadeesh 1990 (in-sample 1934-1987, published Jul 1990). VW large-cap-heavy, unlike the paper's EW deciles.",
)
rmw = P.ff5_monthly()["RMW"]
add(
    "RMW (FF operating profitability, VW 2x3)",
    rmw,
    ("1963-07", "2010-12"),
    ("2013-01", None),
    "Proxy for Novy-Marx 2013 gross profitability (paper sample 1963-2010). RMW is operating, not gross, profitability.",
)
bab = P.bab_usa_monthly()
add(
    "BAB USA (AQR, Frazzini-Pedersen construction)",
    bab,
    ("1926-01", "2012-03"),
    ("2012-04", None),
    "AQR reconstructs full history each update, so 'in-sample' is not the exact published series. Post window = after the paper's sample end; SSRN version dates to 2010.",
)

# Industry momentum proxy: 49 FF industries (VW), rank on past 6-month return (t-6..t-1), long top 5 / short bottom 5, equal-weight, hold 1 month.
ind = P.ind49_vw_monthly()
lr = cast(pd.DataFrame, np.log1p(ind))
sig = lr.rolling(6, min_periods=6).sum()
rets = []
for i in range(6, len(ind) - 1):
    s = sig.iloc[i].dropna()
    if len(s) < 30:
        rets.append(np.nan)
        continue
    nxt = ind.iloc[i + 1]
    top, bot = s.nlargest(5).index, s.nsmallest(5).index
    rets.append(nxt[top].mean() - nxt[bot].mean())
im = pd.Series(rets, index=ind.index[7 : len(ind)])
add(
    "Industry momentum proxy (49 FF industries, 6m formation, top5-bot5, 1m hold)",
    im,
    ("1963-07", "1995-07"),
    ("1999-08", None),
    "Our proxy for Moskowitz-Grinblatt 1999 (20 industries, 6m/6m, sample to Jul 1995, published Aug 1999). Not identical.",
)

out = pd.DataFrame(rows)[
    [
        "factor",
        "window",
        "start",
        "end",
        "n",
        "mean_ann",
        "vol_ann",
        "sharpe_ann",
        "t_stat",
        "max_dd",
        "hit_rate",
        "note",
    ]
]
out.to_csv("post_pub_checks.csv", index=False, float_format="%.4f")
pd.set_option("display.width", 250)
print(out.drop(columns="note").to_string(index=False, float_format=lambda v: f"{v:.3f}"))
