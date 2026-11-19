"""End-to-end H2-C over one partition, on in-memory inputs. No file, network or environment access.

The H2-C HOLDOUT partition is spent: ``run_h2c`` refuses it (``HoldoutRefusedError``) before touching any input.
It also refuses, before computing anything, any input dated inside the spent holdout window 2011-01-01 to
2013-12-31 (inclusive), whatever the partition label: partition bounds, calendar and price sessions, price rows,
and earnings report/fiscal dates. This library must not be used to run the holdout.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from . import events as _ev
from . import stats as _stats
from .config import H2CParams, HoldoutExpectations
from .errors import HoldoutRefusedError
from .gating import assert_events_in_partition, check_purge
from .schema import validate_transcript
from .signal import call_tone, tone_surprise
from .target import beta_adjusted_target, build_return_panel

TranscriptLoader = Callable[[str, str], Any]

HOLDOUT_PARTITION = "HOLDOUT"
HOLDOUT_REFUSED_MSG = (
    "H2-C HOLDOUT partition is spent (single confirmatory run already done); this library must not be used to run it"
)
SPENT_HOLDOUT_LO = dt.date(2011, 1, 1)
SPENT_HOLDOUT_HI = dt.date(2013, 12, 31)
SPENT_WINDOW_REFUSED_MSG = (
    f"H2-C holdout window {SPENT_HOLDOUT_LO.isoformat()} to {SPENT_HOLDOUT_HI.isoformat()} is spent; "
    "this library must not be used on inputs dated inside it"
)
EARNINGS_DATE_FIELDS = ("reportedDate", "fiscalDateEnding")


def _as_date(v: Any) -> dt.date | None:
    """ISO string (first 10 chars), ``date`` or ``datetime`` -> ``date``; anything else -> None."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        try:
            return dt.date.fromisoformat(v.strip()[:10])
        except ValueError:
            return None
    return None


def _in_spent_window(v: Any) -> bool:
    d = _as_date(v)
    return d is not None and SPENT_HOLDOUT_LO <= d <= SPENT_HOLDOUT_HI


def _refuse_spent_window(what: str, values: Iterable[Any]) -> None:
    """Raise ``HoldoutRefusedError`` if any value is a date inside the spent holdout window."""
    for v in values:
        if _in_spent_window(v):
            raise HoldoutRefusedError(f"{SPENT_WINDOW_REFUSED_MSG} ({what}: {v})")


def run_h2c(
    p: H2CParams,
    partition: str,
    *,
    calendar_sessions: Sequence[str],
    price_sessions: Sequence[str],
    price_rows: Iterable[dict[str, Any]],
    earnings_rows: Iterable[dict[str, Any]],
    transcript_keys: Iterable[tuple[str, str]],
    load_transcript: TranscriptLoader,
    fye_months: dict[str, int],
    purge_reference: dict[str, int] | None = None,
    expectations: HoldoutExpectations | None = None,
    dev_mean_ic: float | None = None,
) -> dict[str, Any]:
    """Run the H2-C method on one partition.

    ``calendar_sessions``: exchange sessions covering the partition and at least ``h1`` sessions past it.
    ``price_sessions``: sessions of the price panel (partition plus beta warm-up). ``load_transcript(sym, label)``
    returns the parsed transcript object (the caller verifies integrity). When ``purge_reference`` is given, the
    computed purge counts must equal it and ``expectations.purge``. When ``dev_mean_ic`` is given the generic G2
    gate is evaluated, else the DEV gate (G1).

    The HOLDOUT partition is refused: a ``partition`` naming it (any case) raises ``HoldoutRefusedError`` before any
    input is read. Whatever the label, ``HoldoutRefusedError`` is also raised before any computation when anything
    is dated inside the spent window 2011-01-01 to 2013-12-31 (inclusive): the partition's ``lo``..``hi`` range
    (any overlap), any ``calendar_sessions`` or ``price_sessions`` date, any ``price_rows`` ``date``, or any
    ``earnings_rows`` ``reportedDate`` / ``fiscalDateEnding``. Dates may be ISO strings or ``date`` objects. As a
    last guard, no transcript is loaded for an event dated inside that window. The holdout is spent and this
    library must not be used to run it.
    """
    if partition.strip().upper() == HOLDOUT_PARTITION:
        raise HoldoutRefusedError(HOLDOUT_REFUSED_MSG)
    part = p.partition(partition)
    if part.d_lo <= SPENT_HOLDOUT_HI and part.d_hi >= SPENT_HOLDOUT_LO:
        raise HoldoutRefusedError(f"{SPENT_WINDOW_REFUSED_MSG} (partition {part.name}: {part.lo} to {part.hi})")
    allsess = list(calendar_sessions)
    psess = list(price_sessions)
    prows = list(price_rows)
    erows = list(earnings_rows)
    _refuse_spent_window("calendar_sessions", allsess)
    _refuse_spent_window("price_sessions", psess)
    _refuse_spent_window("price_rows date", (x.get("date") for x in prows))
    _refuse_spent_window("earnings_rows", (x.get(k) for x in erows for k in EARNINGS_DATE_FIELDS))
    syms = list(p.universe) + [p.hedge]
    panel = build_return_panel(prows, psess, syms)
    ER = _ev.prepare_earnings(erows, part, p.universe)
    tx_of, mdiag = _ev.map_transcripts(transcript_keys, ER, fye_months, part, p)
    EV = _ev.build_events(ER, tx_of, allsess, part, p)
    pc = _ev.purge_counts(EV, part, p)
    _ev.apply_timing_filters(EV, allsess, part, p)
    if purge_reference is not None:
        check_purge(pc, purge_reference, (expectations or HoldoutExpectations()).purge)

    def window_ok(i: int | None) -> bool:
        return i is not None and i + p.h1 < len(allsess) and allsess[i + p.h1] <= part.hi

    for ev in EV:
        if ev["status"] not in ("", "excl_no_reporttime") or not ev["label"]:
            continue
        if ev["status"] == "excl_no_reporttime" and not window_ok(ev["info_i0"]):
            continue
        if _in_spent_window(ev["reportedDate"]) or _in_spent_window(ev["day0"]):
            raise HoldoutRefusedError(f"{SPENT_WINDOW_REFUSED_MSG} (event {ev['symbol']} {ev['reportedDate']})")
        entries = validate_transcript(load_transcript(ev["symbol"], ev["label"]), ev["symbol"], ev["label"])
        ev["n_parseable"], ev["tone"] = call_tone(entries, p.tone_min)

    avail: dict[str, list[dict[str, Any]]] = {}
    for ev in EV:
        if ev["status"] == "" and math.isfinite(ev["tone"]):
            avail.setdefault(ev["symbol"], []).append(ev)

    def surprise(ev: dict[str, Any], d0: str) -> tuple[int, float]:
        return tone_surprise(ev["tone"], avail.get(ev["symbol"], []), d0, p.nprior_max, p.nprior_min)

    def target(sym: str, d0: str) -> tuple[str, float, float, float]:
        return beta_adjusted_target(panel, sym, p.hedge, d0, p.beta_n, p.h0, p.h1)

    for ev in EV:
        if ev["status"]:
            continue
        ev["n_prior"], ev["surprise"] = surprise(ev, ev["day0"])
        if ev["reportedDate"] < part.score_lo:
            ev["status"] = "warmup_not_scored"
        elif not ev["label"]:
            ev["status"] = "excl_missing_transcript"
        elif not math.isfinite(ev["tone"]):
            ev["status"] = "excl_tone_lt_min_parseable"
        elif not math.isfinite(ev["surprise"]):
            ev["status"] = "excl_lt_min_prior_calls"
        else:
            st, ev["beta"], ev["ret_raw"], ev["target"] = target(ev["symbol"], ev["day0"])
            ev["status"] = st or "candidate"

    info: dict[str, int] = {}  # INFO: excluded-for-reportTime events a 2nd-session default would have kept
    for ev in EV:
        if ev["status"] != "excl_no_reporttime" or ev["reportedDate"] < part.score_lo or not window_ok(ev["info_i0"]):
            continue
        d0 = allsess[ev["info_i0"]]
        if (
            not ev["label"]
            or not math.isfinite(ev["tone"])
            or not math.isfinite(surprise(ev, d0)[1])
            or target(ev["symbol"], d0)[0]
        ):
            continue
        info[ev["quarter"]] = info.get(ev["quarter"], 0) + 1

    qn: dict[str, int] = {}
    for ev in EV:
        if ev["status"] == "candidate":
            qn[ev["quarter"]] = qn.get(ev["quarter"], 0) + 1
    for ev in EV:
        if ev["status"] == "candidate":
            ev["status"] = "included" if qn[ev["quarter"]] >= p.q_min_events else "excl_quarter_lt_min_events"
    assert_events_in_partition(EV, part)

    periods = []
    for q in part.scored_quarters:
        g = [ev for ev in EV if ev["status"] == "included" and ev["quarter"] == q]
        m = _stats.quarter_metrics(g, q, {id(e): allsess[e["a0"] + p.h0] for e in g}, p)
        if m is not None:
            periods.append(m)
    res = (
        _stats.evaluate_g2(periods, qn, part, p, dev_mean_ic)
        if dev_mean_ic is not None
        else _stats.evaluate_g1(periods, qn, part, p)
    )
    status_counts: dict[str, int] = {}
    for ev in EV:
        status_counts[ev["status"]] = status_counts.get(ev["status"], 0) + 1
    counts = dict(
        status=status_counts,
        purge=pc,
        mapping=mdiag,
        info_default_would_keep=info,
        quarters_lt_min={q: qn.get(q, 0) for q in part.scored_quarters if qn.get(q, 0) < p.q_min_events},
    )
    return dict(partition=part.name, stats=res, periods=periods, events=EV, counts=counts)
