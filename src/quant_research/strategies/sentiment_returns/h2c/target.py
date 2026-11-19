"""Return panel, rolling beta and beta-adjusted forward return."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from .errors import PartitionError, SchemaError


@dataclass
class ReturnPanel:
    sessions: list[str]
    symbols: list[str]
    returns: np.ndarray  # simple returns, row i = sessions[i-1] -> sessions[i]; row 0 NaN

    @property
    def index(self) -> dict[str, int]:
        return {d: i for i, d in enumerate(self.sessions)}

    @property
    def col(self) -> dict[str, int]:
        return {s: j for j, s in enumerate(self.symbols)}


def build_return_panel(rows: Iterable[dict[str, Any]], sessions: Sequence[str], symbols: Sequence[str]) -> ReturnPanel:
    """``rows``: {symbol, date, adjusted_close}. Every date must be one of ``sessions`` (the partition's price
    sessions); duplicates and unknown symbols are refused."""
    sess = list(sessions)
    sidx = {d: i for i, d in enumerate(sess)}
    col = {s: j for j, s in enumerate(symbols)}
    A = np.full((len(sess), len(col)), np.nan)
    seen: set[tuple[str, str]] = set()
    for x in rows:
        d, s = x["date"], x["symbol"]
        if d not in sidx:
            raise PartitionError(f"price date not a partition session: {d}")
        if s not in col:
            raise SchemaError(f"unknown price symbol {s}")
        if (s, d) in seen:
            raise SchemaError(f"duplicate price {s} {d}")
        seen.add((s, d))
        A[sidx[d], col[s]] = float(x["adjusted_close"])
    r = np.full_like(A, np.nan)
    r[1:] = A[1:] / A[:-1] - 1.0
    return ReturnPanel(sess, list(symbols), r)


def beta_adjusted_target(
    panel: ReturnPanel, sym: str, hedge: str, day0: str, beta_n: int, h0: int, h1: int
) -> tuple[str, float, float, float]:
    """Beta over the ``beta_n`` returns ending the session before ``day0``; compounded return over sessions
    (day0+h0, day0+h1]. Returns (status, beta, raw return, raw - beta * hedge return); status '' when OK."""
    nan = float("nan")
    sidx = panel.index
    if day0 not in sidx:
        return "excl_missing_target", nan, nan, nan
    i0 = sidx[day0]
    if i0 - beta_n < 1:
        return "excl_beta_warmup", nan, nan, nan
    c = panel.col
    j, m = c[sym], c[hedge]
    r = panel.returns
    x, y = r[i0 - beta_n : i0, m], r[i0 - beta_n : i0, j]
    if i0 + h1 >= len(panel.sessions) or not (np.isfinite(x).all() and np.isfinite(y).all()):
        return "excl_missing_target", nan, nan, nan
    bta = float(np.cov(y, x, ddof=1)[0, 1] / np.var(x, ddof=1))
    g = np.prod(1 + r[i0 + h0 + 1 : i0 + h1 + 1], axis=0) - 1
    if not (np.isfinite(g[j]) and np.isfinite(g[m])):
        return "excl_missing_target", nan, nan, nan
    return "", bta, float(g[j]), float(g[j] - bta * g[m])
