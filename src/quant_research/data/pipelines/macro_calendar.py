"""Historical macro release calendar -> data/macro/macro_releases.parquet (+ raw HTML/JSON in macro/raw/).

Sources (free, no invention):
  * BEA news-release archive (www.bea.gov/news/archive?field_related_product_target_id=<id>&page=N): every GDP and
    Personal Income & Outlays (PCE price index) release since 1996, with the publication timestamp from the page's
    <time datetime="...-04:00"> attribute (normally 08:30 ET).
  * FRED API release dates (api.stlouisfed.org/fred/release/dates) for CPI (rid 10), Employment Situation / NFP (50),
    GDP (53), Personal Income & Outlays (54), PPI (46) - ONLY if env FRED_API_KEY is set (free key from fred.stlouisfed.org).
    api.stlouisfed.org is reachable from the box; fred.stlouisfed.org web pages and bls.gov are not (timeout / HTTP 403).
    FRED gives the date only; BLS CPI/NFP/PPI are released 08:30 ET (standard BLS time; assumed, flagged time_source).
Idempotent: full rebuild each run."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import pandas as pd
import requests

from quant_research.data.pipelines.common import DATA, log, update_manifest, write_parquet

OUT = DATA / "macro"
UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "CIO-Desk-Research research-data@example.com")}
BEA = {"451": "BEA_GDP", "716": "BEA_PERSONAL_INCOME_OUTLAYS_PCE"}
FRED = {10: "CPI", 50: "EMPLOYMENT_SITUATION_NFP", 53: "GDP", 54: "PERSONAL_INCOME_OUTLAYS", 46: "PPI"}
ROW = re.compile(
    r'<a href="([^"]+)"[^>]*>([^<]+)</a>\s*</td>\s*<td[^>]*views-field-created[^>]*><time datetime="([^"]+)"', re.S
)


def bea(pid: str, name: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    page = 0
    raw = OUT / "raw" / "bea"
    raw.mkdir(parents=True, exist_ok=True)
    while True:
        url = f"https://www.bea.gov/news/archive?field_related_product_target_id={pid}&page={page}"
        for k in range(4):
            try:
                r = requests.get(url, headers=UA, timeout=40)
                r.raise_for_status()
                break
            except Exception as e:
                log.warning("BEA %s p%d try %d: %s", pid, page, k, e)
                time.sleep(3 * (k + 1))
        else:
            raise RuntimeError(f"BEA {pid} page {page} failed")
        (raw / f"{pid}_p{page}.html").write_text(r.text)
        found = ROW.findall(r.text)
        if not found:
            break
        for href, title, ts in found:
            rows.append(
                {
                    "release": name,
                    "title": title.strip(),
                    "url": "https://www.bea.gov" + href,
                    "release_time_local": ts,
                    "source": "bea_news_archive",
                    "time_source": "bea_page_timestamp",
                }
            )
        page += 1
        time.sleep(1.0)
    return rows


def fred(rid: int, name: str, key: str) -> list[dict[str, str]]:
    j = requests.get(
        "https://api.stlouisfed.org/fred/release/dates",
        timeout=40,
        params={  # type: ignore[arg-type]  # requests params accept str and int together
            "release_id": rid,
            "api_key": key,
            "file_type": "json",
            "realtime_start": "1776-07-04",
            "limit": 10000,
            "sort_order": "asc",
            "include_release_dates_with_no_data": "false",
        },
    ).json()
    return [
        {
            "release": "FRED_" + name,
            "title": name,
            "url": f"fred release_id={rid}",
            "release_time_local": d["date"] + "T08:30:00",
            "source": "fred_api_release_dates",
            "time_source": "assumed_0830_ET",
        }
        for d in j.get("release_dates", [])
    ]


def main() -> None:
    rows: list[dict[str, str]] = []
    status: dict[str, Any] = {}
    for pid, name in BEA.items():
        try:
            r = bea(pid, name)
            rows += r
            status[name] = len(r)
        except Exception as e:
            status[name] = f"FAILED {e}"
    key = os.environ.get("FRED_API_KEY")
    if key:
        for rid, name in FRED.items():
            try:
                r = fred(rid, name, key)
                rows += r
                status["FRED_" + name] = len(r)
            except Exception as e:
                status["FRED_" + name] = f"FAILED {type(e).__name__}"
    else:
        status["FRED"] = "skipped: env FRED_API_KEY not set (needed for CPI/NFP/PPI history)"
    df = pd.DataFrame(rows)
    ts = [pd.Timestamp(x) for x in df["release_time_local"]]
    utc = [
        x.tz_convert("UTC") if x.tzinfo is not None else x.tz_localize("America/New_York").tz_convert("UTC") for x in ts
    ]
    df["knowledge_time_utc"] = pd.to_datetime(utc, utc=True)
    df["release_time_et"] = df["knowledge_time_utc"].dt.tz_convert("America/New_York")
    df["release_date_et"] = df["release_time_et"].dt.date
    # older BEA archive rows carry a date only (midnight timestamp): time unknown -> conservative knowledge time 16:00 ET
    df["time_known"] = ~(
        (df["source"] == "bea_news_archive") & (df["release_time_et"].dt.strftime("%H:%M") == "00:00")
    ) & (df["time_source"] != "assumed_0830_ET")
    unk = (df["source"] == "bea_news_archive") & ~df["time_known"]
    df.loc[unk, "time_source"] = "bea_page_date_only"
    df["knowledge_time_conservative_utc"] = df["knowledge_time_utc"]
    df.loc[unk, "knowledge_time_conservative_utc"] = [
        pd.Timestamp(d).replace(hour=16).tz_localize("America/New_York").tz_convert("UTC")
        for d in df.loc[unk, "release_date_et"]
    ]
    df["fetched_at_utc"] = pd.Timestamp.now(tz="UTC")
    df = (
        df.drop_duplicates(["release", "release_date_et", "title"])
        .sort_values(["release_date_et", "release"])
        .reset_index(drop=True)
    )
    write_parquet(df.drop(columns="release_time_local"), OUT / "macro_releases.parquet")
    update_manifest(
        "macro_releases",
        {
            "rows": len(df),
            "by_release": status,
            "min": str(df.release_date_et.min()),
            "max": str(df.release_date_et.max()),
        },
    )
    log.info("macro releases: %s", status)


if __name__ == "__main__":
    main()
