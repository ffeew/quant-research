"""PREREG-v3 engine: limits-compliant ETF trend sleeve (dollar NAV accounting, open fills, H6 stops, H8/H9 breakers).

Spec: PREREG-v3.md §3-§5 + the review's amendments A1-A6 (§9.A) + implementation clarifications (§9.B).
The v1/v2 engine (tsmom/engine.py) is untouched; this is a separate module.

Panel (all DataFrames indexed by session date, columns = symbols):
    tr      total-return index (splits + dividends)          -> P&L between closes
    open, high, low, close   raw as-traded OHLC (or split-adjusted; split days are detected either way)
    volume  shares
    rf      Series, daily risk-free rate (decimal per session)
Accounting: NAV = cash + sum(holdings$). Cash (incl. short proceeds) earns rf; borrow is charged on short MV
(calendar days / 360). Costs (TCA owner v1.1 trade_cost) and borrow reduce NAV. Daily excess return = NAV_k/NAV_k-1 - 1 - rf_k.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

sys.path.insert(0, f"{_QR.COSTS_DIR}")
from quant_research.backtest.costs import (
    cost_model as tca,  # TCA owner v1.1 (hash pinned in PREREG-v3 §2; verified by run_v3.py)
)

ANN = 252
EPS = 1e-12


class ATRUnavailable(RuntimeError):
    """Raised when a stop is needed but ATR(14) cannot be computed (no high/low). PREREG-v3 §9.B(8): abort."""


@dataclass(frozen=True)
class V3Config:
    name: str = "V3_PRIMARY"
    # signal / sizing (MOP 2012, HOP 2017 defaults)
    lookback: int = 252  # sessions (12 months)
    min_sig_obs: int = 252  # A3: >= 252 return observations for the signal
    min_vol_obs: int = 60  # A3: >= 60 observations for the EWMA
    vol_com: float = 60.0
    asset_vol_target: float = 0.40
    port_vol_target: float | None = 0.10
    allow_scale_up: bool = False  # H4: m = min(1, target / sigma_book)
    cov_window: int = 252
    cov_min: int = 60
    long_flat: tuple[str, ...] = ("USO",)  # pinned list (not shortable)
    # limits (portfolio-construction lead buffers; LIMITS §1)
    pos_cap: float | None = 0.095  # H1 buffer
    pos_hard: float = 0.10  # H1 hard (breach counter)
    risk_cap: float | None = 0.0095  # H2 buffer: |w| * stop_dist <= 0.95%
    gross_cap: float | None = 0.58  # H3 buffer
    gross_hard: float = 0.60  # H3 hard (breach counter)
    band_rel: float | None = 0.25
    band_abs: float = 0.005
    fill: str = "open"  # "open" (primary) | "close" (v2-equivalence unit test only)
    drift_trim: str = "next_open"  # "next_open" (primary) | "close" (v2-equivalence) | "off"
    # stops (H6)
    stops: bool = True
    atr_n: int = 14
    atr_mult: float = 2.0
    # breakers (H8/H9 + LIMITS §2a/§2b)
    breakers: bool = True
    h8_dd: float = 0.05
    h8_cap: float = 0.29  # buffer under 30%
    h8_hard: float = 0.30
    restore_dd: float = 0.03
    h9_dd: float = 0.08
    h9_min_days: int = 5
    shadow_days: int = 5
    intraday_breaker: bool = True  # A5: trips on live (intraday) NAV, conservative adverse-extreme bound
    # costs
    nav0: float = 100_000.0
    cost_nav_basis: float = 100_000.0  # §9.B(6): notional = |dw| * basis
    cost_mult: float = 1.0
    venue: str = "continuous"
    impact_k: float = 1.0
    borrow_rate: float = 0.01  # STANDARD floor
    split_tol: float = 1.3  # §9.B(7) heuristic: cross-check only (validation decision 9B-7)
    split_source: str = (
        "table"  # "table" = the data owner's corporate-action table (required for the run); "heuristic" = tests only
    )
    split_xcheck_tol: float = 0.05  # |log(implied / table factor)| tolerance on a table split day
    trim_venue: str = "continuous"  # H8 close trim costed at TCA owner venue "continuous"
    max_open_fallback: float = 0.005  # missing-open -> close fallback allowed on <= 0.5% of open-priced fills


class DataAbort(RuntimeError):
    """Pre-registered abort: the run stops rather than invent data (§9.B(7), §9.B(8))."""


class SplitMismatch(DataAbort):
    pass


class SplitTableMissing(DataAbort):
    pass


class OHLCUnavailable(DataAbort):
    pass


class OpenFallbackExceeded(DataAbort):
    pass


FROZEN_BREAKER = dict(
    h8_dd=0.05,
    h8_cap=0.29,
    h8_hard=0.30,
    restore_dd=0.03,
    h9_dd=0.08,
    h9_min_days=5,
    shadow_days=5,
    intraday_breaker=True,
)  # §5/§9.A A5/§9.B(1), frozen; LIMITS v0.3.x NOT adopted


def month_ends(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    s = pd.Series(idx, index=idx)
    return pd.DatetimeIndex(s.groupby(idx.to_period("M")).max().values)


def split_ratios(tr: pd.DataFrame, close: pd.DataFrame, tol: float) -> pd.DataFrame:
    """Implied raw-price split factor per day (1.0 on normal days). >1 = reverse split (price up), <1 = forward split."""
    raw_r = close / close.shift(1)
    tr_r = tr / tr.shift(1)
    s = raw_r / tr_r
    flag = (np.log(s.abs()) > np.log(tol)) | (np.log(s.abs()) < -np.log(tol))
    return s.where(flag & s.notna(), 1.0).fillna(1.0)


def split_matrix_from_table(
    table: pd.DataFrame | None, tr: pd.DataFrame, close: pd.DataFrame, tol_heur: float, tol_x: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """§9.B(7) as amended: splits come from the data owner's corporate-action table (columns symbol, date, price_factor, where
    price_factor = raw price after / before, e.g. 2-for-1 -> 0.5, 1-for-8 reverse -> 8). The >30% raw-vs-TR heuristic is a
    cross-check only; any mismatch aborts. Returns (split factor matrix, applied-splits DataFrame)."""
    syms = list(close.columns)
    implied = (close / close.shift(1)) / (tr / tr.shift(1))
    S = pd.DataFrame(1.0, index=close.index, columns=syms)
    t = table.copy() if table is not None else pd.DataFrame(columns=["symbol", "date", "price_factor"])
    t["date"] = pd.to_datetime(t["date"])
    t = t[t.symbol.isin(syms)]
    problems: list[str] = []
    applied: list[dict[str, Any]] = []
    for r in t.itertuples():
        symbol = cast(str, r.symbol)
        when = cast(pd.Timestamp, r.date)
        factor = cast(float, r.price_factor)
        f = float(factor)
        if not (np.isfinite(f) and f > 0):
            problems.append(f"{symbol} {when.date()}: bad factor {factor}")
            continue
        if when not in S.index:
            first = cast(pd.Timestamp | None, tr[symbol].first_valid_index())
            last = cast(pd.Timestamp, tr[symbol].last_valid_index())
            if first is not None and first < when <= last:
                problems.append(f"{symbol} {when.date()}: table split date is not a session in the build")
            continue
        imp = cast(float, implied.at[when, symbol])
        if not np.isfinite(imp) or abs(np.log(imp / f)) > tol_x:
            problems.append(f"{symbol} {when.date()}: table factor {f:g} vs implied raw/TR {imp:.4f}")
        S.at[when, symbol] = f
        applied.append(
            {
                "symbol": symbol,
                "date": when,
                "price_factor": f,
                "implied_raw_over_tr": float(imp),
                "source": getattr(r, "source", "table"),
            }
        )
    heur = (np.log(implied.abs()) > np.log(tol_heur)) | (np.log(implied.abs()) < -np.log(tol_heur))
    heur = heur & implied.notna()
    for dte, sym in zip(*np.nonzero(cast(np.ndarray, heur.values))):
        if S.iat[dte, sym] == 1.0:
            session = cast(pd.Timestamp, S.index[dte])
            implied_cell = cast(float, implied.iat[dte, sym])
            problems.append(f"{syms[sym]} {session.date()}: heuristic split {implied_cell:.4f} not in the table")
    if problems:
        raise SplitMismatch(
            "split source (CA table from 2016-01-05, Yahoo before) vs raw/TR cross-check mismatch (run aborts, C7): "
            + "; ".join(problems)
        )
    return S, pd.DataFrame(applied, columns=["symbol", "date", "price_factor", "implied_raw_over_tr", "source"])


def atr_pct(
    o: pd.DataFrame, h: pd.DataFrame, l: pd.DataFrame, c: pd.DataFrame, split: pd.DataFrame, n: int
) -> pd.DataFrame:
    """Desk H6 convention (portfolio/construct.py): simple mean of the last n true ranges, on split-adjusted OHLC,
    divided by the (split-adjusted) close. Dividends are NOT adjusted (a resting stop is not)."""
    F = split.cumprod()
    H, L, C = h / F, l / F, c / F
    pc = C.shift(1)
    trng = pd.concat({"a": H - L, "b": (H - pc).abs(), "c": (L - pc).abs()}, axis=1)
    trng = trng.T.groupby(level=1).max().T if isinstance(trng.columns, pd.MultiIndex) else trng
    trng = trng[c.columns]
    # require all n bars to have high/low data
    a = trng.rolling(n, min_periods=n).mean()
    return a / C


def precompute(panel: dict[str, Any], syms: list[str], cfg: V3Config) -> dict[str, Any]:
    tr = panel["tr"][syms]
    c = panel["close"][syms]
    o = panel["open"][syms]
    h = panel["high"][syms]
    l = panel["low"][syms]
    v = panel["volume"][syms]
    rf = panel["rf"]
    R = tr.pct_change(fill_method=None)
    RX = R.sub(rf, axis=0)
    vol = np.sqrt(RX.ewm(com=cfg.vol_com, min_periods=cfg.min_vol_obs, ignore_na=False).var() * ANN)
    n_ret = RX.notna().cumsum()
    logx = np.log1p(RX.fillna(0.0))
    cumx = logx.cumsum()
    if cfg.split_source == "table":
        if panel.get("splits") is None:
            raise SplitTableMissing("split_source='table' but the panel carries no corporate-action table")
        split, applied = split_matrix_from_table(panel["splits"], tr, c, cfg.split_tol, cfg.split_xcheck_tol)
    elif cfg.split_source == "heuristic":
        split = split_ratios(tr, c, cfg.split_tol)
        st = cast(pd.Series, split.stack())
        st = st[st != 1.0]
        applied_rows: list[dict[str, Any]] = []
        for key, v_ in st.items():
            d_, s_ = cast(tuple[Any, Any], key)
            factor = cast(float, v_)
            applied_rows.append(
                {"symbol": s_, "date": d_, "price_factor": float(factor), "implied_raw_over_tr": float(factor)}
            )
        applied = pd.DataFrame(
            applied_rows,
            columns=["symbol", "date", "price_factor", "implied_raw_over_tr"],
        )
    else:
        raise ValueError(cfg.split_source)
    atrp = atr_pct(o, h, l, c, split, cfg.atr_n)
    adv = v.rolling(20, min_periods=10).mean().shift(1)
    sd20 = R.rolling(20, min_periods=10).std().shift(1)
    return dict(
        tr=tr,
        c=c,
        o=o,
        h=h,
        l=l,
        R=R,
        RX=RX,
        vol=vol,
        n_ret=n_ret,
        cumx=cumx,
        split=split,
        atrp=atrp,
        adv=adv,
        sd20=sd20,
        rf=rf,
        splits_applied=applied,
    )


def signal_targets(
    pc: dict[str, Any], syms: list[str], cfg: V3Config, i: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Targets known at close of session i (month-end). Returns (w_target pre-gross-cap, stop_dist d, live mask)."""
    RX, vol, n_ret, cumx = pc["RX"], pc["vol"], pc["n_ret"], pc["cumx"]
    nS = len(syms)
    # A3: live once >= min_sig_obs return observations (signal) and >= min_vol_obs for the EWMA (vol not NaN)
    live = (
        (n_ret.iloc[i] >= max(cfg.min_sig_obs, cfg.min_vol_obs)) & vol.iloc[i].notna() & pc["tr"].iloc[i].notna()
    ).values
    w = np.zeros(nS)
    d = np.full(nS, np.nan)
    if i - cfg.lookback < 0 or live.sum() == 0:
        return w, d, cast(np.ndarray, live)
    sig = np.sign((cumx.iloc[i] - cumx.iloc[i - cfg.lookback]).values)
    for a, s in enumerate(syms):
        if s in cfg.long_flat:
            sig[a] = max(sig[a], 0.0)
    sig = np.where(live, sig, 0.0)
    nl = int(live.sum())
    raw = np.where(live, sig * cfg.asset_vol_target / vol.iloc[i].values, 0.0) / nl
    raw = np.nan_to_num(raw)
    if cfg.port_vol_target is not None and np.abs(raw).sum() > 0:
        lv = np.nonzero(live)[0]
        win = RX.iloc[max(0, i - cfg.cov_window + 1) : i + 1].iloc[:, lv]
        cov = win.cov(min_periods=cfg.cov_min).fillna(0.0).values * ANN
        pv = float(np.sqrt(max(raw[lv] @ cov @ raw[lv], 0.0)))
        if pv > 0:
            m = cfg.port_vol_target / pv
            if not cfg.allow_scale_up:
                m = min(1.0, m)
            raw = raw * m
    if cfg.stops:
        d = cfg.atr_mult * pc["atrp"].iloc[i].values
        need = (np.abs(raw) > 0) & ~np.isfinite(d)
        if need.any():
            raise ATRUnavailable(
                f"ATR({cfg.atr_n}) unavailable on {pc['tr'].index[i].date()} for "
                f"{[syms[a] for a in np.nonzero(need)[0]]}: high/low data missing"
            )
    if cfg.pos_cap is not None:
        raw = np.clip(raw, -cfg.pos_cap, cfg.pos_cap)
    if cfg.risk_cap is not None and cfg.stops:
        lim = np.where(np.isfinite(d) & (d > 0), cfg.risk_cap / np.where(d > 0, d, 1.0), np.inf)
        raw = np.sign(raw) * np.minimum(np.abs(raw), lim)
    return cast(np.ndarray, raw), cast(np.ndarray, d), cast(np.ndarray, live)


def _cap_gross(w: np.ndarray, cap: float | None) -> np.ndarray:
    if cap is None:
        return w
    g = np.abs(w).sum()
    return w * (cap / g) if g > cap + EPS else w


def run(
    panel: dict[str, Any], symbols: list[str], cfg: V3Config, shadow_nav: pd.Series | None = None
) -> dict[str, Any]:
    syms = [s for s in symbols if s in panel["tr"].columns]
    missing = [s for s in symbols if s not in panel["tr"].columns]
    if missing:
        raise ValueError(f"pinned universe symbols missing from panel: {missing}")
    if cfg.breakers and shadow_nav is None:
        from dataclasses import replace

        shadow_nav = run(panel, syms, replace(cfg, name=cfg.name + "_shadow", breakers=False))["daily"]["nav"]
    pc = precompute(panel, syms, cfg)
    idx = pc["tr"].index
    n = len(idx)
    nS = len(syms)
    _TRv = pc["tr"].values
    Rv = pc["R"].values
    Ov, Hv, Lv, Cv = pc["o"].values, pc["h"].values, pc["l"].values, pc["c"].values
    SPLv = pc["split"].values
    ADVv = pc["adv"].values
    SDv = pc["sd20"].values
    rfv = pc["rf"].reindex(idx).fillna(0.0).values
    shadow = shadow_nav.reindex(idx).values if shadow_nav is not None else None

    me = month_ends(idx)
    pos = {t: k for k, t in enumerate(idx)}
    fill_at = {}  # fill session k -> (signal session i)
    for t in me:
        i = pos[t]
        k = i + 1  # both open and close fills land on the next session
        if k < n:
            fill_at[k] = i
    sig_cache: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    h = np.zeros(nS)
    cash = cfg.nav0
    nav = cfg.nav0
    hwm = cfg.nav0
    stop = np.full(nS, np.nan)
    stopped_day = np.full(nS, -1)
    pending_trim = False
    h8 = False
    halted = False
    h8_armed = True
    h9_armed = True
    halt_day = -1
    rec = {
        k_: np.zeros(n)
        for k_ in [
            "nav",
            "cash",
            "gross_lev",
            "net_lev",
            "long_mv",
            "short_mv",
            "cost",
            "borrow",
            "dd",
            "hwm",
            "worst_dd_intraday",
            "h8",
            "halted",
            "n_pos",
            "n_live",
            "turnover",
            "pnl_long",
            "pnl_short",
            "rf",
            "breach_pos_hard",
            "breach_gross_hard",
            "unstopped_positions",
            "gross_post_open",
            "pos_post_open",
            "is_fill",
        ]
    }
    contrib = np.zeros((n, nS))
    W = np.zeros((n, nS))
    STOP = np.full((n, nS), np.nan)
    trades = []
    events = []
    h2_log = []
    loosen_violations = 0
    flows = np.zeros(nS)
    n_live_last = 0
    no_open_today = np.zeros(nS, bool)

    def exec_trade(
        a: int,
        dv: float,
        price: float,
        k: int,
        reason: str,
        nav_now: float,
        venue: str | None = None,
        at: str = "open",
    ) -> float:
        nonlocal cash
        if abs(dv) < 1e-9 or not np.isfinite(price) or price <= 0:
            return 0.0
        dw = abs(dv) / nav_now
        notional = dw * cfg.cost_nav_basis
        adv = ADVv[k, a] if np.isfinite(ADVv[k, a]) and ADVv[k, a] > 0 else None
        sd = SDv[k, a] if np.isfinite(SDv[k, a]) else None
        side = "buy" if dv > 0 else "sell"
        before, after = h[a], h[a] + dv
        kind = (
            "entry"
            if before == 0
            else "exit"
            if abs(after) < 1e-9
            else "flip"
            if np.sign(before) != np.sign(after)
            else "resize"
        )
        venue = venue or cfg.venue
        fb = bool(at in ("open", "intraday") and no_open_today[a])
        tc = tca.trade_cost(
            side, price, notional / price, adv, sd, None, k=cfg.impact_k, venue=venue, trade_date=idx[k].date()
        )
        bps = tc["total_bps"] * cfg.cost_mult
        cst = dw * bps / 1e4 * nav_now
        cash -= dv + cst
        h[a] += dv
        flows[a] += dv
        pct_adv = notional / (adv * price) if adv else np.nan
        trades.append(
            (
                idx[k],
                syms[a],
                reason,
                kind,
                side,
                float(price),
                float(dv),
                float(dw),
                float(notional),
                float(bps),
                float(cst),
                tc["bucket"],
                float(pct_adv),
                venue,
                at,
                fb,
            )
        )
        return cst

    def set_stop(a: int, new: float, k: int, why: str) -> None:
        nonlocal loosen_violations
        old = stop[a]
        if np.isfinite(old) and np.isfinite(new):
            if (h[a] > 0 and new < old - 1e-12) or (h[a] < 0 and new > old + 1e-12):
                loosen_violations += 1
        stop[a] = new
        events.append((idx[k], syms[a], "stop_" + why, float(new) if np.isfinite(new) else np.nan))

    def stop_exit(
        a: int, px_fill: float, k: int, reason: str, nav_now: float, value_now: float, at: str = "open"
    ) -> float:
        # value_now: holding $ marked at px_fill
        h[a] = value_now
        cst = exec_trade(a, -h[a], px_fill, k, reason, nav_now, at=at)
        h[a] = 0.0
        stop[a] = np.nan
        stopped_day[a] = k
        return cst

    for k in range(n):
        cost_today = 0.0
        borrow_today = 0.0
        turn_today = 0.0
        flows[:] = 0.0
        if k == 0:
            rec["nav"][0] = nav
            rec["hwm"][0] = hwm
            rec["cash"][0] = cash
            continue
        _nav_prev = nav
        days = (idx[k] - idx[k - 1]).days
        short_mv = -h[h < 0].sum()
        borrow_today = short_mv * cfg.borrow_rate * days / 360.0
        cash = cash * (1 + rfv[k]) - borrow_today
        # split adjustment of resting stop levels (raw price terms)
        spl = SPLv[k]
        for a in range(nS):
            if spl[a] != 1.0 and np.isfinite(stop[a]):
                stop[a] = stop[a] * spl[a]
                events.append((idx[k], syms[a], "stop_split_adjust", float(stop[a])))
        # ---- overnight mark to the open ----
        r = Rv[k]
        o = Ov[k].copy()
        c = Cv[k]
        hi = Hv[k]
        lo = Lv[k]
        has_tr = np.isfinite(r)
        no_open = ~np.isfinite(o)
        no_open_today[:] = no_open
        o = np.where(no_open, c, o)
        has_hl = np.isfinite(hi) & np.isfinite(lo)
        # §9.B(8) as ruled: no OHLC fallback is pre-granted -- a held position needs close, high and low every session
        bad = (h != 0) & has_tr & (~np.isfinite(c) | ~has_hl)
        if bad.any():
            raise OHLCUnavailable(
                f"OHLC missing on {idx[k].date()} for held {[syms[a] for a in np.nonzero(bad)[0]]} "
                f"(no fallback pre-granted)"
            )
        g_on = np.where(has_tr, (1 + np.nan_to_num(r)) * np.where(np.isfinite(o / c), o / c, 1.0), 1.0)
        g_oc = np.where(has_tr & np.isfinite(c / o), c / o, 1.0)
        h_prev = h.copy()
        h = h * g_on
        nav_open_pre = cash + h.sum()
        # ---- open: pending close-fallback exits, then gap stops ----
        for a in range(nS):
            if h[a] == 0 or not has_tr[a]:
                continue
            if (
                cfg.stops
                and np.isfinite(stop[a])
                and ((h[a] > 0 and o[a] <= stop[a]) or (h[a] < 0 and o[a] >= stop[a]))
            ):
                cost_today += stop_exit(a, o[a], k, "stop_gap_open", nav_open_pre, h[a])
        _nav_open = cash + h.sum()
        # ---- open: rebalance fill or pending drift trim ----
        is_fill = k in fill_at
        cap_now = cfg.h8_cap if (cfg.breakers and h8) else cfg.gross_cap

        def do_rebalance(price_vec: np.ndarray, k: int, at_: str = "open") -> None:
            nonlocal cost_today, turn_today, n_live_last
            i = fill_at[k]
            if i not in sig_cache:
                sig_cache[i] = signal_targets(pc, syms, cfg, i)
            tgt, d, live = sig_cache[i]
            tgt = tgt.copy()
            n_live_last = int(live.sum())
            navx = cash + h.sum()
            cur = h / navx
            tgt[stopped_day == k] = 0.0  # §9.B(3)
            if halted:  # H9: no new positions, no adds
                for a in range(nS):
                    if cur[a] == 0 or np.sign(tgt[a]) != np.sign(cur[a]):
                        tgt[a] = 0.0
                    else:
                        tgt[a] = np.sign(cur[a]) * min(abs(tgt[a]), abs(cur[a]))
            tgt = _cap_gross(tgt, cap_now)
            if cfg.band_rel is not None:
                for a in range(nS):
                    if np.sign(tgt[a]) == np.sign(cur[a]) and abs(tgt[a] - cur[a]) <= max(
                        cfg.band_rel * abs(tgt[a]), cfg.band_abs
                    ):
                        tgt[a] = cur[a]
            tgt = _cap_gross(tgt, cap_now)
            prev_sign = np.sign(h)
            for a in range(nS):
                dv = tgt[a] * navx - h[a]
                if abs(dv) > 1e-9:
                    turn_today += abs(dv) / navx
                    cost_today += exec_trade(a, dv, price_vec[a], k, "rebalance", navx, at=at_)
                if cfg.stops:
                    p = price_vec[a]
                    if h[a] == 0:
                        if np.isfinite(stop[a]):
                            stop[a] = np.nan
                        continue
                    sg = np.sign(h[a])
                    cand = p * (1 - sg * d[a]) if np.isfinite(d[a]) else np.nan
                    if prev_sign[a] != sg:  # new entry (or flip)
                        if not np.isfinite(cand):
                            raise ATRUnavailable(f"no stop distance for new {syms[a]} entry on {idx[k].date()}")
                        stop[a] = np.nan
                        set_stop(a, cand, k, "entry")
                    elif np.isfinite(cand):  # kept: tighten only
                        new = max(stop[a], cand) if sg > 0 else min(stop[a], cand)
                        if not np.isfinite(stop[a]):
                            new = cand
                        if new != stop[a]:
                            set_stop(a, new, k, "tighten")
                    if np.isfinite(stop[a]) and abs(dv) > 1e-9:
                        navy = cash + h.sum()
                        h2_log.append((idx[k], syms[a], abs(h[a]) / navy * abs(p - stop[a]) / p))

        if is_fill and cfg.fill == "open":
            do_rebalance(o, k)
            pending_trim = False
        elif pending_trim and cfg.drift_trim == "next_open":
            navx = cash + h.sum()
            w = h / navx
            tgt = w.copy()
            if cfg.pos_cap is not None:
                tgt = np.clip(tgt, -cfg.pos_cap, cfg.pos_cap)
            tgt = _cap_gross(tgt, cap_now)
            for a in range(nS):
                dv = (tgt[a] - w[a]) * navx
                if abs(dv) > 1e-9:
                    turn_today += abs(dv) / navx
                    cost_today += exec_trade(a, dv, o[a], k, "drift_trim", navx)
            pending_trim = False
        # ---- intraday: stops (A5: worse of stop and open; stop assumed first) ----
        h_post_open = h.copy()
        rec["gross_post_open"][k] = np.abs(h).sum() / max(cash + h.sum(), 1e-9)
        rec["pos_post_open"][k] = np.abs(h).max() / max(cash + h.sum(), 1e-9)
        rec["is_fill"][k] = is_fill
        bad = (h != 0) & has_tr & ~has_hl
        if bad.any():
            raise OHLCUnavailable(
                f"high/low missing on {idx[k].date()} for position {[syms[a] for a in np.nonzero(bad)[0]]} "
                f"opened/held this session (no fallback pre-granted)"
            )
        for a in range(nS):
            if h[a] == 0 or not cfg.stops or not np.isfinite(stop[a]) or not has_tr[a]:
                continue
            if h[a] > 0 and lo[a] <= stop[a]:
                px = min(stop[a], o[a])
                cost_today += stop_exit(a, px, k, "stop_intraday", cash + h.sum(), h[a] * px / o[a], at="intraday")
            elif h[a] < 0 and hi[a] >= stop[a]:
                px = max(stop[a], o[a])
                cost_today += stop_exit(a, px, k, "stop_intraday", cash + h.sum(), h[a] * px / o[a], at="intraday")
        _stopped_intraday = (h_post_open != 0) & (h == 0)
        # conservative live-NAV bound (A5): remaining positions at adverse extremes
        ext = np.where(h > 0, np.where(has_hl, lo, c), np.where(has_hl, hi, c))
        worst = cash + np.sum(np.where(h != 0, h * np.where(np.isfinite(ext / o), ext / o, 1.0), 0.0))
        worst = min(worst, nav_open_pre)
        h = h * g_oc
        if is_fill and cfg.fill == "close":
            do_rebalance(c, k, at_="close")
        nav = cash + h.sum()
        # ---- breakers: intraday trip check (A5, LIMITS §1) ----
        dd_live = 1 - (worst if cfg.intraday_breaker else nav) / hwm
        if cfg.breakers:
            tripped = False
            if h9_armed and dd_live >= cfg.h9_dd - EPS:
                halted = True
                halt_day = k
                h9_armed = False
                if not h8:
                    h8 = True
                    h8_armed = False
                tripped = True
                events.append((idx[k], "BOOK", "H9_halt", float(dd_live)))
            elif h8_armed and dd_live >= cfg.h8_dd - EPS:
                h8 = True
                h8_armed = False
                tripped = True
                events.append((idx[k], "BOOK", "H8_halve", float(dd_live)))
            for _rep in range(3):  # repeat: the trim's own cost lowers NAV slightly
                if not (h8 and np.abs(h).sum() / nav > cfg.h8_cap + (EPS if _rep == 0 else 1e-4)):
                    break
                if True:
                    # reduce to <= 29% by today's close, largest risk-to-stop first (LIMITS §2a)
                    navx = nav
                    excess = np.abs(h).sum() - cfg.h8_cap * navx
                    rts = np.array(
                        [abs(h[a]) * (abs(c[a] - stop[a]) / c[a] if np.isfinite(stop[a]) else 1.0) for a in range(nS)]
                    )
                    for a in np.argsort(-rts):
                        if excess <= 1e-9:
                            break
                        if h[a] == 0:
                            continue
                        cut = min(abs(h[a]), excess)
                        dv = -np.sign(h[a]) * cut
                        turn_today += cut / navx
                        cost_today += exec_trade(a, dv, c[a], k, "breaker_trim", navx, venue=cfg.trim_venue, at="close")
                        excess -= cut
                        if h[a] == 0:
                            stop[a] = np.nan
                    nav = cash + h.sum()
        # ---- close-mode drift trim (v2-equivalence only) ----
        if (
            cfg.drift_trim == "close"
            and not is_fill
            and cfg.gross_cap is not None
            and np.abs(h).sum() / nav > cfg.gross_cap + EPS
        ):
            navx = nav
            tgt = _cap_gross(h / navx, cfg.gross_cap)
            for a in range(nS):
                dv = tgt[a] * navx - h[a]
                if abs(dv) > 1e-9:
                    turn_today += abs(dv) / navx
                    cost_today += exec_trade(a, dv, c[a], k, "drift_trim", navx, at="close")
            nav = cash + h.sum()
        # ---- EOD ----
        hwm = max(hwm, nav)
        dd = 1 - nav / hwm  # A6: NAV drawdown
        if cfg.breakers:
            if (
                h8 and not halted and not tripped and dd < cfg.restore_dd
            ):  # §9.B(1): first check at the EOD after the trip
                h8 = False
                h8_armed = True
                events.append((idx[k], "BOOK", "H8_restore", float(dd)))
            if (
                halted
                and (k - halt_day) >= cfg.h9_min_days
                and shadow is not None
                and k - cfg.shadow_days >= 0
                and np.isfinite(shadow[k])
                and np.isfinite(shadow[k - cfg.shadow_days])
                and shadow[k] / shadow[k - cfg.shadow_days] - 1 >= 0
            ):
                halted = False
                events.append((idx[k], "BOOK", "H9_lift", float(dd)))
            if not halted and not h9_armed and dd < cfg.h9_dd:
                h9_armed = True
        w = h / nav
        g = np.abs(w).sum()
        cap_hard_now = cfg.h8_hard if (cfg.breakers and h8) else cfg.gross_hard
        if cfg.drift_trim == "next_open":
            # §9.B(4): trigger halfway between buffer and hard limit; trade back to the buffer at the next open
            capb = cfg.h8_cap if (cfg.breakers and h8) else cfg.gross_cap
            if (cfg.pos_cap is not None and np.abs(w).max() > 0.5 * (cfg.pos_cap + cfg.pos_hard) + 1e-9) or (
                capb is not None and g > 0.5 * (capb + cap_hard_now) + 1e-9
            ):
                pending_trim = True
        # records
        contrib[k] = h - h_prev - flows - rfv[k] * h_prev  # excess price P&L $ per asset (ex trade flows)
        sgn = np.where(h_prev != 0, np.sign(h_prev), np.sign(flows))
        rec["pnl_long"][k] = contrib[k][sgn > 0].sum()
        rec["pnl_short"][k] = contrib[k][sgn < 0].sum()
        rec["nav"][k] = nav
        rec["cash"][k] = cash
        rec["gross_lev"][k] = g
        rec["net_lev"][k] = w.sum()
        rec["long_mv"][k] = h[h > 0].sum()
        rec["short_mv"][k] = -h[h < 0].sum()
        rec["cost"][k] = cost_today
        rec["borrow"][k] = borrow_today
        rec["dd"][k] = dd
        rec["hwm"][k] = hwm
        rec["worst_dd_intraday"][k] = dd_live
        rec["h8"][k] = h8
        rec["halted"][k] = halted
        rec["n_pos"][k] = int((h != 0).sum())
        rec["n_live"][k] = n_live_last
        rec["turnover"][k] = turn_today
        rec["rf"][k] = rfv[k]
        rec["breach_pos_hard"][k] = np.abs(w).max() > cfg.pos_hard + 1e-9
        rec["breach_gross_hard"][k] = g > cap_hard_now + 1e-9
        rec["unstopped_positions"][k] = int(((h != 0) & ~np.isfinite(stop)).sum()) if cfg.stops else 0
        W[k] = w
        STOP[k] = stop
    daily = pd.DataFrame(rec, index=idx)
    daily["ret"] = daily["nav"] / daily["nav"].shift(1) - 1
    daily["net"] = daily["ret"] - daily["rf"]  # excess, net of costs and borrow
    daily["gross"] = daily["net"] + (daily["cost"] + daily["borrow"]) / daily["nav"].shift(1)
    first = next(
        (idx[k] for k in sorted(fill_at) if np.abs(sig_cache.get(fill_at[k], (np.zeros(1),))[0]).sum() > 0), None
    )
    tr_df = pd.DataFrame(
        trades,
        columns=[
            "date",
            "symbol",
            "reason",
            "kind",
            "side",
            "price",
            "dv_usd",
            "dw",
            "notional_basis_usd",
            "cost_bps_1way",
            "cost_usd",
            "bucket",
            "pct_adv20",
            "venue",
            "at",
            "open_fallback",
        ],
    )
    out_daily = daily.loc[first:] if first is not None else daily.iloc[0:0]
    open_px = tr_df[tr_df["at"].isin(["open", "intraday"])]
    ofb = {
        "open_priced_fills": int(len(open_px)),
        "fallback_fills": int(open_px.open_fallback.sum()),
        "share": float(open_px.open_fallback.mean()) if len(open_px) else 0.0,
        "limit": cfg.max_open_fallback,
    }
    if cfg.max_open_fallback is not None and ofb["share"] > cfg.max_open_fallback + 1e-12:
        raise OpenFallbackExceeded(
            f"missing-open fallback on {ofb['fallback_fills']}/{ofb['open_priced_fills']} open-priced "
            f"fills ({ofb['share']:.2%}) > {cfg.max_open_fallback:.1%}"
        )
    return {
        "daily": out_daily,
        "daily_full": daily,
        "contrib_usd": pd.DataFrame(contrib, index=idx, columns=syms),
        "weights": pd.DataFrame(W, index=idx, columns=syms),
        "stops": pd.DataFrame(STOP, index=idx, columns=syms),
        "trades": tr_df,
        "events": pd.DataFrame(events, columns=["date", "symbol", "event", "value"]),
        "h2_log": pd.DataFrame(h2_log, columns=["date", "symbol", "risk_to_stop_nav"]),
        "loosen_violations": loosen_violations,
        "first_fill": first,
        "cfg": asdict(cfg),
        "symbols": syms,
        "splits_applied": pc["splits_applied"],
        "open_fallback": ofb,
    }


def limits_compliance(o: dict[str, Any], max_breach_share: float = 0.01) -> dict[str, Any]:
    """Criterion 7.9 as ruled (9B-4): every order compliant; every EOD buffer-trigger or hard-limit breach cured at the
    next open; hard breaches listed with dates; 7.9 fails if hard breaches occur on > 1% of sessions."""
    cfg = o["cfg"]
    d = o["daily_full"]
    if o["first_fill"] is not None:
        d = d.loc[o["first_fill"] :]
    n = len(d)
    idx = d.index
    hard = (d.breach_pos_hard > 0) | (d.breach_gross_hard > 0)
    pos_trig = 0.5 * (cfg["pos_cap"] + cfg["pos_hard"]) if cfg["pos_cap"] is not None else np.inf
    w = o["weights"].loc[idx].abs()
    rows, uncured = [], []
    for j in range(n - 1):
        halved = bool(d.h8.iloc[j]) and cfg["breakers"]
        cap_b = cfg["h8_cap"] if halved else cfg["gross_cap"]
        cap_h = cfg["h8_hard"] if halved else cfg["gross_hard"]
        if cap_b is None:
            continue
        trig = (w.iloc[j].max() > pos_trig + 1e-9) or (d.gross_lev.iloc[j] > 0.5 * (cap_b + cap_h) + 1e-9)
        if not (trig or hard.iloc[j]):
            continue
        nx = d.iloc[j + 1]
        cured = (nx.pos_post_open <= (cfg["pos_cap"] or np.inf) * 1.001 + 1e-9) and (
            nx.gross_post_open <= cap_b * 1.001 + 1e-9
        )
        rows.append(
            {
                "date": idx[j],
                "kind": "hard" if hard.iloc[j] else "buffer",
                "max_w": float(w.iloc[j].max()),
                "gross": float(d.gross_lev.iloc[j]),
                "cure_session": idx[j + 1],
                "post_open_max_w": float(nx.pos_post_open),
                "post_open_gross": float(nx.gross_post_open),
                "cured": bool(cured),
            }
        )
        if not cured:
            uncured.append(idx[j])
    br = pd.DataFrame(
        rows, columns=["date", "kind", "max_w", "gross", "cure_session", "post_open_max_w", "post_open_gross", "cured"]
    )
    n_hard = int(hard.sum())
    share = n_hard / n if n else 0.0
    orders_ok = (
        int(d.unstopped_positions.sum()) == 0
        and o["loosen_violations"] == 0
        and (o["h2_log"].risk_to_stop_nav.max() <= (cfg["risk_cap"] or np.inf) + 1e-9 if len(o["h2_log"]) else True)
        and int((d.long_mv > d.nav + 1e-6).sum()) == 0
    )
    return {
        "sessions": n,
        "hard_breach_sessions": n_hard,
        "hard_breach_share": share,
        "hard_breach_dates": [str(x.date()) for x in idx[hard.values]],
        "uncured": [str(x.date()) for x in uncured],
        "orders_ok": bool(orders_ok),
        "max_share": max_breach_share,
        "pass": bool(orders_ok and not uncured and share <= max_breach_share),
        "breaches": br,
    }
