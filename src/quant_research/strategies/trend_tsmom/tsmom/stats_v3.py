"""Statistics for PREREG-v3 (STANDARD.md): Newey-West t, DSR (Bailey & Lopez de Prado), PBO via CSCV."""
from __future__ import annotations
import itertools, math
import numpy as np, pandas as pd
from scipy.stats import norm, skew, kurtosis

ANN = 252


def sharpe(r: pd.Series) -> float:
    r = r.dropna(); sd = r.std()
    return float(r.mean() / sd * math.sqrt(ANN)) if sd > 0 else float("nan")


def nw_t(r: pd.Series, lags: int = 21) -> float:
    x = r.dropna().values; T = len(x); mu = x.mean(); e = x - mu
    v = e @ e / T
    for L in range(1, lags + 1):
        v += 2 * (1 - L / (lags + 1)) * (e[L:] @ e[:-L]) / T
    return float(mu / math.sqrt(v / T)) if v > 0 else float("nan")


def perf(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 2:
        return {"days": len(r)}
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1; yrs = len(r) / ANN
    return {"start": str(r.index[0].date()), "end": str(r.index[-1].date()), "days": len(r), "years": yrs,
            "ann_ret": float(r.mean() * ANN), "ann_vol": float(r.std() * math.sqrt(ANN)), "sharpe": sharpe(r),
            "nw_t": nw_t(r), "cum_ret": float(eq.iloc[-1] - 1), "cagr": float(eq.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 else np.nan,
            "max_dd_series": float(dd.min())}


def dsr(sr_ann: float, r: pd.Series, trial_srs_ann, N: int) -> dict:
    r = r.dropna(); n = len(r)
    v = np.var(np.asarray(trial_srs_ann, float) / math.sqrt(ANN), ddof=1); em = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - em) * norm.ppf(1 - 1 / N) + em * norm.ppf(1 - 1 / (N * math.e)))
    s = sr_ann / math.sqrt(ANN); g3 = float(skew(r)); g4 = float(kurtosis(r, fisher=False))
    den = math.sqrt(max(1 - g3 * s + (g4 - 1) / 4 * s * s, 1e-12))
    return {"N": N, "T": n, "sr_ann": sr_ann, "sr0_ann": sr0 * math.sqrt(ANN), "skew": g3, "kurt": g4,
            "dsr": float(norm.cdf((s - sr0) * math.sqrt(n - 1) / den))}


def pbo_cscv(M: pd.DataFrame, S: int = 16) -> dict:
    T = len(M) - len(M) % S; X = M.iloc[:T].values; blocks = np.array_split(np.arange(T), S)
    def sr(a):
        sd = a.std(0, ddof=1); return np.where(sd > 0, a.mean(0) / np.where(sd > 0, sd, 1), -np.inf)
    lam = []; n = X.shape[1]
    for comb in itertools.combinations(range(S), S // 2):
        isx = np.concatenate([blocks[i] for i in comb]); oos = np.concatenate([blocks[i] for i in range(S) if i not in comb])
        best = int(np.argmax(sr(X[isx]))); so = sr(X[oos])
        rank = (so < so[best]).sum() + 0.5 * ((so == so[best]).sum() - 1) + 1
        w = rank / (n + 1); lam.append(math.log(w / (1 - w)))
    lam = np.array(lam)
    return {"S": S, "n_combinations": len(lam), "n_trials": n, "T": T, "pbo": float((lam <= 0).mean()),
            "median_logit": float(np.median(lam))}
