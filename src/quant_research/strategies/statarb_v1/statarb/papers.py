"""Paper-replication hooks (first-pass, simplified). Same panel/backtest/cost plumbing as the desk strategies, so a
rerun on adjusted or total-return bars is a single config change (config.PRICE_SET).

avellaneda_lee: Avellaneda & Lee (2010) "Statistical arbitrage in the US equities market". Daily. Factors = PCA
  eigenportfolios (k, from trailing 252d correlation, re-estimated monthly here; AL re-estimate daily) or the
  stock's sector ETF. 60d OLS of returns on factors -> residual cumulative X -> AR(1)/OU fit -> s-score
  (centered: m_i - mean m). Bang-bang rules: open long s<-1.25, close long s>-0.5, open short s>1.25, close
  short s<0.75; only names with kappa > 252/30. Equal $ per open position; factor exposure removed (PCA: project
  weights orthogonal to [1, B]; ETF: hedge with sector ETFs). Gross = 1.
blitz_ff3: Blitz, Huij, Lansdorp & Verbeek (2013) "Short-term residual reversal". Monthly. FF3 regression of
  monthly excess returns over trailing 36 months (incl. current), signal = last-month residual / residual sd;
  long bottom decile, short top decile, equal weight, hold one month (drifting). Uses Ken French FF3 monthly
  factors from $QR_DATA_DIR/factors (note: in live trading FF factors are published with a lag)."""
import numpy as np
import pandas as pd
from .data import SECTOR_ETF, CIO


def _pca_loadings(R, mem, adv, dates, k, est_win=252, min_adv=2e7):
    """Monthly PCA: returns dict month_end_index -> (symbols, Q eigenportfolio weights n x k)."""
    out = {}
    month_ends = pd.Series(dates, index=dates).groupby(dates.to_period("M")).last().values
    for me in month_ends:
        i = dates.get_loc(me)
        if i < est_win:
            continue
        win = R.iloc[i - est_win + 1:i + 1]
        ok = win.notna().all() & mem.iloc[i] & (adv.iloc[i] >= min_adv)
        S = ok[ok].index
        X = win[S].values
        sd = X.std(0, ddof=1)
        C = np.corrcoef((X - X.mean(0)) / sd, rowvar=False)
        ev, V = np.linalg.eigh(C)
        out[i] = (S, V[:, ::-1][:, :k] / sd[:, None])
    return out


def al_scores(panel, factors="pca", k=15, win=60, min_kappa=252 / 30, min_adv=2e7):
    """Daily AL s-scores (centered) and factor betas. Returns (S, B): S dates x names (NaN = no valid model),
    B: for 'etf' a dates x names DataFrame of beta to the hedge ETF; for 'pca' dict date -> (names, n x k loadings)."""
    R = panel.ret_cc
    mem = panel.member
    adv = panel.dollar_vol.rolling(60, min_periods=40).median()
    dates = R.index
    etf_r = panel.etf_close.pct_change(fill_method=None)
    S = pd.DataFrame(np.nan, index=dates, columns=R.columns)
    Bdf = pd.DataFrame(np.nan, index=dates, columns=R.columns) if factors == "etf" else {}
    pca = _pca_loadings(R, mem, adv, dates, k) if factors == "pca" else None
    pca_keys = sorted(pca) if pca else []
    for t in range(max(win, 253), len(dates)):
        if factors == "pca":
            j = [m for m in pca_keys if m < t]
            if not j:
                continue
            Sm, Q = pca[j[-1]]
            Rw = R.iloc[t - win + 1:t + 1][Sm]
            ok = Rw.notna().all() & mem.iloc[t][Sm] & (adv.iloc[t][Sm] >= min_adv)
            Sx = Sm[ok.values]
            Fw = Rw.fillna(0.0).values @ Q
            Y = Rw[Sx].values
            A = np.column_stack([np.ones(win), Fw])
            coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
            E = Y - A @ coef
            Bdf[dates[t]] = (Sx, coef[1:].T)
        else:
            Rw = R.iloc[t - win + 1:t + 1]
            ok = Rw.notna().all() & mem.iloc[t] & (adv.iloc[t] >= min_adv)
            Sx = ok[ok].index
            hedge = hedge_etf_map(panel, Sx, t - win + 1)
            F = np.column_stack([etf_r[hedge[s]].iloc[t - win + 1:t + 1].values for s in Sx])
            Y = Rw[Sx].values
            Fm = F - F.mean(0); Ym = Y - Y.mean(0)
            b = (Fm * Ym).sum(0) / (Fm ** 2).sum(0)
            E = Ym - b * Fm
            Bdf.loc[dates[t], Sx] = b
        X = np.cumsum(E, axis=0)
        x0, x1 = X[:-1], X[1:]
        x0m = x0 - x0.mean(0); bb = (x0m * (x1 - x1.mean(0))).sum(0) / (x0m ** 2).sum(0)
        a = x1.mean(0) - bb * x0.mean(0)
        zeta = x1 - a - bb * x0
        valid = (bb > 0) & (bb < 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            kappa = -np.log(np.where(valid, bb, np.nan)) * 252
            m = a / (1 - bb)
            seq = np.sqrt(zeta.var(0, ddof=1) / (1 - bb ** 2))
            mc = m - np.nanmean(np.where(valid, m, np.nan))
            sc = -mc / seq
        S.loc[dates[t], Sx] = np.where(valid & (kappa > min_kappa), sc, np.nan)
    return S, Bdf


def hedge_etf_map(panel, names, t0):
    """Sector SPDR for each name; SPY if the sector ETF has no data at window start t0 (e.g. XLC before 2018-06)."""
    out = {}
    for s in names:
        e = SECTOR_ETF.get(panel.sector.get(s))
        if e is None or e not in panel.etf_close or np.isnan(panel.etf_close[e].iloc[t0]):
            e = "SPY"
        out[s] = e
    return out


def al_weights(panel, S, B, factors="pca", s_open=1.25, s_close_long=0.5, s_close_short=0.75, win=60):
    """Bang-bang AL rules on precomputed s-scores. Long: open s < -s_open, close s > -s_close_long.
    Short: open s > s_open, close s < s_close_short. NaN score -> keep position. Wider bands = higher s_open and/or
    closes nearer/through 0."""
    R = panel.ret_cc; dates = R.index
    cols = list(R.columns) + (list(panel.etf_close.columns) if factors == "etf" else [])
    W = pd.DataFrame(0.0, index=dates, columns=cols)
    Sv = S.values; pos = np.zeros(S.shape[1])
    Bf = B.ffill() if factors == "etf" else None
    live = (panel.member & panel.close.notna()).reindex(columns=S.columns, fill_value=False).values
    colidx = {c: i for i, c in enumerate(cols)}
    for t in range(len(dates)):
        s = Sv[t]
        if np.isnan(s).all() and not pos.any():
            continue
        newp = pos.copy()
        flat, lng, sht = pos == 0, pos > 0, pos < 0
        v = ~np.isnan(s)
        newp[flat & v & (s < -s_open)] = 1.0
        newp[flat & v & (s > s_open)] = -1.0
        newp[lng & v & (s > -s_close_long)] = 0.0
        newp[sht & v & (s < s_close_short)] = 0.0
        newp[~live[t]] = 0.0  # v1 fix: force-exit names that left the index or have no bar (delisting) - no zombie positions
        pos = newp
        if not pos.any():
            continue
        names = S.columns[pos != 0]; x = pos[pos != 0]
        if factors == "pca":
            if dates[t] not in B:
                continue
            Sx, L = B[dates[t]]
            sel = pd.Index(Sx).get_indexer(names)
            keep = sel >= 0
            names, x, L = names[keep], x[keep], L[sel[keep]]
            if len(x) == 0:
                continue
            A2 = np.column_stack([np.ones(len(x)), L])
            x = x - A2 @ np.linalg.lstsq(A2, x, rcond=None)[0]
            W.iloc[t, [colidx[n] for n in names]] = x / np.abs(x).sum()
        else:
            b = Bf.iloc[t][names].fillna(1.0).values
            hm = hedge_etf_map(panel, names, max(t - win + 1, 0))
            h = pd.Series(-x * b, index=names).groupby(pd.Series(hm)).sum()
            tot = np.abs(x).sum() + np.abs(h).sum()
            W.iloc[t, [colidx[n] for n in names]] = x / tot
            for e, hv in h.items():
                W.iloc[t, colidx[e]] += hv / tot
    return W


def avellaneda_lee(panel, factors="pca", k=15, win=60, s_bo=1.25, s_so=1.25, s_bc=0.75, s_sc=0.5, **_):
    """Backward-compatible wrapper (v0 signature)."""
    S, B = al_scores(panel, factors, k, win)
    return al_weights(panel, S, B, factors, s_bo, s_sc, s_bc, win)


def blitz_ff3(panel, est_months=36, min_months=24, decile=0.1, min_adv=2e7):
    ff = pd.read_parquet(CIO / "factors" / "ken_french" / "ff3_monthly.parquet")
    ff["date"] = pd.to_datetime(ff["date"].astype(str), format="mixed")
    ff = ff.set_index(ff["date"].dt.to_period("M"))[["Mkt-RF", "SMB", "HML", "RF"]]
    if ff.abs().max().max() > 1:
        ff = ff / 100.0
    R = panel.ret_cc
    mR = (1 + R.fillna(0.0)).groupby(R.index.to_period("M")).prod() - 1
    mR = mR.where(R.notna().groupby(R.index.to_period("M")).sum() >= 15)
    dates = R.index
    me = pd.Series(dates, index=dates).groupby(dates.to_period("M")).last()
    adv = panel.dollar_vol.rolling(60, min_periods=40).median()
    W = pd.DataFrame(np.nan, index=dates, columns=R.columns)
    W.iloc[:] = np.nan
    first = True
    for per, d in me.items():
        if per not in ff.index:
            continue
        hist = mR.loc[:per].tail(est_months)
        f = ff.reindex(hist.index)
        if f.isna().any().any() or len(hist) < min_months:
            continue
        elig = mem_ok = panel.member.loc[d] & (adv.loc[d] >= min_adv) & (hist.notna().sum() >= min_months) & hist.iloc[-1].notna()
        S = elig[elig].index
        Y = hist[S].sub(f["RF"], axis=0)
        A = np.column_stack([np.ones(len(f)), f[["Mkt-RF", "SMB", "HML"]].values])
        res = {}
        for s in S:
            y = Y[s]; msk = y.notna().values
            coef, *_ = np.linalg.lstsq(A[msk], y.values[msk], rcond=None)
            e = y.values[msk] - A[msk] @ coef
            res[s] = e[-1] / e.std(ddof=1)
        sc = pd.Series(res).dropna()
        n = max(int(len(sc) * decile), 1)
        w = pd.Series(0.0, index=R.columns)
        w[sc.nsmallest(n).index] = 0.5 / n; w[sc.nlargest(n).index] = -0.5 / n
        W.loc[d] = w.values
    return W
