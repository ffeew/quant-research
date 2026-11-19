from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy.stats import norm, skew, kurtosis

ANN = 252


def perf(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 20:
        return {}
    mu = r.mean() * ANN; sd = r.std() * math.sqrt(ANN)
    sr = mu / sd if sd > 0 else np.nan
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    yrs = len(r) / ANN
    return {"ann_ret": mu, "ann_vol": sd, "sharpe": sr, "t_stat": sr * math.sqrt(yrs) if sd > 0 else np.nan,
            "cagr": eq.iloc[-1] ** (1 / yrs) - 1, "max_dd": dd.min(), "years": yrs,
            "skew_m": skew(monthly(r)), "start": str(r.index[0].date()), "end": str(r.index[-1].date())}


def monthly(r: pd.Series) -> pd.Series:
    return (1 + r).groupby(r.index.to_period("M")).prod() - 1


def corr_to(r: pd.Series, b: pd.Series) -> dict:
    d = pd.concat([r, b], axis=1).dropna()
    m = pd.concat([monthly(d.iloc[:, 0]), monthly(d.iloc[:, 1])], axis=1)
    return {"corr_daily": d.corr().iloc[0, 1], "corr_monthly": m.corr().iloc[0, 1]}


def sharpe_se(sr_ann: float, r: pd.Series) -> float:
    # Lo (2002)/Mertens non-normal SE of the annualised Sharpe using daily returns
    r = r.dropna(); n = len(r); s = sr_ann / math.sqrt(ANN)
    g3 = skew(r); g4 = kurtosis(r, fisher=False)
    var = (1 + 0.5 * s * s - g3 * s + (g4 - 3) / 4 * s * s) / n
    return math.sqrt(var * ANN)


def deflated_sharpe(sr_ann: float, r: pd.Series, sr_trials_ann: list[float]) -> dict:
    """Bailey & Lopez de Prado (2014) DSR: P(true SR > E[max SR of N null trials])."""
    r = r.dropna(); n = len(r)
    N = len(sr_trials_ann)
    v = np.var(np.array(sr_trials_ann) / math.sqrt(ANN), ddof=1)
    em = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - em) * norm.ppf(1 - 1 / N) + em * norm.ppf(1 - 1 / (N * math.e)))
    s = sr_ann / math.sqrt(ANN)
    g3 = skew(r); g4 = kurtosis(r, fisher=False)
    z = (s - sr0) * math.sqrt(n - 1) / math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s)
    return {"n_trials": N, "sr0_ann": sr0 * math.sqrt(ANN), "dsr": norm.cdf(z), "psr_vs0": norm.cdf(
        s * math.sqrt(n - 1) / math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s))}
