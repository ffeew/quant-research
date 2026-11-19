"""Earnings rows -> transcript mapping -> events with day0 / return windows, timing filters and purge counts."""
from __future__ import annotations

import bisect
import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any

from quant_research.features.fiscal_quarters import map_fiscal_year

from .config import PURGE_COUNT_KEYS, H2CParams, Partition
from .errors import MappingError, PartitionError, SchemaError

Event = dict[str, Any]


def _pdate(v: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def calendar_quarter(iso: str) -> str:
    return f"{iso[:4]}Q{(int(iso[5:7]) - 1) // 3 + 1}"


def prepare_earnings(rows: Iterable[dict[str, Any]], part: Partition, universe: Iterable[str]) -> list[dict[str, Any]]:
    """Attach parsed ``f``/``r`` dates. Unparseable fiscalDateEnding -> SchemaError; a reportedDate after the
    partition -> PartitionError; before it -> PartitionError unless the partition allows earlier baseline rows
    (``exclude_mapped_before`` set). Unparseable reportedDate becomes ``r = None``."""
    uni = set(universe)
    out = []
    for x in rows:
        e = dict(x)
        if e["symbol"] not in uni:
            raise SchemaError(f"unknown earnings symbol {e['symbol']}")
        e["f"], e["r"] = _pdate(e["fiscalDateEnding"]), _pdate(e["reportedDate"])
        if e["f"] is None:
            raise SchemaError(f"unparseable fiscalDateEnding {e['symbol']}")
        if e["r"] is not None:
            if e["r"] > part.d_hi or (part.exclude_mapped_before is None and e["r"] < part.d_lo):
                raise PartitionError(f"earnings row outside {part.name} {e['symbol']} {e['r']}")
        out.append(e)
    return out


def map_transcripts(
    keys: Iterable[tuple[str, str]], earnings: Sequence[dict[str, Any]], fye_months: dict[str, int],
    part: Partition, p: H2CParams,
) -> tuple[dict[tuple[str, str], str], dict[str, Any]]:
    """Map transcript (symbol, 'YYYYQn') labels to earnings rows via the fiscal calendar.

    Returns ({(symbol, fiscalDateEnding): label}, diag). Every transcript must map to exactly one row and no two
    transcripts may share a row (MappingError). When the partition sets ``exclude_mapped_before``, transcripts
    mapped to an earlier reportedDate are counted (``excluded_mapped``) and keep their row occupied, but get no label.
    """
    by_sym: dict[str, list[dict[str, Any]]] = {}
    for e in earnings:
        if e["r"] is not None:
            by_sym.setdefault(e["symbol"], []).append(e)
    exc = _pdate(part.exclude_mapped_before) if part.exclude_mapped_before else None
    tx_of: dict[tuple[str, str], str] = {}
    occupied: set[tuple[str, str]] = set()
    diag: dict[str, list[int]] = {}
    n_excluded = 0
    for s, lab in sorted(keys):
        if s not in fye_months:
            raise MappingError(f"no fiscal-year-end month for {s}")
        Y, n = int(lab[:4]), int(lab[5])
        qm, why = map_fiscal_year(by_sym.get(s, []), fye_months[s], Y, part.d_lo, part.d_hi, p.lag)
        row = qm[n]
        dg = diag.setdefault(s, [0, 0, 0])
        dg[0] += 1
        if row is None:
            raise MappingError(f"unmappable transcript {s} {lab} {why}")
        key = (s, row["fiscalDateEnding"])
        if key in occupied:
            raise MappingError(f"two transcripts map to one event {key}")
        occupied.add(key)
        if exc is not None and row["r"] < exc:
            n_excluded += 1
            dg[2] += 1
            continue
        if not (part.d_lo <= row["r"] <= part.d_hi):
            raise MappingError(f"transcript maps outside {part.name} {s} {lab}")
        tx_of[key] = lab
        dg[1] += 1
    per_symbol = {s: dict(files=v[0], matched=v[1], excluded_mapped=v[2], rate=v[1] / v[0], flag=v[1] / v[0] < 0.90)
                  for s, v in diag.items()}
    return tx_of, dict(per_symbol=per_symbol, listed=sum(v[0] for v in diag.values()), mapped=len(tx_of),
                       excluded_mapped=n_excluded)


def build_events(
    earnings: Sequence[dict[str, Any]], tx_of: dict[tuple[str, str], str], sessions: Sequence[str],
    part: Partition, p: H2CParams,
) -> list[Event]:
    """One event per earnings row, with day0 from reportTime (pre-market: the reportedDate session or next;
    post-market: the next session after reportedDate), and the return window [day0+h0, day0+h1] on ``sessions``
    (a full exchange calendar that extends past the partition). Then: one event per symbol per calendar quarter
    (earlier kept), and timing filters (missing reportTime, window straddling the partition end)."""
    allsess = list(sessions)

    def sess_next(d_iso: str) -> int | None:
        i = bisect.bisect_left(allsess, d_iso)
        return i if i < len(allsess) else None

    EV: list[Event] = []
    for e in sorted(earnings, key=lambda e: (e["symbol"], str(e["reportedDate"]), e["fiscalDateEnding"])):
        ev: Event = dict(symbol=e["symbol"], fiscalDateEnding=e["fiscalDateEnding"], reportedDate=str(e["reportedDate"]),
                         reportTime=str(e["reportTime"]), label=tx_of.get((e["symbol"], e["fiscalDateEnding"]), ""),
                         day0="", quarter="", ret_start="", ret_end="", n_parseable="", tone=float("nan"), n_prior="",
                         surprise=float("nan"), beta=float("nan"), ret_raw=float("nan"), target=float("nan"),
                         status="", a0=None, info_i0=None)
        if e["r"] is None:
            ev["status"] = "excl_no_timestamp"
            EV.append(ev)
            continue
        ev["quarter"] = calendar_quarter(ev["reportedDate"])
        if e["r"] < part.d_lo:
            ev["status"] = "excl_before_partition"
            EV.append(ev)
            continue
        nxt = (e["r"] + dt.timedelta(1)).isoformat()
        if ev["reportTime"] == p.timed_report_times[0]:
            a = sess_next(ev["reportedDate"])
        elif ev["reportTime"] == p.timed_report_times[1]:
            a = sess_next(nxt)
        else:
            a = None
            b1 = sess_next(nxt)
            ev["info_i0"] = b1 + 1 if b1 is not None else None
        ev["a0"] = a
        if a is not None:
            ev["day0"] = allsess[a]
            ev["ret_start"] = allsess[a + p.h0] if a + p.h0 < len(allsess) else ""
            ev["ret_end"] = allsess[a + p.h1] if a + p.h1 < len(allsess) else ""
        EV.append(ev)
    seenq: set[tuple[str, str]] = set()
    for ev in EV:
        if ev["status"]:
            continue
        k = (ev["symbol"], ev["quarter"])
        if k in seenq:
            ev["status"] = "excl_dup_symbol_quarter"
        else:
            seenq.add(k)
    return EV


def purge_counts(events: Sequence[Event], part: Partition, p: H2CParams) -> dict[str, int]:
    """Counts for events with reportedDate inside ``part.purge_window`` (duplicates included, untimestamped not):
    missing reportTime / window ending after the window end (purged) / kept."""
    w0, w1 = part.purge_window
    pw = [ev for ev in events if ev["status"] not in ("excl_no_timestamp", "excl_before_partition")
          and w0 <= ev["reportedDate"] <= w1]
    pc = dict.fromkeys(PURGE_COUNT_KEYS, 0)
    pc["in_window_rows"] = len(pw)
    for ev in pw:
        if ev["reportTime"] not in p.timed_report_times:
            pc["excl_no_reporttime"] += 1
        elif ev["ret_end"] == "" or ev["ret_end"] > w1:
            pc["purged"] += 1
        else:
            pc["kept"] += 1
    return pc


def apply_timing_filters(events: Sequence[Event], sessions: Sequence[str], part: Partition, p: H2CParams) -> None:
    """In place: missing reportTime -> excl_no_reporttime; window past partition end -> purged_straddle;
    call not available before the return window opens -> excl_call_after_close_p1."""
    allsess = list(sessions)
    for ev in events:
        if ev["status"]:
            continue
        if ev["reportTime"] not in p.timed_report_times:
            ev["status"] = "excl_no_reporttime"
            continue
        if ev["ret_end"] == "" or ev["ret_end"] > part.hi:
            ev["status"] = "purged_straddle"
            continue
        call_session = ev["reportedDate"] if ev["reportTime"] == p.timed_report_times[1] else ev["day0"]
        if call_session > allsess[ev["a0"] + p.h0]:
            ev["status"] = "excl_call_after_close_p1"
