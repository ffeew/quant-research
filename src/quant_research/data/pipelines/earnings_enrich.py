"""Post-step for earnings/earnings_events.parquet (run after earnings.py): adds security_id and event_type.

security_id: from reference/security_segments.parquet via (symbol, cik, date) -> segment; falls back to the symbol's main segment.
event_type (method 'filing_sequence_v1', no exhibit text read):
  quarterly_results           8-K 2.02 that is the LAST 2.02 within the 0-75 days before the issuer's next 10-Q/10-K filing
  preannouncement_or_interim  any other 8-K 2.02 in that window that precedes the quarterly release by > 3 days
                              (preliminary results, guidance updates, restatement notes, investor-day numbers)
  other_202_no_periodic       8-K 2.02 with no 10-Q/10-K in the following 75 days (e.g. acquired before filing, foreign/odd filers)
  periodic_filing_fallback    10-Q/10-K used as the event because no 8-K 2.02 exists (source edgar_10q10k_fallback)
  nasdaq_calendar             rows from the Nasdaq calendar (no filing)
is_preannouncement = event_type == 'preannouncement_or_interim'.
Usage: python earnings_enrich.py
"""
import numpy as np, pandas as pd
from quant_research.data.pipelines.common import DATA, write_parquet, update_manifest, log


def main():
    f = DATA / "earnings/earnings_events.parquet"; ev = pd.read_parquet(f)
    q = pd.read_parquet(DATA / "earnings/edgar_10q10k.parquet")
    q = q[q.form.isin(["10-Q", "10-K"])][["symbol", "filing_date"]].copy(); q["fd"] = pd.to_datetime(q.filing_date).astype("datetime64[ns]")
    ev["d"] = pd.to_datetime(ev.announce_date_et).astype("datetime64[ns]")
    e8 = ev.source.astype(str).str.startswith("edgar_8k")
    x = ev[e8][["symbol", "d"]].reset_index().sort_values("d")
    nxt = pd.merge_asof(x, q.sort_values("fd")[["symbol", "fd"]], left_on="d", right_on="fd", by="symbol", direction="forward")
    nxt["gap"] = (nxt.fd - nxt.d).dt.days
    nxt["in_win"] = nxt.gap.between(0, 75)
    last = nxt[nxt.in_win].groupby(["symbol", "fd"]).d.transform("max")
    nxt.loc[nxt.in_win, "main_d"] = last
    et = np.where(~nxt.in_win, "other_202_no_periodic",
                  np.where(nxt.d >= nxt.main_d - pd.Timedelta(days=3), "quarterly_results", "preannouncement_or_interim"))
    ev["event_type"] = None
    ev.loc[nxt["index"], "event_type"] = et
    ev.loc[ev.source.astype(str).str.contains("10q10k"), "event_type"] = "periodic_filing_fallback"
    ev.loc[ev.source.astype(str).str.startswith("nasdaq"), "event_type"] = "nasdaq_calendar"
    ev["is_preannouncement"] = ev.event_type == "preannouncement_or_interim"
    ev["event_type_method"] = "filing_sequence_v1"
    ev["days_to_next_periodic_filing"] = np.nan
    ev.loc[nxt["index"], "days_to_next_periodic_filing"] = nxt.gap.values
    # security_id
    seg = pd.read_parquet(DATA / "reference/security_segments.parquet")
    ev["security_id"] = None
    for s, g in ev.groupby("symbol"):
        sg = seg[(seg.ticker_at_time == s) | (seg.bars_file == s)]
        idx = DATA  # placeholder
        if sg.empty: continue
        for i, d, c in zip(g.index, g.d.dt.date, g.cik):
            cand = sg[(sg.seg_from <= d) & (sg.seg_to >= d)]
            if pd.notna(c) and (cand.cik == c).any(): cand = cand[cand.cik == c]
            if cand.empty: cand = sg[sg.bars_source == "main"] if (sg.bars_source == "main").any() else sg
            ev.at[i, "security_id"] = cand.security_id.iloc[0]
    ev = ev.drop(columns="d")
    write_parquet(ev, f)
    info = {"rows": len(ev), "event_type": ev.event_type.value_counts().to_dict(), "security_id_coverage": float(ev.security_id.notna().mean())}
    update_manifest("earnings_enrich", info); log.info("%s", info)


if __name__ == "__main__":
    main()
