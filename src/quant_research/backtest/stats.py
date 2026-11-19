"""Shared performance stats (Dave). Returns are simple periodic returns (decimal)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def perf(r: pd.Series, periods_per_year: int = 12) -> dict[str, Any]:
    r = r.dropna()
    n = len(r)
    if n < 2:
        return {"n": n}
    mu, sd = r.mean(), r.std(ddof=1)
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    return {
        "start": str(r.index[0])[:10],
        "end": str(r.index[-1])[:10],
        "n": n,
        "mean_ann": mu * periods_per_year,
        "vol_ann": sd * np.sqrt(periods_per_year),
        "sharpe_ann": (mu / sd) * np.sqrt(periods_per_year) if sd > 0 else np.nan,
        "t_stat": mu / (sd / np.sqrt(n)) if sd > 0 else np.nan,
        "max_dd": dd.min(),
        "hit_rate": (r > 0).mean(),
    }


def fmt(d: dict[str, Any]) -> str:
    if d.get("n", 0) < 2:
        return f"n={d.get('n', 0)} (insufficient)"
    return (
        f"{d['start']}..{d['end']} n={d['n']} mean={d['mean_ann']:.2%}/yr vol={d['vol_ann']:.2%} "
        f"Sharpe={d['sharpe_ann']:.2f} t={d['t_stat']:.2f} maxDD={d['max_dd']:.1%}"
    )
