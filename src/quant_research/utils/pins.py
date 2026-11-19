"""Desk-supplied sha256 pins and desk-only literals, read from config (never committed).

The public repo ships ``configs/pins/desk_pins.toml`` with every value ``PENDING``, so each check
that compares a file against a pin fails closed. A desk run points ``$QR_DESK_PINS`` at its own
copy of the file holding the real values. One TOML table per module (``[strategies.iv_gap.runner]``),
one key per pin; a missing file, table or key reads as ``PENDING``.

A runner that only records a pin (writes it into its outputs rather than comparing a file
against it) must call ``require_pins`` before doing any work, so it refuses to run on a
``PENDING`` or missing pin instead of writing ``PENDING`` into its results.
"""

from __future__ import annotations

import os
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

from quant_research.utils.config import CONFIG_DIR

PINS_ENV = "QR_DESK_PINS"
PENDING = "PENDING"
DEFAULT_PINS = CONFIG_DIR / "pins" / "desk_pins.toml"


def _flatten(prefix: str, table: dict[str, Any], out: dict[str, dict[str, Any]]) -> None:
    leaves = {k: v for k, v in table.items() if not isinstance(v, dict)}
    if leaves:
        out.setdefault(prefix, {}).update(leaves)
    for k, v in table.items():
        if isinstance(v, dict):
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)


@cache
def _tables() -> dict[str, dict[str, Any]]:
    path = Path(os.environ.get(PINS_ENV) or DEFAULT_PINS)
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except OSError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    _flatten("", raw, out)
    return out


def desk_pin(namespace: str, key: str) -> str:
    """The configured value for ``key`` in ``[namespace]``, or ``PENDING``."""
    value = _tables().get(namespace, {}).get(key, PENDING)
    if not isinstance(value, str):
        raise TypeError(f"desk pin {namespace}.{key} must be a string, got {type(value).__name__}")
    return value


class PinPending(RuntimeError):
    """A desk pin needed by a run is PENDING or missing."""


def require_pins(namespace: str, *keys: str) -> dict[str, str]:
    """Values for ``keys`` in ``[namespace]``; raise PinPending if any is PENDING, empty or missing."""
    values = {k: desk_pin(namespace, k) for k in keys}
    bad = [k for k, v in values.items() if not v or v == PENDING]
    if bad:
        raise PinPending(
            f"refusing to run: desk pin(s) {namespace} {bad} are PENDING or missing; "
            f"point ${PINS_ENV} at the desk pin file"
        )
    return values


def reload() -> None:
    """Forget the cached pin file (tests that switch $QR_DESK_PINS)."""
    _tables.cache_clear()
