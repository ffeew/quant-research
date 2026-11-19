"""Store-wide price QA: Alpaca SIP daily bars vs an independent close source (Yahoo via yfinance), flag-only.

Why: Alpaca SIP daily bars include stray / late prints (e.g. SPY 2020-03-12 close 255.24 vs official 248.11 from a 16:07 ET print)
in close and in open/high/low; see bars/daily/extended/signoff/SIGNOFF_trend_v3_20261030.md.
Method (per symbol, 2016-01-04 onward, main raw files bars/daily/raw/<SYM>.parquet):
  Yahoo history(auto_adjust=False) -> split-adjusted OHLC. ratio_t = yahoo_close_t / alpaca_close_t. The split factor is the
  centered 21-session rolling median of the ratio (piecewise constant; robust to isolated bad prints). Yahoo values are put on
  Alpaca's raw basis: yahoo_raw_X = yahoo_X / median_ratio.  dev_X_bp = (alpaca_X / yahoo_raw_X - 1) * 1e4.
  Rows within 3 sessions of a ratio regime change (split) are not judged (flag 'split_window_unjudged').
  price_flag: 'close_gt25bp' | 'ohl_gt50bp' (any of open/high/low) | both joined by '|'; '' = clean; 'no_yahoo' if Yahoo lacks the row.
  corrected_close = yahoo_raw_close where close is flagged; corrected_source = 'yahoo' and, when Alpaca's own 15:59 ET regular-session
  minute bar close is within 10bp of Yahoo, 'yahoo+alpaca_last_regular_minute' (two independent agreeing sources).
  Nothing in the store is overwritten. Output: bars/daily/qa/price_flags.parquet (flagged rows only + per-symbol summary in
  bars/daily/qa/price_qa_summary.parquet); Yahoo raw pulls cached in bars/daily/qa/yahoo/<SYM>.parquet (fetched_at_utc).
Rate: yfinance one request per symbol, >= 1.5 s apart. Alpaca minute checks via lib/desk_data_client (shared throttle).
Usage: python price_qa.py [--symbols A,B] [--no-minute]
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import argparse, sys, time, datetime as dt
import numpy as np, pandas as pd
import yfinance as yf
sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
from quant_research.data.pipelines.common import DATA, write_parquet, update_manifest, log

QA = DATA / "bars/daily/qa"; YDIR = QA / "yahoo"


def yahoo(sym):
    f = YDIR / f"{sym}.parquet"
    if f.exists(): return pd.read_parquet(f)
    time.sleep(1.5)
    try:
        h = yf.Ticker(sym.replace(".", "-")).history(start="2015-12-01", end=dt.date.today().isoformat(), auto_adjust=False, actions=False)
    except Exception as e:
        log.warning("yahoo %s %s", sym, type(e).__name__); return None
    if h is None or h.empty: return None
    h = h.reset_index(); h["session_date"] = pd.to_datetime(h.Date).dt.tz_localize(None).dt.date
    h = h.rename(columns={"Open": "y_open", "High": "y_high", "Low": "y_low", "Close": "y_close"})[["session_date", "y_open", "y_high", "y_low", "y_close"]]
    h["fetched_at_utc"] = pd.Timestamp.now(tz="UTC"); YDIR.mkdir(parents=True, exist_ok=True); write_parquet(h, f)
    return h


def last_minute_close(sym, d):
    from quant_research.data.client import desk_data_client as ddc
    s = pd.Timestamp(f"{d} 15:59", tz="America/New_York").tz_convert("UTC"); e = s + pd.Timedelta(minutes=1)
    j = ddc.alpaca_get("/v2/stocks/bars", dict(symbols=sym, timeframe="1Min", start=s.isoformat().replace("+00:00", "Z"),
                       end=e.isoformat().replace("+00:00", "Z"), adjustment="raw", feed="sip"))
    b = (j.get("bars") or {}).get(sym) or []
    return b[0]["c"] if b else None


def check(sym):
    a = pd.read_parquet(DATA / f"bars/daily/raw/{sym}.parquet", columns=["session_date", "open", "high", "low", "close", "volume"])
    a = a[a.session_date >= dt.date(2016, 1, 4)]
    y = yahoo(sym)
    if y is None: return None, dict(symbol=sym, yahoo="missing", rows=len(a))
    m = a.merge(y, on="session_date", how="left").sort_values("session_date").reset_index(drop=True)
    r = m.y_close / m.close
    med = r.rolling(21, center=True, min_periods=5).median()
    reg = (np.log(med).diff().abs() > 0.05)
    near = reg.rolling(7, center=True, min_periods=1).max().astype(bool)
    for c in ("open", "high", "low", "close"):
        m[f"yahoo_raw_{c}"] = m[f"y_{c}"] / med
        m[f"dev_{c}_bp"] = (m[c] / m[f"yahoo_raw_{c}"] - 1) * 1e4
    fl = []
    for i in range(len(m)):
        if pd.isna(m.y_close[i]): fl.append("no_yahoo"); continue
        if near[i]: fl.append("split_window_unjudged"); continue
        f = []
        if abs(m.dev_close_bp[i]) > 25: f.append("close_gt25bp")
        if any(abs(m[f"dev_{c}_bp"][i]) > 50 for c in ("open", "high", "low") if pd.notna(m[f"dev_{c}_bp"][i])): f.append("ohl_gt50bp")
        fl.append("|".join(f))
    m["price_flag"] = fl; m.insert(0, "symbol", sym)
    bad = m[m.price_flag != ""].copy()
    summ = dict(symbol=sym, yahoo="ok", rows=len(m), no_yahoo=int((m.price_flag == "no_yahoo").sum()),
                close_gt25bp=int(m.price_flag.str.contains("close_gt25bp").sum()), ohl_gt50bp=int(m.price_flag.str.contains("ohl_gt50bp").sum()),
                max_abs_close_bp=float(m.dev_close_bp.abs().max()))
    return bad, summ


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--symbols"); ap.add_argument("--no-minute", action="store_true"); a = ap.parse_args()
    syms = a.symbols.split(",") if a.symbols else sorted(p.stem for p in (DATA / "bars/daily/raw").glob("*.parquet"))
    bads, summ = [], []
    for k, s in enumerate(syms):
        try:
            b, sm = check(s)
        except Exception as e:
            log.warning("qa %s %s", s, e); continue
        summ.append(sm)
        if b is not None and len(b): bads.append(b)
        if k % 50 == 0: log.info("price_qa %d/%d", k, len(syms))
    B = pd.concat(bads, ignore_index=True) if bads else pd.DataFrame()
    if len(B):
        cl = B.price_flag.str.contains("close_gt25bp")
        B["corrected_close"] = np.where(cl, B.yahoo_raw_close, np.nan)
        B["corrected_source"] = np.where(cl, "yahoo", None)
        if not a.no_minute:
            for i in B.index[cl]:
                try:
                    mc = last_minute_close(B.at[i, "symbol"], B.at[i, "session_date"])
                except Exception:
                    mc = None
                B.at[i, "alpaca_last_regular_minute_close"] = mc
                if mc and abs(mc / B.at[i, "yahoo_raw_close"] - 1) < 0.001: B.at[i, "corrected_source"] = "yahoo+alpaca_last_regular_minute"
    B["checked_at_utc"] = pd.Timestamp.now(tz="UTC")
    write_parquet(B, QA / "price_flags.parquet"); S = pd.DataFrame(summ); write_parquet(S, QA / "price_qa_summary.parquet")
    info = {"symbols": len(S), "yahoo_missing": int((S.yahoo == "missing").sum()), "rows_checked": int(S.rows.sum()),
            "close_gt25bp": int(S.close_gt25bp.sum()), "ohl_gt50bp": int(S.ohl_gt50bp.sum()),
            "corrected_two_source": int((B.get("corrected_source") == "yahoo+alpaca_last_regular_minute").sum()) if len(B) else 0}
    update_manifest("price_qa", info); log.info("%s", info)


if __name__ == "__main__":
    main()
