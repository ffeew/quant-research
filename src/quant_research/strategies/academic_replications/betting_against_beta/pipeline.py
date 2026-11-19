"""BAB / low volatility (Frazzini & Pedersen 2014) on Dmitri's SIP total returns, PIT S&P 500. Dave, 2026-10-30 (v2).
Codified rules (base params; perturbed +/-20% in the sensitivity grid):
  Universe at month-end t: PIT S&P 500 members with a bar on t. Market = SPY total return.
  Beta (FP sec. 3.1): sigma_i, sigma_m = std of daily log returns over vol_days (252, >= 120 obs);
       rho = corr of overlapping 3-day log returns over corr_years (5; >= 750 obs, FP's minimum);
       beta_TS = rho*sigma_i/sigma_m; beta = shrink*beta_TS + (1-shrink)*1 (shrink 0.6).
       (Desk data starts 2016-01 -> the 750-obs minimum delays the first signal to ~2019-01.)
  Books: bab_fp  = rank-weighted legs (w ∝ |rank - mean rank|), each leg levered to ex-ante beta 1:
                   h = wL/beta_L - wH/beta_H (net long, financed at rf; NEEDS LEVERAGE: long leg gross = 1/beta_L);
         bab_q   = EW bottom-q minus top-q beta, dollar-neutral (q = 0.2);
         lowvol_long = EW lowest-q 1y total volatility (vol_days), long-only, excess of rf.
  Rebalance monthly; fill next session's open (engine). Ex-ante book beta and leg leverage are recorded per rebalance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

BASE = {"vol_days": 252, "corr_years": 5, "shrink": 0.6, "q": 0.20}


class BabParams(TypedDict):
    vol_days: int
    corr_years: int
    shrink: float
    q: float


def _betas(LR: pd.DataFrame, t: pd.Timestamp, names: Sequence[str], p: BabParams) -> tuple[pd.Series, pd.Series]:
    idx = LR.index
    e = idx.searchsorted(t, side="right")
    s1 = max(e - p["vol_days"], 0)
    sc = idx.searchsorted(t - pd.DateOffset(months=int(round(12 * p["corr_years"]))), side="right")
    y1 = LR.iloc[s1:e]
    sig, sig_m = y1[names].std(), y1["SPY"].std()
    n1 = y1[names].notna().sum()
    yc = LR.iloc[sc:e]
    r3 = yc.rolling(3, min_periods=3).sum()
    rho = r3[names].corrwith(r3["SPY"])
    nn = yc[names].notna().sum()
    ok = (n1 >= 120) & (nn >= 750)
    beta = (rho * sig / sig_m)[ok].dropna()
    return p["shrink"] * beta + (1 - p["shrink"]), sig[n1 >= 120].dropna()


def build_targets(
    panel: dict[str, pd.DataFrame], ctx: dict[str, Any], p: BabParams | None = None
) -> tuple[dict[str, dict[pd.Timestamp, pd.Series]], pd.DataFrame]:
    p = cast(BabParams, {**BASE, **(p or {})})
    R = panel["ret"]
    LR = cast(pd.DataFrame, np.log1p(R))
    out: dict[str, dict[pd.Timestamp, pd.Series]] = {k: {} for k in ["bab_fp", "bab_q", "lowvol_long"]}
    info: dict[pd.Timestamp, dict[str, float]] = {}
    for t in ctx["month_ends"]:
        mem = [s for s in ctx["members_at"](t) if s in R.columns]
        b, vol = _betas(LR, t, mem, p)
        if len(vol) >= 100:
            n = max(int(round(len(vol) * p["q"])), 1)
            lo = vol.sort_values().index[:n]
            out["lowvol_long"][t] = pd.Series(1 / n, lo)
        if len(b) < 100:
            continue
        z = b.rank()
        d = z - z.mean()
        wH = d.clip(lower=0)
        wH /= wH.sum()
        wL = (-d).clip(lower=0)
        wL /= wL.sum()
        bL, bH = float((wL * b).sum()), float((wH * b).sum())
        out["bab_fp"][t] = (wL / bL).sub(wH / bH, fill_value=0)
        n = max(int(round(len(b) * p["q"])), 1)
        r = b.sort_values()
        lo, hi = r.index[:n], r.index[-n:]
        out["bab_q"][t] = pd.concat([pd.Series(1 / n, lo), pd.Series(-1 / n, hi)])
        lv = out["lowvol_long"].get(t)
        info[t] = {
            "beta_L": bL,
            "beta_H": bH,
            "lev_long_leg": 1 / bL,
            "lev_short_leg": 1 / bH,
            "fp_gross": 1 / bL + 1 / bH,
            "fp_net": 1 / bL - 1 / bH,
            "fp_exante_beta": float((out["bab_fp"][t] * b.reindex(out["bab_fp"][t].index)).sum()),
            "q_exante_beta": float(b.reindex(lo).mean() - b.reindex(hi).mean()),
            "lowvol_exante_beta": float(b.reindex(lv.index).mean()) if lv is not None else np.nan,
        }
    return out, pd.DataFrame(info).T
