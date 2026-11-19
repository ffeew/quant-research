# auto-extracted definitions from backtest.py (no outputs written)
"""Rule-based backtests of PEAD-gap and trend-filtered 12-1 momentum on universe U (quant.py).
Signals on bar t close; fills at bar t+1 OPEN. Costs 5bps/side; 1%/yr borrow on shorts.
Read-only: uses data/bars_sip.json produced by fetch.py. No orders."""

from __future__ import annotations

import json
import math
from typing import Any, cast

import numpy as np
import pandas as pd

D = json.load(open("data/bars_sip.json"))
FEED = sorted(set(D["feed"].values()))
COST = 0.0005
BORROW = 0.01
MAXHOLD = 60
ATRK = 2.0
TPR = 2.0
SPLIT = pd.Timestamp("2021-12-31")
RISK_PER_TRADE = 0.0025  # equity fraction per 1R (additive, for %DD reporting only; Sharpe is scale-free)


def _num(value: Any) -> float:
    return cast(float, value)


def _flag(value: Any) -> bool:
    return cast(bool, value)


def frame(b: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(b)
    df["t"] = pd.to_datetime(df["t"].str[:10])
    df = df.set_index("t")
    return df[["o", "h", "l", "c", "v"]].astype(float)


px = {s: frame(b) for s, b in D["bars"].items()}
cal = px["SPY"].index


def align(f: str) -> pd.DataFrame:
    return pd.DataFrame({s: px[s][f] for s in px}).reindex(cal)


O, Hh, L, C, V = (align(f) for f in "ohlcv")
# indicators as of close t (bar t included)
prevC = C.shift(1)
TR = pd.concat([Hh - L, (Hh - prevC).abs(), (L - prevC).abs()]).groupby(level=0).max().reindex(cal)
ATR = TR.rolling(14).mean()  # bars t-13..t: all prior to the t+1 entry bar
SMA50 = C.rolling(50).mean()
SMA200 = C.rolling(200).mean()
GAP = O / prevC - 1
VRAT = V / V.shift(1).rolling(20).mean()  # prior 20 days t-20..t-1
RET = C.pct_change(fill_method=None)
VOL20 = RET.rolling(20).std(ddof=0) * math.sqrt(252) * 100
MOM = (C.shift(21) / C.shift(252) - 1) * 100
R63 = (C / C.shift(63) - 1) * 100
RS63 = R63.sub(R63["SPY"], axis=0)
SCORE = MOM / VOL20.clip(lower=10) + RS63 / VOL20.clip(lower=10)
ABOVE = (C > SMA50) & (C > SMA200)
BELOW = (C < SMA50) & (C < SMA200)
SPY_UP = C["SPY"] > SMA200["SPY"]
idx = {d: i for i, d in enumerate(cal)}


def sim_bracket(s: str, i_sig: int, side: int, maxhold: int = MAXHOLD) -> dict[str, Any] | None:
    """signal at bar i_sig close, enter open i_sig+1. Returns trade dict or None."""
    i = i_sig + 1
    if i >= len(cal):
        return None
    E = _num(O[s].iat[i])
    atr = _num(ATR[s].iat[i_sig])
    if not (E > 0 and atr > 0):
        return None
    Dd = ATRK * atr
    stop = E - side * Dd
    tp = E + side * TPR * Dd
    last = min(i + maxhold - 1, len(cal) - 1)
    X: float | None = None
    why: str | None = None
    for j in range(i, last + 1):
        o, h, l, c = _num(O[s].iat[j]), _num(Hh[s].iat[j]), _num(L[s].iat[j]), _num(C[s].iat[j])
        if np.isnan(c):
            continue
        if j > i:  # gap through levels at open
            if side * (o - stop) <= 0:
                X, why = o, "stop_gap"
                break
            if side * (o - tp) >= 0:
                X, why = o, "tp_gap"
                break
        hit_stop = (l <= stop) if side > 0 else (h >= stop)
        hit_tp = (h >= tp) if side > 0 else (l <= tp)
        if hit_stop:
            X, why = stop, "stop"
            break  # stop assumed first if both touched
        if hit_tp:
            X, why = tp, "tp"
            break
    else:
        j = last
        why = "time" if last == i + maxhold - 1 else "open_eod"
        while j > i and np.isnan(_num(C[s].iat[j])):
            j -= 1
            why = "data_end"  # symbol stopped trading (e.g. MMC after 2026-01-13)
        X = _num(C[s].iat[j])
    return mk(s, i_sig, i, j, side, E, X, Dd, why)


def mk(s: str, i_sig: int, i: int, j: int, side: int, E: float, X: float, Dd: float, why: str | None) -> dict[str, Any]:
    days = j - i + 1
    cost_R = COST * (E + X) / Dd + (BORROW * days / 252 * E / Dd if side < 0 else 0)
    gross_R = side * (X - E) / Dd
    return dict(
        sym=s,
        sig=cal[i_sig],
        entry=cal[i],
        exit=cal[j],
        i=i,
        j=j,
        side=side,
        E=E,
        X=X,
        D=Dd,
        why=why,
        days=days,
        R=gross_R - cost_R,
        R_gross=gross_R,
        regime="SPY>200" if _flag(SPY_UP.iat[i_sig]) else "SPY<200",
    )


def daily_curve(trades: list[dict[str, Any]]) -> pd.Series:
    """additive daily P&L in R units, marked to close; costs booked at exit; equal 1R risk per trade."""
    pnl = np.zeros(len(cal))
    for t in trades:
        s, i, j, side, Dd = t["sym"], t["i"], t["j"], t["side"], t["D"]
        ref = t["E"]
        for k in range(i, j + 1):
            c = _num(C[s].iat[k])
            if k == j:
                c = t["X"]
            if np.isnan(c):
                continue
            pnl[k] += side * (c - ref) / Dd
            ref = c
        pnl[j] -= t["R_gross"] - t["R"]
    return pd.Series(pnl, index=cal)


# ---------------- signal generators ----------------
FIRST = 252  # need 252 bars for momentum / 200dma warmup


def pead(trend: bool, sides: tuple[int, ...] = (1, -1)) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    busy: dict[str, int] = {}
    for i in range(FIRST, len(cal) - 1):
        for s in C.columns:
            g, vr = _num(GAP[s].iat[i]), _num(VRAT[s].iat[i])
            if np.isnan(g) or np.isnan(vr) or abs(g) <= 0.04 or vr <= 1.8:
                continue
            side = 1 if g > 0 else -1
            if side not in sides:
                continue
            if trend and not ((side > 0 and _flag(ABOVE[s].iat[i])) or (side < 0 and _flag(BELOW[s].iat[i]))):
                continue
            if busy.get(s, -1) >= i + 1:
                continue  # one open position per symbol
            t = sim_bracket(s, i, side)
            if t:
                trades.append(t)
                busy[s] = t["j"]
    return trades


month_end = [i for i in range(FIRST, len(cal) - 1) if cal[i].month != cal[i + 1].month]


def mom_select(i: int) -> tuple[list[Any], list[Any]]:
    sc = SCORE.iloc[i].dropna()
    n = max(1, math.ceil(0.10 * len(sc)))
    longs = sc[ABOVE.iloc[i].reindex(sc.index).fillna(False)].sort_values(ascending=False).index[:n]
    shorts = sc[BELOW.iloc[i].reindex(sc.index).fillna(False)].sort_values().index[:n]
    return list(longs), list(shorts)


def mom_bracket(sides: tuple[int, ...] = (1, -1)) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    busy: dict[str, int] = {}
    for i in month_end:
        lg, sh = mom_select(i)
        for side, names in ((1, lg), (-1, sh)):
            if side not in sides:
                continue
            for s in names:
                if busy.get(s, -1) >= i + 1:
                    continue
                t = sim_bracket(s, i, side)
                if t:
                    trades.append(t)
                    busy[s] = t["j"]
    return trades


def mom_monthly(sides: tuple[int, ...] = (1, -1)) -> list[dict[str, Any]]:
    """hold from open after month-end k to open after month-end k+1; each monthly holding = one trade;
    R unit = 2xATR at entry (same risk sizing); full round-trip cost charged every month (conservative)."""
    trades: list[dict[str, Any]] = []
    for a, b in zip(month_end, [*month_end[1:], len(cal) - 1]):
        lg, sh = mom_select(a)
        i = a + 1
        j = b + 1 if b + 1 < len(cal) else len(cal) - 1
        for side, names in ((1, lg), (-1, sh)):
            if side not in sides:
                continue
            for s in names:
                E = _num(O[s].iat[i])
                atr = _num(ATR[s].iat[a])
                X = _num(O[s].iat[j] if j > b else C[s].iat[j])
                if not (E > 0 and atr > 0 and X > 0):
                    continue
                # exit at open of bar j: P&L marked to closes through j-1, then open j
                t = mk(s, a, i, j, side, E, X, ATRK * atr, "rebal" if j > b else "open_eod")
                t["days"] = j - i
                trades.append(t)
    return trades


def daily_curve_monthly(trades: list[dict[str, Any]]) -> pd.Series:
    pnl = np.zeros(len(cal))
    for t in trades:
        s, i, j, side, Dd = t["sym"], t["i"], t["j"], t["side"], t["D"]
        ref = t["E"]
        for k in range(i, j):
            c = _num(C[s].iat[k])
            if np.isnan(c):
                continue
            pnl[k] += side * (c - ref) / Dd
            ref = c
        if t["why"] == "rebal":
            pnl[j] += side * (t["X"] - ref) / Dd  # exit at open of j, booked on j
        else:
            pnl[j] += side * (t["X"] - ref) / Dd
        pnl[j] -= t["R_gross"] - t["R"]
    return pd.Series(pnl, index=cal)


# ---------------- stats ----------------
def tstats(tr: list[dict[str, Any]]) -> dict[str, Any]:
    if not tr:
        return dict(n=0)
    R = np.array([t["R"] for t in tr])
    w = R[R > 0]
    l = R[R <= 0]
    return dict(
        n=len(R),
        hit=round(len(w) / len(R), 3),
        avg_win_R=round(w.mean(), 3) if len(w) else None,
        avg_loss_R=round(l.mean(), 3) if len(l) else None,
        exp_R=round(R.mean(), 4),
        sum_R=round(R.sum(), 1),
        t_stat=round(R.mean() / (R.std(ddof=1) / math.sqrt(len(R))), 2) if len(R) > 2 else None,
        longs=int(sum(t["side"] > 0 for t in tr)),
        shorts=int(sum(t["side"] < 0 for t in tr)),
    )


def cstats(p: pd.Series) -> dict[str, Any]:
    p = p.astype(float)
    sr_d = p.mean() / p.std(ddof=1) if p.std() > 0 else 0.0
    cum = p.cumsum()
    dd = (cum - cum.cummax()).min()
    x = (p - p.mean()) / p.std(ddof=0) if p.std() > 0 else p * 0
    return dict(
        days=len(p),
        sharpe_ann=round(sr_d * math.sqrt(252), 3),
        sr_daily=sr_d,
        maxDD_R=round(dd, 1),
        maxDD_pct_at_0p25pct_risk=round(dd * RISK_PER_TRADE * 100, 1),
        skew=float((x**3).mean()),
        kurt=float((x**4).mean()),
    )
