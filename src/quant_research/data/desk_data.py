"""Shared-store data loader (read-only on the data owner's store). The derivatives researcher, 2026-10-30 (v2).

Primary source (the data owner, SIP, landed 2026-10-30):
  data/bars/daily/total_return/daily_total_return.parquet  -> ret_total_best (recommended research return),
                                                              close_raw / volume_raw (for cost buckets)
  data/universe/sp500_membership.parquet                    -> point-in-time S&P 500 intervals [start, end)
  data/universe/universe.parquet                            -> roles (sp500_current / former / etf), GICS (current only)
  data/factors/ken_french/ff3_daily.parquet                 -> FF3 + RF daily
No fallback: history comes only from the data owner's store; live Alpaca calls only via data/lib/desk_data_client.py (client).
We never write into $QR_DATA_DIR; caches go to research/replication/_cache (the derivatives researcher's).
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Iterable, Sequence
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

CIO = pathlib.Path(f"{_QR.DESK_DIR}")
DATA = CIO / "data"
CACHE = CIO / "research/replication/_cache"
TR_FILE = DATA / "bars/daily/total_return/daily_total_return.parquet"
ADJ_DIR = DATA / "bars/daily/adjusted"
MEMB_FILE = DATA / "universe/sp500_membership.parquet"
UNIV_FILE = DATA / "universe/universe.parquet"
FF3_DAILY = DATA / "factors/ken_french/ff3_daily.parquet"
SECTOR_ETFS = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
ETFS = {"DIA", "EEM", "EFA", "GLD", "HYG", "IWM", "QQQ", "SLV", "SMH", "SPY", "TLT"} | set(SECTOR_ETFS)
SUSPECT_ABS_RET = 0.40


def data_status() -> dict[str, int | bool | float | str | list[str]]:
    """What has landed. Used by run_all.py to check the store is ready (no fallback)."""
    st: dict[str, int | bool | float | str | list[str]] = {
        "bars_adjusted_files": len(list(ADJ_DIR.glob("*.parquet"))) if ADJ_DIR.exists() else 0,
        "total_return": TR_FILE.exists(),
        "membership": MEMB_FILE.exists(),
        "universe": UNIV_FILE.exists(),
        "ff3_daily": FF3_DAILY.exists(),
        "shares_outstanding_files": [str(p.relative_to(DATA)) for p in DATA.rglob("*shares*out*.parquet")],
    }
    if st["universe"]:
        u = pd.read_parquet(UNIV_FILE)
        st["sector_etfs_in_universe"] = sorted(set(SECTOR_ETFS) & set(u.symbol))
        stocks = u[u.role != "etf"]
        st["gics_coverage_current"] = float(stocks.loc[stocks.role == "sp500_current", "gics_sector"].notna().mean())
        st["gics_coverage_former"] = float(stocks.loc[stocks.role != "sp500_current", "gics_sector"].notna().mean())
        st["gics_asof"] = str(u.gics_asof_date.max())
    st["primary_ready"] = bool(
        st["total_return"] and st["membership"] and st["ff3_daily"] and cast(int, st["bars_adjusted_files"]) > 500
    )
    return st


def _clean(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Suspect returns: |r| > 40% on a day with a split, a flagged spin-off/other action, or a >50bp mismatch between
    The data owner's two total-return constructions. These are corporate-action artefacts far more often than real moves
    (QA report 2026-10-30 lists 166 |r|>40% days, e.g. CTVA 2026-10-01 -83.8%). Base case sets them to 0
    (value-neutral corporate action); run_all reports a no-clean sensitivity."""
    sus = (df.ret_total_best.abs() > SUSPECT_ABS_RET) & (
        (df.split_ratio.fillna(1) != 1) | df.other_action | df.tr_mismatch_gt50bps
    )
    log = df.loc[
        sus,
        ["symbol", "session_date", "ret_total_best", "ret_total", "split_ratio", "other_action", "tr_mismatch_gt50bps"],
    ]
    df = df.copy()
    df["ret_clean"] = df.ret_total_best.where(~sus, 0.0)
    return df, log


def load_panel(clean: bool = True, use_cache: bool = True) -> dict[str, pd.DataFrame | str]:
    """Wide daily panels from the data owner's total-return file. Keys: ret, close_raw, vol_raw, suspect_log, source."""
    CACHE.mkdir(parents=True, exist_ok=True)
    ck = CACHE / f"panel_{'clean' if clean else 'raw'}_{int(TR_FILE.stat().st_mtime)}.pkl"
    if use_cache and ck.exists():
        return cast("dict[str, pd.DataFrame | str]", pd.read_pickle(ck))
    cols = [
        "symbol",
        "session_date",
        "close_raw",
        "volume_raw",
        "ret_total_best",
        "ret_total",
        "split_ratio",
        "other_action",
        "tr_mismatch_gt50bps",
        "open_adj",
        "close_adj",
    ]
    df = pd.read_parquet(TR_FILE, columns=cols)
    df["session_date"] = pd.to_datetime(df.session_date)
    df, log = _clean(df)
    rcol = "ret_clean" if clean else "ret_total_best"
    out: dict[str, pd.DataFrame | str] = {
        "ret": df.pivot(index="session_date", columns="symbol", values=rcol).sort_index(),
        "close_raw": df.pivot(index="session_date", columns="symbol", values="close_raw").sort_index(),
        "vol_raw": df.pivot(index="session_date", columns="symbol", values="volume_raw").sort_index().astype(float),
        "suspect_log": log,
        "source": f"dmitri_sip_total_return({'clean' if clean else 'raw'})",
    }
    # Overnight (close t-1 -> open t) and intraday (open t -> close t) legs from adjusted prices, for next-open fills.
    # (1+on)(1+id) == 1+ret_total_best to 1e-15 (checked on AAPL). Suspect days are zeroed in both legs.
    oa = df.pivot(index="session_date", columns="symbol", values="open_adj").sort_index()
    ca = df.pivot(index="session_date", columns="symbol", values="close_adj").sort_index()
    on, idr = oa / ca.shift(1) - 1, ca / oa - 1
    if clean:
        sus = df.pivot(index="session_date", columns="symbol", values="ret_clean").sort_index().eq(0) & df.pivot(
            index="session_date", columns="symbol", values="ret_total_best"
        ).sort_index().ne(0)
        on, idr = on.mask(sus, 0.0), idr.mask(sus, 0.0)
    ret = cast(pd.DataFrame, out["ret"])
    on = on.where(ret.notna())
    out["on"], out["id"] = on, idr.where(ret.notna())
    pd.to_pickle(out, ck)  # type: ignore[attr-defined]  # pandas.to_pickle stores the mixed panel dict
    return out


def load_membership() -> pd.DataFrame:
    m = pd.read_parquet(MEMB_FILE)
    for c in ("start_date", "end_date"):
        m[c] = pd.to_datetime(m[c])
    return m


KNOWN_TICKER_REUSE = {  # symbol -> (end date of the interval that belongs to a DIFFERENT company than the bars, note)
    "SNDK": (
        "2016-05-13",
        "old SanDisk (member until 2016-05-13) has no bars; SNDK bars are the new Sandisk (listed 2025-02, "
        "member from 2025-11-28). Old interval excluded, new interval kept.",
    ),
    "AA": (
        "2016-11-01",
        "member until 2016-11-01 was Alcoa Inc. (renamed Arconic/ARNC); the AA bars from 2016-10 are the new "
        "Alcoa Corp. spin-off (when-issued). Interval excluded.",
    ),
    "Q": (
        "2017-11-15",
        "member 2017-08..11 was Quintiles IMS; the Q bars (from 2025-11) are a different company. Interval excluded.",
    ),
}


def validate_intervals(ret: pd.DataFrame, tol_days: int = 15) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map each membership interval to the price series: an interval is kept only if the symbol's bars cover it
    (first bar <= max(interval start, data start) + tol and last bar >= min(interval end, data end) - tol), i.e.
    the bars belong to the company that was in the index. Partially covered intervals are kept but reported.
    Returns (intervals with keep flag + coverage, coverage-gap report)."""
    m = load_membership()
    d0, d1 = cast(pd.Timestamp, ret.index[0]), cast(pd.Timestamp, ret.index[-1])
    fv, lv = (
        ret.apply(pd.Series.first_valid_index),  # type: ignore[arg-type]  # first valid index is a timestamp
        ret.apply(pd.Series.last_valid_index),  # type: ignore[arg-type]  # last valid index is a timestamp
    )
    rows = []
    for raw in m.itertuples():
        r = cast(Any, raw)  # membership interval cells
        a = max(cast(pd.Timestamp, r.start_date), d0) if pd.notna(r.start_date) else d0
        b = min(cast(pd.Timestamp, r.end_date), d1) if pd.notna(r.end_date) else d1
        if b < d0 or a > d1 or a >= b:
            continue  # interval outside the desk sample
        f, l = cast(pd.Timestamp | None, fv.get(r.symbol)), cast(pd.Timestamp | None, lv.get(r.symbol))
        sess = ret.index[(ret.index >= a) & (ret.index < b)] if pd.notna(r.end_date) else ret.index[ret.index >= a]
        have = ret.loc[sess, r.symbol].notna().sum() if r.symbol in ret.columns else 0
        cov = have / max(len(sess), 1)
        reuse = (
            r.symbol in KNOWN_TICKER_REUSE
            and pd.notna(r.end_date)
            and str(r.end_date.date()) == KNOWN_TICKER_REUSE[r.symbol][0]
        )
        keep = cov > 0 and not reuse
        rows.append(
            {
                "symbol": r.symbol,
                "start": a.date(),
                "end": b.date(),
                "member_sessions": len(sess),
                "sessions_with_bars": int(have),
                "coverage": cov,
                "first_bar": f.date() if f is not None and pd.notna(f) else None,
                "last_bar": l.date() if l is not None and pd.notna(l) else None,
                "keep": bool(keep),
                "note": KNOWN_TICKER_REUSE[r.symbol][1]
                if reuse
                else (
                    ""
                    if cov >= 0.99
                    else (
                        "no bars for this interval"
                        if cov == 0
                        else "partial bar coverage (predecessor ticker history missing / bars start late)"
                    )
                ),
            }
        )
    df = pd.DataFrame(rows)
    return df, df[df.coverage < 0.99]


def pit_mask(
    dates: pd.DatetimeIndex | Sequence[pd.Timestamp],
    symbols: Sequence[str] | pd.Index,
    intervals: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Boolean (dates x symbols): S&P 500 member on that date, intervals [start, end), null start = member since
    before the change log, null end = still a member. Same rule as the data owner's universe.py members_on.
    If `intervals` (from validate_intervals) is given, only kept intervals are used (ticker-reuse guard)."""
    m = load_membership()
    if intervals is not None:
        bad = intervals[~intervals.keep]
        for raw in bad.itertuples():
            r = cast(Any, raw)  # kept-interval cells
            st = pd.Timestamp(r.start)
            m = m[
                ~(
                    (m.symbol == r.symbol)
                    & ((m.end_date.isna() | (m.end_date > st)) & (m.start_date.isna() | (m.start_date <= st)))
                )
            ]
    dates = pd.DatetimeIndex(cast(pd.Index, dates))
    out = pd.DataFrame(False, index=dates, columns=pd.Index(symbols))
    for raw in m.itertuples():
        r = cast(Any, raw)  # membership interval cells
        if r.symbol not in out.columns:
            continue
        ok = np.ones(len(dates), bool)
        if pd.notna(r.start_date):
            ok &= dates >= cast(pd.Timestamp, r.start_date)
        if pd.notna(r.end_date):
            ok &= dates < cast(pd.Timestamp, r.end_date)
        out[r.symbol] |= ok
    return out


def universe() -> pd.DataFrame:
    return pd.read_parquet(UNIV_FILE)


def ff3_daily() -> pd.DataFrame:
    f = pd.read_parquet(FF3_DAILY)
    f["date"] = pd.to_datetime(f["date"].astype(str))
    return f.set_index("date")[["Mkt-RF", "SMB", "HML", "RF"]].astype(float)


# ---------------- live data: ONLY via the desk's shared client (DESK_RULES.md rule #5) ----------------
# History is read from the data owner's store above. The old fallback to statarb/data/daily_bars.json (the stat-arb researcher's IEX file) was
# removed on 2026-10-30; there is no silent fallback any more: if the store is not ready, run_all.py stops.
class _BarsClient(Protocol):
    def get_daily_bars(
        self,
        symbols: list[str],
        start: Any,
        end: Any = ...,
        adjustment: str = ...,
    ) -> pd.DataFrame: ...


def client() -> _BarsClient:
    """The desk's shared Alpaca data client (throttled, cached). Use for any live market-data call."""
    sys.path.insert(0, str(CIO / "data/lib"))
    from quant_research.data.client import desk_data_client as ddc

    return ddc


def live_daily_bars(symbols: Iterable[str], start: Any, end: Any = None, adjustment: str = "all") -> pd.DataFrame:
    """Sessions beyond the store's coverage (or symbols with no local file) via the shared client only."""
    return client().get_daily_bars(list(symbols), start, end, adjustment=adjustment)


def month_ends(idx: pd.DatetimeIndex | Sequence[pd.Timestamp]) -> list[pd.Timestamp]:
    idx = pd.DatetimeIndex(cast(pd.Index, idx))
    s = pd.Series(idx, index=idx)
    return [pd.Timestamp(x) for x in s.groupby([idx.year, idx.month]).max().values]


def load_closes(prefer: str = "store") -> tuple[pd.DataFrame, str]:
    """Legacy (turn-1 backtest.py scripts). Store only; new pipelines use load_panel()."""
    files = list(ADJ_DIR.glob("*.parquet")) if ADJ_DIR.exists() else []
    if not files:
        raise RuntimeError(f"The shared data store was not found at {ADJ_DIR}; no fallback (data-provenance rule).")
    df = pd.concat([pd.read_parquet(f, columns=["symbol", "session_date", "close"]) for f in files])
    df["session_date"] = pd.to_datetime(df["session_date"])
    return df.pivot(index="session_date", columns="symbol", values="close").sort_index(), "dmitri_store_adjusted_sip"
