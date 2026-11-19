"""Read helper for earnings/next_earnings_lookup.parquet (built by pipelines/earnings_calendar_pit.py).

    from earnings_lookup import next_earnings, blocks_short
    next_earnings("AAPL", "2026-10-30")      -> dict(next_earnings_date, next_earnings_timing, next_reaction_session, ...)
    blocks_short("AAPL", "2026-10-30", hold_sessions=5) -> True if the next reaction session falls within the next 5 sessions
                                                         (uses next_reaction_session_latest for UNKNOWN timing; conservative)
method: forward_snapshot (point-in-time Nasdaq snapshot) > realized_event (HINDSIGHT: true date, not necessarily known then)
        > estimated_from_history. Filter on method if strict PIT is needed.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import pandas as pd

_P = Path(__file__).resolve().parents[1] / "earnings/next_earnings_lookup.parquet"


@lru_cache(maxsize=1)
def _load() -> pd.DataFrame:
    L = pd.read_parquet(_P)
    L["as_of_date"] = pd.to_datetime(L.as_of_date).dt.date
    return L.set_index(["symbol", "as_of_date"]).sort_index()


def _d(x: str | dt.date | dt.datetime | pd.Timestamp) -> dt.date:
    return x if isinstance(x, dt.date) and not isinstance(x, dt.datetime) else pd.Timestamp(x).date()


def next_earnings(symbol: str, as_of: str | dt.date | dt.datetime | pd.Timestamp) -> dict[str, Any] | None:
    L = _load()
    a = _d(as_of)
    try:
        g = L.loc[symbol]
    except KeyError:
        return None
    g = g[g.index <= a]
    return None if g.empty else cast(dict[str, Any], g.iloc[-1].to_dict())


def blocks_short(symbol: str, as_of: str | dt.date | dt.datetime | pd.Timestamp, hold_sessions: int) -> bool:
    r = next_earnings(symbol, as_of)
    if not r or pd.isna(r.get("sessions_to_reaction")):
        return False
    n = cast(int, r["sessions_to_reaction"])
    lat, rs = r.get("next_reaction_session_latest"), r.get("next_reaction_session")
    if lat is not None and rs is not None and lat != rs:
        n += 1  # UNKNOWN timing: assume the later of the two possible reaction sessions
    return n <= hold_sessions


def table() -> pd.DataFrame:
    return _load().reset_index()
