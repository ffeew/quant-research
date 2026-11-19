"""Small synthetic fixtures for the H1/H2 harness tests. All values are fabricated."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

STOCKS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
LEADERS = ["AAA", "BBB"]  # highest dollar volume
ETF = "XLK"
SUBIND = "Synthetic Semis"
SECTOR = "Information Technology"


def sessions(start: str = "2016-01-04", end: str = "2017-12-29") -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def make_bars(
    seed: int = 7,
    h1_gap: float = 0.004,
    h1_window: tuple[int, int] = (300, 360),
    h2_shock_i: int | None = 330,
    h2_shock: float = 0.08,
) -> dict[str, pd.DataFrame]:
    """Wide bars: R / PX / VOL / TRI. Leaders outperform followers by h1_gap per day over h1_window;
    AAA and BBB jump by h2_shock on session h2_shock_i (an earnings reaction)."""
    rng = np.random.default_rng(seed)
    dates = sessions()
    syms = STOCKS + [ETF, "SPY"]
    mkt = rng.normal(0.0003, 0.008, len(dates))
    R = pd.DataFrame({s: 1.0 * mkt + rng.normal(0, 0.01, len(dates)) for s in syms}, index=dates)
    R[ETF] = mkt
    R["SPY"] = mkt
    a, b = h1_window
    for s in LEADERS:
        R.iloc[a:b, list(R.columns).index(s)] += h1_gap
    if h2_shock_i is not None:
        for s in LEADERS:
            R.iloc[[h2_shock_i], list(R.columns).index(s)] += h2_shock  # one-row slice: Series arithmetic
    R.iloc[0] = np.nan
    TRI = (1 + R.fillna(0)).cumprod() * 50.0
    PX = TRI.copy()
    VOL = pd.DataFrame(1e6, index=dates, columns=syms)
    VOL[LEADERS] = 3e6
    VOL[[ETF, "SPY"]] = 5e6
    return {"R": R, "PX": PX, "VOL": VOL, "TRI": TRI}


def membership() -> pd.DataFrame:
    return pd.DataFrame({"symbol": STOCKS, "start_date_filled": pd.Timestamp("2015-01-02"), "end_date": None})


def listing() -> pd.DataFrame:
    return pd.DataFrame(
        {"symbol": STOCKS, "ipoDate": "2000-01-03", "delistingDate": "null", "listing_source": "active"}
    )


def gics() -> tuple[pd.Series, pd.Series]:
    return (
        pd.Series(SUBIND, index=STOCKS, name="gics_sub_industry"),
        pd.Series(SECTOR, index=STOCKS, name="gics_sector"),
    )


def earnings(
    dates: pd.DatetimeIndex, leader_idx: tuple[int, ...] = (204, 267, 330, 393, 456), follower_offset: int = -10
) -> pd.DataFrame:
    """Quarterly exact-time events: leaders on leader_idx, followers follower_offset sessions earlier."""
    rows = []
    for s in STOCKS:
        off = 0 if s in LEADERS else follower_offset
        for k in leader_idx:
            d = dates[k + off]
            rows.append(
                {
                    "symbol": s,
                    "source": "sec_8k",
                    "timing_quality": "exact_acceptance_time",
                    "announce_date_et": (d - pd.Timedelta(days=1)).date(),
                    "reaction_session": d.date(),
                    "first_tradable_session": d.date(),
                    "knowledge_time_utc": pd.Timestamp(d.date()) - pd.Timedelta(hours=2),
                }
            )
    ev = pd.DataFrame(rows)
    ev["knowledge_time_utc"] = pd.to_datetime(ev["knowledge_time_utc"]).dt.tz_localize("UTC")
    return ev


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _stacked(wide: pd.DataFrame, name: str) -> pd.Series:
    """Wide (date x symbol) frame to a long Series named `name`; columns are single-level, so stack gives a Series."""
    s = wide.stack(future_stack=True)
    assert isinstance(s, pd.Series)
    return s.rename(name)


def write_inputs(root: Path, *, tr_extra_rows: pd.DataFrame | None = None) -> dict[str, Path]:
    """Write every DEV input under root as small synthetic files; return name -> path."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    root.mkdir(parents=True, exist_ok=True)
    bars = make_bars()
    long = (
        _stacked(bars["R"], "ret_total_best")
        .to_frame()
        .join(_stacked(bars["TRI"], "tr_index_best"))
        .join(_stacked(bars["PX"], "close_raw"))
        .join(_stacked(bars["VOL"], "volume_raw"))
        .reset_index()
        .rename(columns={"level_0": "session_date", "level_1": "symbol"})
    )
    long.columns = ["session_date", "symbol", *long.columns[2:]]
    if tr_extra_rows is not None:
        long = pd.concat([long, tr_extra_rows], ignore_index=True)
    long["session_date"] = [d.date() for d in pd.to_datetime(long["session_date"])]
    p: dict[str, Path] = {}

    def wpq(name: str, df: pd.DataFrame) -> None:
        p[name] = root / f"{name}.parquet"
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), p[name])

    wpq("tr_dev_cut", long[["symbol", "session_date", "close_raw", "volume_raw", "ret_total_best", "tr_index_best"]])
    p["tr_dev_cut_sums"] = root / "SHA256SUMS"
    p["tr_dev_cut_sums"].write_text(f"{sha(p['tr_dev_cut'])}  {p['tr_dev_cut']}\n")
    wpq("earnings_dev_cut", earnings(pd.DatetimeIndex(bars["R"].index)))
    sub, sec = gics()
    wpq("universe_gics", pd.DataFrame({"symbol": STOCKS, "gics_sub_industry": sub.values, "gics_sector": sec.values}))
    m = membership()
    m["end_date"] = pd.Series([None] * len(m), dtype="datetime64[ns]")
    wpq("membership", m)
    wpq("listing_status", listing())
    for name, obj in (
        ("reused_tickers", {"tickers": []}),
        ("missing_names", {"tickers": []}),
        ("h1_terminal_roster", []),
    ):
        p[name] = root / f"{name}.json"
        p[name].write_text(json.dumps(obj))
    p["identity_list"] = root / "identity.tsv"
    p["identity_list"].write_bytes(b"symbol\tdecision\treasons\tissuer_name\nAAA\tKEPT\t\tSynth A\n")
    p["identity_basis_sums"] = root / "IDENTITY_SUMS"
    p["identity_basis_sums"].write_text("0" * 64 + "  synthetic\n")
    p["lineage_exclusions"] = root / "lineage.tsv"
    p["lineage_exclusions"].write_text("symbol\treason\n")
    p["dev_universe"] = root / "dev_universe.csv"
    p["dev_universe"].write_text("symbol\n" + "\n".join(STOCKS) + "\n")
    p["prereg"] = root / "PREREG.md"
    p["prereg"].write_text("# synthetic pre-registration\n")
    return p


def write_config(root: Path, files: dict[str, Path], *, overrides: dict[str, str] | None = None) -> Path:
    lines = ["[trial]", 'title = "synthetic"', "", "[harness]", f'out_dir = "{root / "out"}"', ""]
    for name, path in files.items():
        s = (overrides or {}).get(name, sha(path))
        lines += [f"[harness.inputs.{name}]", f'path = "{path}"', f'sha256 = "{s}"', ""]
    cfg = root / "harness.toml"
    cfg.write_text("\n".join(lines))
    return cfg
