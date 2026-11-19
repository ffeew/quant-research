"""(b) XBRL fallback (PREREG v0.4, COMMON C9): GAAP diluted quarterly EPS, as originally filed, with ET knowledge time.

Inputs (the data owner's store, read-only):
  fundamentals/xbrl_facts.parquet  (companyfacts long table; accn, filed, period_start/end, available_session)
  earnings/edgar_10q10k.parquet    (10-Q/10-K acceptance_datetime_et per accession)
Rules (v0.4):
  - tag us-gaap:EarningsPerShareDiluted (else EarningsPerShareBasicAndDiluted), unit USD/shares, forms 10-Q / 10-K
    (amendments ignored -> values as originally filed).
  - 3-month duration values only (80-100 days). NO Q4 = FY - 9M (or FY - Q1..Q3) derivation: invalid for diluted EPS
    (validator review §5). A Q4 with no reported 3-month value is missing here.
  - Earliest accession: for each (cik, period_start, period_end) the value from the FIRST-accepted filing is kept
    (later filings' comparatives and restatements are ignored).
  - knowledge time: join accn = edgar_10q10k.accession -> acceptance_datetime_et; knowledge_session per the 09:30 ET rule.
    Unmatched accn -> the data owner's `available_session` (flag knowledge_src = 'available_session_fallback'); share logged.
Output: out/xbrl_eps_quarterly.parquet ; log: out/xbrl_eps_quarterly.log.json
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from quant_research.data.sec_edgar import common
from quant_research.utils.pins import require_pins

TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]


def build(save: bool = True) -> tuple[pd.DataFrame, dict[str, Any]]:
    require_pins("data.sec_edgar.common", "RELEASE_TOP_HASH")  # only recorded in the log: refuse if PENDING
    x = pd.read_parquet(common.STORE / "fundamentals/xbrl_facts.parquet", filters=[("tag", "in", TAGS)])
    x = x[(x.unit == "USD/shares") & x.form.isin(["10-Q", "10-K"])].copy()
    x["period_start"] = pd.to_datetime(x.period_start)
    x["period_end"] = pd.to_datetime(x.period_end)
    x["days"] = (x.period_end - x.period_start).dt.days
    x = x[x.days.between(80, 100)].copy()
    acc = pd.read_parquet(
        common.STORE / "earnings/edgar_10q10k.parquet", columns=["accession", "acceptance_datetime_et"]
    )
    acc = acc.drop_duplicates("accession").rename(columns={"accession": "accn"})
    x = x.merge(acc, on="accn", how="left")
    x["knowledge_et"] = pd.to_datetime(x.acceptance_datetime_et)
    sess = common.sessions()
    ks = pd.Series(pd.NaT, index=x.index, dtype="datetime64[ns]")
    m = x.knowledge_et.notna()
    ks[m] = common.knowledge_session(x.loc[m, "knowledge_et"], sess).values
    ks[~m] = pd.to_datetime(x.loc[~m, "available_session"]).values
    x["knowledge_session"] = ks
    x["knowledge_src"] = np.where(m, "acceptance_10q10k", "available_session_fallback")
    x["tag_rank"] = x.tag.map({TAGS[0]: 0, TAGS[1]: 1})
    # earliest filing first; ties within one accession -> Diluted tag first
    x["_ord"] = x.knowledge_et.fillna(pd.to_datetime(x.knowledge_session) + pd.Timedelta(hours=9, minutes=29))
    x = x.sort_values(["cik", "period_start", "period_end", "_ord", "tag_rank"])
    q = x.drop_duplicates(["cik", "period_start", "period_end"], keep="first")
    # one value per (cik, period_end): earliest knowledge
    q = q.sort_values(["cik", "period_end", "_ord"]).drop_duplicates(["cik", "period_end"], keep="first")
    q = q.rename(columns={"value": "eps_diluted_xbrl", "accn": "accession_10q10k", "symbol": "ticker"})
    q["derivation"] = "reported_3m"
    # Effective knowledge time used by SUE as-of lookups: 10-Q/10-K acceptance, else data owner available_session at 09:29 ET
    # (i.e. usable from that session's open, never earlier). Flagged by knowledge_src.
    q["knowledge_et_eff"] = q.knowledge_et.fillna(
        pd.to_datetime(q.knowledge_session) + pd.Timedelta(hours=9, minutes=29)
    )
    cols = [
        "cik",
        "ticker",
        "period_start",
        "period_end",
        "fy",
        "fp",
        "form",
        "accession_10q10k",
        "tag",
        "eps_diluted_xbrl",
        "derivation",
        "knowledge_et",
        "knowledge_src",
        "knowledge_session",
        "knowledge_et_eff",
    ]
    q = q[[c for c in cols if c in q.columns]].sort_values(["cik", "period_end"]).reset_index(drop=True)
    log = {
        "rows": int(len(q)),
        "knowledge_src": q.knowledge_src.value_counts().to_dict(),
        "fallback_share_overall": float((q.knowledge_src != "acceptance_10q10k").mean()),
        "fallback_share_by_period_year": q.assign(y=q.period_end.dt.year)
        .groupby("y")
        .knowledge_src.apply(lambda s: float((s != "acceptance_10q10k").mean()))
        .round(3)
        .to_dict(),
        "ciks_by_period_year": q.groupby(q.period_end.dt.year).cik.nunique().to_dict(),
        "fy_minus_9m_rows": int((q.derivation != "reported_3m").sum()),
        "source_release": common.DATA_RELEASE_ID,
        "source_release_top_hash": common.RELEASE_TOP_HASH,
    }
    if save:
        q.to_parquet(common.OUT / "xbrl_eps_quarterly.parquet", index=False)
        json.dump(log, open(common.OUT / "xbrl_eps_quarterly.log.json", "w"), indent=1, default=str)
    return q, log


if __name__ == "__main__":
    q, log = build()
    print(json.dumps(log, indent=1, default=str))
