"""Shared helpers: store paths, NYSE sessions, the knowledge-time rule (ET)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

HERE = Path(__file__).resolve().parent
LIVE_STORE = Path(f"{_QR.DATA_DIR}")  # NOT read by the SUE build (live store diverges from v1.3 for xbrl_facts, bars)
RELEASE = LIVE_STORE / "releases" / "v1.3"
RELEASE_TOP_HASH = "d137eea39928ec8d27b4e8ace5266c01bf74a81ca7e6d07a9d84f9a71b6dc13a"
STORE = RELEASE  # 2026-11-06 22:xx: ALL SUE inputs read from the immutable v1.3 pin
ETHAN_EVENTS_DIR = Path(f"{_QR.DESK_DIR}/equity/earnings_events")  # read-only
ETHAN_ADDITIVE = LIVE_STORE / "derived" / "earnings_events_8k202_v1.parquet"  # optional ex99/timestamps only
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
DATA_RELEASE_ID = "v1.3"  # top d137eea3…; SIP methodology settled (Victor 2026-11-06). Ethan v1/v2 not used for any EPS/SUE value (SPEC.md).


def sessions() -> pd.DatetimeIndex:
    """NYSE sessions = SPY raw bar dates in the store (the store's calendar)."""
    s = pd.read_parquet(STORE / "bars/daily/raw/SPY.parquet")
    col = "session_date" if "session_date" in s.columns else s.columns[0]
    return cast(
        pd.DatetimeIndex,
        pd.DatetimeIndex(pd.to_datetime(s[col]).dt.normalize().unique()).sort_values().astype("datetime64[ns]"),
    )


def knowledge_session(ts_et: pd.Series, sess: pd.DatetimeIndex) -> pd.Series:
    """Knowledge-time rule: a timestamp before 09:30 ET counts toward that session (if it is a session),
    otherwise the next session. Input: naive ET timestamps."""
    ts = pd.to_datetime(pd.Series(ts_et), format="mixed").astype("datetime64[ns]")
    day = ts.dt.normalize()
    before_open = (ts - day) < pd.Timedelta(hours=9, minutes=30)
    session_values = cast(np.ndarray, sess.values)
    day_values = cast(np.ndarray, day.values)
    idx_same = np.searchsorted(session_values, day_values, side="left")
    idx_next = np.searchsorted(session_values, day_values, side="right")
    idx = np.where(cast(np.ndarray, before_open.values), idx_same, idx_next)
    out = pd.Series(pd.NaT, index=ts.index, dtype="datetime64[ns]")
    ok = (idx < len(sess)) & cast(np.ndarray, ts.notna().values)
    out[ok] = sess.values[idx[ok]]
    return out


def earnings_path(name: str) -> Path:
    """Prefer v1.3 release pin; fall back to live store (byte-identical for earnings as of 2026-11-06)."""
    cand = RELEASE / "earnings" / name
    assert cand.exists(), cand
    return cand
