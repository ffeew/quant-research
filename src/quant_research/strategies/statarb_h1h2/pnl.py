"""Execution lag, costs, borrow, terminal / delisting treatments and Sharpe. Gated by the runner."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from quant_research.backtest.costs import cost_model as cm

from .frames import at_float, iloc_int
from .guards import Blocked
from .splits import (
    AUM,
    BORROW_UNKNOWN_REQUIRED,
    ETFS,
    H1_TERMINAL_PATHS,
    H2_DELISTING_STRESS_LONG,
    H2_DELISTING_STRESS_SHORT,
    PARTICIPATION_CAP,
)


def tradable_mask(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """THE one tradable-print definition, used everywhere (fills, forced cuts and settlements,
    stress, the H1 tau / trusted print and bound, the suspension check, H2 receipts, last print,
    and the gross a held name earns): a session is a print for a name when its close is present
    and > 0 AND its volume is present and > 0 AND it is not forward-filled (bars["FFILL"], when
    supplied; a missing flag counts as forward-filled). A close with zero volume is not a print."""
    PX = bars["PX"]
    VOL = bars["VOL"].reindex(index=PX.index, columns=PX.columns)
    m = PX.notna() & PX.gt(0) & VOL.notna() & VOL.gt(0)
    if "FFILL" in bars:
        ff = bars["FFILL"].reindex(index=PX.index, columns=PX.columns)
        m &= ~ff.fillna(True).astype(bool)
    return m.astype(bool)


def last_print_index(bars: dict[str, pd.DataFrame], s: str, tp: pd.DataFrame | None = None) -> int:
    """Row of the last tradable print of s (tradable_mask), or -1 when it never printed."""
    tp = tradable_mask(bars) if tp is None else tp
    if s not in tp.columns:
        return -1
    idx = np.flatnonzero(tp[s].to_numpy(dtype=bool))
    return int(idx[-1]) if len(idx) else -1


def require_aligned(bars: dict[str, pd.DataFrame], W: pd.DataFrame) -> None:
    """Fail closed when a weight session is not a price session (it would silently never fill)."""
    missing = W.index.difference(bars["PX"].index)
    if len(missing):
        raise Blocked(f"BLOCK: {len(missing)} weight session(s) not in the price index, e.g. {missing[0]!r}.")


def _any(v: Any) -> Any:
    """pd.Timestamp(None) is NaT at runtime; the stubs reject None."""
    return v


@dataclass(frozen=True)
class CostConfig:
    label: str = "unknown_borrow_required"
    borrow_rate: float = BORROW_UNKNOWN_REQUIRED  # on every historically unknown short, ETF hedges included
    is_pass_bar: bool = True
    k_impact: float = cm.K_IMPACT_DEFAULT


class CostModel(Protocol):
    def one_way_bps(
        self,
        side: str,
        px: float,
        shares: float,
        adv_shares: float | None,
        *,
        symbol: str,
        is_etf: bool,
        cfg: CostConfig,
    ) -> float: ...

    def borrow_usd(self, short_mv_usd: float, days: float, cfg: CostConfig) -> float: ...


class SharedCostModel:
    """Default: the repo's shared cost model at the close (MOC) venue, borrow on a 360-day basis
    over calendar days.

    The desk's frozen pre-registered cost path can be injected instead (same protocol)."""

    def one_way_bps(
        self,
        side: str,
        px: float,
        shares: float,
        adv_shares: float | None,
        *,
        symbol: str,
        is_etf: bool,
        cfg: CostConfig,
    ) -> float:
        if not (shares > 0):
            return 0.0
        return float(cm.trade_cost(side, px, shares, adv_shares, k=cfg.k_impact, venue="close")["total_bps"])

    def borrow_usd(self, short_mv_usd: float, days: float, cfg: CostConfig) -> float:
        return float(cm.borrow_cost(short_mv_usd, days=days, annual_rate=cfg.borrow_rate)["usd"])


# Source: backtest/engine.py:39-40 (the 5/5/10/20 bp L1-L4 floor table and the 2 bp ETF floor),
# i.e. the desk validation STANDARD cost floor: per-side minimum = asset-class floor + half-spread.
# The shared cost model (quant_research.backtest.costs.cost_model) has no floor table; its
# BUCKETS / liq_bucket give the L1-L4 buckets and the half-spread used here. Cost-model buckets map
# L1/L2 -> large (5 bps), L3 -> mid (10 bps), L4 -> small / thin (20 bps); liquid ETFs 2 bps. A
# modelled cost below the floor is raised to it, never lowered.
# Known difference: a thin ETF (L4 bucket) gets the 20 bp small-cap floor here but 2 bp in
# backtest/engine.py, which gives every ETF 2 bp whatever its bucket.
STANDARD_FLOOR_BPS = {"L1": 5.0, "L2": 5.0, "L3": 10.0, "L4": 20.0}
STANDARD_ETF_FLOOR_BPS = 2.0


def standard_floor_bps(px: float, adv_shares: float | None, *, is_etf: bool) -> float:
    bucket = cm.liq_bucket(adv_shares * px) if adv_shares else "L4 small (<$50M)"
    code = bucket.split()[0]
    base = STANDARD_ETF_FLOOR_BPS if (is_etf and code != "L4") else STANDARD_FLOOR_BPS[code]
    return base + float(cm.BUCKETS[bucket][1])


class FlooredCostModel:
    """Wraps a cost model so no trade is charged less than the standard's per-side minimum."""

    floor_label = "standard_minimum_plus_half_spread"

    def __init__(self, inner: CostModel | None = None) -> None:
        self.inner: CostModel = inner or SharedCostModel()

    def one_way_bps(
        self,
        side: str,
        px: float,
        shares: float,
        adv_shares: float | None,
        *,
        symbol: str,
        is_etf: bool,
        cfg: CostConfig,
    ) -> float:
        if not (shares > 0):
            return 0.0
        model = self.inner.one_way_bps(side, px, shares, adv_shares, symbol=symbol, is_etf=is_etf, cfg=cfg)
        return max(model, standard_floor_bps(px, adv_shares, is_etf=is_etf))

    def borrow_usd(self, short_mv_usd: float, days: float, cfg: CostConfig) -> float:
        return self.inner.borrow_usd(short_mv_usd, days, cfg)


def build_cost_config(path: str) -> CostConfig:
    paths = {
        "unknown_borrow_required": CostConfig("unknown_borrow_required", BORROW_UNKNOWN_REQUIRED, True),
        "gc_counterfactual": CostConfig("gc_counterfactual", 0.01, False),  # labelled counterfactual only
        "k_lighter_sensitivity": CostConfig("k_lighter_sensitivity", BORROW_UNKNOWN_REQUIRED, False, 0.75),
    }
    if path not in paths:
        raise SystemExit(f"unknown cost path {path!r}; known: {sorted(paths)}")
    return paths[path]


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str
    px: float
    shares: float
    adv_shares: float | None
    forced: str | None = None  # FORCED_CUT / FORCED_SETTLEMENT: charged the stress cost


FORCED_CUT = "zero_adv_cut"  # cut toward 0 with no usable ADV (cap 0): allowed, never a grow
FORCED_SETTLEMENT = "post_last_print_settlement"  # held remainder closed at the last close
# Stress cost on forced trades: STRESS_ONE_WAY_COST_MULT x the ONE-WAY cost of that trade, priced
# with no ADV (the smallest liquidity bucket). Under FlooredCostModel that one-way cost is at least
# the L4 floor plus half-spread; under the bare SharedCostModel there is no floor. 2.0 is a desk
# choice for the one-way stress. It is deliberately NOT cost_model.net_edge's stress_mult, which
# is a round-trip break-even multiple and is not reused here as a one-way multiple.
STRESS_ONE_WAY_COST_MULT = 2.0


def _cut_only(held: float, target: float) -> float:
    """Position after a cut toward 0 that never grows it or flips its sign."""
    if held > 0:
        return min(held, max(target, 0.0))
    if held < 0:
        return max(held, min(target, 0.0))
    return 0.0


def _fills(
    bars: dict[str, pd.DataFrame], W: pd.DataFrame
) -> Iterator[tuple[pd.Timestamp, pd.Timestamp, pd.Series, list[Fill], bool]]:
    """Walk the book session by session from the position actually held.

    W row k is the weight filled at close k (signals put it at their fill session, never the
    signal bar); it earns the next row's return, close k -> k+1. A fill at close k is priced,
    print-checked and ADV-capped on row k itself, never on the row whose return it then earns
    (so an exit at a name's real last print pays its cost there, and nothing fills on a no-print
    day). Each session trades at most 1%
    of ADV20 shares toward the target, where ADV20 is the trailing 20-session mean dollar volume
    ending the session before the fill day (the fill day's own volume is never in it); the
    unfilled remainder carries to later sessions. A name with no usable ADV (no history, 0 or NaN)
    has cap 0: it can never grow, but it may always be cut toward 0 (a forced cut, charged the
    stress cost). A name with no print can't trade, so it stays held. Once a name is past its last
    print and its target is flat, the held position is settled at its last close (null delisting
    return); that settlement is not free: it is charged the stress cost, and the terminal bound /
    delisting stress book their loss on that held amount.
    Yields (session, previous session, held after the session's fills, trades, capped)."""
    require_aligned(bars, W)
    PX, VOL = bars["PX"], bars["VOL"]
    TP = tradable_mask(bars)
    W_exec = W.shift(1).fillna(0.0)
    DV = (PX * VOL).mask(~TP & PX.notna(), 0.0)  # a priced non-print session trades $0
    ADV20 = DV.rolling(20, min_periods=10).mean().shift(1)  # row k: window ending k-1; read at the fill day
    last_print = {str(c): last_print_index(bars, str(c), TP) for c in PX.columns}
    pos = {d: i for i, d in enumerate(PX.index)}
    held = pd.Series(0.0, index=W_exec.columns)
    dates = W_exec.index
    for j in range(1, len(dates)):
        d = dates[j]
        fill_day = dates[j - 1]  # W_exec row j is the weight filled at close j-1: price, print and cap there
        target = W_exec.iloc[j]
        want = target - held
        fill = want.copy()
        trades: list[Fill] = []
        capped = False
        for s, delta in want.items():
            if abs(delta) < 1e-15:
                continue
            printed = bool(TP.at[fill_day, s]) if s in TP.columns else False
            px = at_float(PX, fill_day, s) if printed else float("nan")
            if not printed:
                gone = pos.get(fill_day, len(PX.index)) > last_print.get(str(s), -1)
                lp = last_print.get(str(s), -1)
                if not (gone and lp >= 0 and abs(float(target.loc[str(s)])) < 1e-15):
                    fill.loc[str(s)] = 0.0  # no print: can't trade, the position stays held
                    continue
                px_last = float(PX[s].iloc[lp])  # past its last print, target flat: settle at last close
                side = "buy" if delta > 0 else "sell"
                trades.append(Fill(str(s), side, px_last, abs(delta) * AUM / px_last, None, FORCED_SETTLEMENT))
                continue
            adv = at_float(ADV20, fill_day, s) if s in ADV20.columns and fill_day in pos else np.nan
            adv_sh = (adv / px) if (np.isfinite(adv) and adv > 0) else None
            if adv_sh is None:
                # no usable ADV: cap 0, never left uncapped. It may not grow, but may always be cut
                # toward 0 (review ruling), at the stress cost.
                h = float(held.loc[str(s)])
                cut = _cut_only(h, float(target.loc[str(s)])) - h
                fill.loc[str(s)] = cut
                capped = capped or abs(cut - delta) > 1e-15
                if abs(cut) > 1e-15:
                    side = "buy" if cut > 0 else "sell"
                    trades.append(Fill(str(s), side, float(px), abs(cut) * AUM / px, None, FORCED_CUT))
                continue
            sh = abs(delta) * AUM / px
            if sh > PARTICIPATION_CAP * adv_sh:
                sh = PARTICIPATION_CAP * adv_sh
                fill.loc[str(s)] = math.copysign(sh * px / AUM, delta)  # remainder carries to the next session
                capped = True
            trades.append(Fill(str(s), "buy" if delta > 0 else "sell", float(px), float(sh), adv_sh))
        held = held + fill
        yield d, dates[j - 1], held, trades, capped


def held_positions(bars: dict[str, pd.DataFrame], W: pd.DataFrame) -> pd.DataFrame:
    """Position actually held after each session's fills (row k earns row k's return); row 0 is flat."""
    rows = {W.index[0]: pd.Series(0.0, index=W.columns)} if len(W.index) else {}
    rows.update({d: held for d, _prev, held, _trades, _capped in _fills(bars, W)})
    return pd.DataFrame(rows, columns=W.index).T.reindex(columns=W.columns).astype(float)


def apply_costs_and_returns(
    bars: dict[str, pd.DataFrame], W: pd.DataFrame, cfg: CostConfig, *, idea: str, costs: CostModel | None = None
) -> dict[str, Any]:
    """One-session execution lag, 1% ADV participation cap, trading cost, borrow, daily net.

    The cap limits the trade itself: each session trades at most 1% of ADV20 shares toward the
    target weight; the unfilled remainder carries to the next session. Gross, cost and borrow are
    all on the position actually held (see _fills). Forced trades (cuts at zero ADV, settlements
    after the last print) pay the stress cost and are counted, with their traded notional."""
    if cfg.is_pass_bar and cfg.borrow_rate < BORROW_UNKNOWN_REQUIRED:
        raise RuntimeError("pass-bar config must have borrow_rate >= 10%/yr")
    costs = costs or SharedCostModel()
    TP = tradable_mask(bars)
    R = bars["R"].copy()
    for c in R.columns:  # past its last print a held name is settled at the last close: it earns 0
        lp = last_print_index(bars, str(c), TP) if c in TP.columns else -1
        R.loc[R.index[lp + 1 :], c] = 0.0
    rets = []
    capped_sessions = 0
    forced: dict[str, list[float]] = {FORCED_CUT: [], FORCED_SETTLEMENT: []}
    for d, prev, held, trades, capped in _fills(bars, W):
        trade_cost_frac = 0.0
        for t in trades:
            bps = costs.one_way_bps(
                t.side, t.px, t.shares, t.adv_shares, symbol=t.symbol, is_etf=t.symbol in ETFS, cfg=cfg
            )
            if t.forced is not None:
                bps *= STRESS_ONE_WAY_COST_MULT
                forced[t.forced].append(t.shares * t.px)
            trade_cost_frac += (t.shares * t.px / AUM) * bps / 1e4
        capped_sessions += capped
        rrow = R.loc[[d]].iloc[0].reindex(held.index).fillna(0.0) if d in R.index else None
        gross = float((held * rrow).sum()) if rrow is not None else 0.0
        short_mv = float((-held.clip(upper=0)).sum() * AUM)
        days = float((d - prev).days)  # calendar days since the last close (weekends accrue)
        b = costs.borrow_usd(short_mv, days, cfg) / AUM
        rets.append((d, gross - trade_cost_frac - b, gross, trade_cost_frac, b))
    df = pd.DataFrame(rets, columns=["session_date", "net", "gross", "tc", "borrow"]).set_index("session_date")
    return {
        "idea": idea,
        "cost_path": cfg.label,
        "borrow_rate_used": cfg.borrow_rate,
        "is_pass_bar": cfg.is_pass_bar,
        "k_impact": cfg.k_impact,
        "n_sessions": int(len(df)),
        "n_sessions_adv_capped": int(capped_sessions),
        "n_forced_cuts_zero_adv": len(forced[FORCED_CUT]),
        "forced_cut_notional_usd": float(sum(forced[FORCED_CUT])),
        "n_post_last_print_settlements": len(forced[FORCED_SETTLEMENT]),
        "post_last_print_settlement_notional_usd": float(sum(forced[FORCED_SETTLEMENT])),
        "forced_trade_cost": f"stress: {STRESS_ONE_WAY_COST_MULT} x one-way cost at no ADV",
        "cost_floor": getattr(costs, "floor_label", None),
        "daily": df,
    }


def sharpe_ann(daily_net: pd.Series) -> float:
    mu = daily_net.mean()
    sd = daily_net.std(ddof=1)
    if not (sd > 0):
        return float("nan")
    return float(mu / sd * math.sqrt(252))


# ---- H1 adverse terminal bound (unresolved terminal rows) ----


class AcquirerCloses(Protocol):
    def sessions(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex: ...

    def accepted_acquirer_closes(self, acquirer_id: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series: ...


def trusted_tau(bars: dict[str, pd.DataFrame], s: str) -> int | None:
    """tau = the last tradable print (tradable_mask), the same row as last_print_index."""
    i = last_print_index(bars, s)
    return i if i >= 0 else None


def short_vmax(terms: dict[str, Any], tau_d: pd.Timestamp, h_d: pd.Timestamp, client: AcquirerCloses) -> float:
    """V_max = max_k (cash_k + ratio_k * max accepted acquirer close over [tau, h]); else BLOCK."""
    if terms.get("worthless_cancellation") is True:
        return 0.0
    alts = terms.get("alternatives") or []
    if not alts or terms.get("unaccepted_legs") or terms.get("unfiled_proration"):
        raise Blocked("BLOCK H1: short terms incomplete (V_max undefined).")
    sessions = client.sessions(tau_d, h_d)
    vals = []
    for a in alts:
        cash, ratio = float(a.get("cash", 0.0)), float(a.get("ratio", 0.0))
        if ratio == 0.0:
            vals.append(cash)
            continue
        if not a.get("acquirer_id") or a.get("acquirer_identity_accepted") is not True:
            raise Blocked("BLOCK H1: unaccepted acquirer identity (V_max undefined).")
        px = client.accepted_acquirer_closes(a["acquirer_id"], tau_d, h_d).reindex(sessions)
        if px.isna().any():
            raise Blocked("BLOCK H1: missing acquirer close in [tau, h] (V_max undefined).")
        vals.append(cash + ratio * float(px.max()))
    return float(max(vals))


def h1_terminal_bound(
    bars: dict[str, pd.DataFrame],
    W: pd.DataFrame,
    roster: list[dict[str, Any]],
    cfg: CostConfig,
    *,
    client: AcquirerCloses | None = None,
    path: str = "A",
    costs: CostModel | None = None,
) -> tuple[pd.DataFrame, pd.Series, list[dict[str, Any]]]:
    """Positions stranded in unresolved terminal rows: zero the leg from tau+1 (no print there, so
    it can't fill: no exit-cost credit) and book an equity overlay at tau+1:
    long -100% of marked value; short max(P_tau, V_max) liability plus borrow from tau+1 to
    max(frozen exit, h). The bound applies to the position actually held into tau+1 (after the
    ADV cap), not the target: a capped exit still holding at delisting is bound on what is left.
    Fails closed (Blocked). Paths A and B coincide in this harness."""
    if path not in H1_TERMINAL_PATHS:
        raise ValueError(path)
    costs = costs or SharedCostModel()
    dates = W.index
    W_adj = W.copy()
    overlay = pd.Series(0.0, index=dates)
    receipts = []
    held = held_positions(bars, W) if roster else None
    for row in roster:
        s = row["symbol"]
        if s not in W.columns or not (W[s].abs() > 0).any():
            continue  # never held: nothing to replace (no exclusion by future fate)
        if row.get("identity_ok") is not True:
            raise Blocked(f"BLOCK H1: identity gate not passed for {s}.")
        t = trusted_tau(bars, s)
        if t is None:
            raise Blocked(f"BLOCK H1: no trusted print for held roster row {s}.")
        tau_d = dates[t]
        if (
            row.get("ledger_last_session_status") == "observed_last_trading_session"
            and pd.Timestamp(_any(row.get("ledger_last_session"))) != tau_d
        ):
            raise Blocked(f"BLOCK H1: tau != ledger last_session for {s}.")
        if row.get("economic_event_date") and pd.Timestamp(row["economic_event_date"]) < tau_d:
            raise Blocked(f"BLOCK H1: source-bound economic date < tau for {s}.")
        assert held is not None
        held_pre = held[s].iloc[:t].abs() > 0  # the position actually held over each session, not W
        trusted = tradable_mask(bars)[s]
        if (held_pre & ~trusted.iloc[:t]).any():
            raise Blocked(f"BLOCK H1: suspension gap before tau for {s} (fail closed).")
        if t + 1 >= len(dates):
            continue
        # held after the fills at close tau (the last fill it can get); this is what reaches tau+1
        w = float(held[s].iloc[t + 1])
        if abs(w) < 1e-15:
            continue
        book_i = t + 1
        p_tau = float(bars["PX"][s].iloc[t])
        rec: dict[str, Any] = {
            "symbol": s,
            "sid": row.get("sid"),
            "instrument_id": row.get("instrument_id"),
            "side": "long" if w > 0 else "short",
            "weight": w,
            "target_weight": float(W[s].iloc[t]),
            "entry_session": str(dates[int(np.flatnonzero((W[s].abs() > 0).values)[0])].date()),
            "tau": str(tau_d.date()),
            "booking_session": str(dates[book_i].date()),
            "P_tau": p_tau,
            "path": path,
        }
        if w > 0:
            overlay.iloc[book_i] -= w  # terminal value 0: -100%
        else:
            terms = row.get("short_terms")
            if not terms or not terms.get("h"):
                raise Blocked(f"BLOCK H1: short terms/h missing for {s} (whole run blocked).")
            if client is None:
                raise Blocked("BLOCK H1: acquirer-close provider required for short V_max.")
            h_d = pd.Timestamp(terms["h"])
            vmax = short_vmax(terms, tau_d, h_d, client)
            liab = max(p_tau, vmax)
            overlay.iloc[book_i] -= abs(w) * (liab / p_tau - 1.0)
            post = W[s].iloc[t + 1 :]
            ex_rel = np.flatnonzero((post == 0).values)
            frozen_exit_i = t + 1 + int(ex_rel[0]) if len(ex_rel) else len(dates) - 1
            h_i = int(np.searchsorted(dates.values, h_d.to_datetime64(), side="right")) - 1
            end_i = min(max(frozen_exit_i, h_i), len(dates) - 1)
            rate = max(cfg.borrow_rate, float(terms.get("borrow_rate_source", 0.0)))
            per_day = costs.borrow_usd(abs(w) * AUM, 1.0, cfg) / AUM
            per_day *= rate / cfg.borrow_rate if cfg.borrow_rate > 0 else 1.0
            for j in range(book_i, end_i + 1):
                overlay.iloc[j] -= per_day * (dates[j] - dates[j - 1]).days  # calendar days, weekends accrue
            rec.update({"h": str(h_d.date()), "V_max": vmax, "liability": liab, "borrow_rate": rate})
        # flat from tau+1: the stranded amount is never traded at tau (no exit-cost credit)
        W_adj.iloc[t + 1 :, iloc_int(W_adj.columns, s)] = 0.0
        receipts.append(rec)
    return W_adj, overlay, receipts


# ---- H2 delisting base and counted stress ----


def h2_delisting_receipts(
    bars: dict[str, pd.DataFrame], W: pd.DataFrame, positions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Base: a name still HELD past its last print (after the fills at its last close) is closed
    at that last close (it earns 0 after the last print, see apply_costs_and_returns); the hedge leg and borrow run to the
    planned exit. Keyed on the position actually held (see _fills), not the planned window: a
    capped exit remainder, or a last print at exit_i-1, still gets a receipt. One receipt per name.
    Reporting only: changes no weight and no return."""
    out: list[dict[str, Any]] = []
    PX = bars["PX"]
    dates = W.index
    held: pd.DataFrame | None = None
    tp = tradable_mask(bars)
    for s in dict.fromkeys(p["sym"] for p in positions):
        last_i = last_print_index(bars, s, tp)
        if last_i < 0 or last_i + 1 >= len(dates) or s not in W.columns:
            continue
        if held is None:
            held = held_positions(bars, W)
        w = float(held[s].iloc[last_i + 1])  # after the last fill it can get (close last_i)
        if abs(w) < 1e-15:
            continue
        ps = [p for p in positions if p["sym"] == s and p["entry_i"] <= last_i]
        if not ps:
            continue
        p = ps[-1]
        exit_i = max(int(q["exit_i"]) for q in ps)
        out.append(
            {
                "symbol": s,
                "side": "long" if w > 0 else "short",
                "held_weight": w,
                "entry_session": str(dates[int(p["entry_i"])].date()),
                "last_close_session": str(dates[last_i].date()),
                "last_close": float(PX[s].iloc[last_i]),
                "planned_exit_session": str(dates[min(exit_i, len(dates) - 1)].date()),
                "held_past_planned_exit": bool(last_i >= exit_i - 1),
                "treatment": "base: held remainder closed at last close (null delisting return)",
                "hedge_leg": p["etf"],
                "hedge_held_to_planned_exit": True,
            }
        )
    return out


def h2_delisting_stress(
    bars: dict[str, pd.DataFrame],
    W: pd.DataFrame,
    positions: list[dict[str, Any]],
    supplied_delist_returns: dict[str, Any] | None = None,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    """Counted stress: on a null delisting return, -30% for longs and 0% for shorts, booked at
    last+1 on every nonzero position actually held past the last print (after the ADV cap), not
    the target or the planned window. A supplied delisting return gets no stress."""
    sup = supplied_delist_returns or {}
    dates = W.index
    overlay = pd.Series(0.0, index=dates)
    out = []
    for r in h2_delisting_receipts(bars, W, positions):
        s = r["symbol"]
        if sup.get(s) is not None:
            out.append(dict(r, stress="not applied: supplied (non-null) delisting return"))
            continue
        li = iloc_int(dates, pd.Timestamp(r["last_close_session"]))
        w = float(r["held_weight"])
        shock = H2_DELISTING_STRESS_LONG if w > 0 else H2_DELISTING_STRESS_SHORT
        charge = w * shock if w > 0 else 0.0
        overlay.iloc[li + 1] += charge
        out.append(
            dict(
                r,
                stress="counted: null delisting return",
                stress_weight=w,
                stress_shock=shock,
                stress_charge=charge,
                stress_booking_session=str(dates[li + 1].date()),
            )
        )
    return overlay, out
