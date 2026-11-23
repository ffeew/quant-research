"""Explicit inputs for portfolio construction and the pure helpers that use them.

Research-only for now: this module refuses any session its SIC-2 map does not cover. The current map ends
2021-12-31, so no current-date paper targets can be built until a post-2021 SIC-2 map is built, reviewed
and accepted.

Inputs (all required, no built-in defaults):

* Universe file (``--universe``): UTF-8 text, one symbol per line. Leading/trailing whitespace is
  stripped; blank lines and lines whose first non-blank character is ``#`` are ignored. A symbol is
  upper-case letters, digits, ``.`` or ``-`` and starts with a letter (e.g. ``AAPL``, ``BRK.B``).
  Invalid or duplicate symbols, or an empty file, are refused with every problem listed.
* SIC-2 map (``--sic2_map``): CSV with exactly the header columns ``rebalance_date, symbol, sic2,
  reason`` (any order). ``rebalance_date`` is an ISO session date; only rows for the as-of session
  are used. ``sic2`` is two digits, or blank for an ineligible name (``reason`` says why). A map
  with no rows for the as-of session, a duplicate (session, symbol) row or a malformed ``sic2`` is
  refused.

ETFs are a declared non-SIC asset class (:data:`DECLARED_ETFS`): they are never SIC-grouped and
instead sit in one ETF sleeve with their own caps (per-ETF position cap, sleeve gross and |net|).
The hedge instrument is in neither a SIC group nor the ETF sleeve. Single names (everything else)
must have a SIC-2 group; any that do not are rejected, all listed at once. There is no catch-all
group.

No network access; the readers open only the path they are given.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from quant_research.strategies.portfolio_construction.sic_groups import SectorGroupError, sector_constraint_groups

__all__ = [
    "DECLARED_ETFS",
    "ETF_LABEL",
    "HEDGE_LABEL",
    "NON_ALPHA_ETFS",
    "SECTOR_ETFS",
    "SIC2_LABEL_PREFIX",
    "SIC2_MAP_COLUMNS",
    "ConstructInputError",
    "ConstructionGroups",
    "Exposure",
    "Sic2Snapshot",
    "Universe",
    "add_construct_input_args",
    "apply_etf_position_cap",
    "construction_groups",
    "exposure_by_label",
    "parse_sic2_map",
    "parse_universe",
    "read_sic2_map",
    "read_universe_file",
    "validate_etf_caps",
]

# Index / macro ETFs: never in the alpha cross-section (the hedge is one of them).
NON_ALPHA_ETFS = frozenset({"SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "TLT", "HYG", "GLD", "SLV"})
# Sector ETFs: alpha-eligible, but an ETF, not a single name, so never SIC-grouped.
SECTOR_ETFS = frozenset({"XLK", "SMH", "XLC", "XLY", "XLF", "XLV", "XLE", "XLP", "XLI", "XLB", "XLU", "XLRE"})
DECLARED_ETFS = NON_ALPHA_ETFS | SECTOR_ETFS

SIC2_MAP_COLUMNS = ("rebalance_date", "symbol", "sic2", "reason")
SIC2_LABEL_PREFIX = "SIC2:"
ETF_LABEL = "ETF"
HEDGE_LABEL = "HEDGE"

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]*\Z")
_SIC2 = re.compile(r"[0-9]{2}\Z")


class ConstructInputError(ValueError):
    """A construction input is missing or malformed. ``problems`` lists every problem found."""

    def __init__(self, what: str, problems: Sequence[str]) -> None:
        self.what = what
        self.problems: tuple[str, ...] = tuple(problems)
        super().__init__(f"{what}: " + "; ".join(self.problems))


def _read_bytes(path: str, what: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise ConstructInputError(what, [f"cannot read {path!r}: {exc.strerror or exc}"]) from exc


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConstructInputError(what, [f"not UTF-8 ({exc.reason} at byte {exc.start})"]) from exc


# ---------------------------------------------------------------- universe


@dataclass(frozen=True)
class Universe:
    path: str
    sha256: str
    symbols: tuple[str, ...]


def parse_universe(text: str) -> tuple[str, ...]:
    """Symbols from universe-file text, in file order (format in the module docstring)."""
    problems: list[str] = []
    first_line: dict[str, int] = {}
    symbols: list[str] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        sym = raw.strip()
        if not sym or sym.startswith("#"):
            continue
        if not _SYMBOL.match(sym):
            problems.append(f"line {n}: invalid symbol {sym!r}")
            continue
        if sym in first_line:
            problems.append(f"line {n}: duplicate symbol {sym!r} (first on line {first_line[sym]})")
            continue
        first_line[sym] = n
        symbols.append(sym)
    if not symbols and not problems:
        problems.append("no symbols")
    if problems:
        raise ConstructInputError("universe file rejected", problems)
    return tuple(symbols)


def read_universe_file(path: str) -> Universe:
    data = _read_bytes(path, "universe file rejected")
    symbols = parse_universe(_decode(data, "universe file rejected"))
    return Universe(path=path, sha256=hashlib.sha256(data).hexdigest(), symbols=symbols)


# ---------------------------------------------------------------- SIC-2 map


@dataclass(frozen=True)
class Sic2Snapshot:
    path: str
    sha256: str
    asof: str
    groups: dict[str, str | None]
    reasons: dict[str, str]


def _iso_session(asof: str) -> str:
    try:
        parsed = dt.date.fromisoformat(asof)
    except ValueError as exc:
        raise ConstructInputError("SIC-2 map rejected", [f"as-of session {asof!r} is not an ISO date"]) from exc
    if parsed.isoformat() != asof:
        raise ConstructInputError("SIC-2 map rejected", [f"as-of session {asof!r} is not in YYYY-MM-DD form"])
    return asof


def parse_sic2_map(text: str, asof: str) -> tuple[dict[str, str | None], dict[str, str]]:
    """``(symbol -> sic2 or None, symbol -> reason)`` for the rows whose ``rebalance_date`` is ``asof``."""
    asof = _iso_session(asof)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    if sorted(header) != sorted(SIC2_MAP_COLUMNS):
        raise ConstructInputError(
            "SIC-2 map rejected", [f"header must be exactly {', '.join(SIC2_MAP_COLUMNS)}; got {header}"]
        )
    reader.fieldnames = header
    problems: list[str] = []
    groups: dict[str, str | None] = {}
    reasons: dict[str, str] = {}
    for n, row in enumerate(reader, start=2):
        if (row.get("rebalance_date") or "").strip() != asof:
            continue
        sym = (row.get("symbol") or "").strip()
        sic2 = (row.get("sic2") or "").strip()
        reason = (row.get("reason") or "").strip()
        if not _SYMBOL.match(sym):
            problems.append(f"row {n}: invalid symbol {sym!r}")
            continue
        if sym in groups:
            problems.append(f"row {n}: duplicate row for {sym} on {asof}")
            continue
        if sic2 and not _SIC2.match(sic2):
            problems.append(f"row {n}: {sym} sic2 {sic2!r} is not two digits")
            continue
        groups[sym] = sic2 or None
        if reason:
            reasons[sym] = reason
    if not groups and not problems:
        problems.append(f"no rows for the as-of session {asof}")
    if problems:
        raise ConstructInputError("SIC-2 map rejected", problems)
    return groups, reasons


def read_sic2_map(path: str, asof: str) -> Sic2Snapshot:
    data = _read_bytes(path, "SIC-2 map rejected")
    groups, reasons = parse_sic2_map(_decode(data, "SIC-2 map rejected"), asof)
    return Sic2Snapshot(path=path, sha256=hashlib.sha256(data).hexdigest(), asof=asof, groups=groups, reasons=reasons)


# ---------------------------------------------------------------- optimiser groups


@dataclass(frozen=True)
class ConstructionGroups:
    """Index sets into the optimiser universe.

    ``sector_index``: SIC-2 group -> single-name indices (sorted groups, universe order).
    ``etf_index``: ETF-sleeve indices (declared ETFs, hedge excluded).
    ``labels``: symbol -> ``SIC2:<code>``, ``ETF`` or ``HEDGE`` for every universe symbol.
    """

    sector_index: dict[str, tuple[int, ...]]
    etf_index: tuple[int, ...]
    labels: dict[str, str]


def construction_groups(
    univ: Sequence[str],
    groups: Mapping[str, str | None],
    *,
    etfs: Iterable[str],
    hedge: str,
    reasons: Mapping[str, str] | None = None,
) -> ConstructionGroups:
    """Split ``univ`` into SIC-2 groups (single names), the ETF sleeve and the hedge.

    Raises :class:`SectorGroupError` listing every single name that is ineligible, missing from
    ``groups`` or duplicated (with the map's reason where one is given).
    """
    etf_set = frozenset(etfs)
    singles = [s for s in univ if s != hedge and s not in etf_set]
    try:
        members = sector_constraint_groups(singles, groups)
    except SectorGroupError as exc:
        why = reasons or {}
        raise SectorGroupError(
            [(name, f"{msg}; map reason: {why[name]}" if name in why else msg) for name, msg in exc.offenders]
        ) from exc
    others = [s for s in univ if s == hedge or s in etf_set]
    dup_other = sorted({s for s in others if others.count(s) > 1})
    if dup_other:
        raise SectorGroupError([(s, "duplicate name") for s in dup_other])
    index = {s: i for i, s in enumerate(univ)}
    labels = {s: f"{SIC2_LABEL_PREFIX}{g}" for g, ms in members.items() for s in ms}
    etf_index: list[int] = []
    for i, s in enumerate(univ):
        if s == hedge:
            labels[s] = HEDGE_LABEL
        elif s in etf_set:
            labels[s] = ETF_LABEL
            etf_index.append(i)
    return ConstructionGroups(
        sector_index={g: tuple(index[s] for s in ms) for g, ms in members.items()},
        etf_index=tuple(etf_index),
        labels=labels,
    )


def validate_etf_caps(etf_max_pos: float, etf_sleeve_gross: float, etf_sleeve_net: float) -> None:
    """The ETF caps are required: each must be a finite number in (0, 1]."""
    problems = [
        f"{name} = {val!r} must be in (0, 1]"
        for name, val in (
            ("etf_max_pos", etf_max_pos),
            ("etf_sleeve_gross", etf_sleeve_gross),
            ("etf_sleeve_net", etf_sleeve_net),
        )
        if not (isinstance(val, (int, float)) and math.isfinite(val) and 0.0 < val <= 1.0)
    ]
    if problems:
        raise ConstructInputError("ETF caps rejected", problems)


def apply_etf_position_cap(cap: Any, etf_index: Sequence[int], etf_max_pos: float) -> np.ndarray[Any, Any]:
    """Per-name cap vector with ETF-sleeve entries capped at ``etf_max_pos`` (other entries unchanged)."""
    out = np.array(cap, dtype=float, copy=True)
    if etf_index:
        ix = list(etf_index)
        out[ix] = np.minimum(out[ix], etf_max_pos)
    return out


@dataclass(frozen=True)
class Exposure:
    gross: float
    net: float
    max_abs: float


def exposure_by_label(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[float]], Exposure]:
    """``(SIC-2 label -> [gross, net], ETF-sleeve exposure)`` from target rows.

    Rows carry ``sector`` (a label from :func:`construction_groups`), ``target_weight`` and
    ``target_shares``. Hedge rows and zero targets are skipped. Any other label is refused.
    """
    groups: dict[str, list[float]] = {}
    g_etf = n_etf = m_etf = 0.0
    unknown: list[str] = []
    for r in rows:
        label = str(r["sector"])
        if label == HEDGE_LABEL or r["target_shares"] == 0:
            continue
        w = float(r["target_weight"])
        if label == ETF_LABEL:
            g_etf += abs(w)
            n_etf += w
            m_etf = max(m_etf, abs(w))
        elif label.startswith(SIC2_LABEL_PREFIX) and _SIC2.match(label[len(SIC2_LABEL_PREFIX) :]):
            g = groups.setdefault(label, [0.0, 0.0])
            g[0] += abs(w)
            g[1] += w
        else:
            unknown.append(f"{r.get('symbol')}: {label!r}")
    if unknown:
        raise ConstructInputError("target rows carry an unknown group label", unknown)
    return groups, Exposure(gross=g_etf, net=n_etf, max_abs=m_etf)


# ---------------------------------------------------------------- CLI


def add_construct_input_args(ap: argparse.ArgumentParser) -> None:
    """The required construction inputs and the ETF-sleeve caps, as construct.py CLI options."""
    ap.add_argument(
        "--universe", required=True, help="trading universe file: one symbol per line (construct_inputs docstring)"
    )
    ap.add_argument(
        "--sic2_map",
        required=True,
        help="long CSV rebalance_date,symbol,sic2,reason; the as-of session's rows give single-name SIC-2 groups",
    )
    ap.add_argument("--etf_max_pos", type=float, default=0.095, help="per-ETF |w| cap (sleeve; hedge excluded)")
    ap.add_argument("--etf_sleeve_gross", type=float, default=0.20, help="ETF sleeve aggregate gross cap")
    ap.add_argument("--etf_sleeve_net", type=float, default=0.10, help="ETF sleeve aggregate |net| cap")
