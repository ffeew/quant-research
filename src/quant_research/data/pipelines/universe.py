"""Build universe + point-in-time S&P 500 membership.
Sources: Wikipedia 'List of S&P 500 companies' (current constituents) and
'Historical components of the S&P 500' (changes table); Alpaca /v2/assets (status).
Outputs (data/universe/):
  sp500_current.parquet       current constituents snapshot (as of fetch)
  sp500_changes.parquet       raw changes table (one row per add/remove leg)
  sp500_membership.parquet    reconstructed intervals [start_date, end_date) per ticker
  sp500_membership_anomalies.parquet  inconsistencies found during reconstruction
  universe.parquet            symbols to pull bars for, with role + alpaca status
Idempotent: re-running overwrites with fresh snapshot; dated raw HTML copies kept in universe/raw/.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from typing import Any

import pandas as pd
import requests

from quant_research.data.pipelines.common import DATA, START, TRADING_URL, UA, get, log, update_manifest, write_parquet

OUT = DATA / "universe"
ETFS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
    "SMH",  # sector
    "EFA",
    "EEM",
    "EWJ",
    "EWZ",
    "FXI",
    "EWG",
    "EWU",
    "INDA",
    "EWY",
    "EWT",
    "EWA",
    "EWC",  # country/region
    "TLT",
    "IEF",
    "SHY",
    "LQD",
    "HYG",
    "TIP",
    "AGG",
    "BND",
    "BIL",
    "BWX",  # bonds / T-bill
    "GLD",
    "SLV",
    "USO",
    "DBC",
    "UNG",
    "DBA",
    "CPER",  # commodities
    "UUP",
    "FXE",
    "FXY",
    "FXB",
    "FXA",
    "FXC",
]  # FX
CUR_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HIST_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"


def fetch(url: str, tag: str) -> str:
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"{tag}_{dt.date.today().isoformat()}.html").write_text(r.text)
    return r.text


def norm(t: object) -> str | None:
    if not isinstance(t, str):
        return None
    t = re.sub(r"[^A-Z0-9.]", "", t.strip().upper())
    return t or None


def current_constituents() -> pd.DataFrame:
    t = pd.read_html(io.StringIO(fetch(CUR_URL, "sp500_current")))[0]
    t.columns = [c.lower().replace(" ", "_") for c in t.columns]
    t["symbol"] = t["symbol"].map(norm)
    t["date_added"] = pd.to_datetime(t["date_added"], errors="coerce").dt.date
    t["snapshot_date"] = dt.date.today()
    return t


def changes() -> pd.DataFrame:
    t = pd.read_html(io.StringIO(fetch(HIST_URL, "sp500_hist")), match="Effective Date")[0]
    t.columns = [
        "effective_date",
        "added_ticker",
        "added_security",
        "removed_ticker",
        "removed_security",
        "reason",
        "refs",
    ]
    t["effective_date"] = pd.to_datetime(t["effective_date"], errors="coerce").dt.date
    for c in ("added_ticker", "removed_ticker"):
        t[c] = t[c].map(norm)
    return t.drop(columns=["refs"])


def reconstruct(cur: pd.DataFrame, ch: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Walk changes newest->oldest starting from current set. Convention: change is
    effective at the open of effective_date, so added ticker is a member from
    effective_date (inclusive); removed ticker's membership ends at effective_date (exclusive)."""
    members: dict[Any, Any] = dict.fromkeys(cur["symbol"])  # ticker -> end_date (None = still member)
    intervals: list[tuple[Any, Any, Any]] = []
    anomalies: list[tuple[Any, Any, str]] = []
    groups = sorted(
        ch.dropna(subset=["effective_date"]).groupby("effective_date"),
        key=lambda x: x[0],  # type: ignore[arg-type, return-value]  # group keys are dates
        reverse=True,
    )
    for d, g in groups:
        added = list(g["added_ticker"].dropna())
        removed = list(g["removed_ticker"].dropna())
        for a in added:
            if a in members:
                intervals.append((a, d, members.pop(a)))
            else:
                anomalies.append((d, a, "added but not a member after this date (ticker rename/re-removed/data gap)"))
        for r in removed:
            if r in members:
                anomalies.append((d, r, "removed but already a member before this date (re-add/ticker reuse/data gap)"))
            else:
                members[r] = d
    earliest = ch["effective_date"].min()
    da = dict(zip(cur["symbol"], cur["date_added"]))
    for s, end in members.items():
        start = da.get(s) if end is None and da.get(s) is not None and da.get(s) < earliest else None
        intervals.append((s, start, end))  # start None = member since before earliest recorded change
    m = pd.DataFrame(intervals, columns=["symbol", "start_date", "end_date"]).sort_values(
        ["symbol", "start_date"], na_position="first"
    )
    m["start_known"] = m["start_date"].notna()
    # unknown start = member since before the earliest recorded change (1976-07-01): fill with that lower bound
    m["start_date_filled"] = m["start_date"].where(m["start_date"].notna(), earliest)
    a = pd.DataFrame(anomalies, columns=["effective_date", "symbol", "issue"])
    return m.reset_index(drop=True), a


def alpaca_assets() -> pd.DataFrame:
    a = pd.DataFrame(get(TRADING_URL + "/v2/assets", {"status": "all", "asset_class": "us_equity"}))
    a["symbol"] = a["symbol"].str.upper()
    return a[["symbol", "name", "status", "tradable", "exchange", "id"]].drop_duplicates("symbol")


def members_on(m: pd.DataFrame, date: dt.date | str) -> set[Any]:
    date = pd.Timestamp(date).date()
    ok = (m["start_date"].isna() | (m["start_date"] <= date)) & (m["end_date"].isna() | (m["end_date"] > date))
    return set(m.loc[ok, "symbol"])


def main() -> None:
    cur = current_constituents()
    ch = changes()
    m, a = reconstruct(cur, ch)
    start = dt.date.fromisoformat(START)
    hist = sorted(set(m.loc[m["end_date"].notna() & (m["end_date"] > start), "symbol"]) - set(cur["symbol"]))
    assets = alpaca_assets()
    rows = (
        [(s, "sp500_current") for s in cur["symbol"]]
        + [(s, "etf") for s in ETFS]
        + [(s, "sp500_former_since_2016") for s in hist]
    )
    u = pd.DataFrame(rows, columns=["symbol", "role"]).drop_duplicates("symbol")
    u = u.merge(assets.rename(columns={"name": "alpaca_name", "status": "alpaca_status"}), on="symbol", how="left")
    u["in_alpaca_assets"] = u["alpaca_status"].notna()
    # GICS: CURRENT classification from Wikipedia snapshot (not point-in-time; null for former members)
    u = u.merge(
        cur[["symbol", "security", "gics_sector", "gics_sub-industry", "cik"]].rename(
            columns={"gics_sub-industry": "gics_sub_industry"}
        ),
        on="symbol",
        how="left",
    )
    u.loc[u["role"] == "etf", "gics_sector"] = "ETF"
    u["gics_asof_date"] = dt.date.today()
    # sanity: membership count over time
    checks = {
        d: len(members_on(m, d))
        for d in ["2016-01-04", "2018-01-02", "2020-01-02", "2022-01-03", "2024-01-02", dt.date.today().isoformat()]
    }
    log.info("reconstructed member counts: %s", checks)
    # month-end (last NYSE-ish business day) membership panel 2016..today for convenience
    me = pd.date_range(START, dt.date.today(), freq="BME")
    panel = pd.DataFrame([(d.date(), s) for d in me for s in sorted(members_on(m, d))], columns=["date", "symbol"])
    write_parquet(panel, OUT / "sp500_monthend_members.parquet")
    for name, df in [
        ("sp500_current", cur),
        ("sp500_changes", ch),
        ("sp500_membership", m),
        ("sp500_membership_anomalies", a),
        ("universe", u),
    ]:
        write_parquet(df, OUT / f"{name}.parquet")
    update_manifest(
        "universe",
        {
            "current": len(cur),
            "changes_rows": len(ch),
            "membership_intervals": len(m),
            "anomalies": len(a),
            "universe_symbols": len(u),
            "former_members_since_2016": len(hist),
            "member_count_check": checks,
            "changes_min_date": ch["effective_date"].min(),
            "changes_max_date": ch["effective_date"].max(),
        },
    )
    log.info(
        "universe: %d symbols (%d current, %d ETF, %d former); %d anomalies",
        len(u),
        len(cur),
        len(ETFS),
        len(hist),
        len(a),
    )


if __name__ == "__main__":
    main()
