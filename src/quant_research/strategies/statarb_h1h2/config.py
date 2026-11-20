"""Harness config: input paths and sha256 pins come from TOML + environment, never from code.

Lookup order for the config file: --config, then $QR_STATARB_H1H2_CONFIG, then the repo's
example ``configs/statarb_h1h2.toml`` (all pins PENDING, so the harness refuses to run).
Path values may use ${QR_DATA_DIR} / ${QR_DESK_DIR}; relative paths resolve under QR_DATA_DIR.
"""

from __future__ import annotations

import os
import string
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from quant_research.utils import paths as qr_paths
from quant_research.utils.config import CONFIG_DIR

from .guards import PENDING, Blocked, is_pending

CONFIG_ENV = "QR_STATARB_H1H2_CONFIG"
DEFAULT_CONFIG = CONFIG_DIR / "statarb_h1h2.toml"

# Every input the DEV run may open. Names are roles, not file names.
DEV_INPUTS = (
    "prereg",  # pre-registration document (acceptance hash = its sha256)
    "tr_dev_cut",  # DEV-only cut of the primary total-return file (no rows after embargo end)
    "tr_dev_cut_sums",  # SHA256SUMS that lists the cut as '<sha>  <path>'
    "earnings_dev_cut",  # earnings events, DEV-only cut
    "universe_gics",  # symbol, gics_sub_industry, gics_sector
    "membership",  # PIT index membership: symbol, start_date_filled, end_date [, after_boundary]
    "listing_status",  # symbol, ipoDate, delistingDate, listing_source (active|delisted)
    "reused_tickers",  # JSON {"tickers": [{"ticker", "original_member_periods": [[start, end|null]]}]}
    "missing_names",  # JSON {"tickers": [{"ticker"}]}
    "identity_list",  # TSV identity list (symbol, decision, reasons, issuer_name)
    "identity_basis_sums",  # accepted identity-basis SUMS (hash-only gate)
    "lineage_exclusions",  # TSV with a symbol column
    "dev_universe",  # CSV with a symbol column
    "h1_terminal_roster",  # JSON list of unresolved terminal rows (H1 adverse bound)
)
OPTIONAL_INPUTS = ("acquirer_closes",)  # parquet: symbol, session_date, close (H1 short V_max)


@dataclass(frozen=True)
class Pin:
    path: str
    sha256: str

    @property
    def pending(self) -> bool:
        return is_pending(self.path) or is_pending(self.sha256)


@dataclass(frozen=True)
class HarnessConfig:
    inputs: dict[str, Pin]
    out_dir: str
    expected_lineage_exclusions: int | None = None
    listing_overlap_treatment: dict[str, str] = field(default_factory=dict)
    source: str = ""

    def pin(self, name: str) -> Pin:
        p = self.inputs.get(name)
        if p is None or p.pending:
            raise Blocked(f"REFUSING: input {name!r} path/sha PENDING.")
        return p

    def pending(self, names: tuple[str, ...] = DEV_INPUTS) -> list[str]:
        return sorted(n for n in names if n not in self.inputs or self.inputs[n].pending)


def _expand(v: str) -> str:
    if is_pending(v):
        return PENDING
    s = string.Template(v).safe_substitute(QR_DATA_DIR=qr_paths.DATA_DIR, QR_DESK_DIR=qr_paths.DESK_DIR)
    if "$" in s:
        raise Blocked(f"REFUSING: unresolved variable in config path {v!r}.")
    return s if Path(s).is_absolute() else os.path.join(qr_paths.DATA_DIR, s)


def load_config(path: str | os.PathLike[str] | None = None) -> HarnessConfig:
    src = Path(path or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG)
    with src.open("rb") as fh:
        raw = tomllib.load(fh)
    h = raw.get("harness")
    if not isinstance(h, dict):
        raise Blocked(f"REFUSING: no [harness] section in {src.name}.")
    inputs: dict[str, Pin] = {}
    for name, spec in (h.get("inputs") or {}).items():
        if name not in DEV_INPUTS + OPTIONAL_INPUTS:
            raise Blocked(f"REFUSING: unknown input {name!r} in config.")
        sha = str(spec.get("sha256", PENDING)).strip()
        sha = PENDING if is_pending(sha) else sha.lower()
        if not is_pending(sha) and (len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)):
            raise Blocked(f"REFUSING: input {name!r} sha256 is not 64 hex chars.")
        inputs[name] = Pin(_expand(str(spec.get("path", PENDING))), PENDING if is_pending(sha) else sha)
    n_lin = h.get("expected_lineage_exclusions")
    return HarnessConfig(
        inputs=inputs,
        out_dir=_expand(str(h.get("out_dir", "outputs/statarb_h1h2"))),
        expected_lineage_exclusions=int(n_lin) if n_lin is not None else None,
        listing_overlap_treatment=dict(h.get("listing_overlap_treatment") or {}),
        source=src.name,
    )
