"""Read Risk's state files (owned by the risk manager, READ-ONLY for us) with a FAIL-SAFE.

Files (paths confirmed by Risk 2026-10-30; overridable via construct.py --panic_path / --breaker_path):
  $QR_DESK_DIR/risk/state/panic_flag.json     -> fields used: as_of_sgt, panic (bool), multiplier_momentum_trend
  $QR_DESK_DIR/risk/state/breaker_state.json  -> fields used: as_of_sgt, state (NORMAL|HALVED|HALTED|RESUMED_DISARMED),
                                                    gross_cap_pct, new_trades_allowed, backstop_equity, halt_armed, current_equity
LIMITS.md (current header read at run time by limits_version(); v0.3.7 at 2026-10-30 02:28 SGT):
  * Panic flag (§3) is FINAL since ~02:27 SGT (validator panic_v2: T6 PASS, T7 PASS, T8 CONDITIONAL; CIO signed off; file
    computed on the data owner's S&P 500 official-close history). A flag file WITHOUT a provisional marker is BINDING.
    A file that still says provisional (provisional: true, or 'PROVISIONAL' in status) is returned with provisional=True
    and construct.py reports it for context only (--panic_provisional context, default; 'apply' forces it).
    §3 responses are taken from the file where present, hard-coded values are FAIL-SAFE DEFAULTS only:
      multiplier_momentum_trend           (default when on: 0.5)
      momentum_short_notional_multiplier  (default when on: 0.5; held momentum shorts cut to <= mult x current)
      new_loser_shorts_allowed            (default when on: False)
      net_beta_floor                      (default when on: -0.10; null/missing -> default)
    Invalid values (non-bool / outside [0,1] / non-numeric) fall back to the default; extra or renamed informational
    keys (ret_504d, vol_126d_ann, tr_variant, ...) are ignored and never trip the fail-safe. T8 responses (beta floor,
    loser-short ban) are pending validation per Risk: applied as written when panic is on (they only restrict risk),
    logged as t8_status = 'pending_validation'. A file that itself says stale: true or fail_closed: true -> FAIL-SAFE.
    The FAIL-SAFE is unchanged: missing/stale/invalid -> panic ON with all defaults (Risk's file: "stale: treat as
    UNKNOWN and act as if panic=true").
  * Breaker states (§2b): NORMAL 60% | HALVED 30% | HALTED 30%, no new trades (de-risk only, book held) |
    RESUMED_DISARMED 30%, new trades allowed, H9 disarmed, backstop_equity = the current EPISODE backstop as
    set by Risk (v0.3 (a) level; set once per drawdown episode (v0.3.2), reset by Risk on a resume at/below it (v0.3.3(1))
    and on every exit-(ii) lift (v0.3.5(a)); exit (ii) needs the desk head's logged OK and never fires automatically). We never
    compute the level or infer a lift. backstop_equity is logged. RESUMED_DISARMED with a missing/invalid backstop_equity -> FAIL-SAFE
    HALVED (30%); live current_equity <= backstop_equity -> treated as HALTED (re-halt per §2b) until Risk updates the file.
    Any unknown state -> FAIL-SAFE HALVED 30%.
FAIL-SAFE (risk/LIMITS.md §1-3 + Risk instruction 2026-10-30): if a file is missing, unparseable, has invalid
fields, an as_of_sgt in the future, or an as_of_sgt more than ONE US trading day old, then
  panic   -> ON with momentum/trend multiplier 0.5
  breaker -> HALVED with gross cap 30%
and the result records fail_safe=True with the reason.

"US trading day age" = number of NYSE sessions d with  ET-date(as_of) < d <= ET-date(now).  Stale if > 1.
NYSE full-day holidays 2026-2027 are hard-coded (verify yearly against nyse.com/markets/hours-calendars).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, cast
from zoneinfo import ZoneInfo

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ET, SGT = ZoneInfo("America/New_York"), ZoneInfo("Asia/Singapore")
NYSE_HOLIDAYS = {
    dt.date(*x)
    for x in [
        (2026, 1, 1),
        (2026, 1, 19),
        (2026, 2, 16),
        (2026, 4, 3),
        (2026, 5, 25),
        (2026, 6, 19),
        (2026, 7, 3),
        (2026, 9, 7),
        (2026, 11, 26),
        (2026, 12, 25),
        (2027, 1, 1),
        (2027, 1, 18),
        (2027, 2, 15),
        (2027, 3, 26),
        (2027, 5, 31),
        (2027, 6, 18),
        (2027, 7, 5),
        (2027, 9, 6),
        (2027, 11, 25),
        (2027, 12, 24),
    ]
}
FAILSAFE_PANIC = dict(
    panic=True,
    multiplier_momentum_trend=0.5,
    momentum_short_notional_multiplier=0.5,
    new_loser_shorts_allowed=False,
    net_beta_floor=-0.10,
)
PANIC_DEFAULTS_ON = {k: v for k, v in FAILSAFE_PANIC.items() if k != "panic"}
PANIC_OFF = dict(
    multiplier_momentum_trend=1.0,
    momentum_short_notional_multiplier=1.0,
    new_loser_shorts_allowed=True,
    net_beta_floor=None,
)
T8_STATUS = "pending_validation"  # Risk (the risk manager) 2026-10-30 ~02:28: T8 responses written to the file, validation pending
LIMITS_PATH = f"{_QR.DESK_DIR}/risk/LIMITS.md"


def limits_version(path: str = LIMITS_PATH) -> str | None:
    """Version from the LIMITS.md header line ('# Desk Risk Limits — vX.Y.Z ...'); None if unreadable."""
    import re

    try:
        with open(path) as f:
            h = f.readline()
        m = re.search(r"\bv(\d+(?:\.\d+)+)\b", h)
        return "v" + m.group(1) if m else None
    except OSError:
        return None


FAILSAFE_BREAKER = dict(state="HALVED", gross_cap_pct=30.0, new_trades_allowed=True)
BREAKER_CAPS = {"NORMAL": 60.0, "HALVED": 30.0, "HALTED": 30.0, "RESUMED_DISARMED": 30.0}


def is_session(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in NYSE_HOLIDAYS


def us_trading_days_between(t0: dt.datetime, t1: dt.datetime) -> int:
    d0, d1 = t0.astimezone(ET).date(), t1.astimezone(ET).date()
    n, d = 0, d0 + dt.timedelta(days=1)
    while d <= d1:
        n += is_session(d)
        d += dt.timedelta(days=1)
    return n


def _parse_asof(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=SGT)


def _load(path: str, now: dt.datetime, max_age_days: int) -> tuple[tuple[dict[str, Any], int] | None, str | None]:
    try:
        raw = json.load(open(path))
    except FileNotFoundError:
        return None, "file missing"
    except Exception as e:
        return None, f"unparseable ({type(e).__name__})"
    try:
        asof = _parse_asof(raw["as_of_sgt"])
    except Exception:
        return None, "as_of_sgt missing/invalid"
    if asof > now + dt.timedelta(minutes=5):
        return None, f"as_of_sgt {raw['as_of_sgt']} is in the future"
    age = us_trading_days_between(asof, now)
    if age > max_age_days:
        return None, f"stale: as_of_sgt {raw['as_of_sgt']} is {age} US trading days old (> {max_age_days})"
    return (raw, age), None


def _num01(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1


def read_panic(path: str, now: dt.datetime | None = None, max_age_days: int = 1) -> dict[str, Any]:
    now = now or dt.datetime.now(SGT)
    got, err = _load(path, now, max_age_days)
    base = dict(path=path, read_at_sgt=now.astimezone(SGT).isoformat(timespec="seconds"), t8_status=T8_STATUS)
    if got:
        raw, age = got
        p = raw.get("panic")
        if not isinstance(p, bool):
            err = "field 'panic' missing/not boolean"
        elif raw.get("stale") is True or raw.get("fail_closed") is True:
            err = f"file itself says stale={raw.get('stale')} / fail_closed={raw.get('fail_closed')}"
        if not err:
            st = str(raw.get("status") or "")
            prov = bool(raw.get("provisional") is True or "PROVISIONAL" in st.upper())
            resp: dict[str, Any] = {}
            src: dict[str, str] = {}
            if p:
                for k, dflt in PANIC_DEFAULTS_ON.items():
                    v = raw.get(k, None)
                    ok = (
                        isinstance(v, bool)
                        if k == "new_loser_shorts_allowed"
                        else (isinstance(v, (int, float)) and not isinstance(v, bool) and -1 <= v <= 0)
                        if k == "net_beta_floor"
                        else _num01(v)
                    )
                    resp[k], src[k] = (
                        (v, "file")
                        if ok
                        else (
                            dflt,
                            "default (missing/invalid in file)"
                            if v is not None or k not in raw
                            else "default (null in file)",
                        )
                    )
            else:
                resp = dict(PANIC_OFF)
                src = dict.fromkeys(PANIC_OFF, "panic off")
            return dict(
                base,
                panic=p,
                **resp,
                response_source=src,
                as_of_sgt=raw["as_of_sgt"],
                age_us_trading_days=age,
                fail_safe=False,
                reason="valid",
                provisional=prov,
                final=not prov,
                status=st or None,
                file_fields={
                    k: raw.get(k)
                    for k in (
                        "panic",
                        "multiplier_momentum_trend",
                        "momentum_short_notional_multiplier",
                        "new_loser_shorts_allowed",
                        "net_beta_floor",
                        "momentum_short_cut_deadline",
                        "status",
                        "validation",
                        "data_through",
                        "provisional",
                    )
                },
            )
    return dict(
        base,
        **FAILSAFE_PANIC,
        response_source=dict.fromkeys(PANIC_DEFAULTS_ON, "fail-safe default"),
        as_of_sgt=None,
        age_us_trading_days=None,
        fail_safe=True,
        provisional=None,
        final=None,
        status=None,
        reason=cast(str, err)
        + " -> FAIL-SAFE: panic ON, momentum/trend x0.5, momentum shorts x0.5, no new loser-shorts, net beta >= -0.10",
    )


LIFT_KEYS = ("lift", "episode", "exit", "daniel", "resume", "review", "chain", "lock")


def read_breaker(path: str, now: dt.datetime | None = None, max_age_days: int = 1) -> dict[str, Any]:
    """LIMITS T4 (change log v0.3-v0.3.5; current header via limits_version()): Risk owns every transition. This reader NEVER infers a lift, a re-arm or a backstop level:
    state / new_trades_allowed / gross_cap_pct / halt_armed / backstop_equity are taken from breaker_state.json only.
    backstop_equity = the CURRENT EPISODE backstop as Risk set it (v0.3.2 episode level, reset by Risk on a resume at
    or below it (v0.3.3(1)) and on EVERY exit-(ii) lift (v0.3.5(a))); it is never recomputed here (no 0.97 x equity).
    Tighten-only checks on top of the file:
      * HALTED is always de-risk only, whatever new_trades_allowed says (a lift is valid only when Risk's file says so);
      * RESUMED_DISARMED needs a valid backstop_equity, else FAIL-SAFE HALVED;
      * any non-HALTED state with a backstop and current_equity <= backstop -> treated as HALTED until Risk updates;
      * halt_armed == false outside RESUMED_DISARMED is inconsistent with §2b -> FAIL-SAFE HALVED;
      * unknown state -> FAIL-SAFE HALVED.
    Lift / episode fields present in the file (any key containing lift, episode, exit, daniel, resume, review, chain,
    lock) are passed through verbatim for the log; they are never used to relax anything."""
    now = now or dt.datetime.now(SGT)
    got, err = _load(path, now, max_age_days)
    base = dict(path=path, read_at_sgt=now.astimezone(SGT).isoformat(timespec="seconds"))
    raw = got[0] if got else None
    lift_fields = {k: v for k, v in (raw or {}).items() if any(t in k.lower() for t in LIFT_KEYS)}
    if got:
        raw, age = got
        st, cap, nta = raw.get("state"), raw.get("gross_cap_pct"), raw.get("new_trades_allowed")
        bs, ceq, armed = raw.get("backstop_equity"), raw.get("current_equity"), raw.get("halt_armed")
        bs_ok = isinstance(bs, (int, float)) and not isinstance(bs, bool) and bs > 0
        if st not in BREAKER_CAPS:
            err = f"field 'state' invalid ({st!r})"
        elif not isinstance(cap, (int, float)) or not 0 < cap <= 60:
            err = f"field 'gross_cap_pct' invalid ({cap!r})"
        elif not isinstance(nta, bool):
            err = "field 'new_trades_allowed' missing/not boolean"
        elif bs is not None and not bs_ok:
            err = f"backstop_equity invalid ({bs!r})"
        elif st == "RESUMED_DISARMED" and not bs_ok:
            err = f"state RESUMED_DISARMED but backstop_equity invalid ({bs!r})"
        elif armed is False and st in ("NORMAL", "HALVED"):
            err = (
                f"state {st} with halt_armed=false is inconsistent with LIMITS §2b (only RESUMED_DISARMED is disarmed)"
            )
        if not err:
            cap_eff = float(
                min(cast(float, cap), BREAKER_CAPS[cast(str, st)])
            )  # never looser than LIMITS.md H8/H9 for that state
            nta_eff = bool(nta) and st != "HALTED"  # HALTED never allows new trades (no inferred lift)
            reason, st_eff = "valid", st
            if (
                st != "HALTED" and bs_ok and isinstance(ceq, (int, float)) and cast(float, ceq) <= cast(float, bs)
            ):  # episode backstop breached -> re-halt
                st_eff, nta_eff, reason = (
                    "HALTED",
                    False,
                    f"{st} and current_equity {ceq} <= episode backstop_equity {bs}: treated as HALTED (LIMITS §2b / v0.3.2) until Risk updates the file",
                )
            return dict(
                base,
                state=st_eff,
                state_in_file=st,
                gross_cap_pct=cap_eff,
                new_trades_allowed=nta_eff,
                backstop_equity=(float(cast(float, bs)) if bs_ok else None),
                backstop_role="current episode backstop as set by Risk (never recomputed here)",
                halt_armed=armed,
                lift_fields_in_file=lift_fields or None,
                as_of_sgt=raw["as_of_sgt"],
                age_us_trading_days=age,
                fail_safe=False,
                reason=reason,
                file_fields={
                    k: raw.get(k)
                    for k in (
                        "state",
                        "gross_cap_pct",
                        "new_trades_allowed",
                        "drawdown_pct",
                        "peak_eod_equity",
                        "current_equity",
                        "backstop_equity",
                        "halt_armed",
                    )
                },
            )
    return dict(
        base,
        **FAILSAFE_BREAKER,
        state_in_file=(raw.get("state") if raw else None),
        backstop_equity=None,
        halt_armed=None,
        backstop_role=None,
        lift_fields_in_file=lift_fields or None,
        as_of_sgt=None,
        age_us_trading_days=None,
        fail_safe=True,
        reason=cast(str, err) + " -> FAIL-SAFE: breaker HALVED, gross cap 30%",
    )
