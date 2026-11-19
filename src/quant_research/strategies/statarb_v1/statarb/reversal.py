"""Short-horizon residual reversal strategies (dollar-neutral, daily rebalance, gross = 1).
sector_etf_reversal: residual of stock vs its sector factor (sector ETF where it exists, else EW basket of
    PIT sector members), beta from trailing `beta_win` days (past only). Signal = -sum residual over `lookback`
    days, z-scored WITHIN sector -> long/short within sector; residual sector-ETF beta hedged with the ETF.
pca_reversal: Avellaneda-Lee-lite. Each month: PCA (k factors) on trailing 252d standardized returns of PIT
    members, eigenportfolios -> factor returns; per-stock loadings by OLS on the window. Daily residual =
    r - B F. Signal = -sum residual over `lookback` days; weights projected orthogonal to [1, B] (dollar &
    factor neutral), gross = 1. (Full AL s-score/OU version is the next replication task.)"""
import numpy as np
import pandas as pd
from .data import SECTOR_ETF


def _gross1(w):
    g = w.abs().sum(axis=1).replace(0, np.nan)
    return w.div(g, axis=0).fillna(0.0)


def sector_etf_reversal(panel, lookback=5, beta_win=60, min_adv=2e7, hedge_etf=True):
    r = panel.ret_cc
    er = panel.etf_close.pct_change(fill_method=None)
    mem = panel.member
    adv = panel.dollar_vol.rolling(60, min_periods=40).median()
    elig = mem & (adv >= min_adv) & r.notna()
    W = pd.DataFrame(0.0, index=r.index, columns=list(r.columns) + list(er.columns))
    resid = pd.DataFrame(np.nan, index=r.index, columns=r.columns)
    betas = {}
    for sec, etf in SECTOR_ETF.items():
        names = panel.sector[panel.sector == sec].index.intersection(r.columns)
        if len(names) == 0:
            continue
        ew = r[names].where(mem[names]).mean(axis=1)
        f = er[etf] if etf in er else ew
        f = f.where(f.notna(), ew)  # ETF missing (e.g. XLC pre-2018-06) -> EW basket
        use_etf = er[etf].notna() if etf in er else pd.Series(False, index=r.index)
        cov = r[names].rolling(beta_win, min_periods=40).cov(f)
        var = f.rolling(beta_win, min_periods=40).var()
        b = cov.div(var, axis=0)
        resid[names] = r[names] - b.mul(f, axis=0)
        betas[sec] = (names, b, use_etf, etf)
    sig = -resid.rolling(lookback, min_periods=lookback).sum()
    for sec, (names, b, use_etf, etf) in betas.items():
        s = sig[names].where(elig[names])
        z = s.sub(s.mean(axis=1), axis=0).div(s.std(axis=1), axis=0)
        W[names] = z.fillna(0.0)
    tot = W[list(r.columns)].abs().sum(axis=1).replace(0, np.nan)
    W = W.div(tot, axis=0).fillna(0.0)
    if hedge_etf:
        for sec, (names, b, use_etf, etf) in betas.items():
            if etf in W:
                h = -(W[names] * b.fillna(0)).sum(axis=1)
                W[etf] = W[etf] + h.where(use_etf, 0.0)
        W = _gross1(W)
    return W


def pca_reversal(panel, k=5, lookback=5, est_win=252, min_adv=2e7, start=None):
    r = panel.ret_cc
    mem = panel.member
    adv = panel.dollar_vol.rolling(60, min_periods=40).median()
    dates = r.index
    month_ends = pd.Series(dates, index=dates).groupby(dates.to_period("M")).last().values
    W = pd.DataFrame(0.0, index=dates, columns=r.columns)
    resid = pd.DataFrame(np.nan, index=dates, columns=r.columns)
    loads = {}
    for me in month_ends:
        i = dates.get_loc(me)
        if i < est_win:
            continue
        win = r.iloc[i - est_win + 1:i + 1]
        ok = win.notna().all() & mem.iloc[i] & (adv.iloc[i] >= min_adv)
        S = ok[ok].index
        X = win[S].values
        mu, sd = X.mean(0), X.std(0, ddof=1)
        Z = (X - mu) / sd
        C = np.corrcoef(Z, rowvar=False)
        ev, V = np.linalg.eigh(C)
        V = V[:, ::-1][:, :k]
        Q = V / sd[:, None]  # eigenportfolio weights
        F = X @ Q
        A = np.column_stack([np.ones(len(F)), F])
        coef, *_ = np.linalg.lstsq(A, X, rcond=None)
        B = coef[1:].T  # n x k
        nxt = dates[i + 1:i + 1 + 23]
        nxt = nxt[nxt <= (pd.Timestamp(me) + pd.offsets.MonthEnd(1))]
        Rn = r.loc[nxt, S].fillna(0.0).values
        Fn = Rn @ Q
        resid.loc[nxt, S] = Rn - Fn @ B.T
        for d in nxt:
            loads[d] = (S, B)
    sig = -resid.rolling(lookback, min_periods=lookback).sum()
    for d, (S, B) in loads.items():
        s = sig.loc[d, S]
        good = s.notna().values & mem.loc[d, S].values
        if good.sum() < 50:
            continue
        x = s.values[good]; Bg = B[good]
        A = np.column_stack([np.ones(good.sum()), Bg])
        x = x - A @ np.linalg.lstsq(A, x, rcond=None)[0]
        x = x / np.abs(x).sum()
        W.loc[d, S[good]] = x
    return W
