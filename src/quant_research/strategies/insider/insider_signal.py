"""Opportunistic vs routine insider trading signal (Cohen, Malloy & Pomorski 2012), research prototype.

Pipeline:
 1. trades.parquet (from build_trades.py): Form 4 open-market P/S, filing_date + trans_date.
 2. Classification per (insider CIK, issuer CIK) at the start of each calendar year Y, using trades
    (trans_date) in Y-3..Y-1 only (known before Y): eligible if it traded in each of the 3 prior years;
    ROUTINE if it traded in the same calendar month in all 3 prior years; else OPPORTUNISTIC.
    Pairs without 3 years of history are UNCLASSIFIED (as in CMP).
 3. Signal month t = month of FILING_DATE (public date, not transaction date). Universe filter:
    issuer is a point-in-time S&P 500 member on the filing date (Dmitri's membership file).
 3b. Issuer->ticker mapping chain: see code (Dmitri's ticker_cik_map first; SEC ticker file as stopgap).
 4. Returns: enter at close of first trading day of month t+1 (>= 1 full trading day after any filing
    in month t, so no intraday look-ahead), exit at close of first trading day of month t+1+h, h=1,3.
    Excess vs SPY over the same window. Delisted names: last close x (1+terminal_return)
    from Dmitri's delisting_returns.parquet when available; else last close (listed in diagnostics).
 5. Benchmarks: SPY (primary, as specified) and equal-weighted PIT S&P 500 members (secondary;
    our portfolios are equal-weighted, so SPY embeds the 2016-26 cap-weighted vs EW gap).
 6. Stats: equal-weighted monthly cohort portfolios; N months, N stock-months, hit rate, mean,
    month-clustered t (h=1) and Newey-West(h-1) t on cohort means for overlapping h=3.
Config: see ../desk_data.py (env DESK_MEMBERSHIP / DESK_UNIVERSE / DESK_BARS_DIR / DESK_BENCH).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

sys.path.insert(0, f"{_QR.DESK_DIR}/equity")
from quant_research.data import desk_data as _desk_data


class DeskStore(Protocol):
    """Attributes the insider runner reads. They are not declared on the typed desk_data module."""

    OUT: str
    BENCH: str
    UNIVERSE_MODE: str
    USE_TERMINAL: bool
    DROP_REUSE: bool
    CURRENT: str
    MEMBERSHIP: str
    UNIVERSE: str
    BARS_DIR: str
    TICKER_CIK: str
    DELISTING: str

    def membership(self) -> pd.DataFrame: ...
    def ticker_cik_map(self) -> pd.DataFrame | None: ...
    def is_member(self, symbol: Any, when: Any) -> pd.Series: ...
    def universe(self) -> pd.DataFrame: ...
    def calendar(self) -> pd.DatetimeIndex: ...
    def bars(self, sym: str) -> pd.DataFrame | None: ...
    def terminal_returns(self) -> dict[str, tuple[Any, float]]: ...
    def clustered_t(self, values: Any, months: Any) -> float: ...
    def nw_t(self, values: Any, lag: int) -> float: ...
    def ff(self, freq: str) -> pd.DataFrame: ...
    def ff_alpha(self, r: pd.Series, factors: pd.DataFrame, lag: int) -> dict[str, Any]: ...


dd = cast(DeskStore, _desk_data)

FIRST_TEST = pd.Timestamp("2016-01-01")
HORIZONS = (1, 3)

tr = pd.read_parquet("trades.parquet")
tr = tr[(tr.trans_shares > 0)]
# ---- 2. classification -------------------------------------------------------------------
tr["ty"] = tr.trans_date.dt.year
tr["tm"] = tr.trans_date.dt.month
hist = tr.groupby(["rptownercik", "issuercik", "ty"]).tm.agg(lambda s: frozenset(s)).reset_index()  # type: ignore[type-var]  # pandas agg stub rejects a frozenset reducer
H: dict[tuple[Any, Any, Any], frozenset[int]] = {
    (r.rptownercik, r.issuercik, r.ty): cast(frozenset[int], r.tm) for r in hist.itertuples()
}


def classify(o: Any, i: Any, Y: Any) -> str:
    ms = [H.get((o, i, Y - k)) for k in (1, 2, 3)]
    if any(m is None for m in ms):
        return "unclassified"
    months = cast(tuple[frozenset[int], frozenset[int], frozenset[int]], (ms[0], ms[1], ms[2]))
    return "routine" if (months[0] & months[1] & months[2]) else "opportunistic"


tr["fy"] = tr.filing_date.dt.year
keys = tr[["rptownercik", "issuercik", "fy"]].drop_duplicates()
keys["cls"] = [classify(o, i, y) for o, i, y in keys.itertuples(index=False)]
tr = tr.merge(keys, on=["rptownercik", "issuercik", "fy"])
# ---- 3. map issuer -> universe symbol, PIT membership --------------------------------------
# Mapping chain (first hit wins), all restricted to tickers present in the membership file:
#   1. Dmitri's reference ticker_cik_map (CIK -> ticker valid on the filing date)   [DESK_TICKER_CIK]
#   2. Dmitri's universe.parquet cik column (current CIKs, no dates)
#   3. SEC company_tickers.json stopgap (current tickers only; ref/company_tickers.json)
#   4. issuer's own ticker on the filing (ISSUERTRADINGSYMBOL), only for membership symbols with no CIK anywhere
mem_syms = set(dd.membership().symbol)
tr = tr[tr.filing_date >= FIRST_TEST].copy()
keys = tr[["issuercik", "filing_date"]].drop_duplicates().astype({"issuercik": int})
ref = dd.ticker_cik_map()
sym1 = pd.Series(dtype=object)
if ref is not None:
    r = ref[ref.ticker.isin(mem_syms)][["cik", "ticker", "vf", "vt", "confidence"]]
    j = keys.merge(r, left_on="issuercik", right_on="cik")
    j = j[(j.filing_date >= j.vf) & (j.filing_date < j.vt)]
    j["is_mem"] = dd.is_member(j.ticker, j.filing_date)
    j = j.sort_values(["is_mem", "confidence", "ticker"], ascending=[False, True, True]).drop_duplicates(
        ["issuercik", "filing_date"]
    )
    sym1 = j.set_index(["issuercik", "filing_date"]).ticker
tr["symbol"] = pd.Series(
    list(pd.MultiIndex.from_arrays([tr.issuercik.astype(int), tr.filing_date]).map(lambda k: sym1.get(k)))
    if len(sym1)
    else [None] * len(tr),
    index=tr.index,
    dtype=object,
)
map_via = np.where(tr.symbol.notna(), "dmitri_ticker_cik_map", None)  # type: ignore[call-overload]  # pandas where stub rejects a None fill
tr["map_via"] = pd.Series(map_via, index=tr.index, dtype=object)
tr["issuertradingsymbol"] = tr.issuertradingsymbol.astype(object)
u = dd.universe()
cik_u = {int(c): s for s, c in zip(u.symbol, u.cik) if pd.notna(c) and s in mem_syms}
import os
import urllib.request

os.makedirs("ref", exist_ok=True)
if not os.path.exists("ref/company_tickers.json"):
    req = urllib.request.Request(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": "CIO-desk research (paper trading desk) research-contact@example.com"},
    )
    open("ref/company_tickers.json", "wb").write(urllib.request.urlopen(req, timeout=60).read())
sec: dict[int, str] = {}
for v in json.load(open("ref/company_tickers.json")).values():
    t = v["ticker"].upper().replace("-", ".")
    if t in mem_syms:
        sec.setdefault(int(v["cik_str"]), t)
for name, mp in (("universe_cik", cik_u), ("sec_company_tickers_stopgap", sec)):
    k = tr.symbol.isna()
    tr.loc[k, "symbol"] = tr.loc[k, "issuercik"].map(lambda c: mp.get(int(c)))
    tr.loc[k & tr.symbol.notna(), "map_via"] = name
known_ciks = set(ref.cik) if ref is not None else set()
known_ciks |= set(cik_u) | set(sec)
k = tr.symbol.isna() & tr.issuertradingsymbol.isin(mem_syms) & ~tr.issuercik.astype(int).isin(known_ciks)
tr.loc[k, "symbol"] = tr.loc[k, "issuertradingsymbol"]
tr.loc[k, "map_via"] = "issuer_ticker_fallback"
# known misses: filings whose own ticker is an S&P member that day, but no mapping found / mapped elsewhere
ism = dd.is_member(tr.issuertradingsymbol.fillna(""), tr.filing_date)
miss = (
    tr[ism & tr.symbol.isna()].groupby(["issuertradingsymbol", "issuercik"]).size().rename("n_trade_rows").reset_index()
)
miss.to_csv(f"{dd.OUT}/mapping_misses.csv", index=False)
tr = tr[tr.symbol.notna()].copy()
tr = tr[dd.is_member(tr.symbol, tr.filing_date)]
tr["fmonth"] = tr.filing_date.dt.to_period("M")
# ---- 4. returns ---------------------------------------------------------------------------
cal = dd.calendar()


def first_td(period: pd.Period) -> pd.Timestamp | None:
    d = cal[cal >= period.to_timestamp()]
    return d[0] if len(d) and d[0].to_period("M") == period else None


def px(sym: str, d: pd.Timestamp) -> tuple[float, pd.Timestamp] | None:
    b = dd.bars(sym)
    if b is None:
        return None
    s = b.close[:d]
    return (s.iloc[-1], s.index[-1]) if len(s) else None


_cache: dict[tuple[str, pd.Period, int], float | None] = {}


def fwd_raw(sym: str, period: pd.Period, h: int) -> float | None:
    """Raw buy-and-hold return, close(first td of t+1) -> close(first td of t+1+h)."""
    k = (sym, period, h)
    if k in _cache:
        return _cache[k]
    e, x = first_td(period + 1), first_td(period + 1 + h)
    r = None
    if e is not None and x is not None:
        pe, px_ = px(sym, e), px(sym, x)
        if pe and px_ and (e - pe[1]).days <= 5 and pe[1] <= px_[1]:
            r = px_[0] / pe[0] - 1
            tm = dd.terminal_returns().get(sym)
            if tm and px_[1] == tm[0] and px_[1] < x:  # bars stopped inside the window: apply deal terminal return
                r = (1 + r) * (1 + tm[1]) - 1
                _delist_applied.add(sym)
            elif (x - px_[1]).days > 7:
                _delist_missing.add(sym)
    _cache[k] = r
    return r


_delist_applied: set[str] = set()
_delist_missing: set[str] = set()


def fwd(sym: str, period: pd.Period, h: int) -> float | None:
    r, b = fwd_raw(sym, period, h), fwd_raw(dd.BENCH, period, h)
    return None if r is None or b is None else r - b


_ew: dict[tuple[pd.Period, int], float | None] = {}


def ew_bench(period: pd.Period, h: int) -> float | None:
    """Equal-weighted return of all PIT index members at formation (last day of month t)."""
    k = (period, h)
    if k not in _ew:
        m = dd.membership()
        d = period.to_timestamp(how="end").normalize()
        syms = m[(m.start <= d) & (m.end > d)].symbol.unique()
        rs = [fwd_raw(s, period, h) for s in syms]
        present = [r for r in rs if r is not None]
        _ew[k] = cast(float, np.mean(present)) if len(present) > 100 else None
    return _ew[k]


def fwd_ew(sym: str, period: pd.Period, h: int) -> float | None:
    r, b = fwd_raw(sym, period, h), ew_bench(period, h)
    return None if r is None or b is None else r - b


# ---- signals -----------------------------------------------------------------------------
groups = {
    "opp_buy": (tr.trans_code == "P") & (tr.cls == "opportunistic"),
    "routine_buy": (tr.trans_code == "P") & (tr.cls == "routine"),
    "all_buy": (tr.trans_code == "P"),
    "opp_sell": (tr.trans_code == "S") & (tr.cls == "opportunistic"),
    "routine_sell": (tr.trans_code == "S") & (tr.cls == "routine"),
}
ev_frames: list[pd.DataFrame] = []
for g, msk in groups.items():
    sm = (
        tr[msk]
        .groupby(["symbol", "fmonth"])
        .agg(
            n_trades=("trans_shares", "size"),
            value=("trans_shares", lambda s: float((s * tr.loc[s.index, "trans_pricepershare"]).sum())),
            n_insiders=("rptownercik", "nunique"),
        )
        .reset_index()
    )
    for h in HORIZONS:
        sm[f"xr{h}"] = [fwd(s, p, h) for s, p in zip(sm.symbol, sm.fmonth)]  # vs SPY (primary)
        sm[f"xe{h}"] = [fwd_ew(s, p, h) for s, p in zip(sm.symbol, sm.fmonth)]  # vs EW PIT S&P 500
    sm["group"] = g
    ev_frames.append(sm)
ev = pd.concat(ev_frames, ignore_index=True)
ev.to_csv(f"{dd.OUT}/events.csv", index=False)
# raw 1M returns for factor regressions
ev["rr1"] = [fwd_raw(s_, p, 1) for s_, p in zip(ev.symbol, ev.fmonth)]


def summarize(x: Any, months: Any, h: int) -> tuple[dict[str, Any], pd.Series]:
    x = pd.Series(x, dtype=float)
    ok = x.notna()
    x, months = x[ok], pd.Series(list(months))[ok.values]
    coh = x.groupby(months.values).mean()
    return dict(
        n_events=int(len(x)),
        n_months=int(len(coh)),
        hit_rate=round(float((x > 0).mean()), 3) if len(x) else None,
        mean_event=round(float(x.mean()), 5) if len(x) else None,
        t_event_month_clustered=round(float(dd.clustered_t(x.values, months.values)), 2) if len(coh) > 2 else None,
        mean_monthly_port=round(float(coh.mean()), 5) if len(coh) else None,
        port_hit_rate=round(float((coh > 0).mean()), 3) if len(coh) else None,
        t_port=round(float(dd.nw_t(coh.values, h - 1)), 2) if len(coh) > 2 else None,
    ), coh


res: dict[str, Any] = {}
ports: dict[tuple[str, str, int], pd.Series] = {}
for bm in ("xr", "xe"):
    for g in groups:
        for h in HORIZONS:
            e = ev[ev.group == g]
            res[f"{g}_{bm}{h}"], ports[(g, bm, h)] = summarize(e[f"{bm}{h}"].values, e.fmonth.astype(str).values, h)
for a, b in (("opp_buy", "routine_buy"), ("opp_buy", "opp_sell")):
    for h in HORIZONS:
        ls = (ports[(a, "xr", h)] - ports[(b, "xr", h)]).dropna()  # benchmark cancels in a long-short
        res[f"LS_{a}_minus_{b}_{h}m"] = dict(
            n_months=int(len(ls)),
            mean=round(float(ls.mean()), 5) if len(ls) else None,
            hit_rate=round(float((ls > 0).mean()), 3) if len(ls) else None,
            t=round(float(dd.nw_t(ls.values, h - 1)), 2) if len(ls) > 2 else None,
        )
# Fama-French 5 + momentum alpha (monthly). Cohort t is held ~month t+1 (first-td to first-td).
F = dd.ff("monthly")
F.index = cast(pd.DatetimeIndex, F.index).to_period("M")
X = F[["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]]


def cohort_raw(g: str) -> pd.Series:
    e = ev[ev.group == g].dropna(subset=["rr1"])
    c = e.groupby(e.fmonth.astype(str)).rr1.mean()
    c.index = pd.PeriodIndex(c.index, freq="M") + 1
    return c


for g in ("opp_buy", "routine_buy", "all_buy", "opp_sell"):
    c = cohort_raw(g)
    res[f"FF5Mom_alpha_{g}_1m"] = dd.ff_alpha(c - F.RF.reindex(c.index), X, 2)
for a_, b_ in (("opp_buy", "routine_buy"), ("opp_buy", "opp_sell")):
    c = (cohort_raw(a_) - cohort_raw(b_)).dropna()
    res[f"FF5Mom_alpha_LS_{a_}_minus_{b_}_1m"] = dd.ff_alpha(c, X, 2)
# subperiods for the headline series
for h in HORIZONS:
    for bm in ("xr", "xe"):
        p = ports[("opp_buy", bm, h)].copy()
        p.index = pd.PeriodIndex(p.index, freq="M")
        for lo, hi in (("2016-01", "2020-12"), ("2021-01", "2026-12")):
            q = p[(p.index >= pd.Period(lo, freq="M")) & (p.index <= pd.Period(hi, freq="M"))]
            res[f"opp_buy_{bm}{h}_{lo[:4]}-{hi[:4]}"] = dict(
                n_months=int(len(q)),
                mean=round(float(q.mean()), 5) if len(q) else None,
                t=round(float(dd.nw_t(q.values, h - 1)), 2) if len(q) > 2 else None,
            )
by_code_cls = {
    str(k): v
    for k, v in cast(
        dict[Any, int], tr.groupby(["trans_code", "cls"]).size().astype(int).rename(lambda x: str(x)).to_dict()
    ).items()
}
diag: dict[str, Any] = dict(
    trades_in_universe=int(len(tr)),
    by_code_cls=by_code_cls,
    map_via=tr.map_via.value_counts().to_dict(),
    symbols=int(tr.symbol.nunique()),
    filing_lag_days_median=float((tr.filing_date - tr.trans_date).dt.days.median()),
    filing_range=[str(tr.filing_date.min().date()), str(tr.filing_date.max().date())],
    variants_reported=len(res),
    mapping_misses_rows=int(miss.n_trade_rows.sum()),
    mapping_misses_issuers=miss.issuertradingsymbol.tolist(),
    delisting_terminal_return_applied=sorted(_delist_applied),
    delisted_in_window_no_terminal_return_last_close_used=sorted(_delist_missing),
    universe_mode=dd.UNIVERSE_MODE,
    terminal_returns_used=dd.USE_TERMINAL,
    drop_reuse=dd.DROP_REUSE,
    files_used=[
        dd.CURRENT if dd.UNIVERSE_MODE == "current" else "",
        dd.MEMBERSHIP,
        dd.UNIVERSE,
        dd.BARS_DIR,
        dd.TICKER_CIK,
        dd.DELISTING,
        "ref/company_tickers.json (SEC stopgap)",
    ],
)
json.dump(dict(diag=diag, results=res), open(f"{dd.OUT}/results.json", "w"), indent=1)
print(json.dumps(dict(diag=diag, results=res), indent=1))
