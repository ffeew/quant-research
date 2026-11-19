"""Load REAL price data from the desk bar store ($QR_DATA_DIR). No simulated prices.

Price source priority per ETF (recorded in the returned `sources` dict):
  1. total_return/daily_total_return.parquet  tr_index_best  (desk-validated total return, splits+divs)
  2. bars/daily/adjusted/<SYM>.parquet        close          (Alpaca adjustment=all: split+dividend back-adjusted)
  3. bars/daily/raw/<SYM>.parquet             close          (AS TRADED: no dividends -> understates bond/equity ETF returns; flagged)
Crypto: EXCLUDED by desk decision (30 Oct 2026); this sleeve is ETFs only.
Risk-free: Ken French daily RF (ff3_daily), forward-filled past its last date (flagged).
"""
from __future__ import annotations
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import os
import numpy as np
import pandas as pd

ROOT = f"{_QR.DATA_DIR}"
BARS = f"{ROOT}/bars/daily"

ASSET_CLASS = {
    # equity indices
    **{s: "equity" for s in "SPY QQQ IWM DIA EFA EWJ EWG EWU EEM EWZ FXI INDA EWY EWT EWA EWC".split()},
    # rates / credit
    **{s: "rates" for s in "SHY IEF TLT BWX AGG BND TIP LQD HYG".split()},
    # commodities
    **{s: "commodity" for s in "GLD SLV USO UNG CPER DBA DBC".split()},
    # FX
    **{s: "fx" for s in "UUP FXE FXY FXB FXA FXC FXF".split()},
}

# Universe from the TSMOM paper card (pre-specified before any backtest was run).
CARD_UNIVERSE = ("SPY QQQ IWM EFA EWJ EWG EWU EEM SHY IEF TLT BWX GLD SLV USO UNG CPER DBA DBC "
                 "UUP FXE FXY FXB FXA FXC").split()   # crypto (BTC/ETH) excluded by desk decision
# Extended (robustness): card + other liquid country/credit ETFs the Data Engineer loaded.
EXT_EXTRA = "EWZ FXI INDA EWY EWT EWA EWC AGG BND TIP LQD HYG".split()
CRYPTO: list[str] = []   # crypto excluded by desk decision (30 Oct 2026); kept empty for engine compatibility


def _tr_index() -> pd.DataFrame:
    p = f"{BARS}/total_return/daily_total_return.parquet"
    d = pd.read_parquet(p, columns=["symbol", "session_date", "tr_index_best"])
    return d


def load_etf(sym: str, tr: pd.DataFrame | None = None) -> tuple[pd.DataFrame | None, str]:
    """Return (frame with columns px [return index], close_raw, volume_raw), source label)."""
    raw_p = f"{BARS}/raw/{sym}.parquet"
    if not os.path.exists(raw_p):
        return None, "MISSING"
    raw = pd.read_parquet(raw_p, columns=["session_date", "close", "volume"])
    raw["session_date"] = pd.to_datetime(raw["session_date"])
    raw = raw.set_index("session_date").rename(columns={"close": "close_raw", "volume": "volume_raw"})
    src = None
    if tr is not None:
        t = tr[tr.symbol == sym]
        if len(t):
            t = t.assign(session_date=pd.to_datetime(t.session_date)).set_index("session_date")["tr_index_best"]
            raw["px"] = t
            src = "total_return(tr_index_best)"
    if src is None:
        adj_p = f"{BARS}/adjusted/{sym}.parquet"
        if os.path.exists(adj_p):
            a = pd.read_parquet(adj_p, columns=["session_date", "close"])
            a["session_date"] = pd.to_datetime(a["session_date"])
            raw["px"] = a.set_index("session_date")["close"]
            src = "adjusted(alpaca adjustment=all)"
        else:
            raw["px"] = raw["close_raw"]
            src = "RAW(as traded, no dividends)"
    return raw, src


def load_rf() -> tuple[pd.Series, str]:
    d = pd.read_parquet(f"{ROOT}/factors/ken_french/ff3_daily.parquet")
    # find date + RF columns robustly
    if "RF" not in d.columns:
        raise ValueError("RF column missing in ff3_daily")
    if not isinstance(d.index, pd.DatetimeIndex):
        dc = [c for c in d.columns if "date" in c.lower()]
        d = d.set_index(pd.to_datetime(d[dc[0]]))
    rf = d["RF"].astype(float)
    if rf.abs().max() > 0.01:  # KF publishes percent
        rf = rf / 100.0
    return rf.sort_index(), str(rf.index.max().date())


def load_shortable() -> dict[str, bool]:
    a = pd.read_parquet(f"{ROOT}/assets/snapshots/assets_2026-10-29.parquet",
                        columns=["symbol", "shortable", "easy_to_borrow"])
    return {r.symbol: bool(r.shortable and r.easy_to_borrow) for r in a.itertuples()}


def build_panel(symbols: list[str]):
    """Return dict with daily session-indexed frames: px (return index), close_raw, volume_raw, rf, sources."""
    tr = _tr_index()
    px, cl, vo, sources = {}, {}, {}, {}
    for s in symbols:
        f, src = load_etf(s, tr)
        sources[s] = src
        if f is None:
            continue
        px[s], cl[s], vo[s] = f["px"], f["close_raw"], f["volume_raw"]
    sessions = pd.DatetimeIndex(sorted(set().union(*[v.index for v in px.values()])))
    P = pd.DataFrame(px).reindex(sessions)
    C = pd.DataFrame(cl).reindex(sessions)
    V = pd.DataFrame(vo).reindex(sessions)
    rf, rf_last = load_rf()
    rf_s = rf.reindex(sessions).ffill()
    return {"px": P, "close_raw": C, "volume_raw": V, "rf": rf_s, "rf_last": rf_last, "sources": sources}
