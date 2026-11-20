"""H2-C parameters and partitions.

Method parameters (windows, horizons, gates, costs) come from the ``[h2c]`` section of
``configs/sentiment_returns.toml`` (located via ``quant_research.utils.config.CONFIG_DIR``).

Holdout-specific expected counts (purge-row counts, row counts, excluded-transcript counts) are NOT in the repo.
They are supplied at run time from a JSON file named by the ``QR_H2C_HOLDOUT_EXPECTED`` environment variable
(or an explicit path). Missing values stay ``None`` and the purge/count gates refuse to run on them.
The H2-C HOLDOUT partition itself is spent: ``pipeline.run_h2c`` refuses it before reading any input.

The ``exclude_mapped_before`` field (pre-2010 transcript exclusion) and the ``excl_before_partition`` status for pre-partition holdout earnings rows are unverified against main_holdout; not for holdout use.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from quant_research.utils import config as _cfg

from .errors import ConfigError

HOLDOUT_EXPECTED_ENV = "QR_H2C_HOLDOUT_EXPECTED"
PURGE_COUNT_KEYS = ("in_window_rows", "purged", "kept", "excl_no_reporttime")


def quarters(first_year: int, last_year: int) -> tuple[str, ...]:
    return tuple(f"{y}Q{q}" for y in range(first_year, last_year + 1) for q in range(1, 5))


@dataclass(frozen=True)
class Partition:
    """One sample partition (e.g. DEV or HOLDOUT)."""

    name: str
    lo: str  # earliest reportedDate / transcript mapping date (ISO); earlier rows are baselines or excluded
    hi: str  # last reportedDate and last allowed return-window end (ISO)
    score_lo: str  # first scored reportedDate (ISO); earlier events are warm-up only
    scored_quarters: tuple[str, ...]
    g0_min_quarters: int
    purge_window: tuple[str, str]
    purge_boundary: str  # label of the boundary row in a purge reference table
    exclude_mapped_before: str | None = None  # mapped reportedDate before this is counted EXCLUDED, never scored

    @property
    def d_lo(self) -> dt.date:
        return dt.date.fromisoformat(self.lo)

    @property
    def d_hi(self) -> dt.date:
        return dt.date.fromisoformat(self.hi)


@dataclass(frozen=True)
class H2CParams:
    universe: tuple[str, ...]
    hedge: str = "SPY"
    beta_n: int = 252
    h0: int = 1
    h1: int = 21
    lag: int = 100
    nprior_max: int = 4
    nprior_min: int = 2
    tone_min: int = 10
    q_min_events: int = 20
    quantile_div: int = 5
    cost_side: float = 0.0010
    cost_side_sens: float = 0.0020
    borrow: float = 0.10
    nw_lag: int = 1
    g1_min_t: float = 2.0
    g2_alpha: float = 0.01
    g2_ic_frac: float = 0.5
    timed_report_times: tuple[str, str] = ("pre-market", "post-market")
    partitions: dict[str, Partition] = field(default_factory=dict)

    def partition(self, name: str) -> Partition:
        try:
            return self.partitions[name]
        except KeyError:
            raise ConfigError(f"unknown partition {name!r}; known: {sorted(self.partitions)}") from None


def params_from_dict(d: dict[str, Any]) -> H2CParams:
    d = dict(d)
    parts = {}
    for name, p in d.pop("partitions", {}).items():
        y0, y1 = p["scored_years"]
        parts[name] = Partition(
            name=name,
            lo=p["lo"],
            hi=p["hi"],
            score_lo=p["score_lo"],
            scored_quarters=quarters(int(y0), int(y1)),
            g0_min_quarters=int(p["g0_min_quarters"]),
            purge_window=(p["purge_window"][0], p["purge_window"][1]),
            purge_boundary=str(p["purge_boundary"]),
            exclude_mapped_before=p.get("exclude_mapped_before"),
        )
    known = {f.name for f in fields(H2CParams)}
    unknown = set(d) - known
    if unknown:
        raise ConfigError(f"unknown h2c config keys {sorted(unknown)}")
    if "universe" not in d:
        raise ConfigError("h2c config needs a universe")
    d["universe"] = tuple(sorted(d["universe"]))
    if "timed_report_times" in d:
        d["timed_report_times"] = tuple(d["timed_report_times"])
    return H2CParams(partitions=parts, **d)


def load_h2c_params(path: str | os.PathLike[str] | None = None, section: str = "h2c") -> H2CParams:
    """Load parameters from a TOML file (default ``<CONFIG_DIR>/sentiment_returns.toml``) section ``[h2c]``."""
    p = Path(path) if path is not None else Path(_cfg.CONFIG_DIR) / "sentiment_returns.toml"
    with p.open("rb") as fh:
        cfg = tomllib.load(fh)
    if section not in cfg:
        raise ConfigError(f"{p.name} has no [{section}] section")
    return params_from_dict(cfg[section])


@dataclass(frozen=True)
class HoldoutExpectations:
    """Runtime-only expected counts for a holdout run. All ``None`` unless supplied."""

    purge: dict[str, int] | None = None
    rows: dict[str, int] | None = None
    excluded_mapped: int | None = None

    def require(self, *names: str) -> None:
        missing = [n for n in names if getattr(self, n) is None]
        if missing:
            raise ConfigError("holdout expectations unfilled: " + ",".join(missing))


def _int_dict(v: Any, what: str, keys: tuple[str, ...] | None = None) -> dict[str, int]:
    if not isinstance(v, dict) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v.values()):
        raise ConfigError(f"{what}: must be a dict of plain ints")
    if keys is not None and set(v) != set(keys):
        raise ConfigError(f"{what}: keys must be exactly {list(keys)}")
    return dict(v)


def load_holdout_expectations(path: str | os.PathLike[str] | None = None) -> HoldoutExpectations:
    """Read expectations from ``path`` or ``$QR_H2C_HOLDOUT_EXPECTED`` (JSON with optional keys
    ``purge``, ``rows``, ``excluded_mapped``). Returns an empty object when neither is set."""
    p = path if path is not None else os.environ.get(HOLDOUT_EXPECTED_ENV)
    if not p:
        return HoldoutExpectations()
    with open(p, encoding="utf-8") as fh:
        raw = json.load(fh)
    purge = raw.get("purge")
    rows = raw.get("rows")
    exc = raw.get("excluded_mapped")
    if exc is not None and (not isinstance(exc, int) or isinstance(exc, bool)):
        raise ConfigError("excluded_mapped: must be a plain int")
    return HoldoutExpectations(
        purge=None if purge is None else _int_dict(purge, "purge", PURGE_COUNT_KEYS),
        rows=None if rows is None else _int_dict(rows, "rows"),
        excluded_mapped=exc,
    )
