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


# Desk validation standard, cost section: per-side minimum = asset-class floor + half-spread.
# US large-cap 5 bps, mid-cap 10 bps, small-cap / thin 20 bps; liquid ETFs 2 bps (thin ETFs use the
# small-cap row). Cost-model buckets map L1/L2 -> large, L3 -> mid, L4 -> small; the half-spread is
# the bucket default. A modelled cost below the floor is raised to it, never lowered.
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


def _fills(
    bars: dict[str, pd.DataFrame], W: pd.DataFrame
) -> Iterator[tuple[pd.Timestamp, pd.Timestamp, pd.Series, list[Fill], bool]]:
    """Walk the book session by session from the position actually held.

    W row k is the weight filled at close k (signals put it at their fill session, never the
    signal bar); it earns the next row's return, close k -> k+1. Each session trades at most 1%
    of ADV20 shares toward the target; the unfilled remainder carries to later sessions. A name
    with no print can't trade, so it stays held. Once a name is past its last print and its
    target is flat, the held position is settled at its last close at no cost (null delisting
    return); the terminal bound and the delisting stress book their loss on that held amount.
    Yields (session, previous session, held after the session's fills, trades, capped)."""
    PX, VOL = bars["PX"], bars["VOL"]
    W_exec = W.shift(1).fillna(0.0)
    DV = PX * VOL
    ADV20 = DV.rolling(20, min_periods=10).mean().shift(1)
    printed = (PX > 0).to_numpy()
    last_print = {
        str(c): (int(np.flatnonzero(printed[:, k])[-1]) if printed[:, k].any() else -1)
        for k, c in enumerate(PX.columns)
    }
    pos = {d: i for i, d in enumerate(PX.index)}
    held = pd.Series(0.0, index=W_exec.columns)
    dates = W_exec.index
    for j in range(1, len(dates)):
        d = dates[j]
        target = W_exec.iloc[j]
        want = target - held
        fill = want.copy()
        trades: list[Fill] = []
        capped = False
        for s, delta in want.items():
            if abs(delta) < 1e-15:
                continue
            px = at_float(PX, d, s) if s in PX.columns and d in pos else float("nan")
            if not (px > 0):
                gone = pos.get(d, len(PX.index)) > last_print.get(str(s), -1)
                if not (gone and abs(float(target.loc[str(s)])) < 1e-15):
                    fill.loc[str(s)] = 0.0  # no print: can't trade, the position stays held
                continue  # (or: past its last print with a flat target, settled at last close)
            adv = at_float(ADV20, d, s) if s in ADV20.columns else np.nan
            adv_sh = (adv / px) if (np.isfinite(adv) and adv > 0) else None
            sh = abs(delta) * AUM / px
            if adv_sh and sh > PARTICIPATION_CAP * adv_sh:
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
    all on the position actually held (see _fills)."""
    if cfg.is_pass_bar and cfg.borrow_rate < BORROW_UNKNOWN_REQUIRED:
        raise RuntimeError("pass-bar config must have borrow_rate >= 10%/yr")
    costs = costs or SharedCostModel()
    R = bars["R"]
    rets = []
    capped_sessions = 0
    for d, prev, held, trades, capped in _fills(bars, W):
        trade_cost_frac = 0.0
        for t in trades:
            bps = costs.one_way_bps(
                t.side, t.px, t.shares, t.adv_shares, symbol=t.symbol, is_etf=t.symbol in ETFS, cfg=cfg
            )
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
    """tau = last trusted print: volume > 0, price present, not forward-filled."""
    if s not in bars["PX"].columns:
        return None
    tr = (bars["VOL"][s] > 0) & bars["PX"][s].notna()
    if "FFILL" in bars:
        tr &= ~bars["FFILL"][s].fillna(True).astype(bool)
    idx = np.flatnonzero(tr.to_numpy(dtype=bool))
    return int(idx[-1]) if len(idx) else None


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
    """Positions stranded in unresolved terminal rows: zero the leg from tau (the execution lag
    closes it at tau+1 with no exit-cost credit) and book an equity overlay at tau+1:
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
        held_pre = W[s].iloc[:t].abs() > 0
        trusted = (bars["VOL"][s] > 0) & bars["PX"][s].notna()
        if "FFILL" in bars:
            trusted &= ~bars["FFILL"][s].fillna(True).astype(bool)
        if (held_pre & ~trusted.iloc[:t]).any():
            raise Blocked(f"BLOCK H1: suspension gap before tau for {s} (fail closed).")
        assert held is not None
        # held after close tau's session; no print after tau, so this is what reaches tau+1
        w = float(held[s].iloc[t])
        if abs(w) < 1e-15 or t + 1 >= len(dates):
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
        W_adj.iloc[t:, iloc_int(W_adj.columns, s)] = 0.0
        receipts.append(rec)
    return W_adj, overlay, receipts


# ---- H2 delisting base and counted stress ----


def h2_delisting_receipts(bars: dict[str, pd.DataFrame], positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Base: a name that stops printing before its planned exit is closed at its last close
    (R is NaN afterwards, so it adds 0); the hedge leg and borrow run to the planned exit.
    Reporting only: changes no weight and no return."""
    out = []
    PX = bars["PX"]
    dates = PX.index
    for p in positions:
        s = p["sym"]
        if s not in PX.columns:
            continue
        idx = np.flatnonzero(PX[s].notna().values)
        if not len(idx):
            continue
        last_i = int(idx[-1])
        if p["entry_i"] <= last_i < p["exit_i"] - 1:
            out.append(
                {
                    "symbol": s,
                    "side": "long" if p["w_sym"] > 0 else "short",
                    "entry_session": str(dates[p["entry_i"]].date()),
                    "last_close_session": str(dates[last_i].date()),
                    "last_close": float(PX[s].iloc[last_i]),
                    "planned_exit_session": str(dates[min(p["exit_i"], len(dates) - 1)].date()),
                    "treatment": "base: closed at last close (null delisting return)",
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
    last+1 on the position actually held over that session (after the ADV cap), not the target.
    A supplied delisting return gets no stress."""
    sup = supplied_delist_returns or {}
    dates = W.index
    held: pd.DataFrame | None = None
    overlay = pd.Series(0.0, index=dates)
    out = []
    for r in h2_delisting_receipts(bars, positions):
        s = r["symbol"]
        if sup.get(s) is not None:
            out.append(dict(r, stress="not applied: supplied (non-null) delisting return"))
            continue
        li = iloc_int(dates, pd.Timestamp(r["last_close_session"]))
        if li + 1 >= len(dates):
            continue
        if held is None:
            held = held_positions(bars, W)
        w = float(held[s].iloc[li]) if s in held.columns else 0.0  # no print after li: carried into li+1
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
