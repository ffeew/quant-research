"""Fail-closed validators for the AV payload shapes H2-C consumes. Inputs are already-read bytes/objects."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from typing import Any

from .errors import IntegrityError, PathError, SchemaError

ISO_DATE = re.compile(r"\d{4}-\d\d-\d\d")
PRICE_KEYS = frozenset(
    {
        "1. open",
        "2. high",
        "3. low",
        "4. close",
        "5. adjusted close",
        "6. volume",
        "7. dividend amount",
        "8. split coefficient",
    }
)
PRICE_ADJ_KEY = "5. adjusted close"
EARN_KEYS = frozenset(
    {"fiscalDateEnding", "reportedDate", "reportedEPS", "estimatedEPS", "surprise", "surprisePercentage", "reportTime"}
)
TX_KEYS = frozenset({"symbol", "quarter", "transcript"})
TX_ENTRY_KEYS = frozenset({"content", "sentiment", "speaker", "title"})
PURGE_HEADER = ("boundary", "in_window_rows", "purged", "kept", "excl_no_reporttime")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def verify_sha(b: bytes, want: str, what: str = "input") -> bytes:
    """Raise ``IntegrityError`` unless sha256(b) == want. Returns ``b`` unchanged."""
    got = sha256_hex(b)
    if got != want:
        raise IntegrityError(f"sha mismatch {what}: got {got} want {want}")
    return b


def parse_sums(text: str) -> dict[str, str]:
    """Parse a sha256sum listing into {relative path: sha}. Absolute or escaping paths and duplicates are refused."""
    d: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        h, q = line.split(None, 1)
        q = q.lstrip("*")
        if q.startswith("./"):
            q = q[2:]
        if q.startswith("/") or ".." in q.split("/") or q == "":
            raise PathError(f"sums path not relative / escapes root: {q!r}")
        if len(h) != 64 or q in d:
            raise SchemaError(f"sums format: {line!r}")
        d[q] = h
    return d


def _fnum(v: Any, what: str) -> float:
    if not isinstance(v, str):
        raise SchemaError(f"{what}: value not str")
    try:
        return float(v)
    except ValueError:
        raise SchemaError(f"{what}: non-float string") from None


def parse_prices(obj: Any, symbols: Iterable[str]) -> list[dict[str, Any]]:
    """``obj``: {symbol: [[date, {8 AV keys: str}], ...]} with exactly ``symbols`` as keys.
    Returns flat rows {symbol, date, adjusted_close} sorted by symbol then ascending date."""
    want = set(symbols)
    if not isinstance(obj, dict) or set(obj) != want:
        raise SchemaError(f"prices: top level not a dict of {len(want)} symbols")
    out: list[dict[str, Any]] = []
    for s in sorted(obj):
        seq = obj[s]
        if not isinstance(seq, list):
            raise SchemaError(f"prices {s}: value not a list")
        rows = []
        for x in seq:
            if not (isinstance(x, list) and len(x) == 2 and isinstance(x[0], str) and isinstance(x[1], dict)):
                raise SchemaError(f"prices {s}: row not [str, dict]")
            if not ISO_DATE.fullmatch(x[0]):
                raise SchemaError(f"prices {s}: date not ISO")
            if set(x[1]) != PRICE_KEYS:
                raise SchemaError(f"prices {s}: key set {sorted(x[1])}")
            if not all(isinstance(v, str) for v in x[1].values()):
                raise SchemaError(f"prices {s}: value not str")
            v = _fnum(x[1][PRICE_ADJ_KEY], f"prices {s}")
            if not (math.isfinite(v) and v > 0):
                raise SchemaError(f"prices {s}: bad adjusted close on {x[0]}")
            rows.append(dict(symbol=s, date=x[0], adjusted_close=v))
        rows.sort(key=lambda r: r["date"])
        out += rows
    return out


def parse_earnings(
    obj: Any, symbols: Iterable[str], held: Iterable[str] = (), exact: bool = True
) -> list[dict[str, Any]]:
    """``obj``: {symbol: [7-key dict of str]}. Symbols in ``held`` are checked as containers only and dropped.
    ``exact``: top-level keys must equal ``symbols``; otherwise they must be a subset (late-listed names may be absent)."""
    want, held_ = set(symbols), set(held)
    if not isinstance(obj, dict) or (set(obj) != want if exact else not set(obj) <= want):
        raise SchemaError("earnings: top-level symbol set mismatch")
    out: list[dict[str, Any]] = []
    for s in sorted(obj):
        seq = obj[s]
        if not isinstance(seq, list) or not all(isinstance(x, dict) for x in seq):
            raise SchemaError(f"earnings {s}: not a list of dicts")
        if s in held_:
            continue
        rows = []
        for x in seq:
            if set(x) != EARN_KEYS:
                raise SchemaError(f"earnings {s}: key set {sorted(x)}")
            if not all(isinstance(v, str) for v in x.values()):
                raise SchemaError(f"earnings {s}: value not str")
            rows.append(dict(x, symbol=s))
        rows.sort(key=lambda r: (r["reportedDate"], r["fiscalDateEnding"]))
        out += rows
    return out


def parse_transcript_label(rel: str, universe: Iterable[str]) -> tuple[str, str]:
    """``SYM/YYYYQn.json`` -> (SYM, 'YYYYQn')."""
    parts = rel.split("/")
    if len(parts) != 2 or not parts[1].endswith(".json"):
        raise SchemaError(f"transcript name {rel}")
    sym, lab = parts[0], parts[1][:-5]
    if sym not in set(universe) or len(lab) != 6 or lab[4] != "Q" or lab[5] not in "1234" or not lab[:4].isdigit():
        raise SchemaError(f"transcript label {rel}")
    return sym, lab


def validate_transcript(obj: Any, symbol: str, label: str) -> list[dict[str, str]]:
    """Check an AV transcript object and return its entries."""
    from .errors import MappingError

    if not isinstance(obj, dict) or set(obj) != TX_KEYS:
        raise SchemaError("transcript schema")
    if obj["symbol"] != symbol or obj["quarter"] != label:
        raise MappingError(f"transcript key mismatch {symbol} {label}")
    if not isinstance(obj["transcript"], list):
        raise SchemaError("transcript schema: transcript not a list")
    for ent in obj["transcript"]:
        if not isinstance(ent, dict) or set(ent) != TX_ENTRY_KEYS or not all(isinstance(x, str) for x in ent.values()):
            raise SchemaError(f"transcript entry schema {symbol} {label}")
    return obj["transcript"]


def loads_json(b: bytes | str) -> Any:
    return json.loads(b)
