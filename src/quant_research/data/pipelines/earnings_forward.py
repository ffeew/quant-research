"""Forward earnings calendar snapshot (point-in-time) + next-earnings lookup.

Daily, idempotent:  $QR_DATA_DIR/.venv/bin/python $QR_DATA_DIR/pipelines/earnings_forward.py
  1) fetches the Nasdaq earnings calendar (api.nasdaq.com/api/calendar/earnings?date=D) for every weekday from today (ET)
     to today + --days-ahead (default 100 calendar days), fresh (no cache), raw JSON -> earnings/forward/raw/<UTC date>/
  2) writes earnings/forward/snapshots/<UTC date>.parquet (universe symbols only), every row carrying fetched_at_utc.
     Re-running on the same UTC date replaces that date's snapshot (idempotent); earlier dates are never touched.
  3) rebuilds earnings/next_earnings_lookup.parquet (see earnings_calendar_pit.build_lookup).

Columns: snapshot_date_utc, fetched_at_utc, symbol, report_date, timing (BMO/AMC/UNKNOWN), fiscal_quarter_ending, eps_forecast,
n_estimates, last_year_report_date, date_status, date_status_method.

date_status: Nasdaq does not publish an explicit confirmed flag (its per-symbol page marks every date "expected*").
  confirmed_proxy  = Nasdaq row has a session label (pre-market / after-hours) -> in practice set once the company announces
  estimated        = Nasdaq row with time-not-supplied (Zacks projection typical)
  estimated_from_history = no Nasdaq row in the window; last known event + median own spacing (only in the lookup)
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import argparse, json, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo
import pandas as pd, requests
from quant_research.data.pipelines.common import DATA, write_parquet, update_manifest, log

FWD = DATA / "earnings/forward"


def fetch_day(d, rawdir):
    for k in range(6):
        try:
            r = requests.get("https://api.nasdaq.com/api/calendar/earnings", params={"date": d}, timeout=30,
                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            if r.status_code == 200:
                j = r.json(); j["_fetched_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
                (rawdir / f"{d}.json").write_text(json.dumps(j)); return d, j
        except Exception:
            pass
        time.sleep(2 ** k)
    return d, None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days-ahead", type=int, default=100); a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc); snap = now.date().isoformat()
    today_et = now.astimezone(ZoneInfo("America/New_York")).date()
    rawdir = FWD / "raw" / snap; rawdir.mkdir(parents=True, exist_ok=True)
    days = [d.date().isoformat() for d in pd.bdate_range(today_et, today_et + dt.timedelta(days=a.days_ahead))]
    u = pd.read_parquet(DATA / "universe/universe.parquet"); uni = set(u.loc[u.role != "etf", "symbol"])
    rows, failed = [], []
    with ThreadPoolExecutor(3) as ex:
        for d, j in ex.map(lambda x: fetch_day(x, rawdir), days):
            if j is None: failed.append(d); continue
            for r in ((j.get("data") or {}).get("rows") or []):
                rows.append({"report_date": d, **r, "fetched_at_utc": j["_fetched_at_utc"]})
    if not rows: raise SystemExit(f"Nasdaq returned no rows; failed dates: {failed}")
    df = pd.DataFrame(rows)
    df["symbol"] = df.symbol.str.upper().str.replace("/", ".").str.replace("-", ".")
    df = df[df.symbol.isin(uni)].copy()
    df["timing"] = df.time.map({"time-pre-market": "BMO", "time-after-hours": "AMC"}).fillna("UNKNOWN")
    df["date_status"] = df.timing.map(lambda t: "estimated" if t == "UNKNOWN" else "confirmed_proxy")
    df["date_status_method"] = "nasdaq_session_label_proxy"
    out = pd.DataFrame({"snapshot_date_utc": snap, "fetched_at_utc": pd.to_datetime(df.fetched_at_utc, utc=True), "symbol": df.symbol,
                        "report_date": pd.to_datetime(df.report_date).dt.date, "timing": df.timing, "fiscal_quarter_ending": df.fiscalQuarterEnding,
                        "eps_forecast": df.epsForecast, "n_estimates": df.noOfEsts, "last_year_report_date": df.lastYearRptDt,
                        "date_status": df.date_status, "date_status_method": df.date_status_method, "source": "api.nasdaq.com/api/calendar/earnings"})
    out = out.sort_values(["report_date", "symbol"]).drop_duplicates(["symbol", "report_date"])
    (FWD / "snapshots").mkdir(parents=True, exist_ok=True)
    write_parquet(out, FWD / "snapshots" / f"{snap}.parquet")
    info = {"snapshot_date_utc": snap, "days_requested": len(days), "failed_days": failed, "rows_universe": len(out),
            "symbols_with_upcoming_date": int(out.symbol.nunique()), "universe_non_etf": len(uni),
            "by_status": out.date_status.value_counts().to_dict()}
    log.info("forward snapshot %s", info)
    from quant_research.data.pipelines import earnings_calendar_pit
    info["lookup"] = earnings_calendar_pit.build_lookup()
    update_manifest("earnings_forward", info)


def _staleness(*names):
    """Write data/staleness/<name>.json from on-disk observation maxima (lib/staleness.py). Never changes exit code."""
    try:
        import sys as _s; _s.path.insert(0, f"{_QR.DATA_DIR}/lib"); from quant_research.data.client import staleness
        for n in names: staleness.record(n)
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
    _staleness("earnings_forward")
