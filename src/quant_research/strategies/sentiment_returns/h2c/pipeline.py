"""End-to-end H2-C over one partition, on in-memory inputs. No file, network or environment access."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from . import events as _ev
from . import stats as _stats
from .config import H2CParams, HoldoutExpectations
from .gating import assert_events_in_partition, check_purge
from .schema import validate_transcript
from .signal import call_tone, tone_surprise
from .target import beta_adjusted_target, build_return_panel

TranscriptLoader = Callable[[str, str], Any]


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
    computed purge counts must equal it and ``expectations.purge``. When ``dev_mean_ic`` is given the holdout gate
    (G2) is evaluated, else the DEV gate (G1).
    """
    part = p.partition(partition)
    allsess = list(calendar_sessions)
    syms = list(p.universe) + [p.hedge]
    panel = build_return_panel(price_rows, price_sessions, syms)
    ER = _ev.prepare_earnings(earnings_rows, part, p.universe)
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
