"""Point-in-time readers with a hard research cutoff.

Rows dated on or after ``CUTOFF`` never materialise: the cutoff is pushed into the
pyarrow dataset scan (row-group statistics prune whole groups, the rest is filtered
inside the scanner), only the named columns are read, and the result is checked
again before it is returned. The cutoff is a module constant on purpose: callers
cannot widen it.

Column roles for ``read_pre_cutoff``:

* ``date_cols``: start-type dates. Rows are kept only where ``col < CUTOFF``
  (a null fails the comparison and drops the row).
* ``nullable_date_cols``: start-type dates that may be null. Rows are kept where
  the value is null or ``col < CUTOFF``.
* ``mask_cols``: nullable end-type dates that must not drop rows. They are
  projected in the scan as ``if_else(col < CUTOFF, col, null)``.

Any requested column with a date or timestamp type must have one of these roles.
ISO ``YYYY-MM-DD`` string columns may be given a role too; they are cast to
``date32`` inside the scan. Timestamps are compared against midnight of the cutoff
day in the column's own time zone (naive timestamps as-is).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds

CUTOFF = dt.date(2022, 3, 30)

_OFFSET_TZ = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


class CutoffError(ValueError):
    """A read would expose (or did expose) data dated on or after the cutoff."""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_sha(path: Path, expect_sha256: str | None) -> None:
    if expect_sha256 is None:
        return
    want = expect_sha256.lower()
    if len(want) < 8 or not all(c in "0123456789abcdef" for c in want):
        raise ValueError("expect_sha256 must be at least 8 hex characters")
    if not sha256_file(path).startswith(want):
        raise CutoffError(f"sha256 mismatch for {path.name}: expected prefix {want[:8]}")


def _tzinfo(tz: str) -> dt.tzinfo:
    m = _OFFSET_TZ.match(tz)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return dt.timezone(sign * dt.timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    return ZoneInfo(tz)


def _is_temporal(t: pa.DataType) -> bool:
    return bool(pa.types.is_date(t) or pa.types.is_timestamp(t))


def _is_string(t: pa.DataType) -> bool:
    return bool(pa.types.is_string(t) or pa.types.is_large_string(t))


def _cutoff_scalar(t: pa.DataType) -> pa.Scalar:
    if pa.types.is_date32(t) or _is_string(t):
        return pa.scalar(CUTOFF, type=pa.date32())
    if pa.types.is_date64(t):
        return pa.scalar(CUTOFF, type=pa.date64())
    if pa.types.is_timestamp(t):
        midnight = dt.datetime(CUTOFF.year, CUTOFF.month, CUTOFF.day)  # noqa: DTZ001 - naive by design
        if t.tz is not None:
            midnight = midnight.replace(tzinfo=_tzinfo(t.tz))
        return pa.scalar(midnight, type=t)
    raise TypeError(f"unsupported cutoff column type: {t}")


def _field_expr(name: str, t: pa.DataType) -> ds.Expression:
    expr = ds.field(name)
    if _is_string(t):
        return expr.cast(pa.date32())
    return expr


def _assert_before_cutoff(table: pa.Table, cols: Iterable[str]) -> None:
    for c in cols:
        col = table[c]
        if col.null_count == len(col):
            continue
        mx = pc.max(col)
        if not pc.less(mx, _cutoff_scalar(col.type)).as_py():
            raise CutoffError(f"column {c!r} has a value on or after the cutoff after the scan")


def read_pre_cutoff(
    path: str | Path,
    columns: Sequence[str],
    date_cols: Sequence[str],
    mask_cols: Sequence[str] = (),
    expect_sha256: str | None = None,
    *,
    nullable_date_cols: Sequence[str] = (),
) -> pa.Table:
    """Read ``columns`` of a parquet file with every row dated on or after CUTOFF excluded in the scan."""
    p = Path(path)
    cols = list(columns)
    if not cols:
        raise ValueError("columns must name at least one column")
    if len(set(cols)) != len(cols):
        raise ValueError("columns must not repeat")
    roles = {"date_cols": list(date_cols), "nullable_date_cols": list(nullable_date_cols), "mask_cols": list(mask_cols)}
    seen: set[str] = set()
    for role, names in roles.items():
        for c in names:
            if c not in cols:
                raise ValueError(f"{role} entry {c!r} is not in columns")
            if c in seen:
                raise ValueError(f"column {c!r} has more than one cutoff role")
            seen.add(c)
    _check_sha(p, expect_sha256)

    dataset = ds.dataset(p, format="parquet")
    schema = dataset.schema
    missing = [c for c in cols if c not in schema.names]
    if missing:
        raise KeyError(f"columns not in file: {missing}")
    types = {c: schema.field(c).type for c in cols}
    for c in cols:
        if _is_temporal(types[c]) and c not in seen:
            raise CutoffError(f"date/timestamp column {c!r} needs a role in date_cols, nullable_date_cols or mask_cols")
    for c in seen:
        if not (_is_temporal(types[c]) or _is_string(types[c])):
            raise TypeError(f"column {c!r} has type {types[c]}, not a date, timestamp or ISO string")

    filt: ds.Expression | None = None
    for c in roles["date_cols"]:
        cond = _field_expr(c, types[c]) < _cutoff_scalar(types[c])
        filt = cond if filt is None else filt & cond
    for c in roles["nullable_date_cols"]:
        cond = ds.field(c).is_null() | (_field_expr(c, types[c]) < _cutoff_scalar(types[c]))
        filt = cond if filt is None else filt & cond

    projection: dict[str, ds.Expression] = {}
    for c in cols:
        expr = _field_expr(c, types[c]) if c in seen else ds.field(c)
        if c in roles["mask_cols"]:
            out_type = pa.date32() if _is_string(types[c]) else types[c]
            null = pa.scalar(None, type=out_type)
            expr = pc.if_else(expr < _cutoff_scalar(types[c]), expr, null)
        projection[c] = expr

    table = dataset.to_table(columns=projection, filter=filt)
    _assert_before_cutoff(table, seen)
    return table


_DROPPED = object()


def _parse_iso_date(value: Any, key: str) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) < 10:
        raise CutoffError(f"date key {key!r} is not an ISO date string")
    return dt.date.fromisoformat(value[:10])


def read_json_pre_cutoff(
    path: str | Path,
    keys: Sequence[str],
    date_keys: Sequence[str] = (),
    records_key: str | None = None,
    expect_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Read a JSON list of records (optionally under ``records_key``), keeping only ``keys``.

    Objects are pruned to the named keys while parsing; an object whose date key is on or
    after CUTOFF is dropped as it is parsed. Null dates are kept. Every record must carry
    every named key.
    """
    p = Path(path)
    wanted = list(keys)
    if not wanted:
        raise ValueError("keys must name at least one key")
    dkeys = list(date_keys)
    for k in dkeys:
        if k not in wanted:
            raise ValueError(f"date key {k!r} is not in keys")
    _check_sha(p, expect_sha256)
    allowed = set(wanted) | ({records_key} if records_key else set())

    def hook(pairs: list[tuple[str, Any]]) -> Any:
        obj = {k: v for k, v in pairs if k in allowed}
        for k in dkeys:
            if k in obj:
                d = _parse_iso_date(obj[k], k)
                if d is not None and d >= CUTOFF:
                    return _DROPPED
        return obj

    with p.open(encoding="utf-8") as f:
        top = json.load(f, object_pairs_hook=hook)
    records = top[records_key] if records_key else top
    if not isinstance(records, list):
        raise TypeError("records are not a JSON list")
    out: list[dict[str, Any]] = []
    for rec in records:
        if rec is _DROPPED:
            continue
        if not isinstance(rec, dict):
            raise TypeError("record is not a JSON object")
        absent = [k for k in wanted if k not in rec]
        if absent:
            raise KeyError(f"record lacks keys {absent}")
        out.append({k: rec[k] for k in wanted})
    return out
