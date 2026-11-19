"""Quantify IEX-only vs SIP (consolidated) daily volume/price differences on a sample.
Output: data/qa/feed_compare_<date>.parquet + .md summary."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import DATA, DATA_URL, get, write_parquet

SAMPLE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "JPM",
    "XOM",
    "JNJ",
    "PG",
    "KO",
    "WMT",
    "BRK.B",
    "LLY",
    "CAT",
    "AMGN",
    "DUK",
    "F",
    "PLTR",
    "SPY",
    "QQQ",
    "IWM",
    "TLT",
    "XLE",
]


def bars(feed: str, start: str, end: str) -> pd.DataFrame:
    out: dict[str, list[Any]] = {}
    tok: str | None = None
    while True:
        p = {
            "symbols": ",".join(SAMPLE),
            "timeframe": "1Day",
            "start": start,
            "end": end,
            "feed": feed,
            "adjustment": "raw",
            "limit": 10000,
        }
        if tok:
            p["page_token"] = tok
        j = get(DATA_URL + "/v2/stocks/bars", p)
        for s, b in (j.get("bars") or {}).items():
            out.setdefault(s, []).extend(b)
        tok = j.get("next_page_token")
        if not tok:
            break
    rows = [
        {"symbol": s, "t": x["t"], "close": x["c"], "volume": x["v"], "trade_count": x["n"], "vwap": x["vw"]}
        for s, b in out.items()
        for x in b
    ]
    return pd.DataFrame(rows)


def main() -> None:
    start, end = "2016-01-01", "2026-10-29T00:00:00Z"
    s = bars("sip", start, end)
    i = bars("iex", start, end)
    m = s.merge(i, on=["symbol", "t"], suffixes=("_sip", "_iex"), how="left")
    m["session_date"] = pd.to_datetime(m["t"], utc=True).dt.tz_convert("America/New_York").dt.date
    m["iex_vol_share"] = m.volume_iex / m.volume_sip
    m["close_diff_bps"] = (m.close_iex / m.close_sip - 1) * 1e4
    today = dt.date.today().isoformat()
    write_parquet(m.drop(columns=["t"]), DATA / "qa" / f"feed_compare_{today}.parquet")
    first_iex = m.dropna(subset=["volume_iex"]).groupby("symbol").session_date.min()
    rec = m[m.session_date >= dt.date(2025, 10, 29)].dropna(subset=["volume_iex"])
    by = rec.groupby("symbol").agg(
        iex_share_median=("iex_vol_share", "median"),
        close_absdiff_bps_median=("close_diff_bps", lambda x: x.abs().median()),
        close_absdiff_bps_p95=("close_diff_bps", lambda x: x.abs().quantile(0.95)),
        days=("session_date", "count"),
    )
    yr = (
        m.dropna(subset=["volume_iex"])
        .assign(year=lambda d: pd.to_datetime(d.session_date).dt.year)
        .groupby("year")
        .iex_vol_share.median()
    )
    md = [
        f"# IEX vs SIP daily bars ({today})",
        "",
        f"Sample: {len(SAMPLE)} symbols, raw daily bars 2016-01-01..2026-10-28.",
        "",
        f"SIP rows: {len(s)}, IEX rows: {len(i)}. Earliest IEX bar in sample: {first_iex.min()} (median {sorted(first_iex)[len(first_iex) // 2]}).",
        "",
        "## Last 12 months, per symbol (IEX volume / SIP volume; close difference)",
        by.round(4).to_markdown(),
        "",
        f"Overall median IEX volume share (last 12m): {rec.iex_vol_share.median():.4f}; mean {rec.iex_vol_share.mean():.4f}.",
        "",
        "## Median IEX share by year",
        yr.round(4).to_markdown(),
    ]
    (DATA / "qa" / f"feed_compare_{today}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
