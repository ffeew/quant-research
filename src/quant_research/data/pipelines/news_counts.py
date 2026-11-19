"""Alpaca (Benzinga) news article counts per symbol per day / month, from 2015.

All requests go through the shared throttled client (lib/desk_data_client.alpaca_get: global token bucket, backoff, cache),
plus a local floor of 0.6 s between requests (<= 100 req/min from this job). Endpoint: /v1beta1/news (no symbol filter,
include_content=false, limit 50, sort asc), i.e. every article of the day is paged and counted against each symbol it tags.
Cost: ~12-18 requests per day (550-900 articles/day) -> full 2015..today backfill is ~55k requests (~9-10 h at 100 rpm).

Modes (resumable; finished days are skipped):
  --sample   first Wednesday of every month 2015-01..now (coverage-gap check and monthly totals estimate; ~1.7k requests)
  --full     every calendar day, newest first or --order asc
  --start/--end to limit the range
Outputs: news/daily_counts/<YYYY>/<date>.parquet  (date, symbol, n_articles, fetched_at_utc; symbol "__ALL__" = all articles)
         news/monthly_counts.parquet  (symbol, month, n_articles, days_fetched, days_in_month, complete)
         news/monthly_totals.parquet  (month, articles_total, days_fetched, articles_per_day, sample_only)
Usage: $QR_DATA_DIR/.venv/bin/python $QR_DATA_DIR/pipelines/news_counts.py --sample
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import argparse, sys, time, datetime as dt
from collections import Counter
import pandas as pd
sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
from quant_research.data.client import desk_data_client as ddc
from quant_research.data.pipelines.common import DATA, write_parquet, update_manifest, log

OUT = DATA / "news"; DAILY = OUT / "daily_counts"
_last = [0.0]


def get(params):
    w = 0.6 - (time.time() - _last[0])
    if w > 0: time.sleep(w)
    _last[0] = time.time()
    return ddc.alpaca_get("/v1beta1/news", params)


def day(d):
    f = DAILY / d[:4] / f"{d}.parquet"
    if f.exists(): return None
    c = Counter(); n = 0; tok = None; ids = set()
    while True:
        p = dict(start=f"{d}T00:00:00Z", end=f"{d}T23:59:59Z", limit=50, sort="asc", include_content="false")
        if tok: p["page_token"] = tok
        j = get(p)
        for a in j.get("news", []):
            if a["id"] in ids: continue
            ids.add(a["id"]); n += 1
            for s in set(a.get("symbols") or []): c[s] += 1
        tok = j.get("next_page_token")
        if not tok: break
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame([("__ALL__", n)] + list(c.items()), columns=["symbol", "n_articles"])
    df.insert(0, "date", pd.Timestamp(d).date()); df["fetched_at_utc"] = now
    f.parent.mkdir(parents=True, exist_ok=True); write_parquet(df, f)
    return n


def aggregate(sample_only):
    files = sorted(DAILY.glob("*/*.parquet"))
    if not files: return {}
    D = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    D["month"] = pd.to_datetime(D.date).dt.to_period("M").astype(str)
    days = D[D.symbol == "__ALL__"].groupby("month").date.nunique()
    dim = {m: pd.Period(m).days_in_month for m in days.index}
    T = D[D.symbol == "__ALL__"].groupby("month").n_articles.sum().to_frame("articles_in_fetched_days")
    T["days_fetched"] = days; T["articles_per_day"] = T.articles_in_fetched_days / T.days_fetched
    T["days_in_month"] = pd.Series(dim); T["complete"] = T.days_fetched == T.days_in_month
    T["est_month_total"] = (T.articles_per_day * T.days_in_month).round()
    write_parquet(T.reset_index(), OUT / "monthly_totals.parquet")
    M = D[D.symbol != "__ALL__"].groupby(["symbol", "month"]).n_articles.sum().reset_index()
    M["days_fetched"] = M.month.map(days); M["days_in_month"] = M.month.map(dim); M["complete"] = M.days_fetched == M.days_in_month
    write_parquet(M, OUT / "monthly_counts.parquet")
    return {"days_fetched": int(D.date.nunique()), "months": len(T), "complete_months": int(T.complete.sum())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true"); ap.add_argument("--full", action="store_true")
    ap.add_argument("--start", default="2015-01-01"); ap.add_argument("--end", default=None); ap.add_argument("--order", default="desc")
    a = ap.parse_args()
    end = pd.Timestamp(a.end or (dt.date.today() - dt.timedelta(days=1)))
    if a.sample:
        days = [d for d in pd.date_range(a.start, end, freq="WOM-1WED")]
    else:
        days = list(pd.date_range(a.start, end, freq="D"))
    days = [d.date().isoformat() for d in days]
    if a.order == "desc" and not a.sample: days = days[::-1]
    for i, d in enumerate(days):
        n = day(d)
        if n is not None and i % 10 == 0: log.info("news %s n=%s (%d/%d)", d, n, i, len(days))
    info = aggregate(a.sample) | {"mode": "sample" if a.sample else "full"}
    update_manifest("news_counts", info); log.info("%s", info)


if __name__ == "__main__":
    main()
