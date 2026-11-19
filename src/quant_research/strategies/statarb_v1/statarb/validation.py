"""Validation statistics per $QR_DESK_DIR/validation/STANDARD.md v1.0.
- nw_t: Newey-West (HAC) t-stat of mean daily return.
- dsr: Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014, eq. 1-2), per-period (daily) SR units;
  SR0 = sqrt(V[SR_trials]) * ((1-g)*Z^-1(1-1/N) + g*Z^-1(1-1/(N e))), g = Euler-Mascheroni.
- pbo_cscv: Probability of Backtest Overfitting via CSCV (Bailey, Borwein, Lopez de Prado, Zhu 2017), S blocks.
- factor_regression: daily strategy returns on FF3 + Mom + ST_Rev (Ken French daily, decimals), HAC t-stats."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import kurtosis, norm, skew

from .data import CIO

EULER = 0.5772156649015329


def nw_t(r: pd.Series | np.ndarray, lags: int | None = None) -> float:
    r = pd.Series(r).dropna()
    if len(r) < 30 or r.std() == 0:
        return np.nan
    lags = lags if lags is not None else int(4 * (len(r) / 100) ** (2 / 9))
    m = sm.OLS(r.values, np.ones(len(r))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(m.tvalues[0])


def expected_max_sr(var_sr: float, n: int) -> float:
    if n <= 1:
        return 0.0
    return float(np.sqrt(var_sr) * ((1 - EULER) * norm.ppf(1 - 1 / n) + EULER * norm.ppf(1 - 1 / (n * np.e))))


def dsr(r: pd.Series | np.ndarray, sr0: float) -> dict[str, Any]:
    r = pd.Series(r).dropna()
    T = len(r)
    sr = r.mean() / r.std()
    g3 = skew(r)
    g4 = kurtosis(r, fisher=False)
    den = np.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    return {
        "DSR": float(norm.cdf((sr - sr0) * np.sqrt(T - 1) / den)),
        "SR_daily": float(sr),
        "SR0_daily": float(sr0),
        "T": T,
        "skew": float(g3),
        "kurtosis": float(g4),
    }


def pbo_cscv(M: pd.DataFrame, S: int = 16) -> dict[str, Any]:
    """M: T x N matrix of (net) daily returns of all trials on a common date range. Returns PBO and logits."""
    M = M.dropna(how="any")
    T, N = M.shape
    if N < 2:
        return {"PBO": np.nan, "n_combinations": 0, "N": N}
    blocks = np.array_split(np.arange(T - T % S), S)
    X = cast(np.ndarray, M.values)
    logits: list[float] = []
    for comb in itertools.combinations(range(S), S // 2):
        tr = np.concatenate([blocks[i] for i in comb])
        te = np.concatenate([blocks[i] for i in range(S) if i not in comb])
        sr_tr = X[tr].mean(0) / X[tr].std(0)
        sr_te = X[te].mean(0) / X[te].std(0)
        best = np.nanargmax(sr_tr)
        rank = (np.argsort(np.argsort(sr_te))[best] + 1) / (N + 1)  # relative rank in (0,1)
        logits.append(float(np.log(rank / (1 - rank))))
    lam = np.array(logits)
    return {
        "PBO": float((lam <= 0).mean()),
        "n_combinations": len(lam),
        "N": N,
        "T": T,
        "median_logit": float(np.median(lam)),
    }


def load_ff_daily() -> pd.DataFrame:
    out = []
    for f, cols in [
        ("ff3_daily", ["Mkt-RF", "SMB", "HML", "RF"]),
        ("mom_daily", ["Mom"]),
        ("st_rev_daily", ["ST_Rev"]),
    ]:
        d = pd.read_parquet(CIO / "factors" / "ken_french" / f"{f}.parquet")
        d["date"] = pd.to_datetime(d["date"].astype(str), format="mixed")
        out.append(d.set_index("date")[cols])
    return pd.concat(out, axis=1).dropna()


def factor_regression(
    r: pd.Series,
    ff: pd.DataFrame,
    cols: Sequence[str] = ("Mkt-RF", "SMB", "HML", "Mom", "ST_Rev"),
) -> dict[str, Any]:
    x = ff[list(cols)].reindex(r.index)
    d = pd.concat([r.rename("r"), x], axis=1).dropna()
    if len(d) < 60:
        return {}
    lags = int(4 * (len(d) / 100) ** (2 / 9))
    m = sm.OLS(d["r"], sm.add_constant(d[list(cols)])).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    out = {
        "alpha_ann": float(m.params["const"] * 252),
        "alpha_t": float(m.tvalues["const"]),
        "r2": float(m.rsquared),
        "n": len(d),
    }
    for c in cols:
        out[f"b_{c}"] = float(m.params[c])
        out[f"t_{c}"] = float(m.tvalues[c])
    return out
