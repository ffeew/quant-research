"""Daily OHLCV bars from Alpaca /v2/stocks/bars (feed=sip by default) for the universe.
Outputs: data/bars/daily/{raw,adjusted}/<SYMBOL>.parquet  (one file per symbol; load the dir with pandas)
  raw      = adjustment=raw   (as traded)
  adjusted = adjustment=all   (split + dividend back-adjusted as of fetch time)
Incremental: each symbol resumes from its last stored session. For `adjusted`, any symbol with a
split/dividend/spin-off ex_date after its last stored session is fully re-pulled (history changes).
Former S&P members are queried with asof=<last membership day> so Alpaca maps the ticker to the
correct (historical) entity and avoids ticker-reuse contamination.
Usage: python daily_bars.py [--adjustment raw|adjusted|both] [--full] [--symbols A,B] [--feed sip|iex]
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import argparse, json, datetime as dt
from collections import defaultdict
import pandas as pd
from quant_research.data.pipelines.common import DATA, DATA_URL, START, get, write_parquet, update_manifest, log, last_completed_session, calendar

ADJ = {"raw": "raw", "adjusted": "all"}
OUT = DATA / "bars" / "daily"
COLS = {"t": "timestamp_utc", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "n": "trade_count", "vw": "vwap"}


def end_param(session):
    # end at 20:00 ET of the last completed session, capped at now-16min (free SIP: no last-15-min data)
    e = pd.Timestamp(f"{session} 20:00", tz="America/New_York").tz_convert("UTC")
    cap = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=16)
    return min(e, cap).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(symbols, start, end, adjustment, feed, asof=None, batch=100):
    out = defaultdict(list)
    for i in range(0, len(symbols), batch):
        syms = symbols[i:i+batch]; tok = None
        while True:
            p = {"symbols": ",".join(syms), "timeframe": "1Day", "start": start, "end": end,
                 "adjustment": adjustment, "feed": feed, "limit": 10000, "sort": "asc"}
            if asof: p["asof"] = asof
            if tok: p["page_token"] = tok
            j = get(DATA_URL + "/v2/stocks/bars", p)
            for s, bars in (j.get("bars") or {}).items(): out[s].extend(bars)
            tok = j.get("next_page_token")
            if not tok: break
    return out


def to_df(sym, bars, adj, feed, asof, fetched):
    df = pd.DataFrame(bars).rename(columns=COLS)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["session_date"] = df["timestamp_utc"].dt.tz_convert("America/New_York").dt.date
    df.insert(0, "symbol", sym)
    df["adjustment"] = ADJ[adj]; df["feed"] = feed; df["asof_mapping"] = asof or ""
    df["fetched_at_utc"] = fetched
    order = ["symbol","session_date","timestamp_utc","open","high","low","close","volume","trade_count","vwap","adjustment","feed","asof_mapping","fetched_at_utc"]
    df = df[[c for c in order if c in df.columns]]
    # PIT: daily bar is final after the session close (16:00 ET, or early close) + feed delay (~15 min SIP free tier)
    return df


def clip_ticker_reuse(df, sessions, max_gap=10):
    """Former members: Alpaca can return a DIFFERENT company that later reused the ticker. Cut the series at the
    first gap of > max_gap NYSE sessions (the old entity stopped trading, a new one appeared later)."""
    pos = sessions.searchsorted(df["session_date"].values)
    gaps = pd.Series(pos).diff().fillna(1).values - 1
    cut = (gaps > max_gap).nonzero()[0]
    return df.iloc[: cut[0]] if len(cut) else df


def clip_stale_fill(df, min_run=5):
    """Former members: after a delisting (merger, bankruptcy, failure) Alpaca keeps emitting PLACEHOLDER bars with
    volume=0 / trade_count=0 and a carried-forward price (seen for MON, INFO, EMC, XL, SBNY, ...), sometimes for years,
    sometimes followed by a new company on the same ticker. Cut at the first run of >= min_run zero-volume bars."""
    z = (df["volume"].fillna(0) == 0).astype(int).values
    run = 0
    for i, v in enumerate(z):
        run = run + 1 if v else 0
        if run >= min_run:
            return df.iloc[: i - run + 1]
    return df


def add_flags(df):
    df = df.copy()
    df["zero_volume"] = df["volume"].fillna(0) == 0   # placeholder/no-trade bar (e.g. suspension); mask in research
    return df


def reclip_all(u, sessions):
    """Idempotent post-process of stored files (used once after adding clip_stale_fill; safe to re-run)."""
    former = set(u.loc[u["role"] == "sp500_former_since_2016", "symbol"])
    out = {}
    for adj in ("raw", "adjusted"):
        for f in sorted((OUT / adj).glob("*.parquet")):
            df = pd.read_parquet(f); n0 = len(df)
            if f.stem in former:
                df = clip_stale_fill(clip_ticker_reuse(df, sessions))
            df = add_flags(df)
            write_parquet(df, f)
            if len(df) != n0: out.setdefault(adj, {})[f.stem] = [n0, len(df), str(df["session_date"].max())]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjustment", default="both", choices=["raw", "adjusted", "both"])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--symbols")
    ap.add_argument("--feed", default="sip")
    ap.add_argument("--reclip", action="store_true", help="only re-apply ticker-reuse/stale-fill clipping + flags to stored files")
    ap.add_argument("--refresh-delisted", action="store_true", help="also re-query former members whose bars ended >14d ago")
    a = ap.parse_args()
    u = pd.read_parquet(DATA / "universe" / "universe.parquet")
    if a.symbols: u = u[u["symbol"].isin(a.symbols.split(","))]
    mem = pd.read_parquet(DATA / "universe" / "sp500_membership.parquet")
    last_end = mem.dropna(subset=["end_date"]).groupby("symbol")["end_date"].max()
    cal = calendar(START)
    sessions = pd.Index(sorted(cal["date"]))
    session = last_completed_session(cal)
    if a.reclip:
        res = reclip_all(u, sessions); log.info("reclip changed: %s", json.dumps(res, default=str))
        update_manifest("bars_daily_reclip", res); return
    end = end_param(session)
    log.info("last completed session %s; end=%s", session, end)
    ca_path = DATA / "corporate_actions" / "all_actions.parquet"
    ca = pd.read_parquet(ca_path) if ca_path.exists() else None
    fetched = pd.Timestamp.now(tz="UTC")
    adjs = ["raw", "adjusted"] if a.adjustment == "both" else [a.adjustment]
    summary = {}
    for adj in adjs:
        d = OUT / adj; d.mkdir(parents=True, exist_ok=True)
        groups = defaultdict(list)  # (start, asof) -> symbols
        existing = {}
        for _, r in u.iterrows():
            s = r["symbol"]
            asof = None
            if r["role"] == "sp500_former_since_2016" and s in last_end:
                asof = (pd.Timestamp(last_end[s]) - pd.Timedelta(days=1)).date().isoformat()
            f = d / f"{s}.parquet"
            start = START
            if f.exists() and not a.full:
                old = pd.read_parquet(f); existing[s] = old
                last = old["session_date"].max()
                if last >= session: continue
                if asof and (session - last).days > 14 and not a.refresh_delisted:
                    continue  # former member that stopped trading: nothing new to fetch
                start = (last + dt.timedelta(days=1)).isoformat()
                if adj == "adjusted" and ca is not None and "symbol" in ca:
                    hit = ca[(ca["symbol"] == s) & (pd.to_datetime(ca["ex_date"]).dt.date > last)]
                    if len(hit): start = START; existing.pop(s)  # history re-adjusted -> full re-pull
            groups[(start, asof)].append(s)
        n_new = 0
        for gi, ((start, asof), syms) in enumerate(sorted(groups.items(), key=lambda x: (x[0][0], x[0][1] or ""))):
            res = fetch(syms, start, end, ADJ[adj], a.feed, asof)
            for s in syms:
                bars = res.get(s, [])
                if not bars: continue
                new = to_df(s, bars, adj, a.feed, asof, fetched)
                old = existing.get(s)
                df = pd.concat([old, new]) if old is not None else new
                df = df.drop_duplicates(["symbol", "session_date"], keep="last").sort_values("session_date").reset_index(drop=True)
                if asof: df = clip_stale_fill(clip_ticker_reuse(df, sessions))
                df = add_flags(df)
                write_parquet(df, d / f"{s}.parquet"); n_new += len(new)
            if gi % 20 == 0: log.info("%s group %d/%d (%d syms, start=%s asof=%s)", adj, gi + 1, len(groups), len(syms), start, asof)
        files = list(d.glob("*.parquet"))
        missing = sorted(set(u["symbol"]) - {f.stem for f in files})
        summary[adj] = {"new_rows_this_run": n_new, "symbol_files": len(files), "symbols_without_bars": missing}
        log.info("%s: +%d rows, %d files, %d symbols without bars", adj, n_new, len(files), len(missing))
    update_manifest("bars_daily", {"feed": a.feed, "last_session": session, "start": START, **summary})


def _staleness(*names):
    """Write data/staleness/<name>.json from on-disk observation maxima (lib/staleness.py). Never changes exit code."""
    try:
        import sys as _s; _s.path.insert(0, f"{_QR.DATA_DIR}/lib"); from quant_research.data.client import staleness
        for n in names: staleness.record(n)
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
    _staleness("bars_daily")
