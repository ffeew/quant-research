"""Stage 3: identity check of each (symbol, CIK) segment against SEC names and filing activity."""

from __future__ import annotations

from typing import cast

import pandas as pd

from quant_research.data.earnings_events.ee_common import load_sub, name_score
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

D = f"{_QR.DATA_DIR}"
seg = pd.read_parquet("work/member_cik_segments.parquet")
cur = pd.read_parquet(f"{D}/universe/sp500_current.parquet")[["symbol", "security"]]
ch = pd.read_parquet(f"{D}/universe/sp500_changes.parquet")
nm = pd.concat(
    [
        cur.rename(columns={"security": "ref_name"}),
        ch[["removed_ticker", "removed_security"]].set_axis(["symbol", "ref_name"], axis=1),
        ch[["added_ticker", "added_security"]].set_axis(["symbol", "ref_name"], axis=1),
    ]
).dropna()
refnames = nm.groupby("symbol").ref_name.apply(lambda x: list(dict.fromkeys(x)))
rows = []
for _, s in seg.iterrows():
    j, f = load_sub(s.cik)
    if j is None:
        rows.append(dict(s, sec_name=None, name_score=None, n_periodic_in_seg=None, fetched=False))
        continue
    filings = cast(pd.DataFrame, f)
    secn = [j["name"]] + [x["name"] for x in j.get("formerNames", [])]
    refs = refnames.get(s.symbol, [])
    sc = max([name_score(a, b) for a in refs for b in secn], default=None)
    fd = pd.to_datetime(filings.filingDate)
    inseg = filings[(fd >= s.seg_start) & (fd < s.seg_end + pd.Timedelta(days=120))]
    rows.append(
        dict(
            s,
            sec_name=j["name"],
            ref_name="|".join(refs),
            name_score=sc,
            n_periodic_in_seg=int(inseg.form.isin(["10-K", "10-Q", "20-F", "40-F", "10-K405"]).sum()),
            fetched=True,
        )
    )
v = pd.DataFrame(rows)
# periodic reports filed during the segment are decisive (abbreviated names like "Lowe's"/"LOWES COMPANIES" score 0);
# name match alone is accepted only for segments too new/short to contain a 10-Q/10-K (start >= 2026-06-01 or < 10 days)
short = (v.seg_start >= "2026-06-01") | ((v.seg_end - v.seg_start).dt.days < 10)
v["identity_ok"] = v.fetched & ((v.n_periodic_in_seg > 0) | ((v.name_score.fillna(0) >= 0.5) & short))
v.to_parquet("work/segments_validated.parquet")
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 500)
print(v.identity_ok.value_counts(dropna=False))
print(
    v[~v.identity_ok][
        [
            "symbol",
            "seg_start",
            "seg_end",
            "cik",
            "map_source",
            "sec_name",
            "ref_name",
            "name_score",
            "n_periodic_in_seg",
        ]
    ].to_string()
)
