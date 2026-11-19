"""H1 (bellwether lag) and H2 (earnings peer read-through) target weights. Frozen primary rules."""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .events import boundary_ambiguous, covered, ev_in
from .splits import LOAD0, NAME_CAP, SECTOR_ETF


def signal_h1(bars: dict[str, pd.DataFrame], ELIG: pd.DataFrame, subind: pd.Series, evidx: dict, *,
              L: int = 60, z_thr: float = 1.0, n_lead: int = 2, min_grp: int = 4, hold_weeks: int = 4,
              eval_start: date, eval_end: date, last_exit_i: int) -> tuple[pd.DataFrame, list]:
    """H1 primary: L=60, |z|>=1, 4 weekly tranches, 2 leaders, min group 4.

    Weekly (last session of each W-FRI week): within each GICS sub-industry, the n_lead names
    with the largest 60d median dollar volume are leaders, the rest followers. G = 60-session
    sum of (leaders - followers) mean return; z = G / (std of the earlier 192 sessions * sqrt(L)).
    Long followers / short leaders in the direction of z (0.5 sleeve each side), skipping names
    with an earnings event in the holding window or no recent event coverage. Signal at t, the
    caller's one-session execution lag fills at t+1. Returns (weights, tranche dates).
    """
    R = bars["R"]
    DV = bars["PX"] * bars["VOL"]
    MEDDV60 = DV.rolling(60, min_periods=40).median()
    dates = R.index
    wk = pd.DatetimeIndex(pd.Series(dates, index=dates).groupby(dates.to_period("W-FRI")).max().values)
    tranches: dict[pd.Timestamp, pd.Series] = {}
    for jj, t in enumerate(wk):
        if t < pd.Timestamp(eval_start) - pd.Timedelta(days=40):
            continue
        if t > pd.Timestamp(eval_end):
            break
        i = dates.get_loc(t)
        if i < 260:
            continue
        el = ELIG.loc[t]
        syms = [s for s in el.index[el.values] if s in subind.index]
        g = pd.Series({s: subind[s] for s in syms}, dtype=object)
        w: dict[str, float] = {}
        act = 0
        for _gname, members in g.groupby(g):
            ms = list(members.index)
            if len(ms) < min_grp:
                continue
            ms = sorted(ms, key=lambda s: -MEDDV60.at[t, s])
            Ld, F = ms[:n_lead], ms[n_lead:]
            win = R.iloc[i - 252 + 1:i + 1]
            d = win[Ld].mean(axis=1) - win[F].mean(axis=1)
            G = d.iloc[-L:].sum()
            sd = d.iloc[:-L].std() * math.sqrt(L)
            if not (sd > 0):
                continue
            z = G / sd
            if abs(z) < z_thr:
                continue
            sgn = np.sign(z)
            ent = i + 1
            if jj + hold_weeks < len(wk):
                ex_i = dates.get_loc(wk[jj + hold_weeks]) + 1
            else:
                ex_i = len(dates) - 1
            if ex_i > last_exit_i:
                continue

            def keep(s: str, i: int = i, ent: int = ent, ex_i: int = ex_i) -> bool:
                return covered(evidx, s, i) and not ev_in(evidx, s, ent, ex_i)

            F2 = [s for s in F if keep(s)]
            L2 = [s for s in Ld if keep(s)]
            if not F2 or not L2:
                continue
            F, Ld = F2, L2
            act += 1
            for s in F:
                w[s] = w.get(s, 0.0) + sgn * 0.5 / len(F)
            for s in Ld:
                w[s] = w.get(s, 0.0) - sgn * 0.5 / len(Ld)
        if act:
            w = {k: v / act for k, v in w.items()}
        tranches[t] = pd.Series(w, dtype=float)
    keys = list(tranches)
    rows = {}
    for j, t in enumerate(keys):
        parts = [tranches[keys[m]] for m in range(max(0, j - hold_weeks + 1), j + 1)]
        book = pd.concat(parts, axis=1).fillna(0).sum(axis=1) / hold_weeks
        rows[t] = book
    Wk = pd.DataFrame(rows).T.fillna(0.0)
    W = Wk.reindex(dates).ffill().fillna(0.0)
    W = W.clip(-NAME_CAP, NAME_CAP)   # name cap: trim, do not reallocate
    return W, list(Wk.index)


def signal_h2(bars: dict[str, pd.DataFrame], ELIG: pd.DataFrame, subind: pd.Series, sector: pd.Series,
              ev_all: pd.DataFrame, evidx: dict, *, H: int = 40, thr: float = 1.5, unit: float = 0.005,
              gap_sessions: int = 50, NMAX: int = 100, eval_start: date, eval_end: date,
              last_exit_i: int) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """H2 primary: H=40, |N|>=1.5, report window 50, unit 0.5%, max 100 live positions.

    On each exact-acceptance-time earnings session d0, reporters' residual reactions (vs the
    sector ETF, SPY if the ETF has < 252 sessions; beta over the prior 252 sessions; sigma =
    last 60 residuals) are averaged per sub-industry into N. If |N| >= thr, peers that already
    reported in [d0-50, d0-2] and have no own event through exit+2 are traded sign(N) * unit
    from d0+1 for H sessions, hedged with -beta * unit of their ETF. Returns (weights, positions).
    """
    R = bars["R"]
    dates = R.index
    ev = ev_all[ev_all.timing_quality == "exact_acceptance_time"].copy()
    ev["d0"] = pd.to_datetime(ev.reaction_session.fillna(ev.first_tradable_session))
    if "knowledge_time_utc" in ev.columns:
        ev = ev[~ev.knowledge_time_utc.map(boundary_ambiguous).astype(bool)]
    ev = ev[(ev.d0 >= pd.Timestamp(LOAD0)) & (ev.d0 <= pd.Timestamp(eval_end))]

    etf_of0 = {s: SECTOR_ETF.get(sector.get(s)) for s in subind.index}

    def hedge_etf(s: str, i: int) -> str:
        e = etf_of0.get(s)
        if e is None or e not in R.columns or R[e].iloc[max(0, i - 252):i].notna().sum() < 252:
            return "SPY"
        return e

    positions: list[dict[str, Any]] = []
    for d0, grp in ev.groupby("d0"):
        if d0 < pd.Timestamp(eval_start) or d0 > pd.Timestamp(eval_end):
            continue
        i = dates.get_loc(d0) if d0 in dates else None
        if i is None or i < 252:
            continue
        reps = []
        for _, row in grp.iterrows():
            s = row.symbol
            if s not in ELIG.columns or i < 1 or not bool(ELIG.iloc[i - 1].get(s, False)):
                continue
            if s not in subind.index:
                continue
            reps.append(s)
        if not reps:
            continue
        by_g: dict[Any, list[str]] = {}
        for s in reps:
            by_g.setdefault(subind[s], []).append(s)
        for gname, reporters in by_g.items():
            reactions = []
            for s in reporters:
                e = hedge_etf(s, i)
                win = R[[s, e]].iloc[i - 252:i]
                if win.dropna().shape[0] < 200:
                    continue
                y = win[s].values
                x = win[e].values
                mask = np.isfinite(y) & np.isfinite(x)
                if mask.sum() < 200:
                    continue
                beta = np.polyfit(x[mask], y[mask], 1)[0]
                r0 = R.at[dates[i], s] - beta * R.at[dates[i], e]
                resid = y - beta * x
                sig = np.nanstd(resid[-60:])
                if not (sig > 0) or not np.isfinite(r0):
                    continue
                reactions.append((s, r0 / sig))
            if not reactions:
                continue
            N = float(np.mean([r for _, r in reactions]))
            if abs(N) < thr:
                continue
            members = [s for s in subind.index[subind == gname]
                       if s in ELIG.columns and bool(ELIG.iloc[i - 1].get(s, False))]
            cands = []
            for s in members:
                if s in reporters:
                    continue
                xs = evidx.get(s)
                if xs is None:
                    continue
                lo, hi = i - gap_sessions, i - 2
                if not np.any((xs >= lo) & (xs <= hi)):   # must have reported in [d0-50, d0-2]
                    continue
                ent = i + 1
                ex_i = ent + H
                if ex_i > last_exit_i:
                    continue
                if ev_in(evidx, s, i - 1, ex_i, margin=0):
                    if np.any((xs >= i - 1) & (xs <= ex_i + 2)):   # no own row in [d0-1, exit+2]
                        continue
                e = hedge_etf(s, i)
                win = R[[s, e]].iloc[i - 252:i]   # follower beta excludes d0
                y = win[s].values
                x_ = win[e].values
                mask = np.isfinite(y) & np.isfinite(x_)
                if mask.sum() < 200:
                    continue
                beta_f = float(np.polyfit(x_[mask], y[mask], 1)[0])
                cands.append((abs(N), s, e, beta_f))
            cands.sort(key=lambda c: (-c[0], c[1]))
            live = {p["sym"] for p in positions if p["entry_i"] <= i + 1 < p["exit_i"]}
            n_live = sum(1 for p in positions if p["entry_i"] <= i + 1 < p["exit_i"])
            for _, s, e, beta_f in cands:
                if s in live:
                    continue
                if n_live >= NMAX:
                    break
                sgn = np.sign(N)
                positions.append({"sym": s, "etf": e, "w_sym": sgn * unit, "w_etf": -sgn * beta_f * unit,
                                  "entry_i": i + 1, "exit_i": i + 1 + H, "N": N})
                live.add(s)
                n_live += 1

    cols = sorted({p["sym"] for p in positions} | {p["etf"] for p in positions})
    W = pd.DataFrame(0.0, index=dates, columns=cols)
    for p in positions:
        sl = slice(p["entry_i"], p["exit_i"])
        W.iloc[sl, W.columns.get_loc(p["sym"])] += p["w_sym"]
        W.iloc[sl, W.columns.get_loc(p["etf"])] += p["w_etf"]
    W = W.clip(-NAME_CAP, NAME_CAP)
    return W, positions
