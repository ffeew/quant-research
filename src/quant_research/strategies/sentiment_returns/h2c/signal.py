"""Call tone and tone surprise."""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np


def call_tone(entries: Sequence[dict[str, Any]], tone_min: int) -> tuple[int, float]:
    """Mean of the finite, parseable per-entry ``sentiment`` values. Returns (n_parseable, tone); tone is NaN
    when fewer than ``tone_min`` entries parse."""
    v: list[float] = []
    for ent in entries:
        try:
            raw = ent.get("sentiment")
            if raw is None:  # float(None) raises TypeError; same skip as below
                continue
            f = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            v.append(f)
    return len(v), (float(np.mean(v)) if len(v) >= tone_min else float("nan"))


def tone_surprise(
    tone: float, prior: Sequence[dict[str, Any]], day0: str, nprior_max: int, nprior_min: int
) -> tuple[int, float]:
    """Tone minus the mean tone of the last ``nprior_max`` prior calls with strictly earlier ``day0``
    (ties ordered by label). NaN unless at least ``nprior_min`` priors and a finite tone."""
    pr = sorted([p for p in prior if p["day0"] < day0], key=lambda p: (p["day0"], p["label"]))[-nprior_max:]
    ok = len(pr) >= nprior_min and math.isfinite(tone)
    return len(pr), (tone - float(np.mean([p["tone"] for p in pr])) if ok else float("nan"))
