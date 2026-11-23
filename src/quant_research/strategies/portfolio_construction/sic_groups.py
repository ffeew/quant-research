"""Point-in-time EDGAR SIC-2 groups for paper-sizing sector caps. Pure functions, no I/O.

Sector caps group names by the 2-digit SIC major group of the point-in-time EDGAR SIC code, at
SIC-2 only with no fallback to another level and no catch-all bucket. This mirrors the PIT
sector slot of the H1 pre-registration so both use the same grouping. It replaces the earlier
current-snapshot classification, which had no coverage for delisted names (survivorship bias).

Point-in-time rule (filing-effective interval SIC with carry-forward)
---------------------------------------------------------------------
For a CIK ``c`` and an exchange session ``t``:

* Only filing headers of ``c`` whose SIC was printed in ``c``'s own header block count as
  SIC-bearing (own-CIK block only). Headers without a SIC never govern and never break an
  interval (carry-forward).
* The governing header ``H(c, t)`` is the SIC-bearing header with the latest ET acceptance
  datetime whose ET acceptance date is strictly before ``t``. Equivalently, a header's SIC is
  valid from the first session strictly after its acceptance date until a later SIC-bearing
  header takes over. Ties on acceptance datetime go to the larger accession number.
* The name's SIC on ``t`` is the SIC of ``H(c, t)`` for the CIK linked to the symbol on ``t``.

A name is INELIGIBLE (group ``None``) on ``t`` for the first matching reason:

* R1 ``NO_CIK_LINK``: no symbol->CIK link interval contains ``t``.
* R2 ``CIK_NOT_IN_HEADERS``: the linked CIK has no header record at all.
* R3 ``NO_HEADER_BEFORE``: no header of the CIK has an acceptance date strictly before ``t``.
* R4 ``NO_SIC_HEADER_BEFORE``: headers before ``t`` exist but none is SIC-bearing.
* R5 ``INVALID_SIC``: the governing SIC is not exactly four ASCII digits, or is ``0000``. There is
  no carry-back to an earlier header past an invalid code.

Ineligible names are never imputed. Feed :func:`group_map` into
``paper_risk.apply_exposure_limits`` / ``paper_risk.pre_trade_check`` with ``group_caps`` set:
a nonzero weight on an ineligible name is rejected there (fail closed).

Inputs are plain records supplied by the caller. Acceptance datetimes are naive ET wall-clock
values (timezone-aware values are rejected rather than converted, so no timezone database is
read). The exchange session calendar is injected as a strictly increasing sequence of dates;
nothing here hard-codes or fetches a calendar or a data window.

:func:`resolve_from_intervals` is an alternative adapter for precomputed per-symbol interval rows
whose end bound is inclusive and whose open end is marked by a flag rather than a date.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

__all__ = [
    "CikLink",
    "IneligibleReason",
    "SicGroupError",
    "SicHeader",
    "SicInterval",
    "SicResolution",
    "first_session_after",
    "group_map",
    "resolve_from_intervals",
    "resolve_sic2_groups",
    "sic2_of",
    "valid_sic",
]

_SIC_RE = re.compile(r"[0-9]{4}")
_ACCESSION_RE = re.compile(r"[0-9]{10}-[0-9]{2}-[0-9]{6}")


class SicGroupError(ValueError):
    """Malformed input (bad calendar, overlapping links or intervals, malformed record)."""


class IneligibleReason(StrEnum):
    NO_CIK_LINK = "R1_NO_CIK_LINK"
    CIK_NOT_IN_HEADERS = "R2_CIK_NOT_IN_HEADERS"
    NO_HEADER_BEFORE = "R3_NO_HEADER_BEFORE"
    NO_SIC_HEADER_BEFORE = "R4_NO_SIC_HEADER_BEFORE"
    INVALID_SIC = "R5_INVALID_SIC"
    NO_INTERVAL = "NO_INTERVAL"


@dataclass(frozen=True)
class SicHeader:
    """One filing header for ``cik``.

    ``sic`` is the code as printed (``None`` or empty if absent). ``sic_block_cik`` is the CIK of
    the header block the code was read from; the code only counts when it equals ``cik``.
    ``acceptance_et`` is a naive ET wall-clock datetime.
    """

    cik: str
    accession: str
    acceptance_et: datetime
    sic: str | None
    sic_block_cik: str | None


@dataclass(frozen=True)
class CikLink:
    """Symbol->CIK link valid on sessions ``start_session <= t < end_session`` (``None`` = open)."""

    symbol: str
    cik: str
    start_session: date
    end_session: date | None


@dataclass(frozen=True)
class SicInterval:
    """Precomputed per-symbol SIC interval, valid on ``effective_from <= t <= effective_to``.

    The end bound is INCLUSIVE. When ``open_end`` is True the interval has no end and
    ``effective_to`` is ignored (whatever placeholder date the source wrote there).
    """

    symbol: str
    cik: str
    sic: str
    effective_from: date
    effective_to: date
    open_end: bool


@dataclass(frozen=True)
class SicResolution:
    symbol: str
    session: date
    cik: str | None
    sic: str | None
    sic2: str | None
    reason: IneligibleReason | None
    source_accession: str | None = None

    @property
    def eligible(self) -> bool:
        return self.reason is None


def valid_sic(sic: str | None) -> bool:
    """Exactly four ASCII digits and not ``0000``."""
    return sic is not None and _SIC_RE.fullmatch(sic) is not None and sic != "0000"


def sic2_of(sic: str | None) -> str | None:
    """2-digit SIC major group of a valid SIC code, else ``None``."""
    return sic[:2] if sic is not None and valid_sic(sic) else None


def _has_sic(h: SicHeader) -> bool:
    return h.sic is not None and h.sic.strip() != "" and h.sic_block_cik == h.cik


def _check_sessions(sessions: Sequence[date], session: date) -> None:
    if len(sessions) == 0:
        raise SicGroupError("session calendar is empty")
    for a, b in itertools.pairwise(sessions):
        if not a < b:
            raise SicGroupError(f"session calendar not strictly increasing at {a} -> {b}")
    if session not in set(sessions):
        raise SicGroupError(f"{session} is not a session in the injected calendar")


def first_session_after(d: date, sessions: Sequence[date]) -> date | None:
    """First session strictly after date ``d`` in a strictly increasing calendar, or ``None``."""
    lo, hi = 0, len(sessions)
    while lo < hi:
        mid = (lo + hi) // 2
        if sessions[mid] <= d:
            lo = mid + 1
        else:
            hi = mid
    return sessions[lo] if lo < len(sessions) else None


def _check_header(h: SicHeader) -> None:
    if not isinstance(h.acceptance_et, datetime):
        raise SicGroupError(f"{h.accession}: acceptance_et must be a datetime")
    if h.acceptance_et.tzinfo is not None:
        raise SicGroupError(f"{h.accession}: acceptance_et must be naive ET wall-clock time")
    if _ACCESSION_RE.fullmatch(h.accession) is None:
        raise SicGroupError(f"malformed accession {h.accession!r}")
    if not h.cik:
        raise SicGroupError(f"{h.accession}: empty cik")


def _accession_key(accession: str) -> int:
    return int(accession.replace("-", ""))


def _governing(
    headers: Sequence[SicHeader], session: date, sessions: Sequence[date]
) -> tuple[IneligibleReason | None, SicHeader | None]:
    """Apply R3/R4 and pick H(c, t) from one CIK's headers (already non-empty)."""
    before: list[SicHeader] = []
    for h in headers:
        start = first_session_after(h.acceptance_et.date(), sessions)
        if start is not None and start <= session:
            before.append(h)
    if not before:
        return IneligibleReason.NO_HEADER_BEFORE, None
    bearing = [h for h in before if _has_sic(h)]
    if not bearing:
        return IneligibleReason.NO_SIC_HEADER_BEFORE, None
    top = max(bearing, key=lambda h: (h.acceptance_et, _accession_key(h.accession)))
    ties = [
        h
        for h in bearing
        if (h.acceptance_et, _accession_key(h.accession)) == (top.acceptance_et, _accession_key(top.accession))
    ]
    if len(ties) > 1:
        raise SicGroupError(f"duplicate accession {top.accession} for cik {top.cik}")
    return None, top


def _active_link(links: Sequence[CikLink], session: date) -> CikLink | None:
    hits = [lk for lk in links if lk.start_session <= session and (lk.end_session is None or session < lk.end_session)]
    return hits[0] if hits else None


def _check_links(links: Iterable[CikLink]) -> dict[str, list[CikLink]]:
    by_sym: dict[str, list[CikLink]] = {}
    for lk in links:
        if lk.end_session is not None and not lk.start_session < lk.end_session:
            raise SicGroupError(f"{lk.symbol}: empty or inverted link interval")
        by_sym.setdefault(lk.symbol, []).append(lk)
    for sym, ls in by_sym.items():
        ls.sort(key=lambda x: x.start_session)
        for a, b in itertools.pairwise(ls):
            if a.end_session is None or b.start_session < a.end_session:
                raise SicGroupError(f"{sym}: overlapping CIK link intervals")
    return by_sym


def resolve_sic2_groups(
    symbols: Iterable[str],
    links: Iterable[CikLink],
    headers: Iterable[SicHeader],
    session: date,
    sessions: Sequence[date],
) -> dict[str, SicResolution]:
    """Resolve each symbol's PIT SIC-2 group on ``session`` from raw filing headers.

    Raises :class:`SicGroupError` on malformed input (bad calendar, ``session`` not in it,
    overlapping links for one symbol, naive/aware datetime misuse, malformed accession,
    duplicate accession). A CIK may be linked to several symbols at once (share classes).
    """
    _check_sessions(sessions, session)
    links_by_sym = _check_links(links)
    headers_by_cik: dict[str, list[SicHeader]] = {}
    for h in headers:
        _check_header(h)
        headers_by_cik.setdefault(h.cik, []).append(h)

    out: dict[str, SicResolution] = {}
    for sym in symbols:
        link = _active_link(links_by_sym.get(sym, []), session)
        if link is None:
            out[sym] = SicResolution(sym, session, None, None, None, IneligibleReason.NO_CIK_LINK)
            continue
        hs = headers_by_cik.get(link.cik)
        if not hs:
            out[sym] = SicResolution(sym, session, link.cik, None, None, IneligibleReason.CIK_NOT_IN_HEADERS)
            continue
        reason, gov = _governing(hs, session, sessions)
        if gov is None:
            out[sym] = SicResolution(sym, session, link.cik, None, None, reason)
            continue
        sic2 = sic2_of(gov.sic)
        out[sym] = SicResolution(
            sym,
            session,
            link.cik,
            gov.sic,
            sic2,
            None if sic2 is not None else IneligibleReason.INVALID_SIC,
            gov.accession,
        )
    return out


def resolve_from_intervals(
    symbols: Iterable[str],
    intervals: Iterable[SicInterval],
    session: date,
    sessions: Sequence[date],
) -> dict[str, SicResolution]:
    """Resolve SIC-2 groups on ``session`` from precomputed per-symbol intervals.

    Validity is ``effective_from <= session <= effective_to`` (inclusive end), or
    ``effective_from <= session`` when ``open_end`` is set. Past a real (non-open) end the name
    is ineligible (``NO_INTERVAL``). Overlapping intervals for one symbol raise. Several symbols
    may share a CIK.
    """
    _check_sessions(sessions, session)
    by_sym: dict[str, list[SicInterval]] = {}
    for iv in intervals:
        if not iv.open_end and iv.effective_to < iv.effective_from:
            raise SicGroupError(f"{iv.symbol}: effective_to before effective_from")
        by_sym.setdefault(iv.symbol, []).append(iv)
    for sym, ivs in by_sym.items():
        ivs.sort(key=lambda x: x.effective_from)
        for a, b in itertools.pairwise(ivs):
            if a.open_end or b.effective_from <= a.effective_to:
                raise SicGroupError(f"{sym}: overlapping SIC intervals")

    out: dict[str, SicResolution] = {}
    for sym in symbols:
        hit = [
            iv
            for iv in by_sym.get(sym, [])
            if iv.effective_from <= session and (iv.open_end or session <= iv.effective_to)
        ]
        if not hit:
            out[sym] = SicResolution(sym, session, None, None, None, IneligibleReason.NO_INTERVAL)
            continue
        iv = hit[0]
        sic2 = sic2_of(iv.sic)
        out[sym] = SicResolution(
            sym, session, iv.cik, iv.sic, sic2, None if sic2 is not None else IneligibleReason.INVALID_SIC
        )
    return out


def group_map(resolutions: Mapping[str, SicResolution]) -> dict[str, str | None]:
    """``symbol -> SIC-2 group`` (``None`` = ineligible), for the paper_risk group-cap path."""
    return {s: r.sic2 for s, r in resolutions.items()}
