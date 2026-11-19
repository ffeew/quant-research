"""Generic partition and reference-count checks (holdout gating), driven by config/runtime inputs only."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .config import PURGE_COUNT_KEYS, Partition
from .errors import ConfigError, PartitionError, PurgeMismatch, SchemaError
from .schema import ISO_DATE, PURGE_HEADER

SCORED_STATUSES = ("candidate", "included", "excl_quarter_lt20_events")


def read_purge_row(text: str, boundary: str, n_data_rows: int | None = None) -> dict[str, int]:
    """Parse a purge reference TSV (header ``PURGE_HEADER``) and return the int counts of the ``boundary`` row."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or tuple(lines[0].split("\t")) != PURGE_HEADER:
        raise SchemaError("purge table header")
    data = [ln.split("\t") for ln in lines[1:]]
    if (n_data_rows is not None and len(data) != n_data_rows) or any(len(r) != len(PURGE_HEADER) for r in data):
        raise SchemaError("purge table data rows/fields")
    rows = [dict(zip(PURGE_HEADER, r)) for r in data if r[0] == boundary]
    if len(rows) != 1:
        raise SchemaError(f"purge table: need exactly one {boundary} row")
    try:
        return {k: int(rows[0][k]) for k in PURGE_HEADER[1:]}
    except ValueError:
        raise SchemaError(f"purge table {boundary} row: non-integer count") from None


def check_purge(computed: dict[str, int], reference: dict[str, int], expected: dict[str, int] | None) -> None:
    """``computed`` must equal the reference row AND the runtime expectation. ``expected`` None -> ConfigError."""
    if expected is None:
        raise ConfigError("expected purge counts not supplied")
    if set(expected) != set(PURGE_COUNT_KEYS):
        raise ConfigError(f"expected purge counts must have keys {list(PURGE_COUNT_KEYS)}")
    if computed != reference or reference != expected:
        raise PurgeMismatch(f"purge mismatch computed {computed} reference {reference} expected {expected}")


def check_expected_counts(observed: dict[str, int], expected: dict[str, int] | None, keys: Iterable[str]) -> None:
    """Every key in ``keys`` must be present in ``expected`` and equal ``observed``."""
    if expected is None:
        raise ConfigError("expected counts not supplied")
    ks = list(keys)
    missing = [k for k in ks if k not in expected]
    if missing:
        raise ConfigError(f"expected counts missing {missing}")
    bad = {k: (observed.get(k), expected[k]) for k in ks if observed.get(k) != expected[k]}
    if bad:
        raise SchemaError(f"count mismatch (observed, expected): {bad}")


def assert_events_in_partition(events: Iterable[dict[str, Any]], part: Partition) -> None:
    """Refuse any event dated after the partition, and any scored/candidate event outside the scored quarters or
    whose return window ends after the partition."""
    for ev in events:
        rd = str(ev["reportedDate"])
        if ISO_DATE.fullmatch(rd) and rd > part.hi:
            raise PartitionError(f"event outside {part.name} {ev['symbol']} {rd}")
        if ev["status"] in SCORED_STATUSES:
            if ev["quarter"] not in part.scored_quarters:
                raise PartitionError(f"scored event outside {part.name} quarters {ev['symbol']} {ev['quarter']}")
            if not ev["ret_end"] or ev["ret_end"] > part.hi:
                raise PartitionError(f"scored event window past {part.hi} {ev['symbol']} {ev['quarter']}")
