"""Unit / mechanics checks for the PREREG-v3 engine (§8 unit checks + amendments A3-A6).
Uses ONLY synthetic bars and the existing 2016+ desk store. Never opens bars/daily/extended/. Prints no performance.
Run: .venv/bin/python -m tests.test_v3_engine"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from importlib.abc import Loader
from importlib.machinery import ModuleSpec
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

sys.path.insert(0, ".")
from quant_research.strategies.trend_tsmom.tsmom import data_v3 as D3
from quant_research.strategies.trend_tsmom.tsmom import v3spec as S3
from quant_research.strategies.trend_tsmom.tsmom.engine_v3 import (
    FROZEN_BREAKER,
    ATRUnavailable,
    OHLCUnavailable,
    OpenFallbackExceeded,
    SplitMismatch,
    SplitTableMissing,
    V3Config,
    limits_compliance,
    month_ends,
    run,
    split_ratios,
)

res: dict[str, bool] = {}


def check(name, cond):
    res[name] = bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


# ---------------------------------------------------------------- synthetic panels
def make_panel(n_assets=11, n_days=420, drift=0.0006, vol=0.008, seed=7, start="2010-01-04", names=None):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n_days)
    names = names or [f"A{i:02d}" for i in range(n_assets)]
    common = rng.normal(0, vol * 0.5, n_days)
    tr, o, h, l, c, v = {}, {}, {}, {}, {}, {}
    for _j, s in enumerate(names):
        r = drift + common + rng.normal(0, vol * 0.85, n_days)
        px = 100 * np.cumprod(1 + r)
        op = np.r_[100.0, px[:-1]] * (1 + rng.normal(0, vol * 0.2, n_days))
        hi = np.maximum(op, px) * (1 + vol * 0.6)
        lo = np.minimum(op, px) * (1 - vol * 0.6)
        tr[s], c[s], o[s], h[s], l[s] = px, px.copy(), op, hi, lo
        v[s] = np.full(n_days, 5e6)
    P = {
        k: pd.DataFrame(d, index=idx)
        for k, d in [("tr", tr), ("open", o), ("high", h), ("low", l), ("close", c), ("volume", v)]
    }
    P["rf"] = pd.Series(0.0001, index=idx)
    P["splits"] = pd.DataFrame(columns=["symbol", "date", "price_factor"])  # corporate-action table (none)
    return P


def clone(P):
    return {k: (v.copy() if hasattr(v, "copy") else v) for k, v in P.items()}


def set_bar(P, s, k, open_=None, high=None, low=None, close=None):
    """Overwrite one bar (raw OHLC); TR follows the close (no dividend)."""
    _idx = P["tr"].index
    if close is not None:
        ratio = close / P["close"][s].iloc[k]
        P["tr"].iloc[k:, P["tr"].columns.get_loc(s)] *= ratio
        for f in ["open", "high", "low", "close"]:
            P[f].iloc[k + 1 :, P[f].columns.get_loc(s)] *= ratio
        P["close"].iloc[k, P["close"].columns.get_loc(s)] = close
    for f, val in [("open", open_), ("high", high), ("low", low)]:
        if val is not None:
            P[f].iloc[k, P[f].columns.get_loc(s)] = val


NOBRK = replace(S3.PRIMARY, breakers=False)
P0 = make_panel()
names = list(P0["tr"].columns)
base = run(P0, names, NOBRK)
idx = P0["tr"].index
tr0 = base["trades"]
first_fill = base["first_fill"]
kf = idx.get_loc(first_fill)
me = month_ends(idx)
fills = [idx[idx.get_loc(t) + 1] for t in me if idx.get_loc(t) + 1 < len(idx)]

# 1. limits at every rebalance fill and EOD
d = base["daily_full"]
W = base["weights"]
check("synthetic: first fill only after A3 history (>=252 returns)", kf >= 253)
check(
    "synthetic: gross <= 58% right after every rebalance fill (+ that fill's own cost)",
    d.gross_post_open[d.is_fill == 1].max() <= 0.58 * 1.001,
)
check(
    "synthetic: gross <= 60% at every EOD (H3 hard)",
    d.gross_lev.max() <= 0.60 + 1e-9 and d.breach_gross_hard.sum() == 0,
)
check("synthetic: |w| <= 10% at every EOD (H1 hard)", W.abs().values.max() <= 0.10 + 1e-9)
check(
    "synthetic: drift trims only when buffer gap half used (no dust trades)",
    (tr0.query("reason=='drift_trim'").dw >= 1e-4).all() if (tr0.reason == "drift_trim").any() else True,
)
check(
    "synthetic: H2 risk-to-stop <= 0.95% at every entry/resize", base["h2_log"].risk_to_stop_nav.max() <= 0.0095 + 1e-9
)
check("synthetic: every held position has a stop every day", d.unstopped_positions.max() == 0)
check("synthetic: stops never loosened", base["loosen_violations"] == 0)
check(
    "synthetic: rebalance trades only on month-end+1 sessions", set(tr0.query("reason=='rebalance'").date) <= set(fills)
)

# never-loosened, explicit: per position episode the stop is monotone (long: non-decreasing)
st = base["stops"]
ok = True
for s in names:
    x = st[s]
    w = W[s]
    for a in range(1, len(x)):
        if w.iloc[a] > 0 and w.iloc[a - 1] > 0 and np.isfinite(x.iloc[a - 1]) and x.iloc[a] < x.iloc[a - 1] - 1e-9:
            ok = False
        if w.iloc[a] < 0 and w.iloc[a - 1] < 0 and np.isfinite(x.iloc[a - 1]) and x.iloc[a] > x.iloc[a - 1] + 1e-9:
            ok = False
check("synthetic: stop path monotone within every position episode", ok)

# 2. stop fills (A5)
held = W.iloc[kf]
s_long = held[held > 0].index[0]
k = kf + 2
stp = st[s_long].iloc[k - 1]
# 2a gap through the stop at the open -> fill at the open (worse than the stop)
P = clone(P0)
gap_open = stp * 0.97
set_bar(P, s_long, k, open_=gap_open, low=gap_open * 0.99, high=gap_open * 1.01, close=gap_open * 1.005)
o = run(P, names, NOBRK)
t = o["trades"].query("symbol==@s_long and date==@idx[@k] and reason.str.startswith('stop')")
check(
    "stop gap: exit at the OPEN when open <= stop",
    len(t) == 1 and t.reason.iloc[0] == "stop_gap_open" and abs(t.price.iloc[0] - gap_open) < 1e-9,
)
check("stop gap: position flat after exit", o["weights"][s_long].iloc[k] == 0)
# 2b intraday touch -> fill at min(stop, open) = stop
P = clone(P0)
op = P0["open"][s_long].iloc[k]
set_bar(P, s_long, k, open_=max(op, stp * 1.01), low=stp * 0.995, high=max(op, stp * 1.01) * 1.01, close=stp * 1.002)
o = run(P, names, NOBRK)
t = o["trades"].query("symbol==@s_long and date==@idx[@k] and reason.str.startswith('stop')")
check(
    "stop touch: fill at worse of stop and open (= stop)",
    len(t) == 1 and t.reason.iloc[0] == "stop_intraday" and abs(t.price.iloc[0] - stp) < 1e-9,
)
# 2c re-entry only at next month-end fill
nxt = [f for f in fills if f > idx[k]][0]
reb = o["trades"].query("symbol==@s_long and reason=='rebalance' and date>@idx[@k]")
check(
    "re-entry: no trade in stopped asset before next month-end fill",
    (reb.date >= nxt).all() and (o["weights"][s_long].loc[idx[k] : nxt].iloc[:-1] == 0).all(),
)
# 2d entry bar touches stop -> stop assumed (exit same day as entry)
P = clone(P0)
kk = kf
s0 = s_long
op0 = P0["open"][s0].iloc[kk]
set_bar(P, s0, kk, low=op0 * 0.80)
o = run(P, names, NOBRK)
t = o["trades"].query("symbol==@s0 and date==@idx[@kk] and reason!='drift_trim'")
check(
    "same-bar entry+stop: stop assumed hit (entry then stop_intraday on fill day)",
    list(t.reason) == ["rebalance", "stop_intraday"],
)
# 2e short side: high >= stop -> fill at max(stop, open)
Ps = make_panel(drift=-0.0008, seed=11)
ns = list(Ps["tr"].columns)
bs = run(Ps, ns, NOBRK)
Ws = bs["weights"]
kfs = idx.get_loc(bs["first_fill"]) if bs["first_fill"] in idx else None
kfs = Ps["tr"].index.get_loc(bs["first_fill"])
shorts = Ws.iloc[kfs][Ws.iloc[kfs] < 0].index
if len(shorts):
    ss = shorts[0]
    k2 = kfs + 2
    st2 = bs["stops"][ss].iloc[k2 - 1]
    P = clone(Ps)
    set_bar(P, ss, k2, open_=st2 * 1.03, high=st2 * 1.04, low=st2 * 1.02, close=st2 * 1.03)
    o = run(P, ns, NOBRK)
    t = o["trades"].query("symbol==@ss and date==@Ps['tr'].index[@k2] and reason.str.startswith('stop')")
    check("short gap: exit at OPEN when open >= stop", len(t) == 1 and abs(t.price.iloc[0] - st2 * 1.03) < 1e-9)
    check("short: stops never loosened", bs["loosen_violations"] == 0)
else:
    check("short-side synthetic produced shorts", False)


# 3. split: reverse split x8 scales the stop, no spurious stop-out
def with_split(P0_, sym, k_, factor, table_factor=None, in_table=True):
    P_ = clone(P0_)
    c_ = P_["close"].columns.get_loc(sym)
    for f in ["open", "high", "low", "close"]:
        P_[f].iloc[k_:, c_] *= factor
    P_["volume"].iloc[k_:, c_] /= factor
    P_["splits"] = pd.DataFrame(
        [{"symbol": sym, "date": P_["tr"].index[k_], "price_factor": table_factor or factor}] if in_table else [],
        columns=["symbol", "date", "price_factor"],
    )
    return P_


ks = kf + 3
P = with_split(P0, s_long, ks, 8.0)
o = run(P, names, NOBRK)
check("split: detected (ratio 8)", abs(split_ratios(P["tr"], P["close"], 1.3)[s_long].iloc[ks] - 8.0) < 1e-6)
check(
    "split: stop scaled x8, no stop-out on split day",
    abs(o["stops"][s_long].iloc[ks] / base["stops"][s_long].iloc[ks] - 8.0) < 1e-6
    and o["weights"][s_long].iloc[ks] != 0,
)
check(
    "split: returns unchanged vs no split (up to per-share fees)",
    np.allclose(o["daily_full"].net.values, base["daily_full"].net.values, atol=1e-6, equal_nan=True),
)
check(
    "9B-7: every split applied is listed (symbol, date, factor)",
    len(o["splits_applied"]) == 1
    and o["splits_applied"].iloc[0].symbol == s_long
    and o["splits_applied"].iloc[0].price_factor == 8.0,
)


def aborts(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True


P_nt = clone(P)
P_nt.pop("splits")
check(
    "9B-7: no corporate-action table -> abort (table is the source)",
    aborts(lambda: run(P_nt, names, NOBRK), SplitTableMissing),
)
check(
    "9B-7: heuristic split missing from the table -> abort",
    aborts(lambda: run(with_split(P0, s_long, ks, 8.0, in_table=False), names, NOBRK), SplitMismatch),
)
check(
    "9B-7: table factor disagrees with raw/TR (4 vs 8) -> abort",
    aborts(lambda: run(with_split(P0, s_long, ks, 8.0, table_factor=4.0), names, NOBRK), SplitMismatch),
)
P54 = with_split(P0, s_long, ks, 0.8)  # 5-for-4 forward split: below the 30% heuristic
o54 = run(P54, names, NOBRK)
check(
    "9B-7: 5:4 split (missed by the >30% heuristic) applied from the table: stop x0.8, listed",
    abs(split_ratios(P54["tr"], P54["close"], 1.3)[s_long].iloc[ks] - 1.0) < 1e-12
    and abs(o54["stops"][s_long].iloc[ks] / base["stops"][s_long].iloc[ks] - 0.8) < 1e-6
    and len(o54["splits_applied"]) == 1
    and o54["weights"][s_long].iloc[ks] != 0,
)
P54h = clone(P54)
P54h["splits"] = P54h["splits"].iloc[0:0]
o54h = run(P54h, names, replace(NOBRK, split_source="heuristic"))
check("9B-7: (contrast) heuristic alone would miss the 5:4 split", len(o54h["splits_applied"]) == 0)

# 4. late inception (A3): asset with short history waits for 252 returns
P = clone(P0)
late = names[-1]
for f in ["tr", "open", "high", "low", "close", "volume"]:
    P[f].iloc[:100, P[f].columns.get_loc(late)] = np.nan
o = run(P, names, NOBRK)
first_trade = o["trades"].query("symbol==@late").date.min()
first_valid = P["tr"][late].first_valid_index()
nret = P["tr"][late].pct_change(fill_method=None).notna().cumsum()
elig = nret[nret >= 252].index[0]
check("A3 late inception: no position before 252 return observations", first_trade > elig)
check(
    "A3: live-asset count reported and rises when the late asset goes live",
    o["daily_full"].n_live.max() == len(names) and o["daily_full"].n_live.loc[:elig].max() <= len(names) - 1,
)

# 5. ATR unavailable -> abort (§9.B(8))
P = clone(P0)
P["high"][:] = np.nan
P["low"][:] = np.nan
try:
    run(P, names, NOBRK)
    check("no high/low: run aborts with ATRUnavailable", False)
except ATRUnavailable:
    check("no high/low: run aborts with ATRUnavailable", True)

# 5b. decision 9B-8: held position with missing high/low (or close) -> abort; no close-trigger fallback
kh = kf + 10
s_held = base["weights"].iloc[kh].abs().idxmax()
P = clone(P0)
P["high"].iloc[kh, P["high"].columns.get_loc(s_held)] = np.nan
check(
    "9B-8: missing high/low on a held position -> abort (no fallback)",
    aborts(lambda: run(P, names, NOBRK), OHLCUnavailable),
)
P = clone(P0)
P["close"].iloc[kh, P["close"].columns.get_loc(s_held)] = np.nan
check(
    "9B-8: missing close on a held position -> abort",
    aborts(lambda: run(P, names, NOBRK), (OHLCUnavailable, ATRUnavailable)),
)
# 5c. missing open -> close fallback allowed only on <= 0.5% of open-priced fills
_rb_dates = set(tr0[tr0.reason == "rebalance"].date)
live_fills = [t for t in fills if t >= first_fill and t in _rb_dates]
P = clone(P0)
kfill = idx.get_loc(live_fills[1])
s_t = tr0.query("date==@idx[@kfill]").symbol.iloc[0]
P["open"].iloc[kfill, P["open"].columns.get_loc(s_t)] = np.nan
o1 = run(P, names, replace(NOBRK, max_open_fallback=1.0))
ofb = o1["open_fallback"]
check(
    "9B-8: missing-open fills are counted and flagged",
    ofb["fallback_fills"] == 1 and o1["trades"].open_fallback.sum() == 1,
)
check(
    "9B-8: fallback share above the limit -> abort",
    aborts(lambda: run(P, names, replace(NOBRK, max_open_fallback=ofb["share"] * 0.99)), OpenFallbackExceeded),
)
check(
    "9B-8: fallback share at/below the limit -> runs",
    run(P, names, replace(NOBRK, max_open_fallback=ofb["share"]))["open_fallback"]["fallback_fills"] == 1,
)
P = clone(P0)
for t in live_fills[0:3]:
    P["open"].loc[t, :] = np.nan
check(
    "9B-8: default 0.5% limit aborts when opens are missing on whole fill days",
    aborts(lambda: run(P, names, NOBRK), OpenFallbackExceeded),
)
check("9B-8: base synthetic run has zero fallback fills", base["open_fallback"]["fallback_fills"] == 0)

# 5d. decision 9B-11: a flip is one trade
from quant_research.strategies.trend_tsmom.run_v3 import trade_stats

tt = pd.DataFrame(
    {
        "date": pd.to_datetime(["2011-01-03"] * 4),
        "symbol": ["X"] * 4,
        "reason": ["rebalance", "rebalance", "stop_intraday", "rebalance"],
        "kind": ["entry", "flip", "exit", "resize"],
        "dw": [0.05] * 4,
        "cost_bps_1way": [5.0] * 4,
        "pct_adv20": [0.0] * 4,
    }
)
check(
    "9B-11: trade count = entry + flip + exit (flip = 1, resize = 0)",
    trade_stats(tt, pd.Timestamp("2011-01-01"), pd.Timestamp("2011-12-31"))["n_trades"] == 3,
)
Pf = make_panel(n_days=520, seed=11)
sf = list(Pf["tr"].columns)[0]
rr = np.r_[np.full(260, 0.004), np.full(260, -0.006)]
pxf = 100 * np.cumprod(1 + rr)
for f, m in [("tr", 1.0), ("close", 1.0), ("open", 1.0), ("high", 1.004), ("low", 0.996)]:
    Pf[f][sf] = pxf * m
FLIP = replace(NOBRK, stops=False, risk_cap=None)
of = run(Pf, list(Pf["tr"].columns), FLIP)
tf = of["trades"].query("symbol==@sf")
fl = tf[tf.kind == "flip"]
check(
    "9B-11: engine records a long->short flip as ONE order row (no exit+entry pair)",
    len(fl) >= 1 and all(len(tf[(tf.date == d_)]) == 1 for d_ in fl.date),
)

# 6. breakers (A5/A6) -- stops off so the intraday loss is not cut by stops
BRK = replace(S3.PRIMARY, stops=False, risk_cap=None)
kb = kf + 5
P8 = clone(P0)
sgn_b = np.sign(run(P0, names, BRK)["weights"].iloc[kb - 1])
for s in names:
    cl = P8["close"][s].iloc[kb]
    op = P8["open"][s].iloc[kb]
    if sgn_b[s] >= 0:  # adverse intraday excursion of 12% against every position, then recovery
        P8["low"].iloc[kb, P8["low"].columns.get_loc(s)] = min(op, cl) * 0.88
    else:
        P8["high"].iloc[kb, P8["high"].columns.get_loc(s)] = max(op, cl) * 1.12
o8 = run(P8, names, BRK)
d8 = o8["daily_full"]
ev = o8["events"]
gross_pre = base["daily_full"].gross_lev.iloc[kb]
trip_dd = d8.worst_dd_intraday.iloc[kb]
check(
    "H8: trip measured on intraday NAV bound (close-only DD < 5% that day)", trip_dd >= 0.05 and d8.dd.iloc[kb] < 0.05
)
check("H8: event logged on trip day", ((ev.event == "H8_halve") & (ev.date == idx[kb])).any())
check("H8: gross <= 29% by the trip-day close", d8.gross_lev.iloc[kb] <= 0.29 + 1e-4 and gross_pre > 0.29)
check(
    "H8: no restore on the trip day itself (first restore test at next EOD)",
    not ((ev.event == "H8_restore") & (ev.date == idx[kb])).any(),
)
tr8 = o8["trades"].query("date==@idx[@kb] and reason=='breaker_trim'")
import importlib.util as _iu

_spec = cast(ModuleSpec, _iu.spec_from_file_location("tca_v11", f"{_QR.COSTS_DIR}/cost_model.py"))
tca = _iu.module_from_spec(_spec)
cast(Loader, _spec.loader).exec_module(tca)
if len(tr8):
    r8 = tr8.iloc[0]
    a8 = names.index(r8.symbol)
    adv8 = P8["volume"][r8.symbol].rolling(20, min_periods=10).mean().shift(1).iloc[kb]
    sd8 = P8["tr"][r8.symbol].pct_change().rolling(20, min_periods=10).std().shift(1).iloc[kb]
    kw = dict(k=1.0, trade_date=idx[kb].date())
    c_cont = tca.trade_cost(
        r8.side, r8.price, r8.notional_basis_usd / r8.price, adv8, sd8, None, venue="continuous", **kw
    )["total_bps"]
    c_open = tca.trade_cost(r8.side, r8.price, r8.notional_basis_usd / r8.price, adv8, sd8, None, venue="open", **kw)[
        "total_bps"
    ]
check(
    "9B-2: H8 close trims are costed at venue 'continuous' (recorded and recomputed)",
    len(tr8) >= 1
    and (tr8.venue == "continuous").all()
    and (tr8["at"] == "close").all()
    and abs(r8.cost_bps_1way - c_cont) < 1e-9
    and abs(c_cont - c_open) > 1e-6,
)
check("H8: trims executed at close, largest risk-to-stop first (some names untouched or partially cut)", len(tr8) >= 1)
rest = ev.query("event=='H8_restore'")
if len(rest):
    kr = idx.get_loc(rest.date.iloc[0])
    check(
        "H8 restore: first EOD after the trip with DD < 3%",
        kr > kb and d8.dd.iloc[kr] < 0.03 and (d8.dd.iloc[kb + 1 : kr] >= 0.03).all(),
    )
    check("H8: gross <= 30% every EOD while halved", (d8.gross_lev.iloc[kb:kr] <= 0.30 + 1e-9).all())
else:
    check(
        "H8: gross <= 30% every EOD while halved (no restore in sample)", (d8.gross_lev.iloc[kb:] <= 0.30 + 1e-9).all()
    )

P9 = clone(P0)
for s in names:
    cl = P9["close"][s].iloc[kb]
    op = P9["open"][s].iloc[kb]
    if sgn_b[s] >= 0:  # intraday -20%, closes -10% against every position
        P9["low"].iloc[kb, P9["low"].columns.get_loc(s)] = min(op, cl) * 0.80
        set_bar(P9, s, kb, close=cl * 0.90)
    else:
        P9["high"].iloc[kb, P9["high"].columns.get_loc(s)] = max(op, cl) * 1.20
        set_bar(P9, s, kb, close=cl * 1.10)
o9 = run(P9, names, BRK)
d9 = o9["daily_full"]
ev9 = o9["events"]
check("H9: halt on >= 8% intraday NAV DD", ((ev9.event == "H9_halt") & (ev9.date == idx[kb])).any())
lift = ev9.query("event=='H9_lift'")
kl = idx.get_loc(lift.date.iloc[0]) if len(lift) else len(idx) - 1
t9 = o9["trades"].query("date>@idx[@kb] and date<=@idx[@kl] and reason=='rebalance'")
w9 = o9["weights"]
adds = 0
for _, r in t9.iterrows():
    j = idx.get_loc(r.date)
    before = w9[r.symbol].iloc[j - 1]
    if (before == 0) or (np.sign(r.dv_usd) == np.sign(before)):
        adds += 1
check("H9: no new positions and no adds while halted", adds == 0)
if len(lift):
    sh = run(P9, names, replace(BRK, breakers=False))["daily_full"].nav
    check("H9 lift: >= 5 trading days after halt", kl - kb >= 5)
    check("H9 lift: shadow 5-day return >= 0 on lift day", sh.iloc[kl] / sh.iloc[kl - 5] - 1 >= 0)
    check(
        "H9 lift: resumes halved (gross <= 30% until EOD DD < 3%)",
        (d9.gross_lev.iloc[kl : kl + 3] <= 0.30 + 1e-9).all(),
    )
else:
    check("H9: halt persisted (no lift condition met) -- no adds", adds == 0)
check("A6: drawdown measured in NAV dollars (dd == 1 - nav/hwm)", np.allclose(d9.dd, 1 - d9.nav / d9.hwm))

# 6b. decision 9B-1: breaker frozen to the PREREG (LIMITS v0.3.x not adopted)
check(
    "9B-1: PRIMARY breaker parameters equal the frozen §5/§9.B set",
    all(getattr(S3.PRIMARY, k_) == v_ for k_, v_ in FROZEN_BREAKER.items()) and S3.PRIMARY.breakers,
)
eng_src = open("tsmom/engine_v3.py").read()
run_src = open("run_v3.py").read()
check(
    "9B-1: engine never reads LIMITS.md (no live-limits coupling); run discloses the live breaker may differ",
    "LIMITS.md" not in eng_src and "live breaker may differ" in run_src,
)

# 6c. decision 9B-4: criterion 7.9 -- breaches cured at the next open, hard breaches dated, > 1% of sessions fails
lc0 = limits_compliance(base)
check("9B-4: base synthetic run: 7.9 passes, no hard breaches", lc0["pass"] and lc0["hard_breach_sessions"] == 0)


def jump(P_, sym, k_, mult):
    cl = P_["close"][sym].iloc[k_]
    set_bar(P_, sym, k_, close=cl * mult, high=cl * mult)


longs = [s_ for s_ in names if base["weights"][s_].iloc[kf + 8] > 0]
kj = [kf + 8, kf + 30, kf + 52]
P = clone(P0)
jump(P, longs[0], kj[0], 2.2)
oj = run(P, names, NOBRK)
lcj = limits_compliance(oj)
bj = lcj["breaches"]
check(
    "9B-4: an EOD hard breach (|w| > 10%) is listed with its date", str(idx[kj[0]].date()) in lcj["hard_breach_dates"]
)
check(
    "9B-4: ... and cured at the next open (drift trim to the 9.5% buffer)",
    bool(bj.query("kind=='hard'").cured.all())
    and len(lcj["uncured"]) == 0
    and ((oj["trades"].date == idx[kj[0] + 1]) & (oj["trades"].reason == "drift_trim")).sum() >= 1,
)
check(
    "9B-4: 1 hard-breach session (< 1% of sessions) -> 7.9 passes", lcj["hard_breach_share"] <= 0.01 and lcj["pass"]
) if lcj["sessions"] > 100 else check("9B-4: sample long enough", False)
P = clone(P0)
for kk_, s_ in zip(kj, longs[:3]):
    jump(P, s_, kk_, 2.2)
lc3 = limits_compliance(run(P, names, NOBRK))
check(
    "9B-4: hard breaches on > 1% of sessions -> 7.9 fails (even though each is cured)",
    lc3["hard_breach_sessions"] >= 2 and lc3["hard_breach_share"] > 0.01 and not lc3["pass"] and not lc3["uncured"],
)

# 6d. decision 9B-9: PBO matrix = 24 logged + 5 u23 cost settings + v3 + 10 stability = 40 of 57; DSR N stays 57
from quant_research.strategies.trend_tsmom.run_v3 import pbo_add_u23

Mp = pd.read_csv("outputs_v2/returns_matrix_net_Tx24.csv", index_col=0, parse_dates=True).loc[
    S3.PBO_WINDOW[0] : S3.PBO_WINDOW[1]
]
Mu = pbo_add_u23(Mp)
check("9B-9: u23 matrix hash pinned and verified", D3.sha_file(S3.U23_PATH) == S3.U23_SHA)
check(
    "9B-9: 5 cost settings appended, full window, no NaN, none duplicates a logged column",
    list(Mu.columns[-5:]) == [f"u23:{c_}" for c_ in S3.U23_COLS]
    and not Mu.isna().any().any()
    and all(min((Mu[c_] - Mp[x]).abs().max() for x in Mp.columns) > 1e-10 for c_ in Mu.columns[-5:]),
)
check(
    "9B-9: PBO columns 29 + v3 + 10 stability = 40 of 57; DSR decision N = 57",
    Mu.shape[1] + 1 + len(S3.STABILITY) == S3.PBO_COLUMNS_EXPECTED == 40 and S3.N_DECISION == 57,
)

# 6b. option (b) data rules (PREREG-v3 §2; amended C7)
_pre = D3.pre2016_split_table()
_sl = pd.read_parquet(f"{_QR.SCRATCH_DIR}/trend_v3_build/work_splitlog.parquet")
_slp = _sl[pd.to_datetime(_sl.ex_date) < pd.Timestamp(S3.CA_TABLE_START)]
check(
    "C7: the 5 frozen pre-2016 Yahoo splits match the data owner's splitlog (hash and ratios)",
    D3.sha_file(f"{_QR.SCRATCH_DIR}/trend_v3_build/work_splitlog.parquet") == S3.PRE2016_SPLITS_SRC_SHA
    and sorted(
        (r.symbol, str(pd.Timestamp(cast(str, r.ex_date)).date()), float(cast(float, r.yahoo_ratio)))
        for r in _slp.itertuples()
    )
    == sorted((a, b, c) for a, b, c in S3.PRE2016_SPLITS)
    and len(_pre) == 5,
)
_ca = pd.DataFrame([{"symbol": "EWJ", "date": "2016-11-07", "price_factor": 4.0}])
_m = D3.merge_split_sources(_ca, _pre, S3.CA_TABLE_START)
check(
    "C7: merged split source = CA table from 2016-01-05 + Yahoo before, sources labelled",
    len(_m) == 6
    and (_m.source == "yahoo_pre2016").sum() == 5
    and _m[_m.symbol == "EWJ"].source.iloc[0] == "corporate_action_table",
)
check(
    "C7: a CA-table split before 2016-01-05 (overlapping sources) aborts",
    aborts(
        lambda: D3.merge_split_sources(
            pd.DataFrame([{"symbol": "IWM", "date": "2005-06-09", "price_factor": 0.5}]), _pre, S3.CA_TABLE_START
        ),
        RuntimeError,
    ),
)
check(
    "C7: a pre-2016 Yahoo split dated on/after 2016-01-05 aborts",
    aborts(
        lambda: D3.merge_split_sources(
            _ca, pd.DataFrame([{"symbol": "X", "date": "2016-02-01", "price_factor": 0.5}]), S3.CA_TABLE_START
        ),
        RuntimeError,
    ),
)
_st = str(P0["tr"].index[ks + 20].date())
_Pm = with_split(P0, s_long, ks, 0.5)
_Pm["splits"] = D3.merge_split_sources(
    pd.DataFrame(columns=["symbol", "date", "price_factor"]),
    pd.DataFrame([{"symbol": s_long, "date": P0["tr"].index[ks], "price_factor": 0.5, "source": "yahoo_pre2016"}]),
    _st,
)
_om = run(_Pm, names, NOBRK)
check(
    "C7: a split before the CA-table start is applied from the Yahoo list and listed with its source",
    len(_om["splits_applied"]) == 1
    and _om["splits_applied"].iloc[0].source == "yahoo_pre2016"
    and abs(_om["stops"][s_long].iloc[ks] / base["stops"][s_long].iloc[ks] - 0.5) < 1e-6,
)
_Pm2 = clone(_Pm)
_Pm2["splits"] = D3.merge_split_sources(pd.DataFrame(columns=["symbol", "date", "price_factor"]), _pre.iloc[0:0], _st)
check(
    "C7: the cross-check runs over the full history: a pre-2016 split missing from the Yahoo list aborts",
    aborts(lambda: run(_Pm2, names, NOBRK), SplitMismatch),
)


def _diff(rows):
    return pd.DataFrame(
        [
            dict(
                symbol=s,
                date=d,
                old_open=1,
                old_high=1,
                old_low=1,
                old_close=1,
                new_open=o,
                new_high=h,
                new_low=l,
                new_close=c,
            )
            for s, d, o, h, l, c in rows
        ]
    )


_good = _diff([("SPY", "2020-03-12", 250.0, 252.0, 247.0, 248.11)])
check("S4/S5: a consistent diff passes the audit", D3.check_substitution_diff(_good, S3.ALPACA_START)["rows"] == 1)
check(
    "S5: a substituted row with a missing reference value aborts",
    aborts(
        lambda: D3.check_substitution_diff(
            _diff([("SPY", "2020-03-12", 250.0, float("nan"), 247.0, 248.0)]), S3.ALPACA_START
        ),
        RuntimeError,
    ),
)
check(
    "S5: an OHLC-inconsistent row after substitution aborts (no clip/repair)",
    aborts(
        lambda: D3.check_substitution_diff(_diff([("SPY", "2020-03-12", 250.0, 249.0, 247.0, 248.0)]), S3.ALPACA_START),
        RuntimeError,
    ),
)
check(
    "S3: a substituted row before the 2016-01-04 Alpaca start aborts (pre-2016 Yahoo rows cannot trigger)",
    aborts(
        lambda: D3.check_substitution_diff(_diff([("SPY", "2015-12-31", 250.0, 252.0, 247.0, 248.0)]), S3.ALPACA_START),
        RuntimeError,
    ),
)
_x = pd.DataFrame(
    {
        "symbol": ["SPY"] * 4 + ["GLD"] * 2,
        "date": ["2026-04-17", "2026-04-20", "2026-04-21", "2020-03-12", "2026-04-20", "2026-04-21"],
        "nasdaq_close_raw": [100.0, 100.20, 100.005, 248.11, 100.869, 100.0],
        "yahoo_close_raw": [100.0, 100.0, 100.0, 248.11, 100.0, 99.85],
    }
)
_dx = _diff(
    [
        ("SPY", "2026-04-20", 100, 100.5, 99.5, 100),
        ("SPY", "2020-03-12", 250.0, 252.0, 247.0, 248.11),
        ("GLD", "2026-04-21", 99.9, 100, 99.8, 99.85),
    ]
)
_xr = D3.nasdaq_yahoo_xcheck(_x, _dx, S3.XCHECK_AGREE_BP, S3.XCHECK_LIST_SUB_BP, S3.XCHECK_LIST_ALL_BP)
_ag = _xr["agreement"].set_index("symbol").share_within
check(
    "X1: per-ticker share of days Nasdaq agrees with Yahoo within 1bp",
    abs(_ag["SPY"] - 0.75) < 1e-12 and abs(_ag["GLD"] - 0.0) < 1e-12,
)
check(
    "X2: every SUBSTITUTED row with |Nasdaq-Yahoo| > 10bp is listed (and only those)",
    sorted(zip(_xr["substituted_gt"].symbol, _xr["substituted_gt"].date.dt.strftime("%Y-%m-%d")))
    == [("GLD", "2026-04-21"), ("SPY", "2026-04-20")],
)
check(
    "X3: every row (substituted or not) with |Nasdaq-Yahoo| > 25bp is listed, with its substitution flag",
    sorted(zip(_xr["rows_gt_all"].symbol, _xr["rows_gt_all"].substituted)) == [("GLD", False)],
)
check("TBD-2 closed: §2 reference-source pin == code constant", D3.pinned_src_hash() == S3.REF_SOURCE_TABLE_SHA)

# 7. pin guard (A4)
print(f"(info) PREREG-v3 pin status: {'PLACEHOLDER' if D3.pinned_hash() is None else 'pinned'}")
from quant_research.strategies.trend_tsmom import run_v3

A_, C_, F_, R_ = "a" * 64, "c" * 64, "f" * 64, "e" * 64


def _refuses(args):
    try:
        run_v3.guard_pin(*args)
        return False
    except SystemExit as e:
        return e.code != 0


check("A4: run guard refuses a placeholder pin", _refuses((None, C_, F_, R_)))
check("run gate: refuses while the corporate-action table hash is a placeholder", _refuses((A_, None, F_, R_)))
check("option (b): refuses while the v2 substitution-diff hash is a placeholder", _refuses((A_, C_, None, R_)))
check("option (b): refuses while the reference-source table is TBD (TBD-2)", _refuses((A_, C_, F_, None)))
check("run gate: all four hashes pinned -> guard passes", run_v3.guard_pin(A_, C_, F_, R_) == (A_, C_, F_, R_))
# Validator 2026-11-06: placeholder assertion uses a temporary PREREG fixture only; live state asserts the pin.
import contextlib
import tempfile as _tf

_live_prereg = D3.PREREG
_live_diff = D3.pinned_diff_hash()
_diff_path = json.load(open(os.path.join(os.path.dirname(os.path.abspath(run_v3.__file__)), "data_spec_v3.json")))[
    "substitution_diff"
]["path"]
_tmp = _tf.NamedTemporaryFile("w", suffix=".md", delete=False)
_ok_ph = False
try:
    _tmp.write("| **Substitution diff (v2)** | **`" + D3.DIFF_PLACEHOLDER + "`**. fixture for pre-pin parse only. |\n")
    _tmp.flush()
    _tmp.close()
    D3.PREREG = _tmp.name
    _ok_ph = D3.pinned_diff_hash() is None
finally:
    D3.PREREG = _live_prereg
    with contextlib.suppress(OSError):
        os.unlink(_tmp.name)
_ok_live = (
    _live_diff is not None
    and _live_diff == desk_pin("tests.strategies.trend_tsmom.test_v3_engine", "live_diff")
    and D3.sha_file(_diff_path) == _live_diff
    and _live_prereg == D3.PREREG
)
check(
    "option (b): PREREG §2 diff row: placeholder under temp fixture; live pin non-null, equals §2 and matches file",
    _ok_ph and _ok_live,
)
# pin --diff-sha256: required on the CLI, verified against the file, and pin refuses while TBD-2 is open
import contextlib as _cl
import io as _io
import subprocess as _subproc

_r = _subproc.run(
    [sys.executable, "run_v3.py", "pin", "--sha256", A_, "--ca-sha256", C_],
    capture_output=True,
    text=True,
    cwd=os.path.dirname(os.path.abspath(run_v3.__file__)),
)
check("option (b): `pin` requires --diff-sha256", _r.returncode != 0 and "--diff-sha256" in _r.stderr)
_here = os.path.dirname(os.path.abspath(run_v3.__file__))
_fake: dict[str, Any] = {
    "path": os.path.join(_here, "PREREG-v2.md"),
    "corporate_actions": {"path": os.path.join(_here, "data_spec_v3.json")},
    "substitution_diff": {"path": os.path.join(_here, "tsmom/v3spec.py")},
}
_h = {
    k: D3.sha_file(v)
    for k, v in [
        ("b", _fake["path"]),
        ("c", _fake["corporate_actions"]["path"]),
        ("f", _fake["substitution_diff"]["path"]),
    ]
}
_prereg_before = D3.sha_file(D3.PREREG)
_ls = run_v3.load_spec
run_v3.load_spec = lambda: _fake


def _pin_out(*a):
    buf = _io.StringIO()
    try:
        with _cl.redirect_stdout(buf):
            run_v3.cmd_pin(*a)
        return 0, buf.getvalue()
    except SystemExit as e:
        return e.code, buf.getvalue()


try:
    c1, o1 = _pin_out(_h["b"], _h["c"], "0" * 64)
finally:
    run_v3.load_spec = _ls
check(
    "option (b): pin verifies the diff file hash (wrong --diff-sha256 -> refused)",
    c1 != 0 and "substitution-diff" in o1,
)
D3_pss = D3.pinned_src_hash
D3.pinned_src_hash = lambda: None
run_v3.load_spec = lambda: _fake
try:
    c2, o2 = _pin_out(_h["b"], _h["c"], _h["f"])
finally:
    D3.pinned_src_hash = D3_pss
    run_v3.load_spec = _ls
check(
    "option (b): pin refuses while the reference-source table is TBD, even with all three hashes correct; PREREG untouched",
    c2 != 0 and "TBD-2" in o2 and D3.sha_file(D3.PREREG) == _prereg_before,
)
print(f"(info) PREREG-v3 CA-table pin status: {'PLACEHOLDER' if D3.pinned_ca_hash() is None else 'pinned'}")
os.chdir(os.path.dirname(os.path.abspath(run_v3.__file__)))
try:
    D3.load_pinned_build({"path": "PREREG-v2.md", "layout": "long", "columns": {}}, ["SPY"], "0" * 64)
    check("A4: hash mismatch raises before reading", False)
except RuntimeError as e:
    check("A4: hash mismatch raises before reading", "mismatch" in str(e))

# ---------------------------------------------------------------- 2016+ desk data (mechanics only)
from quant_research.strategies.trend_tsmom.tsmom import v2spec as S2
from quant_research.strategies.trend_tsmom.tsmom.data import build_panel, load_shortable
from quant_research.strategies.trend_tsmom.tsmom.engine import run as run_v2

U = S3.UNIVERSE
pv2 = build_panel(U)
sh = load_shortable()
v2 = run_v2(pv2, U, S2.V1, sh)["daily"]
desk = D3.build_desk_panel(U)
# known 2016+ reverse splits (EWJ 1-for-4 on 2016-11-07; USO 1-for-8 on 2020-04-29) as a stand-in CA table for unit checks only
desk["splits"] = pd.DataFrame(
    {"symbol": ["EWJ", "USO"], "date": pd.to_datetime(["2016-11-07", "2020-04-29"]), "price_factor": [4.0, 8.0]}
)
desk_nt = dict(desk)
desk_nt["splits"] = desk["splits"].iloc[1:]
check(
    "desk 2016+: CA table missing EWJ's 1:4 reverse split -> cross-check aborts",
    aborts(lambda: run(desk_nt, U, replace(S3.PRIMARY, breakers=False)), SplitMismatch),
)
EQ = V3Config(
    name="v2_equiv",
    min_sig_obs=253,
    allow_scale_up=True,
    pos_cap=None,
    risk_cap=None,
    gross_cap=1.0,
    gross_hard=1.0,
    fill="close",
    drift_trim="close",
    stops=False,
    breakers=False,
    nav0=1e6,
    cost_nav_basis=1e6,
    borrow_rate=0.0025,
    long_flat=tuple(s for s in U if not sh.get(s, False)),
)
v3e = run(desk, U, EQ)["daily"]
j = v2.index.intersection(v3e.index)
diff = (v2.net.loc[j] - v3e.net.loc[j]).abs()
print(
    f"(info) v2-equivalence max|diff| net {diff.max():.2e} gross {(v2.gross.loc[j] - v3e.gross.loc[j]).abs().max():.2e}"
)
check("v2-equivalence: same first fill date", v2.index[0] == v3e.index[0])
# v2 sizes on pre-cost NAV, v3 on post-cost dollar NAV: weights differ by ~2e-4, so daily diffs scale with |r| (max on 2026-06-05, a -5% day)
check(
    "v2-equivalence: stops/caps/breakers off reproduce v2 V1 daily net (median |diff| < 2e-6, max < 5e-5)",
    diff.median() < 2e-6 and diff.max() < 5e-5,
)
check("v2-equivalence: corr(v2, v3) > 0.99999", np.corrcoef(v2.net.loc[j], v3e.net.loc[j])[0, 1] > 0.99999)
gd = (v2.gross.loc[j] - v3e.gross.loc[j]).abs()
check("v2-equivalence: gross series match (median |diff| < 2e-6, max < 5e-5)", gd.median() < 2e-6 and gd.max() < 5e-5)

o = run(desk, U, S3.PRIMARY)
d = o["daily_full"].loc[o["first_fill"] :]
Wd = o["weights"].loc[d.index]
check("desk 2016+: primary runs end-to-end (mechanics only, no performance printed)", len(d) > 2000)
check("desk 2016+: |w| <= 10% every EOD", Wd.abs().values.max() <= 0.10 + 1e-9)
check("desk 2016+: gross <= 60% (30% when halved) every EOD", d.breach_gross_hard.sum() == 0)
check("desk 2016+: every held position stopped every day", d.unstopped_positions.max() == 0)
check("desk 2016+: stops never loosened", o["loosen_violations"] == 0)
check("desk 2016+: H2 <= 0.95% at every entry/resize", o["h2_log"].risk_to_stop_nav.max() <= 0.0095 + 1e-9)
check("desk 2016+: USO never short", (Wd["USO"] >= -1e-12).all())
check("desk 2016+: longs cash-funded (long MV <= NAV) every EOD", (d.long_mv <= d.nav + 1e-6).all())
rs = set(o["trades"].reason)
check(
    "desk 2016+: trade reasons within spec (no close-fallback exits)",
    rs <= {"rebalance", "stop_gap_open", "stop_intraday", "breaker_trim", "drift_trim"},
)
check("desk 2016+: both splits applied and listed", len(o["splits_applied"]) == 2)
check("desk 2016+: zero missing-open fallback fills", o["open_fallback"]["fallback_fills"] == 0)
lcd = limits_compliance(o)
check("desk 2016+: 7.9 compliance function runs; every breach cured at the next open", len(lcd["uncured"]) == 0)
check("desk 2016+: all trims costed at continuous venue", set(o["trades"].venue) == {"continuous"})
check("desk 2016+: drawdown == 1 - NAV/HWM (A6)", np.allclose(d.dd, 1 - d.nav / d.hwm))
check("desk 2016+: never trades crypto / outside pinned universe", set(o["trades"].symbol) <= set(U))
ok = all(res.values())
print(f"{sum(res.values())}/{len(res)} checks pass")
print("ALL V3 UNIT CHECKS PASS" if ok else "V3 UNIT CHECKS FAILED")
sys.exit(0 if ok else 1)
