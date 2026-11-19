"""Statistics required by the review's STANDARD.md v1.0 (the derivatives researcher, 2026-10-30). All on DAILY net returns unless noted.
DSR: Bailey & Lopez de Prado (2014) eq. 1-2. PBO: Bailey, Borwein, Lopez de Prado & Zhu (2017) CSCV.
Newey-West HAC with Bartlett kernel, lag = floor(4 (T/100)^(2/9))."""

from __future__ import annotations

import itertools
import math
from statistics import NormalDist
from typing import Any, cast

import numpy as np
import pandas as pd

ND = NormalDist()
EULER = 0.5772156649
DSR_MIN_OBS = 4  # smallest series dsr() accepts: bias-corrected sample kurtosis needs n >= 4


def nw_lag(T: int) -> int:
    return int(math.floor(4 * (T / 100) ** (2 / 9)))


def ols_nw(y: np.ndarray, X: np.ndarray, lag: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and Newey-West standard errors."""
    T = len(y)
    lag = nw_lag(T) if lag is None else lag
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    u = y - X @ b
    Xu = X * u[:, None]
    S = Xu.T @ Xu
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        G = Xu[l:].T @ Xu[:-l]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return b, np.sqrt(np.diag(V))


def basic(r: pd.Series, ppy: int = 252) -> dict[str, Any]:
    r = r.dropna()
    T = len(r)
    if T < 30 or r.std() == 0:
        return {"T": T}
    mu, sd = r.mean(), r.std(ddof=1)
    b, se = ols_nw(cast(np.ndarray, r.values), np.ones((T, 1)))
    eq = (1 + r).cumprod()
    return {
        "start": str(r.index[0].date()),
        "end": str(r.index[-1].date()),
        "T": T,
        "ann_ret": mu * ppy,
        "ann_vol": sd * math.sqrt(ppy),
        "sharpe": mu / sd * math.sqrt(ppy),
        "t_nw": b[0] / se[0],
        "t_iid": mu / sd * math.sqrt(T),
        "max_dd": float(cast(float, (eq / eq.cummax() - 1).min())),
        "skew": float(cast(float, r.skew())),
        "kurt": float(cast(float, r.kurt()) + 3),
    }


def dsr(r: pd.Series, trial_srs_daily: np.ndarray, N: int) -> dict[str, Any]:
    """r: daily returns of the selected strategy; trial_srs_daily: non-annualised Sharpe of the logged trials;
    N: trial count used for the expected-max benchmark.

    Input checks (ValueError; they run first and do not change the arithmetic for valid inputs):
      * N >= 1 (N = 1 means a single trial, benchmark SR0 = 0);
      * after dropping NaNs, r needs at least DSR_MIN_OBS = 4 observations: the bias-corrected sample kurtosis
        used in the denominator is undefined below 4 (skewness below 3, the std below 2), and the formula would
        silently return NaN or a meaningless value;
      * r and trial_srs_daily must be finite (+/-inf would propagate silently)."""
    if not N >= 1:
        raise ValueError(f"dsr: N (trial count) must be >= 1, got {N!r}")
    r = r.dropna()
    T = len(r)
    if T < DSR_MIN_OBS:
        raise ValueError(f"dsr: need at least {DSR_MIN_OBS} non-NaN returns for skew/kurtosis, got {T}")
    if not np.isfinite(r.to_numpy(dtype=float)).all():
        raise ValueError("dsr: returns contain non-finite values")
    if not np.isfinite(np.asarray(trial_srs_daily, dtype=float)).all():
        raise ValueError("dsr: trial_srs_daily contains non-finite values")
    sr = r.mean() / r.std(ddof=1)
    g3, g4 = cast(float, r.skew()), cast(float, r.kurt()) + 3
    V = float(np.var(trial_srs_daily, ddof=1)) if len(trial_srs_daily) > 1 else 0.0
    if N < 2:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(V) * ((1 - EULER) * ND.inv_cdf(1 - 1 / N) + EULER * ND.inv_cdf(1 - 1 / (N * math.e)))
    den = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    z = (sr - sr0) * math.sqrt(T - 1) / den
    return {
        "DSR": ND.cdf(z),
        "SR_daily": sr,
        "SR_ann": sr * math.sqrt(252),
        "SR0_daily": sr0,
        "SR0_ann": sr0 * math.sqrt(252),
        "N": N,
        "T": T,
        "skew": g3,
        "kurt": g4,
        "V_trial_SR_daily": V,
        "n_trial_srs": len(trial_srs_daily),
    }


def pbo_cscv(M: pd.DataFrame, S: int = 16) -> dict[str, Any]:
    M = M.dropna()
    T, N = M.shape
    if N < 2 or T < S * 10:
        return {"PBO": np.nan, "N": N, "T": T, "note": "insufficient"}
    blocks = np.array_split(np.arange(T), S)
    X = M.values
    s1 = np.array([X[b].sum(0) for b in blocks])
    s2 = np.array([(X[b] ** 2).sum(0) for b in blocks])
    n = np.array([len(b) for b in blocks])
    lam_values: list[float] = []
    for comb in itertools.combinations(range(S), S // 2):
        isb = np.zeros(S, bool)
        isb[list(comb)] = True

        def sr(mask: np.ndarray) -> np.ndarray:
            nn = n[mask].sum()
            m1 = s1[mask].sum(0) / nn
            m2 = s2[mask].sum(0) / nn
            return cast(np.ndarray, m1 / np.sqrt(np.maximum(m2 - m1**2, 1e-18)))

        sr_is, sr_oos = sr(isb), sr(~isb)
        best = int(np.argmax(sr_is))
        rank = (sr_oos < sr_oos[best]).sum() + 1  # 1..N (N = best OOS)
        w = rank / (N + 1)
        lam_values.append(math.log(w / (1 - w)))
    lam = np.array(lam_values)
    return {
        "PBO": float((lam <= 0).mean()),
        "N": N,
        "T": T,
        "S": S,
        "n_combos": len(lam),
        "median_logit": float(np.median(lam)),
    }


def alpha_beta(r: pd.Series, mkt_ex: pd.Series, factors: pd.DataFrame | None = None) -> dict[str, Any]:
    d = pd.concat([r.rename("r"), mkt_ex.rename("mkt")], axis=1).dropna()
    X = np.column_stack([np.ones(len(d)), cast(np.ndarray, d.mkt.values)])
    b, se = ols_nw(cast(np.ndarray, d.r.values), X)
    out = {
        "alpha_ann_vs_spy": b[0] * 252,
        "alpha_t_nw_vs_spy": b[0] / se[0],
        "beta_spy": b[1],
        "beta_t_nw": b[1] / se[1],
        "beta_neutral_test": "beta within +/-0.1 and |t|<2"
        if abs(b[1]) <= 0.1 and abs(b[1] / se[1]) < 2
        else "NOT beta-neutral",
    }
    resid = d.r - X @ b
    out["alpha_sharpe_vs_spy"] = (
        (b[0] + resid).mean() / (b[0] + resid).std() * math.sqrt(252) if resid.std() > 0 else np.nan
    )
    if factors is not None:
        f = pd.concat([r.rename("r"), factors], axis=1).dropna()
        Xf = np.column_stack([np.ones(len(f)), cast(np.ndarray, f.drop(columns="r").values)])
        bf, sef = ols_nw(cast(np.ndarray, f.r.values), Xf)
        out["alpha_ann_ff4"] = bf[0] * 252
        out["alpha_t_nw_ff4"] = bf[0] / sef[0]
        for i, c in enumerate(factors.columns, start=1):
            out[f"load_{c}"] = bf[i]
    return out


def regimes(r: pd.Series, spy_ret: pd.Series, vix: pd.Series) -> pd.DataFrame:
    """Regime labels use information up to the previous close (no look-ahead)."""
    spy_idx = (1 + spy_ret.fillna(0)).cumprod()
    above = (spy_idx > spy_idx.rolling(200).mean()).shift(1)
    v = vix.reindex(r.index).ffill().shift(1)
    med = v.median()
    lab = {
        "SPY>200dma": above == True,
        "SPY<200dma": above == False,
        "VIX>median": v > med,
        "VIX<=median": v <= med,
        "VIX>25": v > 25,
        "VIX<=25": v <= 25,
    }
    rows = []
    for k, m in lab.items():
        x = r[m.reindex(r.index).fillna(False).astype(bool)]
        rows.append(
            {
                "regime": k,
                "days": len(x),
                "ann_ret": x.mean() * 252,
                "sharpe": x.mean() / x.std() * math.sqrt(252) if len(x) > 20 and x.std() > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def by_year(r: pd.Series) -> pd.DataFrame:
    g = r.groupby(cast(pd.DatetimeIndex, r.index).year)
    df = pd.DataFrame(
        {
            "ret": g.apply(lambda x: cast(float, (1 + x).prod()) - 1),
            "pnl_sum": g.sum(),
            "sharpe": g.apply(lambda x: x.mean() / x.std() * math.sqrt(252) if x.std() > 0 else np.nan),
            "days": g.size(),
        }
    )
    tot = r.sum()
    df["share_of_total_pnl"] = df.pnl_sum / tot if tot > 0 else np.nan
    return df


def walk_forward(
    cands: dict[str, pd.Series],
    first_test_year: int,
    last_year: int,
    embargo_days: int = 21,
    min_train_days: int = 252,
) -> tuple[pd.Series, pd.DataFrame]:
    """cands: name -> daily net return Series. Expanding train window; test = one calendar year; the selected
    candidate = best train Sharpe; an embargo of `embargo_days` sessions (>= 1 monthly rebalance) is dropped at the
    start of each test year. Returns the concatenated OOS series and the per-fold choices."""
    M = pd.DataFrame(cands)
    oos, folds = [], []
    for y in range(first_test_year, last_year + 1):
        tr = M[M.index < f"{y}-01-01"].dropna(how="all")
        te = M[(M.index >= f"{y}-01-01") & (M.index <= f"{y}-12-31")]
        if len(te) <= embargo_days or len(tr) < min_train_days:
            continue
        te = te.iloc[embargo_days:]
        srs = tr.mean() / tr.std() * math.sqrt(252)
        srs = srs[tr.notna().sum() >= min_train_days]
        if srs.dropna().empty:
            continue
        pick = cast(str, srs.idxmax())
        x = te[pick].dropna()
        oos.append(x)
        folds.append(
            {
                "test_year": y,
                "train_end": str(tr.index[-1].date()),
                "pick": pick,
                "train_sharpe": srs[pick],
                "test_sharpe": x.mean() / x.std() * math.sqrt(252) if x.std() > 0 else np.nan,
                "test_days": len(x),
            }
        )
    s = pd.concat(oos) if oos else pd.Series(dtype=float)
    return s, pd.DataFrame(folds)


# ---------------------------------------------------------------------------------------------------------------
# Shared overfitting guards (Victor). Minimal, dependency-free helpers so every trial uses the same purged CV and
# the same hold-out check instead of re-implementing them per strategy. Code above keeps its original arithmetic.
# ---------------------------------------------------------------------------------------------------------------


class HoldoutViolation(ValueError):
    """Raised when data reaches into a sealed hold-out window."""


def assert_before_holdout(timestamps: Any, holdout_start: Any, who: str = "") -> None:
    """Fail closed unless EVERY timestamp is strictly before `holdout_start`.

    The cutoff is always a parameter (never hard-coded here); a timestamp exactly at the cutoff is already hold-out.
    Missing timestamps (NaT) are rejected because they cannot be shown to be outside the hold-out."""
    cut = pd.Timestamp(holdout_start)
    if pd.isna(cut):
        raise ValueError("holdout_start must be a valid timestamp")
    ts = pd.DatetimeIndex(pd.to_datetime(pd.Index(np.asarray(timestamps).ravel())))
    tag = f"{who}: " if who else ""
    if ts.hasnans:
        raise HoldoutViolation(
            f"{tag}{int(cast(np.ndarray, ts.isna()).sum())} missing timestamp(s); cannot prove they precede {cut}"
        )
    bad = ts >= cut
    if bad.any():
        raise HoldoutViolation(
            f"{tag}{int(bad.sum())} timestamp(s) at or after hold-out start {cut} (first offending {ts[bad].min()})"
        )


def purged_kfold(
    t0: Any, t1: Any, n_splits: int = 5, embargo_pct: float = 0.0, holdout_start: Any = None
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Purged and embargoed K-fold split (Lopez de Prado 2018, Advances in Financial ML, ch. 7).

    t0[i], t1[i]: start and end of observation i's label span (t0 sorted ascending, t1 >= t0).
    Test folds are contiguous blocks of positions that partition 0..T-1 exactly once. For each fold:
      * purge: drop from train every i whose span [t0[i], t1[i]] overlaps [min t0(test), max t1(test)];
      * embargo: also drop the h = ceil(embargo_pct * T) positions immediately after the fold's last position.
    If `holdout_start` is given, every t0 and t1 must be strictly before it (assert_before_holdout).
    Returns a list of (train_positions, test_positions) integer arrays, deterministic given the inputs."""
    a = pd.DatetimeIndex(pd.to_datetime(pd.Index(np.asarray(t0).ravel())))
    b = pd.DatetimeIndex(pd.to_datetime(pd.Index(np.asarray(t1).ravel())))
    T = len(a)
    if len(b) != T:
        raise ValueError("t0 and t1 must have the same length")
    if not isinstance(n_splits, (int, np.integer)) or n_splits < 2 or n_splits > T:
        raise ValueError(f"n_splits must be an int in [2, T={T}], got {n_splits!r}")
    if not (0.0 <= embargo_pct < 1.0):
        raise ValueError(f"embargo_pct must be in [0, 1), got {embargo_pct!r}")
    if a.hasnans or b.hasnans:
        raise ValueError("t0/t1 contain missing timestamps")
    if not a.is_monotonic_increasing:
        raise ValueError("t0 must be sorted ascending")
    if (b < a).any():
        raise ValueError("every label end t1 must be >= its start t0")
    if holdout_start is not None:
        assert_before_holdout(a, holdout_start, "purged_kfold t0")
        assert_before_holdout(b, holdout_start, "purged_kfold t1")
    h = int(math.ceil(embargo_pct * T))
    pos = np.arange(T)
    a_v, b_v = a.asi8, b.asi8
    out: list[tuple[np.ndarray, np.ndarray]] = []
    for test in np.array_split(pos, n_splits):
        lo, hi = a_v[test].min(), b_v[test].max()
        keep = (b_v < lo) | (a_v > hi)  # no overlap with the fold's label span
        keep[test] = False
        keep[test[-1] + 1 : test[-1] + 1 + h] = False  # embargo after the fold
        out.append((pos[keep], test.copy()))
    return out
