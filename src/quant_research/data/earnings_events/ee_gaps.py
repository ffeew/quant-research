"""Stage 3b: flag accepted segments whose CIK does not file periodic reports across the whole segment
(successor holdco / predecessor issuer problems, e.g. APA Corp 2021 vs Apache Corp)."""
import pandas as pd
from quant_research.data.earnings_events.ee_common import load_sub
seg = pd.read_parquet("work/segments_final.parquet"); seg = seg[seg.identity_ok]
LAST = pd.Timestamp("2026-06-30")
out = []
for _, s in seg.iterrows():
    j, f = load_sub(s.cik)
    fd = pd.to_datetime(f.filingDate); per = fd[f.form.isin(["10-K", "10-Q", "20-F", "40-F"])].sort_values()
    a, b = max(s.seg_start, pd.Timestamp("2015-01-01")), min(s.seg_end, LAST)
    if b - a < pd.Timedelta(days=150): continue
    p = per[(per >= a - pd.Timedelta(days=120)) & (per < b + pd.Timedelta(days=120))]
    first, last = (p.iloc[0], p.iloc[-1]) if len(p) else (None, None)
    gaps = p.diff().dt.days.max() if len(p) > 1 else None
    bad = first is None or first > a + pd.Timedelta(days=150) or last < b - pd.Timedelta(days=150) or (gaps or 0) > 200
    if bad: out.append(dict(symbol=s.symbol, seg_start=s.seg_start.date(), seg_end=s.seg_end.date(), cik=s.cik,
                            sec_name=j["name"], first_periodic=first, last_periodic=last, max_gap_days=gaps,
                            former=[x["name"] for x in j.get("formerNames", [])][:2]))
o = pd.DataFrame(out); o.to_csv("work/segment_gaps.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200); pd.set_option("display.max_colwidth", 45)
print(len(o)); print(o.to_string())
