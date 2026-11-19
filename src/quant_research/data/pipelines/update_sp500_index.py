#!/usr/bin/env python3
"""Daily updater for the frozen S&P 500 index history (Rachel / Risk).

Run (after the close, each trading day):
    $QR_DATA_DIR/.venv/bin/python $QR_DATA_DIR/pipelines/update_sp500_index.py

What it does
  1. Reads index/sp500/LATEST.json (or, on first run, bootstraps from sp500_index_daily_20261030.parquet,
     last session 2026-10-28). Never modifies or deletes existing parquet files.
  2. Target = last COMPLETED XNYS session: a session counts as completed only after 16:30 America/New_York
     (official close known ~16:00-16:30 ET; early-close days are covered by the same conservative cut-off).
     Never appends a partial day.
  3. Fetches ^GSPC and ^SP500TR daily rows from Yahoo via yfinance (same source as the 20261030 build).
  4. Validates: every XNYS session between the previous last session and the target is present in both
     series; no partial/zero rows; OHLC consistent; the latest close is within 1bp of FRED SP500 once FRED
     has published it (FRED via the desk client ddc.fred_series, falling back to fredgraph.csv). Rows whose
     FRED value was still pending in earlier files are re-checked when FRED has them. Cboe SPX_History.csv
     is cross-checked when available (warning only: Cboe's file has known stale rows).
  5. Appends the new sessions (history rows are carried over unchanged, except that FRED/Cboe cross-check
     columns are filled where they were previously empty) and writes a NEW frozen file
     index/sp500/sp500_index_daily_<YYYYMMDD of last session>.parquet (atomic write, chmod 444), then
     atomically updates index/sp500/LATEST.json.
Idempotent: if the target session is already in LATEST, it prints the current line and exits 0.

Partial-day guard: also requires Yahoo's regularMarketTime >= the XNYS session close of the target.
Exit codes: 0 ok / already up to date; 2 validation failed; 3 source not updated yet (Yahoo lacks the
completed target session); 4 output conflict (a file for that session exists with a different sha256);
5 fetch error. On non-zero exit nothing is written.
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import argparse, datetime as dt, hashlib, io, json, os, sys, tempfile
from pathlib import Path
import numpy as np, pandas as pd, pyarrow as pa, pyarrow.parquet as pq, requests
import exchange_calendars as xc

ET, SGT = "America/New_York", "Asia/Singapore"
CLOSE_KNOWN = pd.Timedelta(hours=16, minutes=30)
BOOTSTRAP = "sp500_index_daily_20261030.parquet"
UA = {"User-Agent": "Mozilla/5.0 (cio-desk sp500 updater)"}
FRED_TOL_BP = 1.0  # overridable with --fred-tol-bp (testing only)
CBOE_WARN_BP = 1.0


class Fail(Exception):
    def __init__(self, code, msg): super().__init__(msg); self.code = code


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def atomic_write_bytes(path: Path, data: bytes, mode=0o644):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, mode); os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.remove(tmp)


def last_completed_session(cal, now_utc):
    now_et = now_utc.tz_convert(ET)
    d = pd.Timestamp(now_et.date())
    s = d if cal.is_session(d) else cal.date_to_session(d, direction="previous")
    if s == d and now_et < (d.tz_localize(ET) + CLOSE_KNOWN):
        s = cal.previous_session(s)
    return s.date()


def fetch_yahoo(sym, start, end):
    import yfinance as yf
    t = yf.Ticker(sym)
    h = t.history(start=str(start), end=str(end + dt.timedelta(days=1)), auto_adjust=False, raise_errors=True)
    rmt = (t.history_metadata or {}).get("regularMarketTime")
    h = h.reset_index()
    h.attrs["regularMarketTime"] = pd.Timestamp(rmt) if rmt is not None else None
    h["session_date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.date
    return h


def fetch_fred(start):
    """Returns (DataFrame[session_date, fred], how). Desk client first, fredgraph.csv fallback."""
    errs = []
    try:
        sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
        from quant_research.data.client import desk_data_client as ddc
        f = ddc.fred_series("SP500", start=start, use_cache=False, max_total_wait=120)
        return f.rename(columns={"observation_date": "session_date", "value": "fred"})[["session_date", "fred"]].dropna(), "ddc.fred_series"
    except Exception as e:
        errs.append(f"ddc:{type(e).__name__}")
    try:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": "SP500", "cosd": str(start)}, headers=UA, timeout=60)
        r.raise_for_status()
        f = pd.read_csv(io.StringIO(r.text))
        f["session_date"] = pd.to_datetime(f.iloc[:, 0]).dt.date
        f["fred"] = pd.to_numeric(f.iloc[:, 1], errors="coerce")
        return f[["session_date", "fred"]].dropna(), "fredgraph.csv"
    except Exception as e:
        errs.append(f"fredgraph:{type(e).__name__}")
    return None, ";".join(errs)


def fetch_cboe():
    try:
        r = requests.get("https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv", headers=UA, timeout=60, allow_redirects=True)
        r.raise_for_status()
        c = pd.read_csv(io.StringIO(r.text))
        c["session_date"] = pd.to_datetime(c.DATE, format="%m/%d/%Y").dt.date
        return c[["session_date", "SPX"]].rename(columns={"SPX": "cboe"}), "ok"
    except Exception as e:
        return None, type(e).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=f"{_QR.DATA_DIR}/index/sp500")
    ap.add_argument("--now-utc", default=None, help="override clock (testing), e.g. 2026-10-29T21:00Z")
    ap.add_argument("--strict-fred", action="store_true", help="fail if FRED is unreachable (default: record as unavailable)")
    ap.add_argument("--fred-tol-bp", type=float, default=1.0, help="FRED tolerance in bp (default 1.0; spec value)")
    a = ap.parse_args()
    global FRED_TOL_BP; FRED_TOL_BP = a.fred_tol_bp
    d = Path(a.dir)
    now = pd.Timestamp(a.now_utc) if a.now_utc else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None: now = now.tz_localize("UTC")
    cal = xc.get_calendar("XNYS", start="1990-01-01")
    latest_p = d / "LATEST.json"
    if latest_p.exists():
        L = json.loads(latest_p.read_text()); base_path = Path(L["path"])
        if sha256(base_path) != L["sha256"]:
            raise Fail(2, f"LATEST.json sha256 does not match {base_path} — refusing to build on a modified file")
    else:
        base_path = d / BOOTSTRAP; L = None
    base = pq.read_table(base_path); schema = base.schema; B = base.to_pandas()
    last = max(B.session_date)
    target = last_completed_session(cal, now)
    hist = (L or {}).get("history", [])
    if L is None:   # bootstrap pointer to the original frozen build
        L = {"path": str(base_path), "sha256": sha256(base_path), "last_session_date": str(last), "built_at_utc": None,
             "validation": {"status": "PASS", "note": "original 2026-10-30 build; see README.md"}}
    if target <= last:
        if not latest_p.exists():
            L.update(updated_at_utc=now.isoformat(), history=[{k: L[k] for k in ("path", "sha256", "last_session_date")}])
            atomic_write_bytes(latest_p, (json.dumps(L, indent=1) + "\n").encode())
        print(f"{L['path']} {L['sha256']} {L['last_session_date']} (already up to date; last completed session {target})")
        return 0
    need = [s.date() for s in cal.sessions_in_range(str(last), str(target))][1:]
    out_path = d / f"sp500_index_daily_{target:%Y%m%d}.parquet"
    # ---- fetch
    try:
        start = last - dt.timedelta(days=10)
        G = fetch_yahoo("^GSPC", start, target); T = fetch_yahoo("^SP500TR", start, target)
    except Exception as e:
        raise Fail(5, f"Yahoo fetch failed: {type(e).__name__}: {e}")
    fetched = pd.Timestamp.now(tz="UTC").floor("s")
    rmts = {"^GSPC": G.attrs.get("regularMarketTime"), "^SP500TR": T.attrs.get("regularMarketTime")}
    G = G[G.session_date <= target]; T = T[T.session_date <= target]
    if target not in set(G.session_date) or target not in set(T.session_date):
        raise Fail(3, f"source not updated yet: Yahoo has ^GSPC through {max(G.session_date, default=None)}, ^SP500TR through {max(T.session_date, default=None)}; completed target session {target}")
    # guard against a partial/intraday daily row: Yahoo's last trade time must be at/after the official close
    sc = cal.session_close(pd.Timestamp(target))
    for nm_, rmt in rmts.items():
        if rmt is None:
            raise Fail(3, f"source not updated yet: {nm_} has no regularMarketTime; cannot prove {target} row is final")
        if rmt.tz is None: rmt = rmt.tz_localize("UTC")
        if rmt < sc:
            raise Fail(3, f"source not updated yet: {nm_} {target} row is intraday (Yahoo last trade {rmt.tz_convert(ET):%Y-%m-%d %H:%M} ET < close {sc.tz_convert(ET):%H:%M} ET)")
    v = {"target": str(target), "new_sessions": [str(x) for x in need], "checks": {}, "warnings": []}
    miss = [str(x) for x in need if x not in set(G.session_date) or x not in set(T.session_date)]
    extra = [str(x) for x in G.session_date if x > last and x not in set(need)]
    v["checks"]["missing_sessions"] = miss; v["checks"]["non_xnys_rows"] = extra
    # revision check of the overlap with the frozen history (informational)
    ov = B[["session_date", "close", "tr_close"]].merge(G[["session_date", "Close"]], on="session_date").merge(T[["session_date", "Close"]].rename(columns={"Close": "TRC"}), on="session_date")
    rev = pd.concat([(ov.Close / ov.close - 1).abs(), (ov.TRC / ov.tr_close - 1).abs()]).max() * 1e4 if len(ov) else 0.0
    v["checks"]["yahoo_revision_vs_frozen_max_bp"] = float(rev)
    if rev > 0.5: v["warnings"].append(f"Yahoo revised overlap history by up to {rev:.2f}bp; frozen history rows kept unchanged")
    # ---- build new rows
    N = G[G.session_date.isin(need)][["session_date", "Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)
    N = N.merge(T[["session_date", "Close"]].rename(columns={"Close": "tr_close"}), on="session_date", how="left")
    bad_vals = N[(N[["open", "high", "low", "close", "tr_close"]] <= 0).any(axis=1) | N[["open", "high", "low", "close", "tr_close"]].isna().any(axis=1) | (N.volume <= 0)]
    v["checks"]["partial_or_nonpositive_rows"] = [str(x) for x in bad_vals.session_date]
    N["ohlc_inconsistent"] = (N.low > N[["open", "close"]].min(axis=1) + 1e-6) | (N.high < N[["open", "close"]].max(axis=1) - 1e-6)
    v["checks"]["ohlc_inconsistent"] = [str(x) for x in N.session_date[N.ohlc_inconsistent]]
    N["ohlc_close_only"] = (N.open == N.close) & (N.high == N.close) & (N.low == N.close)
    N["is_xnys_session"] = True
    A = pd.concat([B, N], ignore_index=True).sort_values("session_date").reset_index(drop=True)
    if A.session_date.duplicated().any(): raise Fail(2, "duplicate session dates after append")
    A["ret_price"] = A["ret_price"].where(A.session_date <= last, A.close / A.close.shift() - 1)
    A["ret_total"] = A["ret_total"].where(A.session_date <= last, A.tr_close / A.tr_close.shift() - 1)
    # ---- cross-checks
    fred, how = fetch_fred(dt.date(2016, 1, 1)); v["fred_source"] = how
    if fred is not None:
        fm = dict(zip(fred.session_date, fred.fred))
        fill = A.fred_sp500_close.isna() & (A.session_date >= min(fred.session_date))
        A.loc[fill, "fred_sp500_close"] = A.loc[fill, "session_date"].map(fm)
        A["xcheck_fred_bp"] = (A.close / A.fred_sp500_close - 1) * 1e4
        v["fred_last_date"] = str(max(fred.session_date))
        chk = A[(A.session_date > last) | fill]
        chk = chk[chk.fred_sp500_close.notna()]
        bad = chk[chk.xcheck_fred_bp.abs() > FRED_TOL_BP]
        v["checks"]["fred_checked_sessions"] = [str(x) for x in chk.session_date]
        v["checks"]["fred_gt_1bp"] = [[str(r.session_date), float(r.close), float(r.fred_sp500_close), float(r.xcheck_fred_bp)] for r in bad.itertuples()]
        v["checks"]["fred_pending_sessions"] = [str(x) for x in A.session_date[(A.session_date > last) & A.fred_sp500_close.isna()]]
    else:
        v["checks"]["fred_gt_1bp"] = []; v["checks"]["fred_pending_sessions"] = [str(x) for x in need]
        msg = f"FRED unreachable ({how}); latest close not yet verified against FRED"
        if a.strict_fred: raise Fail(2, msg)
        v["warnings"].append(msg)
    cb, cst = fetch_cboe(); v["cboe_status"] = cst
    if cb is not None:
        cm = dict(zip(cb.session_date, cb.cboe))
        fill = A.cboe_spx_close.isna() & (A.session_date >= dt.date(1975, 1, 2))
        A.loc[fill, "cboe_spx_close"] = A.loc[fill, "session_date"].map(cm)
        A["xcheck_cboe_bp"] = (A.close / A.cboe_spx_close - 1) * 1e4
        nb = A[(A.session_date > last) & (A.xcheck_cboe_bp.abs() > CBOE_WARN_BP)]
        if len(nb): v["warnings"].append("Cboe SPX differs >1bp on " + ", ".join(f"{r.session_date} {r.xcheck_cboe_bp:+.2f}bp" for r in nb.itertuples()))
        v["checks"]["cboe_pending_sessions"] = [str(x) for x in A.session_date[(A.session_date > last) & A.cboe_spx_close.isna()]]
    # ---- flags / metadata columns for new rows
    nm = A.session_date > last
    def flag(r):
        f = []
        if r.ohlc_close_only: f.append("ohlc_close_only_open_high_low_set_to_close")
        if r.ohlc_inconsistent: f.append("ohlc_inconsistent")
        if pd.notna(r.xcheck_cboe_bp) and abs(r.xcheck_cboe_bp) > 1: f.append("close_vs_cboe_gt1bp")
        if pd.notna(r.xcheck_fred_bp) and abs(r.xcheck_fred_bp) > 1: f.append("close_vs_fred_gt1bp")
        if pd.notna(r.ret_price) and abs(r.ret_price) > 0.07: f.append("abs_price_return_gt7pct")
        if pd.isna(r.fred_sp500_close): f.append("fred_pending")
        return ";".join(f)
    A.loc[nm, "qa_flag"] = A[nm].apply(flag, axis=1)
    refl = (~nm) & A.qa_flag.fillna("").str.contains("fred_pending") & A.fred_sp500_close.notna()
    A.loc[refl, "qa_flag"] = A.loc[refl, "qa_flag"].str.replace(";?fred_pending", "", regex=True).str.strip(";")
    ny = pd.to_datetime(A.session_date.astype(str)).dt.tz_localize(ET)
    A.loc[nm, "close_available_et"] = (ny + CLOSE_KNOWN)[nm]
    A["close_available_et"] = pd.to_datetime(A.close_available_et).dt.tz_convert(ET) if A.close_available_et.dt.tz is None else A.close_available_et
    A.loc[nm, "close_available_utc"] = A.loc[nm, "close_available_et"].dt.tz_convert("UTC")
    A.loc[nm, "close_available_sgt"] = A.loc[nm, "close_available_et"].dt.tz_convert(SGT)
    A.loc[nm, "close_available_sgt_str"] = A.loc[nm, "close_available_sgt"].dt.strftime("%Y-%m-%d %H:%M SGT")
    A.loc[nm, "source_price"] = "yahoo:^GSPC"; A.loc[nm, "source_tr"] = "yahoo:^SP500TR"; A.loc[nm, "yahoo_fetched_at_utc"] = fetched
    # ---- verdict
    c = v["checks"]
    fails = []
    if c["missing_sessions"]: fails.append(f"missing sessions {c['missing_sessions']}")
    if c["non_xnys_rows"]: fails.append(f"non-XNYS rows {c['non_xnys_rows']}")
    if c["partial_or_nonpositive_rows"]: fails.append(f"partial/non-positive rows {c['partial_or_nonpositive_rows']}")
    if c["ohlc_inconsistent"]: fails.append(f"OHLC inconsistent {c['ohlc_inconsistent']}")
    if c["fred_gt_1bp"]: fails.append(f"close vs FRED > {FRED_TOL_BP}bp: {c['fred_gt_1bp']}")
    v["status"] = "FAIL" if fails else "PASS"; v["failures"] = fails
    if fails: raise Fail(2, "VALIDATION FAILED: " + " | ".join(fails))
    # ---- write
    A = A[schema.names]
    tbl = pa.Table.from_pandas(A, schema=schema.remove_metadata(), preserve_index=False)
    meta = dict(schema.metadata or {})
    meta[b"sp500_update"] = json.dumps({"parent_file": str(base_path), "parent_sha256": sha256(base_path), "built_at_utc": now.isoformat() if a.now_utc else pd.Timestamp.now(tz='UTC').isoformat(), "yahoo_fetched_at_utc": fetched.isoformat(), "validation": v}, default=str).encode()
    tbl = tbl.replace_schema_metadata(meta)
    buf = pa.BufferOutputStream(); pq.write_table(tbl, buf); data = buf.getvalue().to_pybytes()
    new_sha = hashlib.sha256(data).hexdigest()
    if out_path.exists():
        if sha256(out_path) == new_sha or (latest_p.exists() and json.loads(latest_p.read_text()).get("path") == str(out_path)):
            print(f"{out_path} {sha256(out_path)} {target} (already exists)"); return 0
        raise Fail(4, f"{out_path} already exists with a different sha256; not overwriting")
    atomic_write_bytes(out_path, data, mode=0o444)
    assert sha256(out_path) == new_sha
    b_utc = pd.Timestamp.now(tz="UTC").floor("s")
    hist = hist or [{"path": L["path"], "sha256": L["sha256"], "last_session_date": L["last_session_date"]}]
    hist.append({"path": str(out_path), "sha256": new_sha, "last_session_date": str(target)})
    NL = {"path": str(out_path), "sha256": new_sha, "last_session_date": str(target), "rows": len(A),
          "built_at_utc": b_utc.isoformat(), "built_at_sgt": b_utc.tz_convert(SGT).strftime("%Y-%m-%d %H:%M:%S SGT"),
          "validation": v, "history": hist}
    atomic_write_bytes(latest_p, (json.dumps(NL, indent=1, default=str) + "\n").encode())
    print(f"{out_path} {new_sha} {target}")
    return 0


def _staleness(*names):
    """Write data/staleness/<name>.json from on-disk observation maxima (lib/staleness.py). Never changes exit code."""
    try:
        import sys as _s; _s.path.insert(0, f"{_QR.DATA_DIR}/lib"); from quant_research.data.client import staleness
        for n in names: staleness.record(n)
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    try:
        rc = main()
    except Fail as e:
        print(f"ERROR (exit {e.code}): {e}", file=sys.stderr); _staleness("index_sp500"); sys.exit(e.code)
    _staleness("index_sp500"); sys.exit(rc)
