"""Cointegrated pairs (Engle-Granger), within-sector, rolling formation/trading (GGR-style schedule).
Every `trade_len` sessions: formation = previous `form_len` sessions; candidates = PIT S&P members on the
formation end date with complete prices in the window and trailing $ADV >= min_adv. EG: OLS log(y) on log(x),
ADF(lag=1, const) on residual, MacKinnon p-value (N=2). Both orderings tested, best kept per unordered pair.
Multiple testing: Benjamini-Hochberg FDR (q) over ALL pairs tested in that formation; plus half-life filter,
hedge-ratio bounds (beta in [1/3,3]) and max 2 selected pairs per stock (avoid one-stock concentration).
Trading: z from formation mean/sd of the spread (fixed, no re-estimation); enter |z|>z_in, exit |z|<z_out,
stop-loss at |z|>z_stop, forced close at end of trading window or if a leg loses PIT membership/prices. Decision at close t.
Capital: K slots, each pair gets 1/K gross (|w_y|+|w_x| = 1/K) -> returns on committed capital."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
from statsmodels.tsa.adfvalues import mackinnonp

from .data import Panel


def eg_batch(
    Y: np.ndarray, X: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Y, X: (T, P) log-price arrays. Returns beta, alpha, adf t-stat, residual sd, half-life (days)."""
    _T = Y.shape[0]
    xm, ym = X.mean(0), Y.mean(0)
    beta = ((X - xm) * (Y - ym)).sum(0) / ((X - xm) ** 2).sum(0)
    alpha = ym - beta * xm
    e = Y - alpha - beta * X
    de = np.diff(e, axis=0)
    y_ = de[1:]
    l1 = e[1:-1]
    d1 = de[:-1]
    n = y_.shape[0]
    # regress y_ on [1, l1, d1] per column via normal equations
    P = Y.shape[1]
    tstat = np.empty(P)
    gam = np.empty(P)
    for j in range(P):
        A = np.column_stack([np.ones(n), l1[:, j], d1[:, j]])
        coef, _res, *_ = np.linalg.lstsq(A, y_[:, j], rcond=None)
        resid = y_[:, j] - A @ coef
        s2 = resid @ resid / (n - 3)
        cov = s2 * np.linalg.inv(A.T @ A)
        gam[j] = coef[1]
        tstat[j] = coef[1] / np.sqrt(cov[1, 1])
    # half-life from AR(1) on e
    phi = (e[1:] * e[:-1]).sum(0) / (e[:-1] ** 2).sum(0)  # e is mean ~0
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = -np.log(2) / np.log(np.clip(phi, 1e-9, None))
    return beta, alpha, tstat, e.std(0, ddof=1), e.mean(0), hl


def bh(p: np.ndarray, q: float) -> np.ndarray:
    p = np.asarray(p)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    thr = q * np.arange(1, m + 1) / m
    passed = ranked <= thr
    k = np.max(np.where(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(m, bool)
    out[order[:k]] = True
    return out


def form_pairs(
    panel: Panel,
    end_idx: int,
    form_len: int = 252,
    min_adv: float = 2e7,
    q: float = 0.05,
    hl_range: tuple[float, float] = (1, 63),
    top_k: int = 20,
    beta_range: tuple[float, float] = (1 / 3, 3),
    max_per_stock: int = 2,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    c = panel.px_clean
    win = c.iloc[end_idx - form_len + 1 : end_idx + 1]
    mem = panel.member.iloc[end_idx]
    adv = panel.dollar_vol.iloc[end_idx - 59 : end_idx + 1].median()
    ok = win.notna().all() & mem & (adv >= min_adv)
    syms = ok[ok].index
    logp = cast(pd.DataFrame, np.log(win[syms]))
    recs = []
    for sec, grp in panel.sector.reindex(syms).groupby(panel.sector.reindex(syms)):
        g = list(grp.index)
        if len(g) < 2:
            continue
        ii, jj = np.triu_indices(len(g), 1)
        L = logp[g].values
        for a, b in [(ii, jj), (jj, ii)]:
            beta, alpha, t, sd, mu, hl = eg_batch(L[:, a], L[:, b])
            for k in range(len(a)):
                recs.append((sec, g[a[k]], g[b[k]], beta[k], alpha[k], t[k], sd[k], mu[k], hl[k]))
    df = pd.DataFrame(recs, columns=["sector", "y", "x", "beta", "alpha", "adf_t", "sd", "mu", "half_life"])
    df["p"] = [mackinnonp(t, regression="c", N=2) for t in df["adf_t"]]
    df["key"] = [tuple(sorted(k)) for k in zip(df.y, df.x)]
    df = df.sort_values("p").drop_duplicates("key")  # keep better ordering per pair
    n_tested = len(df)
    df["bh_pass"] = bh(cast(np.ndarray, df["p"].values), q)
    df["raw_pass"] = df["p"] < 0.05
    sel = df[df.bh_pass & df.raw_pass & df.beta.between(*beta_range) & df.half_life.between(*hl_range)].sort_values("p")
    # diversification: a stock may appear in at most `max_per_stock` selected pairs (greedy by p-value)
    cnt: dict[Any, int] = {}
    keep: list[Any] = []
    for i, r in sel.iterrows():
        if cnt.get(r.y, 0) < max_per_stock and cnt.get(r.x, 0) < max_per_stock:
            keep.append(i)
            cnt[r.y] = cnt.get(r.y, 0) + 1
            cnt[r.x] = cnt.get(r.x, 0) + 1
        if len(keep) == top_k:
            break
    sel = sel.loc[keep]
    stats = {
        "n_candidates": len(syms),
        "n_pairs_tested": n_tested,
        "n_raw_p05": int(df.raw_pass.sum()),
        "expected_false_at_p05": 0.05 * n_tested,
        "n_bh_pass": int(df.bh_pass.sum()),
        "n_selected": len(sel),
    }
    return sel, stats


def run_pairs(
    panel: Panel,
    start_date: str | pd.Timestamp,
    form_len: int = 252,
    trade_len: int = 126,
    z_in: float = 2.0,
    z_out: float = 0.5,
    z_stop: float = 4.0,
    top_k: int = 20,
    q: float = 0.05,
    min_adv: float = 2e7,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c = panel.px_clean
    dates = c.index
    W = pd.DataFrame(0.0, index=dates, columns=c.columns)
    first = max(cast(int, dates.searchsorted(pd.Timestamp(start_date))), form_len)
    trades = []
    form_log = []
    for fe in range(first - 1, len(dates) - 2, trade_len):
        sel, st = form_pairs(panel, fe, form_len, min_adv, q, top_k=top_k)
        st["formation_end"] = dates[fe].date()
        form_log.append(st)
        t0, t1 = fe + 1, min(fe + trade_len, len(dates) - 1)
        mem = panel.member
        for _, p in sel.iterrows():
            ly, lx = np.log(c[p.y].iloc[t0 : t1 + 1]), np.log(c[p.x].iloc[t0 : t1 + 1])
            z = ((ly - p.alpha - p.beta * lx) - p.mu) / p.sd
            alive = (mem[p.y].iloc[t0 : t1 + 1] & mem[p.x].iloc[t0 : t1 + 1]).values
            pos = 0
            entry = None
            stopped = False
            gy, gx = 1 / (1 + p.beta), p.beta / (1 + p.beta)
            for k, (d, zv) in enumerate(z.items()):
                last = (k == len(z) - 1) or not alive[k] or np.isnan(zv)
                if pos == 0 and not last and not stopped and z_in < abs(zv) < z_stop:
                    pos = -np.sign(zv)
                    entry = (d, zv)
                elif pos != 0 and (abs(zv) < z_out or abs(zv) > z_stop or last):
                    trades.append(
                        {
                            "y": p.y,
                            "x": p.x,
                            "sector": p.sector,
                            "entry": cast(tuple[Any, Any], entry)[0],
                            "exit": d,
                            "z_entry": cast(tuple[Any, Any], entry)[1],
                            "z_exit": zv,
                            "reason": "stop" if abs(zv) > z_stop else ("conv" if abs(zv) < z_out else "end/delist"),
                            "side": pos,
                            "beta": p.beta,
                            "p": p.p,
                        }
                    )
                    stopped = abs(zv) > z_stop  # after a stop-out the pair is retired for this trading window
                    pos = 0
                if pos != 0:
                    W.at[d, p.y] += pos * gy / top_k
                    W.at[d, p.x] += -pos * gx / top_k
    return W.loc[dates[first] :], pd.DataFrame(trades), pd.DataFrame(form_log)


def trade_pnl(trades: pd.DataFrame, W: pd.DataFrame, fwd: pd.DataFrame) -> np.ndarray:
    """Per-round-trip gross return (sum of daily contributions while open) for hit-rate."""
    out = []
    for _, t in trades.iterrows():
        rng = fwd.loc[t.entry : t.exit].iloc[:-1]  # weight at exit day is 0 (closed at that decision)
        gy, gx = 1 / (1 + t.beta), t.beta / (1 + t.beta)
        r = (t.side * gy * rng[t.y].fillna(0) - t.side * gx * rng[t.x].fillna(0)).sum()
        out.append(r)
    return np.array(out)


def run_pairs_weights(panel: Panel, start_date: str | pd.Timestamp | None = None, **kw: Any) -> pd.DataFrame:
    """Strategy-registry entry point. Returns W; trades and formation log attached in W.attrs."""
    start_date = start_date or (cast(pd.Timestamp, panel.close.index[0]) + pd.Timedelta(days=380))
    W, trades, flog = run_pairs(panel, start_date, **kw)
    W.attrs["trades"] = trades
    W.attrs["formation_log"] = flog
    return W
