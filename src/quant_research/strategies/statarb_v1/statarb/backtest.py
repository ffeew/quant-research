"""Generic daily weight-based backtester + metrics.
Weights W_t (index = signal date t) use information up to close(t) only. Execution is lagged one period:
  exec="open_t1":  trade at open(t+1) (MOO), earn open(t+1)->open(t+2)
  exec="close_t1": trade at close(t+1) (MOC, order sent before 15:50 ET), earn close(t+1)->close(t+2)
Forward returns spanning a flagged jump day (panel.bad) or |r|>40% are set to 0 (position treated as flat).
Book: gross = 1 (sum|w| <= 1), returns are on gross capital, NOT levered 2x.
Costs: the TCA owner's cost model (costs.py) per name-day, size-dependent impact at a given gross AUM, plus borrow on
short market value (calendar-day accrual / 360)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from . import costs as C

TD = 252
VENUE = {"open_t1": "open", "close_t1": "close"}


def fwd_returns(open_: pd.DataFrame, close: pd.DataFrame, bad: pd.DataFrame, exec: str = "open_t1") -> pd.DataFrame:
    if exec == "open_t1":
        f = open_.shift(-2) / open_.shift(-1) - 1
        b = bad.shift(-1, fill_value=False) | bad.shift(-2, fill_value=False)
    elif exec == "close_t1":
        f = close.shift(-2) / close.shift(-1) - 1
        b = bad.shift(-2, fill_value=False)
    else:
        raise ValueError(exec)
    b = b.reindex_like(f).fillna(False).astype(bool)
    return f.mask(b | (f.abs() > 0.40))


def apply_buffer(W: pd.DataFrame, R: pd.DataFrame, band: float) -> pd.DataFrame:
    """No-trade buffer. Target W_t vs drifted holding d_t: open/close/flip always trade; otherwise trade a name only
    if |W - d| > band * |W| (relative band). All-NaN target rows = hold (drift)."""
    Wv = W.values
    Rv = R.values
    out = np.zeros_like(Wv, dtype=float)
    prev = np.zeros(Wv.shape[1])
    prevR = np.zeros(Wv.shape[1])
    for t in range(len(Wv)):
        d = prev * (1 + prevR)
        g = prev @ prevR
        d = d / (1 + g) if t else d
        T = Wv[t]
        if np.isnan(T).all():
            w = d
        else:
            T = np.nan_to_num(T)
            must = (np.sign(T) != np.sign(d)) | (T == 0) | (d == 0)
            trade = must | (np.abs(T - d) > band * np.abs(T))
            w = np.where(trade, T, d)
        out[t] = w
        prev = w
        prevR = Rv[t]
    return pd.DataFrame(out, index=W.index, columns=W.columns)


def run(
    W: pd.DataFrame,
    fwd: pd.DataFrame,
    adv_usd: pd.DataFrame,
    sigma: pd.DataFrame,
    exec: str = "open_t1",
    aum: float = 10e6,
    k: float = 0.75,
    borrow: float = 0.0025,
    buffer: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    R = fwd.reindex_like(W).fillna(0.0)
    hold = W.isna().all(axis=1)  # all-NaN row = no rebalance: let the book drift (monthly strategies)
    if buffer > 0:
        w = apply_buffer(W, R, buffer)
    elif hold.any():
        wv = W.fillna(0.0).values.copy()
        Rv = R.values
        hv = hold.values
        started = False
        for t in range(len(wv)):
            if hv[t] and started:
                d = wv[t - 1] * (1 + Rv[t - 1])
                wv[t] = d / (1 + wv[t - 1] @ Rv[t - 1])
            elif not hv[t]:
                started = True
        w = pd.DataFrame(wv, index=W.index, columns=W.columns)
    else:
        w = W.fillna(0.0)
    gross = (w * R).sum(axis=1)
    drifted = (w.shift(1) * (1 + R.shift(1))).fillna(0.0).div((1 + gross.shift(1)).fillna(1.0), axis=0)
    trades = (w - drifted).abs()
    adv = adv_usd.reindex_like(w)
    sig = sigma.reindex_like(w)
    # ETFs (no $vol in panel) -> treat as mega-cap with 1% vol
    adv = adv.fillna(5e9)
    sig = sig.fillna(0.01)
    cbps = C.cost_bps(trades, aum, adv, sig, VENUE[exec], k)
    tcost = (trades * cbps).sum(axis=1) / 1e4
    caldays = pd.Series(w.index, index=w.index).diff().dt.days.shift(-1).fillna(1.0)
    short = w.clip(upper=0).abs().sum(axis=1)
    bcost = short * borrow * caldays / 360
    res = pd.DataFrame(
        {
            "gross": gross,
            "net": gross - tcost - bcost,
            "tcost": tcost,
            "bcost": bcost,
            "turnover": trades.sum(axis=1),
            "gross_exposure": w.abs().sum(axis=1),
            "net_exposure": w.sum(axis=1),
            "n_names": (w.abs() > 1e-9).sum(axis=1),
            "n_name_trades": (trades > 1e-6).sum(axis=1),
        }
    )
    res.attrs["w"] = w
    return res, trades


def capacity(W: pd.DataFrame, trades: pd.DataFrame, adv_usd: pd.DataFrame) -> dict[float, float]:
    """$ gross AUM at which material trades hit p% of ADV (10th pct over names per day, median over days)."""
    w = W.fillna(0.0)
    adv = adv_usd.reindex_like(w)
    avgpos = w.abs().where(w.abs() > 1e-9).mean(axis=1)
    mat = trades.where(trades.ge(0.25 * avgpos, axis=0) & (trades > 1e-6))
    return {p: float(((p * adv) / mat).quantile(0.10, axis=1).median()) for p in (0.01, 0.05)}


def metrics(r: pd.Series) -> dict[str, Any]:
    r = r.dropna()
    if len(r) < 20 or r.std() == 0:
        return {}
    ann, vol = r.mean() * TD, r.std() * np.sqrt(TD)
    eq = (1 + r).cumprod()
    nz = r[r != 0]
    return {
        "ann_ret": ann,
        "ann_vol": vol,
        "sharpe": ann / vol,
        "t_stat": r.mean() / r.std() * np.sqrt(len(r)),
        "max_dd": (eq / eq.cummax() - 1).min(),
        "hit_rate_days": (nz > 0).mean() if len(nz) else np.nan,
        "n_days": len(r),
    }


def summarise(res: pd.DataFrame, label: str, period: str, extra: dict[str, Any]) -> list[dict[str, Any]]:
    base = {
        "avg_daily_turnover": res["turnover"].mean(),
        "annual_turnover": res["turnover"].mean() * TD,
        "gross_edge_bps_per_$traded": res["gross"].sum() / res["turnover"].sum() * 1e4
        if res["turnover"].sum() > 0
        else np.nan,
        "avg_cost_bps_per_$traded": res["tcost"].sum() / res["turnover"].sum() * 1e4
        if res["turnover"].sum() > 0
        else np.nan,
        "borrow_drag_ann": res["bcost"].mean() * TD,
        "avg_gross_exp": res["gross_exposure"].mean(),
        "avg_abs_net_exp": res["net_exposure"].abs().mean(),
        "avg_names": res["n_names"].mean(),
        "name_trades": int(res["n_name_trades"].sum()),
    }
    rows = []
    for col in ("gross", "net"):
        m = metrics(res[col])
        if m:
            rows.append({"strategy": label, "period": period, "pnl": col, **extra, **m, **base})
    return rows
