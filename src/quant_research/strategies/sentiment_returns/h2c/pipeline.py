"""End-to-end H2-C over one partition, on in-memory inputs. No file, network or environment access.

The H2-C HOLDOUT partition is spent: ``run_h2c`` refuses it (``HoldoutRefusedError``) before touching any input.
Whatever the partition label, it also refuses observations dated inside the spent holdout window 2011-01-01 to
2013-12-31 (inclusive): partition bounds overlapping it, earnings rows whose ``reportedDate`` falls in it,
transcripts dated in it, and any return/outcome row in it that would feed a target or a score. ``fiscalDateEnding``
is a label, not an observation date, and is not checked. In-window price history (price rows, price sessions,
calendar sessions) is allowed only as beta warm-up: dated before the partition start and among the last
``beta_n + 1`` sessions before it (the prices behind the ``beta_n`` returns of a beta estimated at the first partition
session). Session and price dates fail closed: any value that is not a ``datetime.date`` (``datetime.datetime``
excluded) or a strict ISO ``YYYY-MM-DD`` string is refused, since it cannot be shown to lie outside the window.
Session order is checked too: ``calendar_sessions`` and ``price_sessions`` must each be strictly increasing, so
an unsorted or duplicated sequence is refused. Day0 is found by binary search over the calendar and beta windows are
read by position in the price panel, so a misplaced in-window session could otherwise shift day0 past the outcome
guards or feed a warm-up price into a scored beta. This library must not be used to run the holdout.
"""

from __future__ import annotations

import datetime as dt
import math
import re
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
EARNINGS_DATE_FIELDS = ("reportedDate",)  # observation dates only; fiscalDateEnding is a label
TRANSCRIPT_DATE_FIELDS = ("date", "reportedDate")  # date keys a loaded transcript object may carry
WARMUP_EXTRA_SESSIONS = 1  # beta_n returns need beta_n + 1 prices
_STRICT_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)


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


def _strict_session_date(v: Any) -> dt.date | None:
    """Session/price date parser for the fail-closed guards: a ``date`` object, or a string that is exactly
    ``YYYY-MM-DD`` (no time part, whitespace or other separator) and a valid calendar date -> ``date``; anything else
    -> None. ``datetime.datetime`` (a ``date`` subclass) -> None: a session date is a calendar day, and a timestamp
    (possibly tz-aware) is not one, so it is refused rather than truncated."""
    if isinstance(v, dt.datetime):
        return None
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and _STRICT_ISO_DATE.fullmatch(v):
        try:
            return dt.date.fromisoformat(v)
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


def _warmup_allowance(sessions: Iterable[Any], part_lo: dt.date, lookback: int) -> frozenset[dt.date]:
    """The last ``lookback`` distinct session dates strictly before ``part_lo``: the only dates where in-window
    price history may appear (beta warm-up)."""
    before = sorted({d for d in map(_strict_session_date, sessions) if d is not None and d < part_lo})
    return frozenset(before[-lookback:]) if lookback > 0 else frozenset()


def _refuse_spent_window_except_warmup(what: str, values: Iterable[Any], allowed: frozenset[dt.date]) -> None:
    """Session/price guard, fail closed: refuse any value that is not a strict date (``_strict_session_date``), and
    any in-window date not in ``allowed`` (pre-partition beta warm-up)."""
    for v in values:
        d = _strict_session_date(v)
        if d is None:
            raise HoldoutRefusedError(
                f"{SPENT_WINDOW_REFUSED_MSG} ({what}: {v!r} is not a date object or strict ISO YYYY-MM-DD date;"
                " session and price dates fail closed)"
            )
        if SPENT_HOLDOUT_LO <= d <= SPENT_HOLDOUT_HI and d not in allowed:
            raise HoldoutRefusedError(
                f"{SPENT_WINDOW_REFUSED_MSG} ({what}: {v}; in-window dates are allowed only as pre-partition beta"
                " warm-up within beta_n + 1 sessions before the partition start)"
            )


def _refuse_unordered_sessions(cal: Sequence[Any], psess: Sequence[Any]) -> None:
    """Raise ``HoldoutRefusedError`` unless ``cal`` (calendar sessions) and ``psess`` (price sessions, one sequence
    shared by all symbols) are each strictly increasing, compared as parsed dates; an unsorted or duplicated sequence
    is refused. Day0 and the outcome window are located by binary search over the calendar, and beta windows are read
    by position in the price panel, so a misplaced session could move day0 and let an in-window session escape the
    outcome guards, or carry an in-window warm-up price into a scored beta. Call only after the fail-closed date
    checks: every value is a strict date."""
    for what, seq in (("calendar_sessions", cal), ("price_sessions", psess)):
        ds = [_strict_session_date(v) for v in seq]
        for i in range(1, len(ds)):
            a, b = ds[i - 1], ds[i]
            if a is None or b is None or not a < b:
                raise HoldoutRefusedError(
                    f"{SPENT_WINDOW_REFUSED_MSG} ({what}: not strictly increasing at index {i}:"
                    f" {seq[i - 1]!r} then {seq[i]!r}; unsorted or duplicate sessions are refused)"
                )


def _refuse_outcome_window(what: str, sessions: Sequence[Any], i0: int, h1: int) -> None:
    """Raise ``HoldoutRefusedError`` if any session from ``sessions[i0]`` (day0) through ``sessions[i0 + h1]`` (the
    horizon end) is inside the spent window: those dates carry the prices of the outcome/target return rows and the
    scoring entry session, which may never be in-window (warm-up allowance covers beta estimation only)."""
    for d in sessions[max(i0, 0) : i0 + h1 + 1]:
        if _in_spent_window(d):
            raise HoldoutRefusedError(f"{SPENT_WINDOW_REFUSED_MSG} ({what} outcome row: {d})")


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
    input is read. Whatever the label, ``HoldoutRefusedError`` is also raised for observations dated inside the
    spent window 2011-01-01 to 2013-12-31 (inclusive):

    - before any input is read: the partition's ``lo``..``hi`` range overlapping the window;
    - before any computation: an ``earnings_rows`` ``reportedDate`` in the window (``fiscalDateEnding`` is a label
      and is not checked); a ``calendar_sessions``, ``price_sessions`` or ``price_rows`` ``date`` in the window
      unless it is beta warm-up, i.e. before ``lo`` and among the last ``beta_n + 1`` sessions of that sequence
      before ``lo``; and (fail closed) any of those session/price dates that is not a ``datetime.date`` (a
      ``datetime.datetime`` is refused) or a strict ISO ``YYYY-MM-DD`` string;
    - before any computation, after those date checks: ``calendar_sessions`` or ``price_sessions`` not strictly
      increasing (unsorted or with a duplicate; day0 is found by binary search over the calendar and betas are read
      by position in the price panel, so a misplaced session could otherwise shift day0 past the outcome guards or
      feed an in-window warm-up price into a scored beta);
    - per transcript: before ``load_transcript``, an event whose ``reportedDate`` or ``day0`` is in the window; after
      loading, a transcript object carrying an in-window ``date`` / ``reportedDate``;
    - per target and score: any session from ``day0`` through ``day0 + h1`` (price panel and calendar) in the
      window, so no in-window return row ever feeds an outcome.

    Session and price dates must be ``date`` objects or strict ISO ``YYYY-MM-DD`` strings; earnings and transcript
    dates may be ISO strings (first 10 characters) or ``date`` objects, and an unparseable ``reportedDate`` keeps its
    existing handling. The holdout is spent and this library must not be used to run it.
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
    lookback = p.beta_n + WARMUP_EXTRA_SESSIONS
    cal_ok = _warmup_allowance(allsess, part.d_lo, lookback)
    px_ok = _warmup_allowance(psess, part.d_lo, lookback)
    _refuse_spent_window("earnings_rows", (x.get(k) for x in erows for k in EARNINGS_DATE_FIELDS))
    _refuse_spent_window_except_warmup("calendar_sessions", allsess, cal_ok)
    _refuse_spent_window_except_warmup("price_sessions", psess, px_ok)
    _refuse_spent_window_except_warmup("price_rows date", (x.get("date") for x in prows), px_ok)
    _refuse_unordered_sessions(allsess, psess)
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
            raise HoldoutRefusedError(
                f"{SPENT_WINDOW_REFUSED_MSG} (transcript {ev['symbol']} {ev['label']} for event {ev['reportedDate']})"
            )
        obj = load_transcript(ev["symbol"], ev["label"])
        if isinstance(obj, dict):
            _refuse_spent_window(
                f"transcript {ev['symbol']} {ev['label']}", (obj.get(k) for k in TRANSCRIPT_DATE_FIELDS)
            )
        entries = validate_transcript(obj, ev["symbol"], ev["label"])
        ev["n_parseable"], ev["tone"] = call_tone(entries, p.tone_min)

    avail: dict[str, list[dict[str, Any]]] = {}
    for ev in EV:
        if ev["status"] == "" and math.isfinite(ev["tone"]):
            avail.setdefault(ev["symbol"], []).append(ev)

    def surprise(ev: dict[str, Any], d0: str) -> tuple[int, float]:
        return tone_surprise(ev["tone"], avail.get(ev["symbol"], []), d0, p.nprior_max, p.nprior_min)

    pidx = panel.index

    def target(sym: str, d0: str) -> tuple[str, float, float, float]:
        if d0 in pidx:
            _refuse_outcome_window(f"price {sym} {d0}", panel.sessions, pidx[d0], p.h1)
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
            _refuse_outcome_window(f"calendar {ev['symbol']} {ev['day0']}", allsess, ev["a0"], p.h1)
            st, ev["beta"], ev["ret_raw"], ev["target"] = target(ev["symbol"], ev["day0"])
            ev["status"] = st or "candidate"

    info: dict[str, int] = {}  # INFO: excluded-for-reportTime events a 2nd-session default would have kept
    for ev in EV:
        if ev["status"] != "excl_no_reporttime" or ev["reportedDate"] < part.score_lo or not window_ok(ev["info_i0"]):
            continue
        d0 = allsess[ev["info_i0"]]
        _refuse_outcome_window(f"calendar {ev['symbol']} {d0}", allsess, ev["info_i0"], p.h1)
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
