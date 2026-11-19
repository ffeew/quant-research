# Frozen pre-migration snapshot of quant_research.backtest.engine for equivalence tests.
# Imports cost_model v1.1. Do not use outside tests/backtest.
"""Daily portfolio simulator: Tomas's cost model v1.1 (read-only import) with Victor's STANDARD.md v1.0 minimums.
Dave, 2026-10-30 (v2).

Conventions
- Targets: {signal_date: pd.Series(weight per $1 NAV)}; the signal uses data up to the close of signal_date only.
- Fills (base, STANDARD §2): NEXT SESSION'S OPEN (market-on-open). On the trade day the old book earns the overnight
  leg (close t -> open t+1) and the new book earns the intraday leg (open -> close). Alternative fill="close" =
  next session's close (MOC), logged as a separate trial.
- Names with no bar (delisted / halted) earn rf (cash at the last close) and pay no exit cost. Delisting returns are
  NOT yet in Dmitri's data (in progress), so a bankrupt name's last-print-to-zero is missed. sim() counts these events.
- Returns are excess over rf per $1 NAV: sum_i h_i (r_i - rf). Dollar-neutral books are unaffected by rf; long-only and
  FP-levered BAB books are excess returns (financing at rf).
- Cost per name per trade (one way, bps) = max(Tomas trade_cost total_bps, Victor floor), where
    Tomas: fees + half-spread x venue + k*sigma*sqrt(Q/ADV) x venue + paper buffer; venue "open" (MOO) or "close" (MOC);
           price = raw close of the previous session, ADV = 20d mean SIP volume, sigma = 20d std, both lagged 1 day;
           spread = bucket default (no quote history).
    Victor §5 floor: stock L1/L2 (>= $200M ADV) 5 bps + half-spread; L3 10 + half-spread; L4 20 + half-spread;
           liquid ETFs 2 bps + half-spread (half-spread = Tomas bucket default, paid in full).
- Borrow: short MV x 1.00%/yr / 360 per calendar day (Victor GC minimum; Tomas ETB default is 0.25%). No point-in-time
  borrow/ETB history exists (snapshots start 2026-10-29), so unborrowable names cannot be excluded at signal time.
- Stress: costs x2 and borrow x2.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

sys.path.insert(0, f"{_QR.COSTS_DIR}")
from quant_research.backtest.costs import cost_model as cm

BOOK_USD = 100_000.0  # desk paper account equity ~ $100k (risk/2026-10-30-pilot-positions-review.md)
BORROW_RATE = 0.01  # Victor §5 GC minimum
VICTOR_FLOOR = {"L1": 5.0, "L2": 5.0, "L3": 10.0, "L4": 20.0}
ETF_FLOOR = 2.0


def _liq_inputs(panel):
    if "_liq" not in panel:
        adv = panel["vol_raw"].rolling(20, min_periods=10).mean().shift(1)
        sig = panel["ret"].rolling(20, min_periods=10).std().shift(1)
        px = panel["close_raw"].shift(1)
        panel["_liq"] = (adv, sig, px)
    return panel["_liq"]


def trade_costs(panel, date, dh: pd.Series, book_usd, venue, etfs=frozenset()):
    adv, sig, pxs = _liq_inputs(panel)
    px = pxs.loc[date]
    rows = []
    for s, d in dh.items():
        p = px.get(s, np.nan)
        if not (abs(d) > 1e-12) or not (p > 0):
            continue
        a = adv.at[date, s] if s in adv.columns else np.nan
        sd = sig.at[date, s] if s in sig.columns else np.nan
        sh = abs(d) * book_usd / float(p)
        tc = cm.trade_cost(
            "buy" if d > 0 else "sell",
            float(p),
            sh,
            adv_shares=float(a) if a > 0 else None,
            sigma_daily=float(sd) if sd > 0 else None,
            venue=venue,
            trade_date=date.date(),
        )
        b = tc["bucket"].split()[0]
        hs = cm.BUCKETS[tc["bucket"]][1]
        floor = (ETF_FLOOR if s in etfs else VICTOR_FLOOR[b]) + hs
        rows.append((date, s, d, b, tc["total_bps"], floor, max(tc["total_bps"], floor), sh / a if a > 0 else np.nan))
    return pd.DataFrame(
        rows, columns=["date", "symbol", "dw", "bucket", "tomas_bps", "victor_floor_bps", "bps", "participation"]
    )


def simulate(
    panel,
    targets: dict[pd.Timestamp, pd.Series],
    rf: pd.Series,
    fill="open",
    book_usd=BOOK_USD,
    borrow_rate=BORROW_RATE,
    etfs=frozenset(),
    beta_exante: dict[str, float] | None = None,
    terminal: dict[str, tuple[float, float]] | None = None,
):
    """terminal: {symbol: (return if held long, return if held short)} applied once, on the first session after the
    symbol's last bar (delisting), to a held position; None = cash at the last close (0%)."""
    R, ON, ID = panel["ret"], panel["on"], panel["id"]
    dates = R.index
    rf = rf.reindex(dates).ffill().fillna(0.0)
    venue = "open" if fill == "open" else "close"
    trade_on = {}
    for sd, w in targets.items():
        i = dates.searchsorted(sd)
        if i < len(dates) and dates[i] == sd and i + 1 < len(dates):
            trade_on[dates[i + 1]] = w[w.abs() > 1e-12]
    if not trade_on:
        return None
    first = min(trade_on)
    h = pd.Series(dtype=float)
    rows, trades, delist = [], [], []
    prev_d = None
    last_bar = panel.setdefault("_last_bar", R.apply(pd.Series.last_valid_index))
    end_all = dates[-1]
    applied, events = set(), []

    def grow(h, r, rfd, d=None):
        rr = r.reindex(h.index)
        dead = rr.isna()
        rr = rr.where(~dead, rfd)
        if d is not None:
            for s_ in h.index[dead.values]:
                lb = last_bar.get(s_)
                if lb is not None and lb < d and lb < end_all and (s_, lb) not in applied:
                    applied.add((s_, lb))
                    tl, ts = terminal.get(s_, (0.0, 0.0)) if terminal else (0.0, 0.0)
                    term = tl if h[s_] > 0 else ts
                    rr[s_] = term
                    events.append((d, s_, float(h[s_]), lb, term))
        ex = h * (rr - rfd)
        nav = 1.0 + float((h * rr).sum()) + (1.0 - h.sum()) * rfd
        return h * (1 + rr) / nav, float(ex[h > 0].sum()), float(ex[h < 0].sum()), dead

    for d in dates[dates.searchsorted(first) :]:
        gl = gs = 0.0
        cost = traded = 0.0
        borrow = 0.0
        if prev_d is not None and len(h):
            borrow = float(h[h < 0].abs().sum()) * borrow_rate * (d - prev_d).days / 360.0
        if d in trade_on:
            tgt = trade_on[d]
            if fill == "open" and len(h):
                h, a1, b1, _ = grow(h, ON.loc[d], 0.0, d)  # rf accrues on the intraday leg below
                gl += a1
                gs += b1
            elif fill == "close" and len(h):
                h, a1, b1, _ = grow(h, R.loc[d], rf[d], d)
                gl += a1
                gs += b1
            _last = R.loc[d].reindex(h.index)
            alive = (ON.loc[d] if fill == "open" else R.loc[d]).reindex(h.index).notna()
            dead_held = h[~alive]
            for s, w in dead_held.items():
                delist.append((d, s, w))
            idx = h[alive].index.union(tgt.index)
            dh = tgt.reindex(idx).fillna(0) - h[alive].reindex(idx).fillna(0)
            tc = trade_costs(panel, d, dh, book_usd, venue, etfs)
            cost = float((tc.dw.abs() * tc.bps).sum() / 1e4) if len(tc) else 0.0
            traded = float(dh.abs().sum())
            trades.append(tc)
            h = tgt.copy()
            if fill == "open":
                h, a2, b2, _ = grow(h, ID.loc[d], rf[d])
                gl += a2
                gs += b2
        elif len(h):
            h, a1, b1, _ = grow(h, R.loc[d], rf[d], d)
            gl += a1
            gs += b1
        rows.append(
            (d, gl + gs, gl, gs, cost, borrow, traded, float(h.clip(lower=0).sum()), float(-h.clip(upper=0).sum()))
        )
        prev_d = d
    daily = pd.DataFrame(
        rows, columns=["date", "gross", "gross_long", "gross_short", "cost", "borrow", "traded", "long_mv", "short_mv"]
    ).set_index("date")
    daily["net"] = daily.gross - daily.cost - daily.borrow
    daily["net2x"] = daily.gross - 2 * daily.cost - 2 * daily.borrow
    tr = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    dl = pd.DataFrame(events, columns=["date", "symbol", "weight", "last_bar", "terminal_return_applied"])
    return daily, tr, dl


def monthly(daily: pd.DataFrame, col: str = "net") -> pd.Series:
    return (1 + daily[col]).groupby(pd.Grouper(freq="ME")).prod() - 1
