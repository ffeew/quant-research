"""Stage 4: build earnings_events_8k202 v1 from SEC submissions (no prices, no returns).
Definition: see README.md. Inputs: work/segments_validated.parquet (+ work/manual_cik_fixes.csv), raw/sec/*.gz."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import os, pandas as pd, numpy as np, exchange_calendars as xc
from quant_research.data.earnings_events.ee_common import load_sub
D = f"{_QR.DATA_DIR}"
START = pd.Timestamp("2015-01-01", tz="America/New_York")
seg = pd.read_parquet("work/segments_validated.parquet")
if os.path.exists("work/manual_cik_fixes.csv"):
    # each fix replaces the original segment (symbol, orig_seg_start) by the listed pieces; a fix with no
    # matching original segment (previously unmapped) is appended
    fx = pd.read_csv("work/manual_cik_fixes.csv", parse_dates=["orig_seg_start", "seg_start", "seg_end"])
    keys = set(zip(fx.symbol, fx.orig_seg_start))
    seg = seg[[k not in keys for k in zip(seg.symbol, seg.seg_start)]]
    add = fx[["symbol", "seg_start", "seg_end", "cik", "note"]].rename(columns={"note": "fix_note"})
    add = add.assign(map_source="ethan_manual_fix", identity_ok=True, cik=add.cik.astype(int))
    seg = pd.concat([seg, add], ignore_index=True).sort_values(["symbol", "seg_start"]).reset_index(drop=True)
seg.to_parquet("work/segments_final.parquet")
seg_ok = seg[seg.identity_ok].copy()

# ---- ticker history for ticker_at_event (dated alpaca_name_change rows only) ----
ref = pd.read_parquet(f"{D}/reference/ticker_cik_map.parquet").dropna(subset=["cik"])
tk = ref[(ref.source == "alpaca_name_change") & (ref.valid_from.notna() | ref.valid_to.notna())
          & ~ref.ticker.str.endswith(".WI")].copy()   # when-issued tickers are not the trading ticker
tk["vf"] = pd.to_datetime(tk.valid_from); tk["vt"] = pd.to_datetime(tk.valid_to)

def ticker_at(cik, d, default):
    r = tk[(tk.cik == cik) & (tk.vf.isna() | (tk.vf <= d)) & (tk.vt.isna() | (tk.vt > d))]
    # a 'renamed_to' row (open start, valid_to = switch) is exactly the old ticker before the switch
    return (r.ticker.iloc[0], "alpaca_name_change") if len(r) == 1 else (default, "index_symbol_fallback")

# ---- all 8-K / 8-K/A with item 2.02 ----
rows = []
for cik in sorted(seg_ok.cik.unique()):
    j, f = load_sub(cik)
    if f is None: continue
    f = f[f.form.isin(["8-K", "8-K/A"]) & f["items"].fillna("").str.split(",").apply(lambda x: "2.02" in [i.strip() for i in x])]
    for _, x in f.iterrows():
        rows.append(dict(cik=int(cik), sec_name=j["name"], accession=x.accessionNumber, form=x.form, items=x["items"],
                         filing_date=x.filingDate, acceptance_raw=x.acceptanceDateTime, primary_doc=x.primaryDocument))
ev = pd.DataFrame(rows)
ev["acceptance_utc"] = pd.to_datetime(ev.acceptance_raw, utc=True)       # verified UTC vs EDGAR header (README)
ev["acceptance_et"] = ev.acceptance_utc.dt.tz_convert("America/New_York")
ev = ev[ev.acceptance_et >= START - pd.Timedelta(days=7)].sort_values(["cik", "acceptance_utc"]).reset_index(drop=True)

# ---- NYSE sessions ----
cal = xc.get_calendar("XNYS", start="2014-01-01")
sched = cal.schedule.loc["2014-06-01":].copy()
opens = sched.open.values.astype("datetime64[ns]")                       # UTC naive
sess = sched.index
def first_session_after(ts_utc, offset_min=0):
    a = ts_utc.tz_convert("UTC").tz_localize(None).to_datetime64()
    i = np.searchsorted(opens - np.timedelta64(offset_min, "m"), a, side="right")   # strictly after
    return sess[i].date() if i < len(sess) else None
ev["session_date"] = [first_session_after(t) for t in ev.acceptance_utc]
ev["session_date_0925"] = [first_session_after(t, 5) for t in ev.acceptance_utc]  # PREREG_sector_lm_5d s5 rule
d_et = ev.acceptance_et.dt.tz_localize(None).dt.normalize()
is_sess = d_et.isin(sess)
op = d_et.map(sched.open.dt.tz_convert("America/New_York").dt.tz_localize(None))
cl = d_et.map(sched.close.dt.tz_convert("America/New_York").dt.tz_localize(None))
t = ev.acceptance_et.dt.tz_localize(None)
ev["pre_open"] = is_sess & (t < op)
ev["intraday"] = is_sess & (t >= op) & (t < cl)
ev["post_close"] = is_sess & (t >= cl)
ev["non_session_day"] = ~is_sess
ev["timing"] = np.select([ev.pre_open, ev.intraday, ev.post_close], ["pre_open", "intraday", "post_close"], "non_session_day")

# ---- dedupe: clusters of 2.02 filings per CIK within 3 calendar days (ET) of the cluster's first filing ----
cid, cur_c, first = [], -1, None
prev_cik = None
for cik, ts in zip(ev.cik, ev.acceptance_et):
    if cik != prev_cik or (ts.normalize() - first.normalize()).days > 3:
        cur_c += 1; first = ts
    prev_cik = cik; cid.append(cur_c)
ev["cluster"] = cid
g = ev.groupby("cluster")
ev["cluster_n_filings"] = g.accession.transform("size")
ev["cluster_has_amendment"] = g.form.transform(lambda x: (x == "8-K/A").any())
ev["cluster_accessions"] = g.accession.transform(lambda x: ";".join(x))
ev.to_parquet("work/all_202_filings.parquet")
k = ev.sort_values("acceptance_utc").groupby("cluster").head(1).copy()
k["is_amendment"] = k.form.eq("8-K/A")
k = k[k.acceptance_et >= START]

# ---- attach PIT membership / tickers ----
def attach(r):
    d = pd.Timestamp(r.acceptance_et.date())
    s = seg_ok[(seg_ok.cik == r.cik) & (seg_ok.seg_start <= d) & (seg_ok.seg_end > d)]
    if len(s):
        syms = sorted(s.symbol, key=lambda x: (-len(x), x))
        t, ts = ticker_at(r.cik, d, syms[0])
        return pd.Series(dict(in_sp500=True, index_symbols=",".join(syms), ticker_at_event=t, ticker_source=ts,
                              map_source=s.map_source.iloc[0]))
    s = seg_ok[seg_ok.cik == r.cik]
    near = s.iloc[((s.seg_start - d).abs()).argsort()[:1]]
    sym = near.symbol.iloc[0]
    t, ts = ticker_at(r.cik, d, sym)
    return pd.Series(dict(in_sp500=False, index_symbols=",".join(sorted(s.symbol.unique())),
                          ticker_at_event=t, ticker_source=ts, map_source=near.map_source.iloc[0]))
k = pd.concat([k, k.apply(attach, axis=1)], axis=1)
k["acceptance_et"] = k.acceptance_et.dt.tz_localize(None)   # wall-clock ET, naive (documented)
k["filing_date"] = pd.to_datetime(k.filing_date).dt.date
k["filing_index_url"] = [f"https://www.sec.gov/Archives/edgar/data/{c}/{a.replace('-', '')}/{a}-index.htm"
                         for c, a in zip(k.cik, k.accession)]
k.to_parquet("work/events_core.parquet")
print("all 2.02 filings", len(ev), "events", len(k), "in_sp500", int(k.in_sp500.sum()), "amend-first", int(k.is_amendment.sum()))
