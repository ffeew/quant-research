"""H3 parameters.

Method constants (windows, band thresholds, costs, minimum counts) come from the ``[h3]`` section of
``configs/sentiment_returns.toml``. Data locations and integrity pins are runtime inputs and are not stored here.

Some design choices are not settled. Each is an explicit optional parameter whose committed value is absent
(``None``); a caller must set it before the code path that depends on it will run:

- ``flat_clears_band_memory``  whether band positions are forgotten when the book is held flat.
- ``drift_renormalise_legs``   whether intra-week weight drift renormalises each leg to +1 / -1.
- ``sector_ic_method``         how the sector-neutral IC is formed (``"demeaned_spearman"`` is implemented).
- ``n_universe``               the required universe size check.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from quant_research.utils import config as _cfg

from .errors import H3ConfigError

SECTOR_IC_METHODS = ("demeaned_spearman",)
UNSETTLED = ("flat_clears_band_memory", "drift_renormalise_legs", "sector_ic_method", "n_universe")


@dataclass(frozen=True)
class H3Params:
    window_sessions: int = 20  # signal window for the primary variant
    window_sessions_fast: int = 5  # signal window for the fast variant
    min_items: int = 5  # min kept news items per name per window
    min_names: int = 40  # min qualifying names for a scored week
    min_leg: int = 5  # min names per leg, else the book is flat
    long_in: float = 0.80
    long_hold: float = 0.60
    short_in: float = 0.20
    short_hold: float = 0.40
    rel_min: float = 0.50
    nw_lag: int = 4
    cost_side: float = 0.0010
    cost_side_sens: float = 0.0020
    beta_n: int = 252
    quantile_div: int = 5
    cutoff_hhmm: tuple[int, int] = (15, 30)
    hedge: str = "SPY"
    research_only: tuple[str, ...] = ()
    flat_clears_band_memory: bool | None = None
    drift_renormalise_legs: bool | None = None
    sector_ic_method: str | None = None
    n_universe: int | None = None

    def require(self, name: str) -> Any:
        """Return parameter ``name`` or raise if it is an unsettled choice with no value."""
        v = getattr(self, name)
        if v is None:
            raise H3ConfigError(f"h3 parameter {name!r} is not set; it is a configurable design choice")
        return v

    def with_choices(self, **kw: Any) -> H3Params:
        bad = set(kw) - set(UNSETTLED)
        if bad:
            raise H3ConfigError(f"not an unsettled choice: {sorted(bad)}")
        return replace(self, **kw)


def params_from_dict(d: dict[str, Any]) -> H3Params:
    d = dict(d)
    unknown = set(d) - {f.name for f in fields(H3Params)}
    if unknown:
        raise H3ConfigError(f"unknown h3 config keys {sorted(unknown)}")
    for k in ("cutoff_hhmm", "research_only"):
        if k in d:
            d[k] = tuple(d[k])
    m = d.get("sector_ic_method")
    if m is not None and m not in SECTOR_IC_METHODS:
        raise H3ConfigError(f"sector_ic_method {m!r} not in {SECTOR_IC_METHODS}")
    p = H3Params(**d)
    if not (0 < p.short_in < p.short_hold <= p.long_hold < p.long_in < 1):
        raise H3ConfigError("band thresholds must satisfy 0 < short_in < short_hold <= long_hold < long_in < 1")
    return p


def load_h3_params(path: str | os.PathLike[str] | None = None, section: str = "h3") -> H3Params:
    """Load ``[h3]`` from a TOML file (default ``<CONFIG_DIR>/sentiment_returns.toml``)."""
    p = Path(path) if path is not None else Path(_cfg.CONFIG_DIR) / "sentiment_returns.toml"
    with p.open("rb") as fh:
        cfg = tomllib.load(fh)
    if section not in cfg:
        raise H3ConfigError(f"{p.name} has no [{section}] section")
    return params_from_dict(cfg[section])
