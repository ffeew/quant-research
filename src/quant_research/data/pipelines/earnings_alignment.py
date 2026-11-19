"""QA: does `reaction_session` land on the day the market reacts? Re-implements the review's gap statistic
(share of |open/prev_close-1| > 4% on announce day d vs next session d+1) and adds close-to-close |ret|>4%
on reaction_session vs the session after it. Input: earnings/earnings_events.parquet + total_return file.
Output: qa/earnings_alignment_<date>.md (+ .parquet). Usage: python earnings_alignment.py [--events path] [--tag x]"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

import numpy as np
import pandas as pd

from quant_research.data.pipelines.common import DATA

ap = argparse.ArgumentParser()
ap.add_argument("--events", default=str(DATA / "earnings/earnings_events.parquet"))
ap.add_argument("--tag", default="")
a = ap.parse_args()
tr = pd.read_parquet(
    DATA / "bars/daily/total_return/daily_total_return.parquet",
    columns=["symbol", "session_date", "open_adj", "close_adj", "ret_total_best"],
)
tr = tr.sort_values(["symbol", "session_date"])
tr["gap"] = tr.open_adj / tr.groupby("symbol").close_adj.shift() - 1
tr["nxt_gap"] = tr.groupby("symbol").gap.shift(-1)
tr["nxt_ret"] = tr.groupby("symbol").ret_total_best.shift(-1)
k = tr.set_index(["symbol", "session_date"])
ev = pd.read_parquet(a.events)
ev = ev[ev.source != "nasdaq_scheduled"].copy()
sess = pd.Index(sorted(tr.session_date.unique()))


def on_or_next(d: object) -> Any:
    i = sess.searchsorted(d, side="left")
    return sess[i] if i < len(sess) else None


ev["d"] = [on_or_next(d) for d in ev.announce_date_et]
rows = []
for col, lab in (("d", "announce day d (or next session)"), ("reaction_session", "reaction_session")):
    if col not in ev:
        continue
    j = ev.join(k, on=["symbol", col], how="inner")
    j["src"] = np.where(j.source.str.startswith("edgar"), j.source, "nasdaq")
    for (src, tm), g in j.groupby(["src", "timing"]):
        rows.append(
            {
                "anchor": lab,
                "source": src,
                "timing": tm,
                "n": len(g),
                "gap_gt4_day0": (g.gap.abs() > 0.04).mean(),
                "gap_gt4_day1": (g.nxt_gap.abs() > 0.04).mean(),
                "ret_gt4_day0": (g.ret_total_best.abs() > 0.04).mean(),
                "ret_gt4_day1": (g.nxt_ret.abs() > 0.04).mean(),
            }
        )
r = pd.DataFrame(rows)
tag = a.tag or dt.date.today().isoformat()
r.to_parquet(DATA / f"qa/earnings_alignment_{tag}.parquet", index=False)
md = [
    f"# Earnings timing alignment ({tag})",
    "",
    "day0 = anchor session, day1 = next session. gap = open_adj/prev close_adj - 1; ret = ret_total_best close-to-close.",
    "Correct alignment: BMO/AMC -> gap concentrated on reaction_session (day0); INTRADAY -> close-to-close move on day0, gap on day1 small.",
    "",
    r.to_markdown(index=False, floatfmt=".3f"),
]
(DATA / f"qa/earnings_alignment_{tag}.md").write_text("\n".join(md))
print(r.to_string())
