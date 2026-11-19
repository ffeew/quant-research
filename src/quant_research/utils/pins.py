"""Desk-supplied sha256 pins and desk-only literals, read from config (never committed).

The public repo ships ``configs/pins/desk_pins.toml`` with every value ``PENDING``, so each check
that compares a file against a pin fails closed. A desk run points ``$QR_DESK_PINS`` at its own
copy of the file holding the real values. One TOML table per module (``[strategies.iv_gap.runner]``),
one key per pin; a missing file, table or key reads as ``PENDING``.
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


def reload() -> None:
    """Forget the cached pin file (tests that switch $QR_DESK_PINS)."""
    _tables.cache_clear()
