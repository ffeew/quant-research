"""Full EX-99.1 EPS extraction across edgar_8k_202 events. Resume-safe checkpoint.
No prices/returns. Uses exhibits.parquet (or ethan-cache fallback) for URLs.
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.data.sec_edgar import common
from quant_research.data.sec_edgar import eps8k_extract as X

CKPT = common.OUT / "eps8k_full.checkpoint.parquet"
OUT = common.OUT / "eps8k_full.parquet"
OUTV = common.OUT / "eps8k_full_with_validation.parquet"
LOG = common.OUT / "eps8k_full.log.json"


def load_events() -> pd.DataFrame:
    ev = pd.read_parquet(common.earnings_path("edgar_8k_202.parquet"))
    # amendments excluded from primary EPS path (COMMON C9)
    ev = ev[ev.form == "8-K"].drop_duplicates("accession").copy()
    # preannouncement flag from combined earnings_events (match on symbol+announce_date+cik)
    ee = pd.read_parquet(common.earnings_path("earnings_events.parquet"))
    ee = ee[ee.source == "edgar_8k_2.02"][
        ["symbol", "cik", "announce_date_et", "is_preannouncement", "event_type", "reaction_session"]
    ].copy()
    ee["announce_date_et"] = pd.to_datetime(ee.announce_date_et).dt.date.astype(str)
    ev["announce_date_et"] = pd.to_datetime(ev.announce_date_et).dt.date.astype(str)
    ev["cik"] = ev.cik.astype(int)
    ee["cik"] = ee.cik.astype(int)
    ev = ev.merge(ee, on=["symbol", "cik", "announce_date_et"], how="left", suffixes=("", "_ee"))
    # exhibits
    # Prefer our exhibits map; overlay the sentiment researcher's additive ex99_url when accession matches (never filter events by it)
    if common.RESEARCH_ADDITIVE.exists():
        eth = pd.read_parquet(common.RESEARCH_ADDITIVE, columns=["accession", "ex99_url"])
        eth = eth.rename(columns={"ex99_url": "ex99_url_ethan"})
    else:
        eth = None
    for p in [common.OUT / "exhibits.parquet", common.OUT / "exhibits_from_ethan_cache.parquet"]:
        if p.exists():
            ex = pd.read_parquet(p)
            break
    else:
        raise SystemExit("no exhibits parquet")
    ev = ev.merge(ex[["accession", "ex99_url", "ex99_type", "ex99_rule"]], on="accession", how="left")
    if eth is not None:
        ev = ev.merge(eth, on="accession", how="left")
        # fill missing ex99 from sentiment researcher additive only
        m = ev.ex99_url.isna() & ev.ex99_url_ethan.notna()
        ev.loc[m, "ex99_url"] = ev.loc[m, "ex99_url_ethan"]
        ev.loc[m, "ex99_rule"] = "ethan_v1_additive"
    # CRITICAL: never drop rows for missing ex99 — use primary_doc url from edgar_8k_202
    miss = ev.ex99_url.isna()
    if "url" in ev.columns:
        ev.loc[miss, "ex99_url"] = ev.loc[miss, "url"]
        ev.loc[miss, "ex99_rule"] = "8k_body_no_ex99"
        ev.loc[miss, "ex99_type"] = "8-K body"
    ev = ev.rename(columns={"symbol": "ticker", "acceptance_datetime_et": "acceptance_et"})
    # session_date from knowledge rule
    ev["session_date"] = common.knowledge_session(ev.acceptance_et, common.sessions()).values
    return ev


def main() -> None:
    ev = load_events()
    done = set()
    rows: list[dict[str, Any]] = []
    if CKPT.exists():
        prev = pd.read_parquet(CKPT)
        done = set(prev.accession)
        rows = cast(list[dict[str, Any]], prev.to_dict("records"))
        print(f"resume: {len(done)} done", flush=True)
    # prefer rows that already have a URL
    todo = ev[~ev.accession.isin(done)].copy()
    todo["_has"] = todo.ex99_url.notna().astype(int)
    todo = todo.sort_values(["_has", "acceptance_et"], ascending=[False, True])
    print(f"todo={len(todo)} with_url={todo._has.sum()} total_events={len(ev)}", flush=True)
    t0 = time.time()
    for i, r in enumerate(todo.to_dict("records"), 1):
        if not r.get("ex99_url"):
            # skip until exhibits fetch fills URL; leave for a later pass
            continue
        try:
            rec = X.extract_one(cast(dict[str, Any], r))
            rec["is_preannouncement"] = r.get("is_preannouncement")
            rec["event_type"] = r.get("event_type")
            rec["reaction_session"] = r.get("reaction_session")
            rec["ex99_rule"] = r.get("ex99_rule")
            rows.append(rec)
        except Exception as e:
            rows.append(
                dict(
                    accession=r["accession"],
                    cik=r["cik"],
                    ticker=r.get("ticker"),
                    acceptance_et=r.get("acceptance_et"),
                    session_date=r.get("session_date"),
                    eps_diluted_reported=np.nan,
                    eps_basis="none",
                    eps_adjusted=np.nan,
                    parse_confidence="none",
                    parse_notes=f"top_error: {type(e).__name__}: {e}"[:300],
                    is_preannouncement=r.get("is_preannouncement"),
                    event_type=r.get("event_type"),
                    reaction_session=r.get("reaction_session"),
                    ex99_rule=r.get("ex99_rule"),
                )
            )
        if i % 100 == 0 or i == len(todo):
            df = pd.DataFrame(rows)
            df.to_parquet(CKPT, index=False)
            n_gaap = int((df.eps_basis == "GAAP").sum()) if "eps_basis" in df else 0
            print(f"extract {i}/{len(todo)} saved={len(df)} gaap={n_gaap} elapsed={time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    # assign fiscal period + validate vs XBRL
    xq = pd.read_parquet(common.OUT / "xbrl_eps_quarterly.parquet")
    df = X.assign_fiscal_period(df, xq)
    v = X.validate(df, xq)
    v.to_parquet(OUTV, index=False)
    cols = [
        "accession",
        "cik",
        "ticker",
        "fiscal_period",
        "eps_diluted_reported",
        "eps_basis",
        "eps_adjusted",
        "source_exhibit",
        "parse_confidence",
        "parse_notes",
        "acceptance_et",
        "session_date",
        "is_preannouncement",
        "event_type",
        "reaction_session",
        "ex99_rule",
        "exhibit_type",
    ]
    keep = [c for c in cols if c in v.columns]
    v[keep].to_parquet(OUT, index=False)
    both = v[v.xbrl_match.notna()]
    log = {
        "n_rows": int(len(v)),
        "eps_basis": v.eps_basis.value_counts(dropna=False).to_dict(),
        "parse_confidence": v.parse_confidence.value_counts(dropna=False).to_dict(),
        "with_xbrl_both": int(len(both)),
        "match_rate_vs_xbrl": float(both.xbrl_match.astype(bool).mean()) if len(both) else None,
        "gaap_match_rate": float(v[(v.eps_basis == "GAAP") & v.xbrl_match.notna()].xbrl_match.astype(bool).mean())
        if ((v.eps_basis == "GAAP") & v.xbrl_match.notna()).any()
        else None,
        "preannouncement_rows": int(v.is_preannouncement.fillna(False).sum()) if "is_preannouncement" in v else None,
    }
    json.dump(log, open(LOG, "w"), indent=1, default=str)
    print(json.dumps(log, indent=1, default=str), flush=True)


if __name__ == "__main__":
    main()
