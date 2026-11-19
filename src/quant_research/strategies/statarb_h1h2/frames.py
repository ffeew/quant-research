"""Typed scalar access on unique-indexed float frames (pandas-stubs type these as any scalar)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def iloc_int(index: pd.Index, key: Any) -> int:
    """Integer position of key in a unique index (fails closed on a non-unique index)."""
    pos = index.get_loc(key)
    if not isinstance(pos, (int, np.integer)):
        raise ValueError(f"non-unique index entry {key!r}")
    return int(pos)


def at_float(df: pd.DataFrame, row: Any, col: Any) -> float:
    """Scalar from a float frame (the stubs type .at as any scalar)."""
    v: Any = df.at[row, col]
    return float(v)
