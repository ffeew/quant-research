"""MXD signal construction (PREREG §3, v0.5 implementation-freeze items). SIGNAL ONLY.

Implements exactly: PIT sector assignment (SPY-residual correlation vs SPDRs with >=240 obs in the trailing 252
sessions), leave-one-out (LOO) equal-weight sector regressor, <5-other-member fallback to the SPDR return,
252-session exposure OLS r_i = a + b_m SPY + b_s SECT_i + sum_k beta_ik r_k, M_k = sum ln(1+r_k) over the last 21
sessions, MXD_i = sum_k beta_ik M_k. Also the signal-only diagnostic MXD rank (LOO) vs MXD rank (SPDR regressor).

Frozen choices (v0.5, written before any return test):
  * window = the 252 sessions ending at the signal date t inclusive (data <= t only; asserted).
  * stock eligibility: >= 240 non-NaN daily total returns in the window.
  * ETF eligibility: >= 240 non-NaN obs in the window (XLC enters mid-2019 by this rule).
  * residualisation: OLS slope on SPY with intercept, pairwise-complete days.
  * correlation: Pearson on pairwise-complete days of the two SPY residual series.
  * TIE-BREAK: highest correlation; exact ties (|diff| <= 1e-12) or NaN-only -> the first ETF in SECT order below;
    a stock with every correlation NaN is unassigned (dropped, counted).
  * LOO: SECT_i,d = mean of r_j,d over other members j of i's cluster on date t with non-NaN r_j,d; days on which
    fewer than 1 other member has data are NaN for that regressor (OLS drops the day).
  * fallback: cluster with < 5 OTHER members (i.e. size < 6) -> SPDR total return as SECT_i (counted).
  * OLS: rows with any NaN dropped; requires >= 240 complete rows else the stock gets no signal (counted).
Inputs: R = DataFrame of daily total returns (ret_total_best), index = sessions, columns = symbols, containing the
stocks, SPY, the SPDRs and TLT/UUP/USO/GLD. No forward data is used or accepted.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import numpy as np
import pandas as pd

MAC = ["TLT", "UUP", "USO", "GLD"]
SECT = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]
WIN, MIN_OBS, M_WIN, MIN_OTHERS = 252, 240, 21, 5
TIE_EPS = 1e-12


def _spy_resid(W: pd.DataFrame, spy: pd.Series) -> pd.DataFrame:
    out = {}
    for c in W.columns:
        df = pd.concat([W[c], spy], axis=1).dropna()
        if len(df) < 2:
            out[c] = W[c] * np.nan
            continue
        x, y = cast(np.ndarray, df.iloc[:, 1].values), cast(np.ndarray, df.iloc[:, 0].values)
        b = np.cov(y, x, ddof=1)[0, 1] / np.var(x, ddof=1)
        a = y.mean() - b * x.mean()
        out[c] = W[c] - (a + b * spy)
    return pd.DataFrame(out, index=W.index)


def assign_sectors(R: pd.DataFrame, t: pd.Timestamp, stocks: Sequence[str]) -> tuple[pd.Series, dict[str, Any]]:
    i = cast(int, R.index.get_loc(t))
    assert i + 1 >= WIN, "insufficient history"
    W = R.iloc[i - WIN + 1 : i + 1]
    assert W.index.max() <= t
    spy = W["SPY"]
    etfs = [e for e in SECT if e in W.columns and W[e].notna().sum() >= MIN_OBS]
    stocks = [s for s in stocks if s in W.columns and W[s].notna().sum() >= MIN_OBS]
    re_ = _spy_resid(W[etfs], spy)
    rs = _spy_resid(W[stocks], spy)
    sec, unassigned = {}, 0
    for s in stocks:
        cors = np.array([rs[s].corr(re_[e]) for e in etfs], dtype=float)
        if np.all(np.isnan(cors)):
            unassigned += 1
            continue
        mx = np.nanmax(cors)
        j = int(np.where(np.abs(cors - mx) <= TIE_EPS)[0][0])  # first in SECT order among ties
        sec[s] = etfs[j]
    return pd.Series(sec, name="sector"), {"eligible_etfs": etfs, "n_stocks": len(stocks), "unassigned": unassigned}


def loo_sector_regressor(W: pd.DataFrame, sectors: pd.Series) -> tuple[pd.DataFrame, dict[str, Any]]:
    out: dict[str, pd.Series] = {}
    fallback: list[str] = []
    for e, member_index in sectors.groupby(sectors).groups.items():
        members = list(member_index)
        X = W[members]
        ssum, scnt = X.sum(axis=1, min_count=1).fillna(0.0), X.notna().sum(axis=1)
        for s in members:
            if len(members) - 1 < MIN_OTHERS:
                out[s] = W[e]
                fallback.append(s)
                continue
            own = X[s]
            num = ssum - own.fillna(0.0)
            den = scnt - own.notna().astype(int)
            out[s] = (num / den.where(den > 0)).where(den > 0)
    return pd.DataFrame(out, index=W.index), {"fallback_spdr": sorted(fallback), "n_fallback": len(fallback)}


def mxd_signal(
    R: pd.DataFrame, t: pd.Timestamp, stocks: Sequence[str], regressor: str = "loo"
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """regressor: 'loo' (primary, Victor) or 'spdr' (diagnostic only)."""
    assert regressor in ("loo", "spdr")
    sectors, info = assign_sectors(R, t, stocks)
    i = cast(int, R.index.get_loc(t))
    W = R.iloc[i - WIN + 1 : i + 1]
    if regressor == "loo":
        S, finfo = loo_sector_regressor(W, sectors)
    else:
        S = pd.DataFrame({s: W[e] for s, e in sectors.items()}, index=W.index)
        finfo = {"n_fallback": 0}
    M = cast(pd.DataFrame, np.log1p(W[MAC].iloc[-M_WIN:])).sum(min_count=M_WIN)
    rows, short = [], 0
    for s, e in sectors.items():
        X = pd.concat([W[s].rename("y"), W["SPY"].rename("spy"), S[s].rename("sect"), W[MAC]], axis=1).dropna()
        if len(X) < MIN_OBS or M.isna().any():
            short += 1
            continue
        A = np.column_stack([np.ones(len(X)), cast(np.ndarray, X[["spy", "sect", *MAC]].values)])
        b = np.linalg.lstsq(A, cast(np.ndarray, X.y.values), rcond=None)[0]
        beta = b[3:]
        rows.append(
            dict(
                symbol=s,
                sector=e,
                mxd=float(beta @ cast(np.ndarray, M.values)),
                **{f"beta_{k}": float(v) for k, v in zip(MAC, beta)},
                b_spy=float(b[1]),
                b_sect=float(b[2]),
                n_obs=int(len(X)),
            )
        )
    df = pd.DataFrame(rows)
    info.update(finfo)
    info.update(n_signal=int(len(df)), n_short_ols=short, signal_date=str(pd.Timestamp(t).date()), regressor=regressor)
    return df, info


def rank_diagnostic(
    R: pd.DataFrame, t: pd.Timestamp, stocks: Sequence[str], focus: Sequence[str] | None = None
) -> pd.DataFrame:
    """Signal-only: MXD percentile rank with LOO vs SPDR regressor. `focus` = names to report (PREREG: the 10
    largest-weight SPDR constituents; constituent weights are NOT in v1.3 -> caller must supply a pinned list)."""
    a, _ = mxd_signal(R, t, stocks, "loo")
    b, _ = mxd_signal(R, t, stocks, "spdr")
    m = a[["symbol", "sector", "mxd"]].merge(b[["symbol", "mxd"]], on="symbol", suffixes=("_loo", "_spdr"))
    m["rank_loo"] = m.mxd_loo.rank(pct=True)
    m["rank_spdr"] = m.mxd_spdr.rank(pct=True)
    m["rank_change"] = m.rank_loo - m.rank_spdr
    return m if focus is None else m[m.symbol.isin(focus)]
