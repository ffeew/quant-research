"""Residual momentum (Blitz, Huij & Martens 2011) on the data owner's SIP total returns, PIT S&P 500. The derivatives researcher, 2026-10-30 (v2).
Codified rules (base params; every number below is a parameter perturbed +/-20% in the sensitivity grid):
  Universe at month-end t: PIT S&P 500 members (membership interval contains t) with a bar on t.
  Fit: OLS with intercept of daily excess returns on FF3 (Mkt-RF, SMB, HML) over (t - fit_months, t - skip_days],
       >= 2/3 of the NOMINAL window's sessions required for every name (24 of 36 months at base, i.e. 504 of 756
       sessions); the window is never silently shortened. Fixed 2026-10-30 02:23 SGT (warm-up bug, see SUBMISSION.md):
       before, min_obs was 2/3 of the window clipped at the data start (2016-01-04) and names with complete (clipped)
       data skipped the check, so in 2016 the fit window equalled the formation window and scores were ~1e-12 noise.
  Formation window must lie entirely inside the data (no clipping).
  Score: residuals (r - a - b'F) over (t - form_months, t - skip_days]; score = sum / std (Blitz et al. eq. 2).
  Comparator: total-return momentum over the same formation window.
  Books: EW quantile `q` (0.20): L/S top-minus-bottom ($1 per leg) and long-only top (excess of rf).
  Rebalance: monthly (last session of month); fill next session's open (engine).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

BASE = {"fit_months": 36, "form_months": 12, "skip_days": 21, "q": 0.20}


class ResMomParams(TypedDict):
    fit_months: int
    form_months: int
    skip_days: int
    q: float


def _scores(
    R: pd.DataFrame, F: pd.DataFrame, t: pd.Timestamp, names: Sequence[str], p: ResMomParams
) -> tuple[pd.Series, pd.Series]:
    idx = R.index
    e = int(idx.searchsorted(t, side="right") - p["skip_days"])
    s_fit = int(idx.searchsorted(t - pd.DateOffset(months=p["fit_months"]), side="right"))
    s_form = int(idx.searchsorted(t - pd.DateOffset(months=p["form_months"]), side="right"))
    empty = (pd.Series(dtype=float), pd.Series(dtype=float))
    if e <= s_form or t - pd.DateOffset(months=p["form_months"]) < idx[0]:
        return empty  # formation window would be clipped at the data start
    nominal = int(round(252 * p["fit_months"] / 12))  # nominal fit-window sessions (756 at base)
    min_obs = int(np.ceil(nominal * 2 / 3))  # 504 at base = 24 of 36 months
    if e - s_fit < min_obs:
        return empty  # not enough history for ANY name yet (warm-up)
    win = idx[s_fit:e]
    Y = R.loc[win, names]
    X = F.reindex(win)
    ok = X.notna().all(axis=1)
    Y, X = Y[ok], X[ok]
    ex = cast(np.ndarray, Y.sub(X["RF"], axis=0).values)
    Xm = np.column_stack([np.ones(len(X)), cast(np.ndarray, X[["Mkt-RF", "SMB", "HML"]].values)])
    w_form = Y.index >= idx[s_form]
    sc: dict[Any, float] = {}
    fin = np.isfinite(ex)
    full = fin.all(axis=0) & (len(ex) >= min_obs)
    # batched OLS for names with complete windows
    if full.any():
        B, *_ = np.linalg.lstsq(Xm, ex[:, full], rcond=None)
        res = ex[:, full] - Xm @ B
        rf_ = res[w_form]
        sd = rf_.std(axis=0, ddof=1)
        cols = np.array(names)[full]
        for j, s in enumerate(cols):
            if sd[j] > 0:
                sc[s] = rf_[:, j].sum() / sd[j]
    for j_raw in np.where(~full)[0]:
        j = int(j_raw)
        m = fin[:, j]
        if m.sum() < min_obs or (m & w_form).sum() < 0.8 * w_form.sum():
            continue
        b, *_ = np.linalg.lstsq(Xm[m], ex[m, j], rcond=None)
        r = (ex[:, j] - Xm @ b)[m & w_form]
        if r.std(ddof=1) > 0:
            sc[names[j]] = r.sum() / r.std(ddof=1)
    Yf = Y[w_form]
    cnt = Yf.notna().sum()
    mom = ((1 + Yf.fillna(0)).prod() - 1)[cnt >= 0.8 * len(Yf)]
    scores = pd.Series(sc)
    return scores, mom.reindex(scores.index).dropna()


def _books(score: pd.Series, q: float) -> tuple[pd.Series, pd.Series]:
    n = max(int(round(len(score) * q)), 1)
    r = score.sort_values()
    lo, hi = r.index[:n], r.index[-n:]
    return pd.concat([pd.Series(1 / n, hi), pd.Series(-1 / n, lo)]), pd.Series(1 / n, hi)


def build_targets(
    panel: dict[str, pd.DataFrame], ctx: dict[str, Any], p: ResMomParams | None = None
) -> dict[str, dict[pd.Timestamp, pd.Series]]:
    p = cast(ResMomParams, {**BASE, **(p or {})})
    R, F = panel["ret"], cast(pd.DataFrame, ctx["ff3"])
    out: dict[str, dict[pd.Timestamp, pd.Series]] = {
        k: {} for k in ["resmom_ls", "resmom_long", "totmom_ls", "totmom_long"]
    }
    for t in ctx["month_ends"]:
        if t > F.index.max() + pd.Timedelta(days=5):
            break
        names = [s for s in ctx["members_at"](t) if s in R.columns]
        sc, mom = _scores(R, F, t, names, p)
        if len(sc) < 100:
            continue
        out["resmom_ls"][t], out["resmom_long"][t] = _books(sc, p["q"])
        out["totmom_ls"][t], out["totmom_long"][t] = _books(mom, p["q"])
    return out
