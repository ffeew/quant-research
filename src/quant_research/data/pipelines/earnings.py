"""Historical earnings-announcement dates for the universe from two public sources.

1) SEC EDGAR 8-K Item 2.02 ("Results of Operations and Financial Condition") filings via
   data.sec.gov/submissions/CIK##########.json  -> data/earnings/edgar_8k_202.parquet
   Point-in-time: acceptance_datetime_utc is the exact moment the filing became public on EDGAR.
   v1.1 timing from acceptance time in ET vs NYSE calendar: before open BMO, open..close INTRADAY, at/after close AMC
   (early closes respected); explicit reaction_session + first_tradable_open_session (see classify()).
   10-Q/10-K filings kept in edgar_10q10k.parquet and used as flagged fallback events (source=edgar_10q10k_fallback).
   CIKs: current constituents from Wikipedia table; former members via SEC company_tickers.json
   (only resolvable if the ticker is still registered) -> unresolved former names listed in manifest.
2) Nasdaq earnings calendar (api.nasdaq.com/api/calendar/earnings?date=D) -> data/earnings/nasdaq_calendar.parquet
   Gives report date, time (pre-market / after-hours / not supplied), actual EPS, consensus, surprise.
   NOT point-in-time for consensus/EPS (shown as of fetch). Raw daily JSON cached in earnings/raw/nasdaq/.
3) Combined events table data/earnings/earnings_events.parquet (universe symbols only): one row per
   (symbol, announcement session) with best timing (EDGAR timestamp preferred, Nasdaq time otherwise),
   and `first_tradable_session` = session whose open first reflects the news.
Usage: python earnings.py [--source edgar|nasdaq|both] [--start 2016-01-01] [--days-ahead 30]
Set SEC_USER_AGENT env var to "<Org> <contact email>" per SEC fair-access policy.
"""
import argparse, json, os, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd, requests
from quant_research.data.pipelines.common import DATA, START, write_parquet, update_manifest, log, calendar

OUT = DATA / "earnings"
SEC_UA = os.environ.get("SEC_USER_AGENT", "CIO-Desk-Research research-data@example.com")


def sec_get(url, tries=6):
    status = None
    for k in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip"}, timeout=60)
            status = r.status_code
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return None
        except requests.RequestException as e:
            status = type(e).__name__
        time.sleep(2 ** k)
    raise RuntimeError(f"SEC {status} {url}")


def edgar(u, cur):
    cik = {s: int(c) for s, c in zip(cur["symbol"], cur["cik"]) if pd.notna(c)}
    tick = sec_get("https://www.sec.gov/files/company_tickers.json")
    sec_map = {v["ticker"].upper().replace("-", "."): int(v["cik_str"]) for v in tick.values()}
    unresolved = []
    ref = DATA / "reference/ticker_cik_map.parquet"
    if ref.exists():  # ticker history map (incl. former members via EFTS name search / Alpaca name changes)
        m = pd.read_parquet(ref).dropna(subset=["cik"])
        pr = {"wikipedia_sp500_cik": 0, "sec_company_tickers": 1, "edgar_submissions": 2, "alpaca_name_change": 3, "manual_verified_edgar": 3, "efts_name_search": 4}
        m = m.assign(p=m.source.map(pr)).sort_values("p").drop_duplicates("ticker")
        for t, c in zip(m.ticker, m.cik):
            if t in set(u["symbol"]) and t not in cik: cik[t] = int(c)
    etf = set(u.loc[u["role"] == "etf", "symbol"])
    for s in u["symbol"]:
        if s in etf: continue
        if s not in cik:
            if s in sec_map: cik[s] = sec_map[s]
            else: unresolved.append(s)
    # v1.2: date-bounded CIK periods (predecessors, reused tickers, issuer reorganisations) from security_master.py
    cpf = DATA / "reference/cik_periods.parquet"
    if cpf.exists():
        cp = pd.read_parquet(cpf).dropna(subset=["cik"])
        cp = cp[cp.index_ticker.isin(set(u["symbol"]) - etf)]
        pairs = [(r.index_ticker, int(r.cik), r.valid_from, r.valid_to) for r in cp.itertuples()]
        covered = set(cp.index_ticker)
        pairs += [(s_, c_, None, None) for s_, c_ in cik.items() if s_ not in covered and s_ not in etf]
    else:
        pairs = [(s_, c_, None, None) for s_, c_ in cik.items() if s_ not in etf]
    rows = []
    sub_cache = {}
    for n, (s, c, vf, vt) in enumerate(sorted(pairs, key=lambda x: (x[0], x[1]))):
        if c not in sub_cache:
            j = sec_get(f"https://data.sec.gov/submissions/CIK{c:010d}.json"); time.sleep(0.12)
            blocks = []
            if j:
                blocks = [j["filings"]["recent"]]
                for f in j["filings"].get("files", []):
                    if f["filingTo"] >= START:
                        blocks.append(sec_get("https://data.sec.gov/submissions/" + f["name"])); time.sleep(0.12)
            sub_cache = {c: (j, blocks)}   # keep only the latest CIK in memory
        j, blocks = sub_cache[c]
        if not j: unresolved.append(s); continue
        lo = str(vf) if vf else START; hi = str(vt) if vt else "2999-12-31"
        for b in blocks:
            for i, form in enumerate(b["form"]):
                is202 = form in ("8-K", "8-K/A") and "2.02" in (b["items"][i] or "")
                fd = b["filingDate"][i]
                if (is202 or form in ("10-Q", "10-K")) and fd >= START and lo <= fd <= hi:
                    rows.append({"symbol": s, "cik": c, "sec_name": j.get("name"), "form": form, "items": b["items"][i],
                                 "filing_date": fd, "acceptance_datetime_utc": b["acceptanceDateTime"][i],
                                 "accession": b["accessionNumber"][i], "primary_doc": b["primaryDocument"][i],
                                 "cik_valid_from": lo, "cik_valid_to": None if hi == "2999-12-31" else hi})
        if n % 100 == 0: log.info("edgar %d/%d", n, len(pairs))
    df = pd.DataFrame(rows)
    df["acceptance_datetime_utc"] = pd.to_datetime(df["acceptance_datetime_utc"], utc=True)
    et = df["acceptance_datetime_utc"].dt.tz_convert("America/New_York")
    df["acceptance_datetime_et"] = et.dt.tz_localize(None)
    df["announce_date_et"] = et.dt.date
    df = add_timing(df, et)
    df["knowledge_time_utc"] = df["acceptance_datetime_utc"]
    df["url"] = [f"https://www.sec.gov/Archives/edgar/data/{c}/{a.replace('-', '')}/{p}" for c, a, p in zip(df.cik, df.accession, df.primary_doc)]
    df = df.drop_duplicates(["symbol", "accession"]).sort_values(["symbol", "acceptance_datetime_utc"]).reset_index(drop=True)
    periodic = df[df.form.isin(["10-Q", "10-K"])].reset_index(drop=True)
    df = df[~df.form.isin(["10-Q", "10-K"])].reset_index(drop=True)
    write_parquet(periodic, OUT / "edgar_10q10k.parquet")
    return df, sorted(set(unresolved))


_CAL = {}
def _cal():
    if not _CAL:
        c = calendar(START); c["date"] = pd.to_datetime(c["date"]).dt.date
        _CAL["sess"] = pd.Index(sorted(c["date"]))
        _CAL["close"] = {d: int(x[:2]) * 60 + int(x[3:5]) for d, x in zip(c["date"], c["close"])}
        _CAL["open"] = {d: int(x[:2]) * 60 + int(x[3:5]) for d, x in zip(c["date"], c["open"])}
    return _CAL


def classify(ts_et):
    """v1.1 timing from an ET timestamp, using the NYSE calendar (early closes respected):
       BMO      before the open (09:30)            -> reaction_session = that session (or next session if not a trading day)
       INTRADAY open <= t < close (16:00 / 13:00)  -> reaction_session = that same session (news hits mid-session);
                                                      first_tradable_open_session = next session (first OPEN after news)
       AMC      t >= close                          -> reaction_session = next session
       non-trading day (weekend/holiday)            -> timing NON_SESSION_DAY, reaction = next session"""
    c = _cal(); d = ts_et.date(); m = ts_et.hour * 60 + ts_et.minute; sess = c["sess"]
    nxt = lambda x: sess[sess.searchsorted(x, side="right")] if sess.searchsorted(x, side="right") < len(sess) else None
    if d not in c["close"]:
        k = sess.searchsorted(d, side="left"); r = sess[k] if k < len(sess) else None
        return "NON_SESSION_DAY", r, r
    if m < c["open"][d]: return "BMO", d, d
    if m < c["close"][d]: return "INTRADAY", d, nxt(d)
    return "AMC", nxt(d), nxt(d)


def add_timing(df, et):
    out = [classify(t) for t in et]
    df["timing"] = [o[0] for o in out]
    df["reaction_session"] = [o[1] for o in out]
    df["first_tradable_open_session"] = [o[2] for o in out]
    df["timing_method"] = "edgar_acceptance_time_vs_nyse_calendar"
    return df


def nasdaq_day(d, refetch_after):
    raw = OUT / "raw" / "nasdaq"; raw.mkdir(parents=True, exist_ok=True)
    f = raw / f"{d}.json"
    if f.exists() and d < refetch_after:
        return d, json.loads(f.read_text())
    for k in range(6):
        try:
            r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d}, timeout=30,
                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            if r.status_code == 200:
                j = r.json(); j["_fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                f.write_text(json.dumps(j)); return d, j
        except Exception:
            pass
        time.sleep(2 ** k)
    return d, None


def nasdaq(start, days_ahead):
    end = dt.date.today() + dt.timedelta(days=days_ahead)
    days = [d.date().isoformat() for d in pd.bdate_range(start, end)]
    refetch_after = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    rows, failed = [], []
    with ThreadPoolExecutor(4) as ex:
        for n, (d, j) in enumerate(ex.map(lambda x: nasdaq_day(x, refetch_after), days)):
            if j is None: failed.append(d); continue
            for r in ((j.get("data") or {}).get("rows") or []):
                rows.append({"report_date": d, **r, "fetched_at_utc": j.get("_fetched_at_utc")})
            if n % 250 == 0: log.info("nasdaq %d/%d", n, len(days))
    df = pd.DataFrame(rows)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    df["symbol"] = df["symbol"].str.upper().str.replace("/", ".").str.replace("-", ".")
    df["timing"] = df["time"].map({"time-pre-market": "BMO", "time-after-hours": "AMC"}).fillna("UNKNOWN")
    df["status"] = ["scheduled" if d > dt.date.today() else "reported_or_past" for d in df["report_date"]]
    return df, failed


def first_tradable(date, timing, sessions):
    # BMO / unknown-before-open -> same session (if session) else next; AMC/DURING -> next session
    idx = sessions.searchsorted(date, side="left" if timing in ("BMO",) else "right")
    return sessions[idx] if idx < len(sessions) else None


def combine(u):
    sess = pd.Index(sorted(calendar(START)["date"]))
    uni = set(u["symbol"])
    ev = []
    e = OUT / "edgar_8k_202.parquet"; n = OUT / "nasdaq_calendar.parquet"
    if e.exists():
        d = pd.read_parquet(e)
        for r in d.itertuples():
            ev.append({"symbol": r.symbol, "cik": r.cik, "announce_date_et": r.announce_date_et, "timing": r.timing, "source": "edgar_8k_2.02",
                       "knowledge_time_utc": r.knowledge_time_utc, "ref": r.url, "reaction_session": r.reaction_session,
                       "first_tradable_open_session": r.first_tradable_open_session, "timing_quality": "exact_acceptance_time"})
    if n.exists():
        d = pd.read_parquet(n); d = d[d.symbol.isin(uni)]
        for r in d.itertuples():
            # Nasdaq: BMO known before open, AMC after 16:00, UNKNOWN -> conservatively assume 16:00 ET
            hh = {"BMO": "07:00", "AMC": "16:05"}.get(r.timing, "16:05")
            kt = pd.Timestamp(f"{r.report_date} {hh}", tz="America/New_York").tz_convert("UTC")
            ft = first_tradable(r.report_date, r.timing, sess)
            ev.append({"symbol": r.symbol, "cik": None, "announce_date_et": r.report_date, "timing": r.timing, "source": f"nasdaq_{r.status}",
                       "knowledge_time_utc": kt, "ref": "api.nasdaq.com/api/calendar/earnings", "reaction_session": ft,
                       "first_tradable_open_session": ft, "timing_quality": "nasdaq_label" if r.timing != "UNKNOWN" else "unknown_assumed_amc"})
    q = OUT / "edgar_10q10k.parquet"
    if q.exists():  # fallback: periodic report filing date, only where no 8-K 2.02 exists in the 50 days before / 5 after
        p = pd.read_parquet(q)
        e8 = pd.read_parquet(e)[["symbol", "announce_date_et"]] if e.exists() else pd.DataFrame(columns=["symbol", "announce_date_et"])
        have = e8.groupby("symbol").announce_date_et.apply(lambda x: np.array(sorted(pd.to_datetime(x).values)))
        for r in p.itertuples():
            a = have.get(r.symbol)
            t = np.datetime64(pd.Timestamp(r.announce_date_et))
            if a is not None and len(a) and ((a >= t - np.timedelta64(50, "D")) & (a <= t + np.timedelta64(5, "D"))).any(): continue
            ev.append({"symbol": r.symbol, "cik": r.cik, "announce_date_et": r.announce_date_et, "timing": r.timing, "source": "edgar_10q10k_fallback",
                       "knowledge_time_utc": r.knowledge_time_utc, "ref": r.url, "reaction_session": r.reaction_session,
                       "first_tradable_open_session": r.first_tradable_open_session,
                       "timing_quality": f"periodic_report_filing_time({r.form}); earnings may have been released earlier"})
    df = pd.DataFrame(ev)
    df["first_tradable_session"] = df["first_tradable_open_session"]   # backward-compatible name (= first OPEN after the news)
    # prefer EDGAR 8-K, then Nasdaq, then 10-Q/10-K fallback, when events fall within +/-3 days
    df["prio"] = df.source.map(lambda x: 0 if x == "edgar_8k_2.02" else (2 if x == "edgar_10q10k_fallback" else 1))
    df = df.sort_values(["symbol", "announce_date_et", "prio"])
    keep = []
    last = {}
    for r in df.itertuples():
        k = r.symbol; p = last.get(k)
        if p is not None and abs((r.announce_date_et - p).days) <= 3: continue
        keep.append(r.Index); last[k] = r.announce_date_et
    out = df.loc[keep].drop(columns="prio")
    src = df.groupby(["symbol", "announce_date_et"]).source.agg(lambda x: ",".join(sorted(set(x))))
    out = out.reset_index(drop=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="both", choices=["edgar", "nasdaq", "both", "none"])
    ap.add_argument("--start", default=START)
    ap.add_argument("--days-ahead", type=int, default=30)
    ap.add_argument("--retime-only", action="store_true", help="re-derive timing/reaction_session on the stored EDGAR file, no fetch")
    a = ap.parse_args()
    if a.retime_only:
        f = OUT / "edgar_8k_202.parquet"; e = pd.read_parquet(f)
        e = add_timing(e, pd.to_datetime(e["acceptance_datetime_utc"], utc=True).dt.tz_convert("America/New_York"))
        write_parquet(e, f); a.source = "none"
    u = pd.read_parquet(DATA / "universe" / "universe.parquet")
    cur = pd.read_parquet(DATA / "universe" / "sp500_current.parquet")
    info = {}
    if a.source in ("edgar", "both"):
        e, unres = edgar(u, cur); write_parquet(e, OUT / "edgar_8k_202.parquet")
        info["edgar"] = {"rows": len(e), "symbols": int(e.symbol.nunique()), "first": e.filing_date.min(), "last": e.filing_date.max(),
                         "timing_counts": e.timing.value_counts().to_dict(), "unresolved_symbols": unres}
        log.info("edgar: %s", {k: v for k, v in info["edgar"].items() if k != "unresolved_symbols"})
    if a.source in ("nasdaq", "both"):
        nd, failed = nasdaq(a.start, a.days_ahead); write_parquet(nd, OUT / "nasdaq_calendar.parquet")
        info["nasdaq"] = {"rows": len(nd), "symbols_all": int(nd.symbol.nunique()), "universe_symbols": int(nd.symbol.isin(set(u.symbol)).sum() and nd[nd.symbol.isin(set(u.symbol))].symbol.nunique()),
                          "first": nd.report_date.min(), "last": nd.report_date.max(), "failed_dates": failed}
        log.info("nasdaq: %s", {k: v for k, v in info["nasdaq"].items() if k != "failed_dates"} | {"failed": len(failed)})
    ev = combine(u); write_parquet(ev, OUT / "earnings_events.parquet")
    info["events"] = {"rows": len(ev), "symbols": int(ev.symbol.nunique()), "by_source": ev.source.value_counts().to_dict()}
    old = {}
    update_manifest("earnings", info)
    log.info("events: %s", info["events"])


if __name__ == "__main__":
    main()
