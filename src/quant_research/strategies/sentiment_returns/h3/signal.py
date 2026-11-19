"""Per-name window scores and the weekly qualifying cross-section."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
from scipy import stats as _st

from .config import H3Params
from .weeks import NY

UTC = dt.UTC


def parse_item(
    item: Mapping[str, Any], symbol: str, rel_min: float
) -> tuple[str, tuple[float, float, float, float] | None]:
    """Classify one AV news-feed item for ``symbol``. Returns ``(status, row)`` where row is
    ``(t_utc, t_et, score, relevance)``: the naive ``time_published`` read as UTC and as New York time.
    Status is one of ``kept``, ``unparseable``, ``no_entry``, ``low_rel``."""
    try:
        naive = dt.datetime.strptime(item["time_published"], "%Y%m%dT%H%M%S")
    except Exception:
        return "unparseable", None
    ents = [e for e in item.get("ticker_sentiment", []) if e.get("ticker") == symbol]
    if not ents:
        return "no_entry", None
    try:
        rel = float(ents[0]["relevance_score"])
        s = float(ents[0]["ticker_sentiment_score"])
        if not (np.isfinite(rel) and np.isfinite(s)):
            raise ValueError
    except Exception:
        return "unparseable", None
    if rel < rel_min:
        return "low_rel", None
    return "kept", (naive.replace(tzinfo=UTC).timestamp(), naive.replace(tzinfo=NY).timestamp(), s, rel)


def window_score(items: np.ndarray, reading: str, ws: float, we: float, min_items: int) -> float | None:
    """Relevance-weighted mean score of items with time in ``(ws, we]`` under ``reading`` ("UTC" or "ET").
    ``items`` is an (n, 4) array of ``(t_utc, t_et, score, relevance)``. None if fewer than ``min_items``."""
    a = np.asarray(items, float).reshape(-1, 4)
    col = 0 if reading == "UTC" else 1
    m = (a[:, col] > ws) & (a[:, col] <= we)
    if m.sum() < min_items:
        return None
    return float(np.average(a[m, 2], weights=a[m, 3]))


def cross_section(scores: Mapping[str, float], p: H3Params) -> tuple[bool, dict[str, tuple[float, float]]]:
    """Mid-rank percentile ``u = (rank - 0.5) / n`` per name. Returns ``(scored, {sym: (S, u)})``; a week is scored
    only with at least ``min_names`` qualifying names."""
    names = sorted(scores)
    n = len(names)
    if not n:
        return False, {}
    rk = _st.rankdata([scores[s] for s in names])
    return n >= p.min_names, {s: (float(scores[s]), float((rk[j] - 0.5) / n)) for j, s in enumerate(names)}


def spearman_ic(scores: Mapping[str, float], target: Mapping[str, float], names: Iterable[str]) -> float:
    ns = list(names)
    return float(_st.spearmanr([scores[s] for s in ns], [target[s] for s in ns]).statistic)
