"""Earnings-event indexing (earliest possible session, blackout windows)."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .splits import MARGIN


def earliest_possible_index(ev: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Map each earnings row to its earliest possible session index.

    Scheduled-only rows are dropped; unknown timing uses min(reaction, announce date);
    fallback / periodic rows are pulled 5 sessions earlier.
    """
    ev = ev[ev.source != "nasdaq_scheduled"].copy()
    ev["d0"] = pd.to_datetime(ev.reaction_session.fillna(ev.first_tradable_session))
    ann = pd.to_datetime(ev.announce_date_et)
    unk = ev.timing_quality.astype(str).str.startswith("unknown")
    fb = (ev.source.astype(str).str.contains("fallback")
          | ev.timing_quality.astype(str).str.startswith("periodic"))
    ev.loc[unk, "d0"] = np.minimum(ev.loc[unk, "d0"], ann[unk])
    ev["_ix"] = np.searchsorted(dates.to_numpy(), ev["d0"].to_numpy().astype("datetime64[ns]"))
    fbm = fb.to_numpy(dtype=bool)
    ev.loc[fbm, "_ix"] = (ev.loc[fbm, "_ix"] - 5).clip(lower=0)
    return ev


def make_evidx(ev: pd.DataFrame) -> dict[str, np.ndarray]:
    return {str(s): np.unique(g["_ix"].to_numpy()) for s, g in ev.groupby("symbol")}


def ev_in(evidx: dict[str, np.ndarray], s: str, a: int, b: int, margin: int = MARGIN) -> bool:
    """True if symbol s has an event index in [a - margin, b + margin]."""
    x = evidx.get(s)
    if x is None:
        return False
    a, b = a - margin, b + margin
    k = np.searchsorted(x, a, side="right")
    return bool(k < len(x) and x[k] <= b)


def covered(evidx: dict[str, np.ndarray], s: str, i: int, lookback: int = 130) -> bool:
    """True if symbol s has an event at or before i within the lookback (calendar coverage)."""
    x = evidx.get(s)
    if x is None:
        return False
    k = np.searchsorted(x, i, side="right")
    return bool(k > 0 and x[k - 1] >= i - lookback)


def boundary_ambiguous(ts: Any) -> bool:
    """Exclude acceptance times within +/-5 min of 09:30, 13:00, 16:00 ET (and missing times)."""
    if ts is None or pd.isna(ts):
        return True
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("America/New_York")
    minutes = t.hour * 60 + t.minute
    return any(abs(minutes - anchor) <= 5 for anchor in (9 * 60 + 30, 13 * 60, 16 * 60))
