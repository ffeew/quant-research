"""Pull Alpaca corporate actions (/v1/corporate-actions) for the universe.
Outputs (data/corporate_actions/):
  splits.parquet       forward/reverse/unit splits
  dividends.parquet    cash dividends (+ stock dividends in stock_dividends.parquet)
  all_actions.parquet  every action type, long format (type column, all fields)
Idempotent full refresh by default (cheap: ~15 requests). Records are de-duplicated on Alpaca `id`.
Usage: python corporate_actions.py [--start 2016-01-01] [--end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Sequence
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import DATA, DATA_URL, START, get, log, update_manifest, write_parquet

OUT = DATA / "corporate_actions"
DATE_COLS = [
    "ex_date",
    "record_date",
    "payable_date",
    "process_date",
    "effective_date",
    "due_bill_on_date",
    "due_bill_off_date",
    "due_bill_redemption_date",
]


def pull(symbols: Sequence[str], start: str, end: str, batch: int = 50) -> pd.DataFrame:
    recs: list[dict[str, Any]] = []
    fetched = dt.datetime.now(dt.UTC)
    for i in range(0, len(symbols), batch):
        syms = ",".join(symbols[i : i + batch])
        tok: str | None = None
        while True:
            p: dict[str, Any] = {"symbols": syms, "start": start, "end": end, "limit": 1000, "sort": "asc"}
            if tok:
                p["page_token"] = tok
            j = get(DATA_URL + "/v1/corporate-actions", p)
            for typ, rows in j.get("corporate_actions", {}).items():
                for r in rows:
                    recs.append({"type": typ, **r})
            tok = j.get("next_page_token")
            if not tok:
                break
        log.info("corp actions batch %d/%d, total %d", i // batch + 1, -(-len(symbols) // batch), len(recs))
    df = pd.DataFrame(recs).drop_duplicates("id")
    for c in DATE_COLS:
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    df["fetched_at_utc"] = fetched
    # knowledge time: Alpaca exposes no announcement/declaration date; the earliest field we can
    # rely on is process_date (date Alpaca processed it). Conservative PIT availability = process_date.
    # Dividends/splits are necessarily public by ex_date (usually declared weeks earlier, declaration date not
    # provided). Conservative knowledge date = min(ex_date, process_date); mergers etc. use process/effective date.
    ex = df["ex_date"] if "ex_date" in df else pd.Series(pd.NaT, index=df.index)
    df["known_as_of_date"] = [
        min(d for d in (e, p) if pd.notna(d)) if (pd.notna(e) or pd.notna(p)) else None
        for e, p in zip(ex, df["process_date"])
    ]
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=START)
    ap.add_argument(
        "--end",
        default=(dt.date.today() + dt.timedelta(days=120)).isoformat(),
        help="Alpaca filters on process_date, which can be ~1 month after ex_date -> look ahead",
    )
    a = ap.parse_args()
    u = pd.read_parquet(DATA / "universe" / "universe.parquet")
    df = pull(sorted(u["symbol"]), a.start, a.end)
    write_parquet(df, OUT / "all_actions.parquet")
    spl = df[df["type"].isin(["forward_splits", "reverse_splits", "unit_splits"])].copy()
    if len(spl):
        spl["split_ratio"] = spl["new_rate"] / spl["old_rate"]
    div = df[df["type"] == "cash_dividends"].copy()
    sdiv = df[df["type"] == "stock_dividends"].copy()
    keep = lambda d, cols: (
        d[[c for c in cols if c in d.columns]].sort_values(["symbol", "ex_date"]).reset_index(drop=True)
    )
    write_parquet(
        keep(  # type: ignore[no-untyped-call]  # lambda has no annotation syntax
            spl,
            [
                "symbol",
                "type",
                "ex_date",
                "record_date",
                "payable_date",
                "process_date",
                "due_bill_redemption_date",
                "old_rate",
                "new_rate",
                "split_ratio",
                "cusip",
                "old_cusip",
                "new_cusip",
                "id",
                "known_as_of_date",
                "fetched_at_utc",
            ],
        ),
        OUT / "splits.parquet",
    )
    write_parquet(
        keep(  # type: ignore[no-untyped-call]  # lambda has no annotation syntax
            div,
            [
                "symbol",
                "ex_date",
                "record_date",
                "payable_date",
                "process_date",
                "rate",
                "special",
                "foreign",
                "cusip",
                "id",
                "known_as_of_date",
                "fetched_at_utc",
            ],
        ),
        OUT / "dividends.parquet",
    )
    if len(sdiv):
        write_parquet(keep(sdiv, list(sdiv.columns)), OUT / "stock_dividends.parquet")  # type: ignore[no-untyped-call]  # lambda has no annotation syntax
    counts = df["type"].value_counts().to_dict()
    update_manifest(
        "corporate_actions",
        {
            "window": [a.start, a.end],
            "counts_by_type": counts,
            "split_symbols": int(spl["symbol"].nunique()),
            "dividend_symbols": int(div["symbol"].nunique()),
        },
    )
    log.info("corporate actions: %s", counts)


if __name__ == "__main__":
    main()
