"""Pure synthetic V1 VIX overlay mechanics engine (isolated reference).

Deterministic fixture-only implementation of parent addendum §5 + binding
erratum E1–E4, amended per validator preflight
the internal review record.

No market data, no production construct/risk_state imports as mutable engines,
no I/O outside caller-supplied fixtures, no P&L / R1–R7.

PASS of this suite certifies only this isolated engine vs fixtures — NOT
production construct V1 (absent), live risk_state I/O, or stop price/gap/intraday.

Reference-only (hash pins elsewhere): portfolio/construct.py, portfolio/risk_state.py.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, SupportsFloat

BREAKER_CAPS = {
    "NORMAL": 60.0,
    "HALVED": 30.0,
    "HALTED": 30.0,
    "RESUMED_DISARMED": 30.0,
}
FAILSAFE_BREAKER_CAP = 30.0
V1_OFF_STREAK_REQUIRED = 5


class DomainError(ValueError):
    """V1 domain violation (e.g. negative w_vix differing from w_base)."""


def _f(x: SupportsFloat | str) -> float:
    return float(x)


def apply_v1_clamp(
    w_base: Mapping[str, float],
    *,
    v1_on_or_failsafe_reduced: bool,
) -> dict[str, float]:
    """Erratum E1: V1 only on w_base>0; ON/fail-safe => w_vix=0.5*w_base; shorts/flat unchanged."""
    out: dict[str, float] = {}
    for name, wb in w_base.items():
        wb = _f(wb)
        if v1_on_or_failsafe_reduced and wb > 0.0:
            out[name] = 0.5 * wb
        else:
            out[name] = wb
    return out


def validate_w_vix_domain(w_base: Mapping[str, float], w_vix: Mapping[str, float]) -> None:
    """Erratum E1: negative w_vix differing from w_base is a domain error."""
    for name, wb in w_base.items():
        wb = _f(wb)
        wv = _f(w_vix.get(name, wb))
        if wv < 0.0 and abs(wv - wb) > 1e-12:
            raise DomainError(f"{name}: negative w_vix {wv} differs from w_base {wb}")


def assert_no_redeployment(
    w_before: Mapping[str, float],
    w_after: Mapping[str, float],
    *,
    halved_longs: Sequence[str],
) -> None:
    """Cash from halving must not increase |w| of any other name in the same step."""
    for name, wa in w_after.items():
        if name in halved_longs:
            continue
        wb = _f(w_before.get(name, 0.0))
        if abs(_f(wa)) > abs(wb) + 1e-12:
            raise AssertionError(f"redeployment forbidden: {name} |w| rose from {wb} to {wa} while longs halved")


def hard_cap_tighten_only(
    w_vix: Mapping[str, float],
    *,
    name_cap: float = 0.10,
    risk_cap: Mapping[str, float] | None = None,
    gross_cap_pct: float = 60.0,
    h7_blocked: Sequence[str] | None = None,
) -> dict[str, float]:
    """Tighten-only hard caps. Long-only gross simplification (positive longs only)."""
    blocked = set(h7_blocked or ())
    risk_cap = risk_cap or {}
    capped: dict[str, float] = {}
    for name, wv in w_vix.items():
        wv = _f(wv)
        if name in blocked and wv > 0.0:
            wv = 0.0
        lim = name_cap
        if name in risk_cap:
            lim = min(lim, _f(risk_cap[name]))
        if wv > 0.0:
            capped[name] = min(wv, lim)
        elif wv < 0.0:
            capped[name] = max(wv, -lim)
        else:
            capped[name] = 0.0
    gross_cap = gross_cap_pct / 100.0
    long_sum = sum(v for v in capped.values() if v > 0.0)
    if long_sum > gross_cap + 1e-12:
        scale = gross_cap / long_sum
        capped = {k: (v * scale if v > 0.0 else v) for k, v in capped.items()}
    return capped


def breaker_effective(breaker: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror risk_state.read_breaker essentials (synthetic only)."""
    raw_state = breaker.get("state", "NORMAL")
    fail_safe = bool(breaker.get("fail_safe", False))
    missing_stale = bool(breaker.get("missing_or_stale_file", False))
    hold = bool(breaker.get("trading_hold", False) or breaker.get("cio_hold", False))
    if fail_safe or missing_stale or raw_state not in BREAKER_CAPS:
        return {
            "state": "HALVED",
            "state_in_file": raw_state if isinstance(raw_state, str) else None,
            "gross_cap_pct": FAILSAFE_BREAKER_CAP,
            "new_trades_allowed": True,
            "halt_armed": None,
            "backstop_equity": None,
            "fail_safe": True,
            "reason": "fail-safe HALVED 30%",
            "trading_hold": hold,
            "cio_hold": bool(breaker.get("cio_hold", False)),
        }
    st = str(raw_state)
    nta = bool(breaker.get("new_trades_allowed", True)) and st != "HALTED"
    cap = min(_f(breaker.get("gross_cap_pct", BREAKER_CAPS[st])), BREAKER_CAPS[st])
    bs = breaker.get("backstop_equity")
    ceq = breaker.get("current_equity")
    reason = breaker.get("reason", "valid")
    armed = breaker.get("halt_armed")
    if armed is False and st in ("NORMAL", "HALVED"):
        return {
            "state": "HALVED",
            "state_in_file": st,
            "gross_cap_pct": FAILSAFE_BREAKER_CAP,
            "new_trades_allowed": True,
            "halt_armed": None,
            "backstop_equity": None,
            "fail_safe": True,
            "reason": f"state {st} with halt_armed=false -> fail-safe HALVED 30%",
            "trading_hold": hold,
            "cio_hold": bool(breaker.get("cio_hold", False)),
        }
    if (
        st != "HALTED"
        and isinstance(bs, (int, float))
        and not isinstance(bs, bool)
        and isinstance(ceq, (int, float))
        and not isinstance(ceq, bool)
        and ceq <= bs
    ):
        st = "HALTED"
        nta = False
        cap = BREAKER_CAPS["HALTED"]
        reason = "backstop breach treated as HALTED"
    if st == "RESUMED_DISARMED" and not (isinstance(bs, (int, float)) and not isinstance(bs, bool) and bs > 0):
        return {
            "state": "HALVED",
            "state_in_file": "RESUMED_DISARMED",
            "gross_cap_pct": FAILSAFE_BREAKER_CAP,
            "new_trades_allowed": True,
            "halt_armed": None,
            "backstop_equity": None,
            "fail_safe": True,
            "reason": "RESUMED_DISARMED missing/invalid backstop -> fail-safe HALVED 30%",
            "trading_hold": hold,
            "cio_hold": bool(breaker.get("cio_hold", False)),
        }
    return {
        "state": st,
        "state_in_file": raw_state,
        "gross_cap_pct": cap,
        "new_trades_allowed": nta,
        "halt_armed": armed,
        "backstop_equity": bs,
        "fail_safe": False,
        "reason": reason,
        "trading_hold": bool(breaker.get("trading_hold", False)),
        "cio_hold": bool(breaker.get("cio_hold", False)),
    }


def panic_effective(panic: Mapping[str, Any]) -> dict[str, Any]:
    """Synthetic panic aligned with risk_state.read_panic labels."""
    stale = bool(panic.get("stale", False))
    fail_closed = bool(panic.get("fail_closed", False))
    status = str(panic.get("status") or "")
    provisional = bool(panic.get("provisional") is True or "PROVISIONAL" in status.upper())
    force_apply = bool(panic.get("force_binding", False) or panic.get("force_apply", False))
    file_panic = bool(panic.get("panic", False))

    fail_safe = False
    mom_short_mult = 1.0
    if stale or fail_closed:
        fail_safe = True
        panic_flag = True
        binding = True
        provisional_out = None
        factor = 0.5
        mom_short_mult = 0.5
        loser_short_ban = True
        beta_floor = -0.10
        reason = "fail-safe: stale/fail_closed -> panic ON"
    elif file_panic:
        panic_flag = True
        binding = (not provisional) or force_apply
        provisional_out = provisional
        if binding:
            factor = _f(panic.get("multiplier_momentum_trend", panic.get("multiplier", 0.5)))
            mom_short_mult = _f(panic.get("momentum_short_notional_multiplier", 0.5))
            if "new_loser_shorts_allowed" in panic:
                loser_short_ban = not bool(panic["new_loser_shorts_allowed"])
            else:
                loser_short_ban = True
            beta_floor = panic.get("net_beta_floor", panic.get("beta_floor", -0.10))
        else:
            factor = 1.0
            mom_short_mult = 1.0
            loser_short_ban = False
            beta_floor = None
        reason = "valid panic as file" + (
            " (provisional context-only unless forced)" if provisional and not force_apply else ""
        )
    else:
        panic_flag = False
        binding = False
        provisional_out = provisional
        factor = 1.0
        mom_short_mult = 1.0
        loser_short_ban = False
        beta_floor = None
        reason = "panic off" + (" (provisional context)" if provisional else "")

    return {
        "panic": panic_flag,
        "binding": binding,
        "stale": stale,
        "fail_closed": fail_closed,
        "provisional": provisional_out,
        "status": status or None,
        "fail_safe": fail_safe,
        "panic_factor": factor,
        "multiplier_momentum_trend": factor,
        "momentum_short_notional_multiplier": mom_short_mult,
        "loser_short_ban": loser_short_ban,
        "new_loser_shorts_allowed": (not (fail_safe or (binding and loser_short_ban))),
        "beta_floor": beta_floor,
        "net_beta_floor": beta_floor,
        "momentum_trend_mult": factor,
        "reason": reason,
    }


def _resolve_session_R(session: Mapping[str, Any]) -> Mapping[str, Any]:
    """Expand R_special tokens (nan/+inf/-inf) for JSON-safe fixtures."""
    s = dict(session)
    tok = s.pop("R_special", None)
    if tok is None:
        return s
    mapping = {
        "nan": float("nan"),
        "+inf": float("inf"),
        "inf": float("inf"),
        "-inf": float("-inf"),
    }
    if tok not in mapping:
        s["R"] = tok  # leave non-mapped as-is (will fail type check)
    else:
        s["R"] = mapping[tok]
    return s


def is_v1_valid_close(session: Mapping[str, Any]) -> bool:
    """E3 + preflight B1: usable non-stale hash-OK inputs; R non-bool int/float, finite, R>=0."""
    if not session.get("available", True):
        return False
    if session.get("missing") or session.get("stale") or session.get("hash_fail"):
        return False
    if not session.get("hash_ok", True):
        return False
    if session.get("availability_lag_unsatisfied"):
        return False
    r = session.get("R")
    if isinstance(r, bool) or not isinstance(r, (int, float)):
        return False
    rf = float(r)
    return not (not math.isfinite(rf) or rf < 0.0)


def v1_should_be_on(session: Mapping[str, Any], prior_state: str, streak_valid_le1: int) -> tuple[str, int, bool]:
    """Return (vix_state, new_streak, block_new). Invalid => FAILSAFE_REDUCED, streak frozen."""
    if not is_v1_valid_close(session):
        return "FAILSAFE_REDUCED", streak_valid_le1, True

    r = float(session["R"])
    if r > 1.0:
        return "ON", 0, False

    new_streak = streak_valid_le1 + 1
    if prior_state in ("ON", "FAILSAFE_REDUCED"):
        if new_streak >= V1_OFF_STREAK_REQUIRED:
            return "OFF", new_streak, False
        return (
            prior_state if prior_state == "ON" else "FAILSAFE_REDUCED",
            new_streak,
            prior_state == "FAILSAFE_REDUCED",
        )
    return "OFF", new_streak, False


def restoration_allowed(
    brkr: Mapping[str, Any],
    vix_state: str,
    *,
    panic_binding: bool = False,
    v1_block_new: bool = False,
) -> str:
    """Erratum E2 / V3a–d. Returns 'full_base' | 'min_base_30' | 'none'."""
    if vix_state != "OFF":
        return "none"
    if panic_binding or v1_block_new:
        return "none"
    st = brkr["state"]
    nta = bool(brkr.get("new_trades_allowed", True))
    hold = bool(brkr.get("trading_hold") or brkr.get("cio_hold"))
    if st == "HALTED" or (brkr.get("reason") or "").startswith("backstop"):
        return "none"
    if hold or not nta:
        return "none"
    if st == "RESUMED_DISARMED":
        return "min_base_30"
    if st == "NORMAL" and nta and not hold:
        return "full_base"
    # HALVED and other states: conservative hold-prior (disclose; restoration_mode none)
    return "none"


def independent_increase_blocked(
    brkr: Mapping[str, Any],
    *,
    panic_binding: bool,
    v1_reduced_or_block_new: bool,
) -> dict[str, bool]:
    flags = {
        "halted": brkr["state"] == "HALTED",
        "cio_or_ops_hold": bool(
            brkr.get("trading_hold") or brkr.get("cio_hold") or not brkr.get("new_trades_allowed", True)
        ),
        "binding_panic": bool(panic_binding),
        "v1_reduced_or_block_new": bool(v1_reduced_or_block_new),
    }
    flags["any"] = any(flags.values())
    return flags


def _path_capped_targets(
    ideal: Mapping[str, float],
    *,
    path_cap: float,
) -> dict[str, float]:
    """Scale positive ideal long targets to fit path_cap. Does not touch non-positive."""
    longs = {k: _f(v) for k, v in ideal.items() if _f(v) > 0.0}
    s = sum(longs.values())
    if s <= path_cap + 1e-12 or s <= 0.0:
        return {k: _f(v) for k, v in ideal.items()}
    scale = path_cap / s
    out = {k: _f(v) for k, v in ideal.items()}
    for k in longs:
        out[k] = longs[k] * scale
    return out


def apply_restoration(
    current_weights: Mapping[str, float],
    w_base: Mapping[str, float],
    *,
    mode: str,
    gross_cap_pct: float,
) -> dict[str, float]:
    """ON→OFF restoration only (V3a/d). Does NOT perform independent base de-risk cuts.

    Semantics (union of prior+base names) — deliberately NOT
    min(base, max(current, target)), which wrongly forces cuts when path/base
    targets lie below an already-held prior long:

    1. Compute ideal restore target per eligible name = w_base for names that are
       existing prior longs (prior>0) AND base>0. Path mode min_base_30 then caps
       those ideal targets to the applicable path (min(gross_cap, 30%)).
    2. For each such eligible name:
         - if prior < target: out = target  (restore up; never above target)
         - if prior >= target: out = prior  (restoration must not cut)
    3. Shorts, flat, prior-only names, and base-only new longs: unchanged from
       prior (or 0 if absent). Restoration never opens/deepens shorts or opens
       new longs from flat.
    4. Independent base/path de-risk that must cut longs below prior is a
       separate operation (see apply_base_derisk); not invoked by restoration.
    """
    names = set(current_weights) | set(w_base)
    prior = {k: _f(current_weights.get(k, 0.0)) for k in names}
    base = {k: _f(w_base.get(k, 0.0)) for k in names}

    if mode == "none":
        return dict(prior)

    # Ideal targets only for eligible existing prior longs with base>0.
    ideal: dict[str, float] = {}
    eligible = []
    for name in names:
        if prior[name] > 0.0 and base[name] > 0.0:
            ideal[name] = base[name]
            eligible.append(name)

    if mode == "min_base_30":
        path_cap = min(_f(gross_cap_pct), 30.0) / 100.0
        targets = _path_capped_targets(ideal, path_cap=path_cap)
    elif mode == "full_base":
        targets = dict(ideal)
    else:
        return dict(prior)

    out = dict(prior)  # start from prior: shorts/flat/prior-only preserved
    for name in eligible:
        tgt = _f(targets.get(name, base[name]))
        # Never above target when restoring up; never cut below prior.
        if prior[name] + 1e-12 < tgt:
            out[name] = tgt
        else:
            out[name] = prior[name]
    # Explicit: do not open base-only new longs (prior<=0, base>0) via restoration.
    for name in names:
        if prior[name] <= 0.0:
            out[name] = prior[name]
    return out


def apply_base_derisk(
    current_weights: Mapping[str, float],
    w_base: Mapping[str, float],
    *,
    path_cap_pct: float | None = None,
) -> dict[str, float]:
    """Separate from V1 ON→OFF restoration: cut longs to min(prior, base[, path]).

    Used only when a fixture explicitly sets apply_base_derisk=true to represent
    independent book de-risk / hard-cap path enforcement — NOT by restoration.
    """
    names = set(current_weights) | set(w_base)
    out: dict[str, float] = {}
    for name in names:
        cur = _f(current_weights.get(name, 0.0))
        wb = _f(w_base.get(name, 0.0))
        if cur > 0.0 and wb >= 0.0:
            out[name] = min(cur, wb)
        else:
            out[name] = cur
    if path_cap_pct is not None:
        path_cap = _f(path_cap_pct) / 100.0
        long_sum = sum(v for v in out.values() if v > 0.0)
        if long_sum > path_cap + 1e-12:
            scale = path_cap / long_sum
            out = {k: (v * scale if v > 0.0 else v) for k, v in out.items()}
    return out


def stop_quantity_coverage(shares: float, stop_covers_shares: float) -> bool:
    """Qty coverage only (not stop price/gap/intraday). Requires full coverage, shares>=0."""
    return abs(stop_covers_shares - shares) <= 1e-12 and shares >= 0.0


def run_step(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one synthetic mechanics step from a fixture dict. Pure / deterministic."""
    fx = deepcopy(dict(fixture))
    m = _f(fx.get("m", 1.0))
    m_apply_count = 0
    panic_apply_count = 0

    if fx.get("apply_m_to_signal"):
        w_signal = {k: _f(v) for k, v in fx["w_signal"].items()}
        w_after_m = {k: v * m for k, v in w_signal.items()}
        m_apply_count = 1
    elif "w_base" in fx:
        # Fixtures may pre-bake post-m weights into w_base (m not applied here).
        w_after_m = {k: _f(v) for k, v in fx["w_base"].items()}
    else:
        w_after_m = {}

    panic = panic_effective(fx.get("panic", {"panic": False}))

    if fx.get("apply_panic_to_weights"):
        w_post_panic = {k: v * panic["panic_factor"] for k, v in w_after_m.items()}
        panic_apply_count = 1
    else:
        w_post_panic = dict(w_after_m)

    brkr = breaker_effective(fx.get("breaker", {"state": "NORMAL", "new_trades_allowed": True, "gross_cap_pct": 60.0}))

    session = _resolve_session_R(fx.get("session", {"R": 1.0, "available": True, "hash_ok": True}))
    prior_state = fx.get("prior_vix_state", "OFF")
    prior_streak = int(fx.get("prior_streak_valid_le1", 0))
    sessions = fx.get("sessions")
    if sessions:
        state = prior_state
        streak = prior_streak
        block_new = False
        for s in sessions:
            state, streak, block_new = v1_should_be_on(_resolve_session_R(s), state, streak)
        vix_state, streak_out, block_new = state, streak, block_new
    else:
        vix_state, streak_out, block_new = v1_should_be_on(session, prior_state, prior_streak)

    reduced = vix_state in ("ON", "FAILSAFE_REDUCED")
    if block_new:
        reduced = True

    prior_weights = {k: _f(v) for k, v in fx.get("prior_weights", w_post_panic).items()}
    transition = fx.get("transition")

    if "restoration_mode" in fx:
        raise ValueError("fixture must not set restoration_mode; mode is derived from restoration_allowed only")

    blockers = independent_increase_blocked(
        brkr,
        panic_binding=bool(panic["binding"]),
        v1_reduced_or_block_new=bool(reduced or block_new),
    )

    if reduced:
        w_vix = apply_v1_clamp(w_post_panic, v1_on_or_failsafe_reduced=True)
        halved = [n for n, wb in w_post_panic.items() if wb > 0.0]
        assert_no_redeployment(w_post_panic, w_vix, halved_longs=halved)
        for name, wv in list(w_vix.items()):
            pw = _f(prior_weights.get(name, 0.0))
            if wv > pw + 1e-12:
                w_vix[name] = pw if pw > 0.0 else 0.0
    else:
        mode = restoration_allowed(
            brkr,
            vix_state,
            panic_binding=bool(panic["binding"]),
            v1_block_new=bool(block_new),
        )
        if transition == "ON→OFF":
            if mode != "none":
                w_vix = apply_restoration(prior_weights, w_post_panic, mode=mode, gross_cap_pct=brkr["gross_cap_pct"])
            else:
                names = set(prior_weights) | set(w_post_panic)
                w_vix = {k: _f(prior_weights.get(k, 0.0)) for k in names}
        else:
            w_vix = dict(w_post_panic)

    # Optional separate base de-risk (never implied by restoration).
    if fx.get("apply_base_derisk"):
        w_vix = apply_base_derisk(
            w_vix,
            w_post_panic,
            path_cap_pct=fx.get("base_derisk_path_cap_pct"),
        )

    if blockers["any"]:
        for name in list(w_vix.keys()):
            pw = _f(prior_weights.get(name, 0.0))
            if w_vix[name] > pw + 1e-12:
                w_vix[name] = pw

    gross_cap = brkr["gross_cap_pct"]
    w_final = hard_cap_tighten_only(
        w_vix,
        name_cap=_f(fx.get("name_cap", 0.10)),
        risk_cap=fx.get("risk_cap"),
        gross_cap_pct=gross_cap,
        h7_blocked=fx.get("h7_blocked"),
    )

    long_gross = sum(v for v in w_final.values() if v > 0.0)
    path_cap = gross_cap / 100.0
    if long_gross > path_cap + 1e-12:
        scale = path_cap / long_gross
        w_final = {k: (v * scale if v > 0.0 else v) for k, v in w_final.items()}
        long_gross = sum(v for v in w_final.values() if v > 0.0)

    # Declaration-only constants — NOT a certified no-auto-lift state machine path.
    lifts = {
        "new_trades_allowed_flipped_true": False,
        "breaker_lifted": False,
        "panic_cleared": False,
        "backstop_cleared": False,
        "halt_rearmed": False,
        "hold_cleared": False,
        "lift_paths_certified": False,
    }
    if brkr["state"] == "HALTED" and brkr["new_trades_allowed"] is not False:
        raise AssertionError("HALTED must have new_trades_allowed=False")

    stop = fx.get("stop", {})
    stop_ok = True
    if stop:
        stop_ok = stop_quantity_coverage(_f(stop["shares"]), _f(stop["stop_covers_shares"]))
        if stop.get("with_v1_shares") is not None:
            stop_ok = stop_ok and stop_quantity_coverage(
                _f(stop["with_v1_shares"]), _f(stop["with_v1_stop_covers_shares"])
            )

    m_applied_once = m_apply_count == 1
    panic_applied_once = panic_apply_count == 1

    log = {
        "m": m,
        "panic_factor": panic["panic_factor"],
        "vix_state": vix_state,
        "w_base": dict(w_post_panic),
        "w_vix": dict(w_vix),
        "w_final": dict(w_final),
    }

    return {
        "fixture_id": fx.get("id"),
        "log": log,
        "breaker": brkr,
        "panic": panic,
        "vix_state": vix_state,
        "streak_valid_le1": streak_out,
        "block_new": block_new,
        "reduced": reduced,
        "long_gross": long_gross,
        "path_cap": path_cap,
        "restoration_mode": restoration_allowed(
            brkr, vix_state, panic_binding=bool(panic["binding"]), v1_block_new=bool(block_new)
        ),
        "increase_blockers": blockers,
        "lifts": lifts,
        "stop_ok": stop_ok,
        "lift_paths_certified": False,
        "m_applied_once": m_applied_once,
        "m_apply_count": m_apply_count,
        "panic_applied_once": panic_applied_once,
        "panic_apply_count": panic_apply_count,
        "h7_applicable": fx.get("h7_applicable", False),
    }


def run_fixture(fixture: Mapping[str, Any]) -> dict[str, Any]:
    return run_step(fixture)
