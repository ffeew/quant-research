#!/usr/bin/env python3
"""Stage A / sealed-holdout backtest runner for the statarb ideas H1 and H2 (frozen v1.3f).

H1 = sub-industry bellwether lag; H2 = earnings peer read-through. Implements the primary
rules of the pre-registration (see research/statarb_bellwether/reports/PREREG_v3.md).

Every input path and sha256 pin is read from the [pins] section of
configs/statarb_bellwether.toml (or the file named by $QR_STATARB_BELLWETHER_CONFIG).
Values may use ${QR_DATA_DIR}, ${QR_DESK_DIR}, ${HOME_DIR} and ${QR_COSTS_DIR}. The repo's
copy holds only PENDING placeholders, so the runner refuses: the vendored-numpy check
below exits 17 at import until its pins are filled in.

HARD RULES:
  - Read-time pyarrow date filters only. DEV never loads post-2021-12-31 rows.
    Holdout loads only its own window, and only when --stage holdout is accepted.
  - --stage holdout REFUSES to run without --acceptance-hash equal to sha256 of
    the current pre-registration file (frozen accepted hash).
  - --stage dev that would compute returns likewise requires --acceptance-hash.
  - Quarantined outputs under QUARANTINE are never read.
  - Holdout rows 2022-03-30 onward are never touched in --stage dev.
  - Costs: costs_original.CostConfig; required path borrow >=10%/yr on EVERY
    historically unknown short including H2 sector-ETF hedges (no ETF exemption).
    The 1%/yr path is a labelled GC counterfactual only.
  - Impact k = cost_model.K_IMPACT_DEFAULT = 1.0 (base); k = 0.75 is a lighter
    sensitivity, not a stress.

This file MAY compute returns when invoked with a valid acceptance hash.
A --help or syntax check is always safe and computes no returns.

Run examples (safe):
  python3 -I -B backtest_h1_h2_v1_3f.py --help
  python3 -I -B backtest_h1_h2_v1_3f.py --syntax-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import string
import sys
import tomllib
from collections.abc import Callable, Iterator
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from quant_research.utils import config as _QRC
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

PENDING = "PENDING"
CONFIG_ENV = "QR_STATARB_BELLWETHER_CONFIG"


def _load_pin_table() -> dict[str, Any]:
    """[pins] of the trial config. Missing file/section/key -> PENDING (fail closed)."""
    cfg = Path(os.environ.get(CONFIG_ENV) or (_QRC.CONFIG_DIR / "statarb_bellwether.toml"))
    try:
        with open(cfg, "rb") as fh:
            return dict(tomllib.load(fh).get("pins", {}))
    except OSError:
        return {}


_PINS = _load_pin_table()
_ROOTS = {
    "QR_DATA_DIR": _QR.DATA_DIR,
    "QR_DESK_DIR": _QR.DESK_DIR,
    "HOME_DIR": _QR.HOME_DIR,
    "QR_COSTS_DIR": _QR.COSTS_DIR,
}


def _pin(name: str, default: Any = PENDING) -> Any:
    """One config value; strings get ${ROOT} expansion. Absent -> default."""
    v = _PINS.get(name, default)
    if isinstance(v, str):
        return string.Template(v).safe_substitute(_ROOTS)
    if isinstance(v, dict):
        return {str(k): (string.Template(x).safe_substitute(_ROOTS) if isinstance(x, str) else x) for k, x in v.items()}
    return v


# ---- Vendored numpy pin: RECORD raw sha is checked BEFORE sys.path is touched ----
NP_SITE = _pin("NP_SITE")
NP_RECORD_REL = _pin("NP_RECORD_REL")
NP_VERSION = _pin("NP_VERSION")
NP_RECORD_SHA256 = _pin("NP_RECORD_SHA256")
RC_C7_NUMPY_PIN = 17  # exit code; distinct from 0 (ok), 1 (SystemExit/Blocked), 2 (argparse)
try:
    with open(NP_SITE + "/" + NP_RECORD_REL, "rb") as _np_rec_fh:
        _np_rec_sha: str | None = hashlib.sha256(_np_rec_fh.read()).hexdigest()
except OSError:
    _np_rec_sha = None
if _np_rec_sha != NP_RECORD_SHA256:
    raise SystemExit(RC_C7_NUMPY_PIN)
sys.path.insert(0, NP_SITE)
import numpy as np

if not (
    os.path.realpath(np.__file__).startswith(os.path.realpath(NP_SITE) + "/numpy/") and np.__version__ == NP_VERSION
):
    raise SystemExit(RC_C7_NUMPY_PIN)
# ---- vendored numpy pin END ----
import pandas as pd

COSTS_ORIGINAL_DIR = _pin("COSTS_ORIGINAL_DIR")  # directory holding the frozen costs_original module
sys.path.insert(0, f"{_QR.COSTS_DIR}")
sys.path.insert(0, f"{COSTS_ORIGINAL_DIR}")
from costs_original import (
    BORROW_UNKNOWN_REQUIRED,
    EARLY_CLOSE_DAYS_2026,
    K_IMPACT_BASE,
    K_IMPACT_LIGHTER,
    borrow_usd,
    build_cost_config,
    one_way_bps,
)

from quant_research.backtest.costs import cost_model as cm

# ---- Paths / pins (all from config) ----
ROOT = Path(f"{_QR.DESK_DIR}")
PREREG_PATH = Path(_pin("PREREG_PATH"))
PREREG_TR_PIN_LINE = int(_pin("PREREG_TR_PIN_LINE", 38))  # 1-based line of the pre-registration holding the TR pin
RELEASE = Path(_pin("RELEASE"))
EARNINGS = Path(_pin("EARNINGS"))  # earnings DEV cut
QUARANTINE = Path(_pin("QUARANTINE"))  # quarantined outputs: never read
OUT_DIR = Path(_pin("OUT_DIR"))

# Desk data client: declared interface in DeskClientInterface below; the runner refuses while PENDING.
DESK_CLIENT_PATH = _pin("DESK_CLIENT_PATH")
DESK_CLIENT_SHA256 = _pin("DESK_CLIENT_SHA256")
PIN_RECONCILIATION_SEAL_SHA256 = _pin("PIN_RECONCILIATION_SEAL_SHA256")  # sealed SHA256SUMS of the reconciliation root
PIN_CA_LEDGER_SHA256 = _pin("PIN_CA_LEDGER_SHA256")  # reconciled corporate-action ledger
PIN_FACTOR_TABLE_SHA256 = _pin("PIN_FACTOR_TABLE_SHA256")  # cumulative PIT desk factor table
PIN_FACTOR_CODE_SHA256 = _pin("PIN_FACTOR_CODE_SHA256")  # factor code (tested on synthetic fixtures)
PIN_AV_RAW_BARS_SHA256 = _pin("PIN_AV_RAW_BARS_SHA256")  # AV raw bar file (--av-factor-sensitivity only)
# H1 terminal roster (unresolved delisting rows), pinned.
H1_TERMINAL_ROSTER_PATH = _pin("H1_TERMINAL_ROSTER_PATH")
H1_TERMINAL_ROSTER_SHA256 = _pin("H1_TERMINAL_ROSTER_SHA256")
H1_TERMINAL_PATHS = ("A", "B")
# Declared interpreter site for pyarrow. Pin = sha256 of the dist-info RECORD file.
PYARROW_SITE_APPROVED = _pin("PYARROW_SITE_APPROVED")
PYARROW_RECORD_REL = _pin("PYARROW_RECORD_REL")
PYARROW_RECORD_SHA256 = _pin("PYARROW_RECORD_SHA256")
# Universe inputs
V13A_DIR = Path(_pin("V13A_DIR"))
R18_INPUT_PATH = Path(_pin("R18_INPUT_PATH"))  # reused tickers: original member periods
R18_INPUT_SHA256 = _pin("R18_INPUT_SHA256")
M14_INPUT_PATH = Path(_pin("M14_INPUT_PATH"))  # names with no usable history
M14_INPUT_SHA256 = _pin("M14_INPUT_SHA256")
PIN_PIT_MEMBERSHIP_SHA256 = _pin("PIN_PIT_MEMBERSHIP_SHA256")
PIN_LISTING_STATUS_SHA256 = _pin("PIN_LISTING_STATUS_SHA256")
# Fill rule (FUTURE HOOK, NOT IMPLEMENTED): any fill input is refused.
FILL_INPUT_PATH = None

# Splits (pre-registered); holdout starts 2022-03-30 — never load in DEV
DEV0, DEV1 = date(2017, 1, 3), date(2021, 12, 31)
EMBARGO0, EMBARGO1 = date(2022, 1, 3), date(2022, 3, 29)
HOLDOUT0, HOLDOUT1 = date(2022, 3, 30), date(2026, 10, 28)
LOAD0 = date(2015, 12, 31)  # warm-up only; still filtered by stage end
# PRIMARY returns = the pre-registered daily total-return file, read ONLY through a sealed
# DEV-only cut (rows <= 2022-03-29). The parent file is never opened, not even with a filter.
TR_PARENT_SHA256 = _pin("TR_PARENT_SHA256")  # pre-registration TR pin literal
TR_DEV_CUT_PATH = _pin("TR_DEV_CUT_PATH")  # sealed DEV-only cut
TR_DEV_CUT_SHA256 = _pin("TR_DEV_CUT_SHA256")  # raw-byte sha256 of that cut
TR_DEV_CUT_SUMS_PATH = _pin("TR_DEV_CUT_SUMS_PATH")  # the cut's accepted SHA256SUMS
TR_DEV_CUT_SUMS_SHA256 = _pin("TR_DEV_CUT_SUMS_SHA256")
# Identity-map FINAL_LIST, re-checked at use.
FINAL_LIST_PATH = _pin("FINAL_LIST_PATH")
FINAL_LIST_SHA256 = _pin("FINAL_LIST_SHA256")
# Header is exactly these 36 bytes, TAB-separated, LF, no CR.
FINAL_LIST_HEADER = b"symbol\tdecision\treasons\tissuer_name\n"
FINAL_LIST_COLUMNS = ("symbol", "decision", "reasons", "issuer_name")  # 4 fields on every row; issuer_name unused
FINAL_LIST_DECISIONS = {"KEPT": "kept", "EXCLUDED": "excluded"}
RC_FINAL_LIST_MISMATCH = 18  # exit code; distinct from 0 (ok), 1 (Blocked), 2 (argparse), 17 (numpy pin)
# H1/H2 refuse until the identity basis (B1c) is accepted.
B1C_ACCEPTED_SUMS_PATH = _pin("B1C_ACCEPTED_SUMS_PATH")  # SHA256SUMS of the accepted identity basis
B1C_ACCEPTED_SUMS_SHA256 = _pin("B1C_ACCEPTED_SUMS_SHA256")
# ---- DEV input binding ----
DEV_INPUTS_DIR = _pin("DEV_INPUTS_DIR")
DEV_INPUTS_SUMS_SHA256 = _pin("DEV_INPUTS_SUMS_SHA256")
ADDENDUM1_DIR = _pin("ADDENDUM1_DIR")
ADDENDUM1_SUMS_SHA256 = _pin("ADDENDUM1_SUMS_SHA256")
LINEAGE_EXCL_FILE, LINEAGE_EXCL_SHA256 = _pin("LINEAGE_EXCL_FILE"), _pin("LINEAGE_EXCL_SHA256")
LINEAGE_EXCL_COUNT = int(_pin("LINEAGE_EXCL_COUNT", -1))  # expected lineage exclusions (-1 = PENDING: refuses)
DEV_UNIVERSE_FILES = tuple(_pin("DEV_UNIVERSE_FILES", []))  # CSVs (symbol column) in DEV_INPUTS_DIR
DEV_CUTS_DIR = _pin("DEV_CUTS_DIR")
DEV_CUTS_SUMS_PATH = _pin("DEV_CUTS_SUMS_PATH")
DEV_CUTS_SUMS_SHA256 = _pin("DEV_CUTS_SUMS_SHA256")
# every parquet the runner (or its client) may open; name -> sha in DEV_CUTS_SUMS
DEV_CUT_PINS = _pin("DEV_CUT_PINS", {})
EARNINGS_SHA256 = DEV_CUT_PINS.get(EARNINGS.name, PENDING)
UNIVERSE_CUT = Path(_pin("UNIVERSE_CUT"))
UNIVERSE_CUT_SHA256 = DEV_CUT_PINS.get(UNIVERSE_CUT.name, PENDING)
# Listing overlap (symbol in both AV active and delisted sources): fail closed unless a pinned
# treatment covers it. None configured -> empty.
LISTING_OVERLAP_IN_UNIVERSE_PATH = _pin("LISTING_OVERLAP_IN_UNIVERSE_PATH")
LISTING_OVERLAP_IN_UNIVERSE_SHA256 = _pin("LISTING_OVERLAP_IN_UNIVERSE_SHA256")
LISTING_OVERLAP_TREATMENT: dict[str, Any] = _pin("LISTING_OVERLAP_TREATMENT", {})

SECTOR_ETF = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
ETFS = set(SECTOR_ETF.values()) | {"SPY", "AGG", "BND"}

AUM = 10e6
NAME_CAP = 0.095 / 0.58  # 9.5% of equity at 58% gross
ATR_STOP_MULT = 3.0  # risk max; fixed ex ante
BASKET_STOP_EQUITY = 0.01  # 1% of equity
PARTICIPATION_CAP = 0.01  # 1% ADV; remainder carries
MARGIN = 2  # 2-session earnings margin
# H2 counted delisting stress (pre-registered)
H2_DELISTING_STRESS_LONG = -0.30
H2_DELISTING_STRESS_SHORT = 0.0


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def assert_quarantine_untouched() -> None:
    """Refuse to proceed if anything tries to open the quarantined stops_dev outputs."""
    if not QUARANTINE.exists():
        return
    # Presence is fine; reading contents is forbidden. We only stat the directory.
    for p in QUARANTINE.iterdir():
        if p.is_file() and os.stat(p).st_mode & 0o444:
            # Mode may be 000; do not open. Byte-hash-only was already done historically.
            pass


def require_acceptance_hash(provided: str | None, stage: str) -> str:
    """Holdout (and any return-computing stage) requires --acceptance-hash == sha256(pre-registration)."""
    if not provided:
        raise SystemExit(
            f"REFUSING --stage {stage}: pass --acceptance-hash <sha256 of the pre-registration>. "
            "No return trial runs until the prereg is accepted at a recorded sha256."
        )
    actual = sha256_file(PREREG_PATH)
    if provided.strip().lower() != actual.lower():
        raise SystemExit(
            f"REFUSING --stage {stage}: --acceptance-hash does not match sha256(pre-registration).\n"
            f"  provided: {provided.strip().lower()}\n"
            f"  actual:   {actual}\n"
            "Re-hash after any prereg edit; the new hash must be accepted before a run."
        )
    return actual


def stage_date_bounds(stage: str) -> tuple[date, date, date]:
    """Return (filter_end_inclusive, eval_start, eval_end) for pyarrow filters / evaluation."""
    if stage == "dev":
        # Read-time filter end = DEV1; warm-up from LOAD0; evaluate DEV0..DEV1
        return DEV1, DEV0, DEV1
    if stage == "holdout":
        return HOLDOUT1, HOLDOUT0, HOLDOUT1
    raise SystemExit(f"unknown stage {stage!r}")


class Blocked(SystemExit):
    """Fail-closed refusal. Subclass of SystemExit: nothing runs after it."""


def verify_pyarrow_site(site: str | None, expected_sha: str | None) -> str:
    """Insert the declared pyarrow site (append, read-only) only if passed and pinned."""
    if not site:
        raise Blocked("REFUSING: --pyarrow-site not passed. The runner never auto-inserts a site path.")
    if os.path.normpath(site) != PYARROW_SITE_APPROVED:
        raise Blocked(f"REFUSING: --pyarrow-site {site!r} is not the declared approved path.")
    if not expected_sha or expected_sha.strip().lower() != PYARROW_RECORD_SHA256:
        raise Blocked("REFUSING: --pyarrow-site-sha missing or != pinned PYARROW_RECORD_SHA256.")
    record = Path(site) / PYARROW_RECORD_REL
    if not record.is_file():
        raise Blocked(f"REFUSING: {record} absent.")
    actual = sha256_file(record)
    if actual != PYARROW_RECORD_SHA256:
        raise Blocked(f"REFUSING: sha256({record}) = {actual} != pin {PYARROW_RECORD_SHA256}.")
    if site not in sys.path:
        sys.path.append(site)  # appended: never shadows stdlib/isolated paths; no writes
    import pyarrow

    if not os.path.realpath(pyarrow.__file__).startswith(os.path.realpath(site) + os.sep):
        raise Blocked(f"REFUSING: pyarrow resolved outside declared site: {pyarrow.__file__}")
    return actual


def require_data_pins(
    av_factor_sensitivity: bool = True,
) -> dict[str, Any]:  # default True = fail closed
    """Refuse while any desk-client / reconciliation / factor pin is PENDING."""
    pins = {
        "DESK_CLIENT_PATH": DESK_CLIENT_PATH,
        "DESK_CLIENT_SHA256": DESK_CLIENT_SHA256,
        "PIN_RECONCILIATION_SEAL_SHA256": PIN_RECONCILIATION_SEAL_SHA256,
        "PIN_CA_LEDGER_SHA256": PIN_CA_LEDGER_SHA256,
        "PIN_FACTOR_TABLE_SHA256": PIN_FACTOR_TABLE_SHA256,
        "PIN_FACTOR_CODE_SHA256": PIN_FACTOR_CODE_SHA256,
        "PIN_AV_RAW_BARS_SHA256": PIN_AV_RAW_BARS_SHA256,
        "TR_DEV_CUT_PATH": TR_DEV_CUT_PATH,
        "TR_DEV_CUT_SHA256": TR_DEV_CUT_SHA256,
        "TR_PARENT_SHA256": TR_PARENT_SHA256,
        "TR_DEV_CUT_SUMS_PATH": TR_DEV_CUT_SUMS_PATH,
        "TR_DEV_CUT_SUMS_SHA256": TR_DEV_CUT_SUMS_SHA256,
        "FINAL_LIST_SHA256": FINAL_LIST_SHA256,
        "B1C_ACCEPTED_SUMS_PATH": B1C_ACCEPTED_SUMS_PATH,
        "B1C_ACCEPTED_SUMS_SHA256": B1C_ACCEPTED_SUMS_SHA256,
        "H1_TERMINAL_ROSTER_PATH": H1_TERMINAL_ROSTER_PATH,
        "H1_TERMINAL_ROSTER_SHA256": H1_TERMINAL_ROSTER_SHA256,  # primary; fail fast
    }
    av_only = (
        "PIN_RECONCILIATION_SEAL_SHA256",
        "PIN_CA_LEDGER_SHA256",
        "PIN_FACTOR_TABLE_SHA256",
        "PIN_FACTOR_CODE_SHA256",
        "PIN_AV_RAW_BARS_SHA256",
    )  # gate only under --av-factor-sensitivity
    pending = [k for k, v in pins.items() if v == PENDING and (av_factor_sensitivity or k not in av_only)]
    if pending:
        raise Blocked(f"REFUSING: data pins PENDING (reconciliation not sealed / desk client not delivered): {pending}")
    return pins


def verify_tr_cut_sums() -> None:
    """The cut's line in its ACCEPTED SHA256SUMS (one pinned file: path + raw sha)
    must be exactly '<TR_DEV_CUT_SHA256>  <TR_DEV_CUT_PATH>'. Hash and text only; the cut is not opened here."""
    if PENDING in (TR_DEV_CUT_SUMS_PATH, TR_DEV_CUT_SUMS_SHA256, TR_DEV_CUT_PATH, TR_DEV_CUT_SHA256):
        raise Blocked(
            "REFUSING: TR pins PENDING (TR_DEV_CUT_SUMS_PATH / TR_DEV_CUT_SUMS_SHA256 / TR_DEV_CUT_PATH / TR_DEV_CUT_SHA256)."
        )
    sums = Path(TR_DEV_CUT_SUMS_PATH)
    if not sums.is_file() or sha256_file(sums) != TR_DEV_CUT_SUMS_SHA256:
        raise Blocked(f"REFUSING: accepted TR cut SUMS absent or sha != TR_DEV_CUT_SUMS_SHA256 at {sums}.")
    mine = [l for l in sums.read_text().splitlines() if l.endswith("  " + TR_DEV_CUT_PATH)]
    if mine != [f"{TR_DEV_CUT_SHA256}  {TR_DEV_CUT_PATH}"]:
        raise Blocked("REFUSING: the cut's line in its accepted SHA256SUMS != TR_DEV_CUT_SHA256 + TR_DEV_CUT_PATH.")


def verify_b1c_accepted() -> None:
    """H1/H2 refuse until B1c is accepted: the accepted B1c SUMS must exist and
    match its pin. Hash only; nothing in it is parsed."""
    if PENDING in (B1C_ACCEPTED_SUMS_PATH, B1C_ACCEPTED_SUMS_SHA256):
        raise Blocked("REFUSING: B1c not accepted (B1C_ACCEPTED_SUMS_PATH / B1C_ACCEPTED_SUMS_SHA256 PENDING).")
    p = Path(B1C_ACCEPTED_SUMS_PATH)
    if not p.is_file() or sha256_file(p) != B1C_ACCEPTED_SUMS_SHA256:
        raise Blocked(f"REFUSING: accepted B1c SUMS absent or sha != B1C_ACCEPTED_SUMS_SHA256 at {p}.")


class FinalListMismatch(Blocked):
    """FINAL_LIST absent, sha != pin, or any header/row violation -> exit code
    RC_FINAL_LIST_MISMATCH (18), silent."""

    def __init__(self, msg: str):
        super().__init__(RC_FINAL_LIST_MISMATCH)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


def verify_final_list_sha() -> None:
    """FINAL_LIST sha pre-check before any loader; hash only, nothing parsed.
    PENDING -> Blocked (rc 1); absent / unreadable / sha != pin -> FinalListMismatch (rc 18)."""
    if FINAL_LIST_SHA256 == PENDING:
        raise Blocked("REFUSING: FINAL_LIST_SHA256 PENDING.")
    p = Path(FINAL_LIST_PATH)
    try:
        ok = p.is_file() and sha256_file(p) == FINAL_LIST_SHA256
    except OSError:
        ok = False
    if not ok:
        raise FinalListMismatch(
            f"REFUSING (rc {RC_FINAL_LIST_MISMATCH}): FINAL_LIST absent or sha != FINAL_LIST_SHA256 at {p} (pre-check)."
        )


def load_final_list() -> dict[str, Any]:
    """Identity-map FINAL_LIST, re-checked at use: the bytes read are
    the bytes hashed. The ONLY source of identity exclusions and their reasons. PENDING -> Blocked (rc 1); absent,
    sha mismatch, header bytes != FINAL_LIST_HEADER (a CR or any other byte), a non-UTF-8 body, a row without exactly 4 fields, a decision outside
    FINAL_LIST_DECISIONS, empty reasons on EXCLUDED, or a duplicate symbol -> FinalListMismatch (rc 18).
    issuer_name is not used."""
    if FINAL_LIST_SHA256 == PENDING:
        raise Blocked("REFUSING: FINAL_LIST_SHA256 PENDING.")
    p = Path(FINAL_LIST_PATH)
    try:
        raw = p.read_bytes() if p.is_file() else None
    except OSError:
        raw = None
    if raw is None or hashlib.sha256(raw).hexdigest() != FINAL_LIST_SHA256:
        raise FinalListMismatch(
            f"REFUSING (rc {RC_FINAL_LIST_MISMATCH}): FINAL_LIST absent or sha != FINAL_LIST_SHA256 at {p}."
        )
    if not raw.startswith(FINAL_LIST_HEADER):
        raise FinalListMismatch(
            f"REFUSING (rc {RC_FINAL_LIST_MISMATCH}): FINAL_LIST header bytes != {FINAL_LIST_HEADER!r}."
        )
    try:
        body = raw[len(FINAL_LIST_HEADER) :].decode("utf-8")
    except UnicodeDecodeError:
        raise FinalListMismatch(f"REFUSING (rc {RC_FINAL_LIST_MISMATCH}): FINAL_LIST body is not UTF-8.")
    rows = [line.split("\t") for line in body.split("\n") if line.strip()]
    excluded, kept = {}, set()
    for r in rows:
        role = FINAL_LIST_DECISIONS.get(r[1]) if len(r) == len(FINAL_LIST_COLUMNS) else None
        if role is None or r[0] in excluded or r[0] in kept or (role == "excluded" and not r[2].strip()):
            raise FinalListMismatch(f"REFUSING (rc {RC_FINAL_LIST_MISMATCH}): malformed FINAL_LIST row {r!r}.")
        if role == "excluded":
            excluded[r[0]] = r[2]
        else:
            kept.add(r[0])
    return {"sha256": FINAL_LIST_SHA256, "excluded": excluded, "kept": kept}


class DeskClientInterface:
    """DECLARED interface the desk client must provide. Not implemented here.

    load_av_raw_with_factor(start: date, end: date, *, seal_sha: str, ledger_sha: str,
                            factor_sha: str) -> pd.DataFrame
        One row per (symbol, session_date) with session_date <= end applied AT READ TIME.
        Columns: symbol, session_date, close_raw (AV raw close), volume_raw,
        desk_factor (cumulative PIT forward-anchored factor: a row dated t carries only
        events with ex-date <= t), ffilled (bool; True if the row is forward-filled).
    bar_file_sha256() -> str          sha256 of the AV raw bar file served (tau source pin)
    xnys_sessions(start, end) -> pd.DatetimeIndex
    accepted_acquirer_closes(acquirer_id: str, start: date, end: date) -> pd.Series
        accepted acquirer closes indexed by session (for H1 short V_max only).
    """

    REQUIRED = ("load_av_raw_with_factor", "bar_file_sha256", "xnys_sessions", "accepted_acquirer_closes")


def load_desk_client(path: str | None = None, expected_sha: str | None = None) -> ModuleType:
    """Import the accepted desk client by exact path, after its sha256 check."""
    path = DESK_CLIENT_PATH if path is None else path
    expected_sha = DESK_CLIENT_SHA256 if expected_sha is None else expected_sha
    if PENDING in (path, expected_sha):
        raise Blocked("REFUSING: desk client path/sha PENDING.")
    if sha256_file(Path(path)) != expected_sha:
        raise Blocked(f"REFUSING: desk client sha mismatch at {path}.")
    import importlib.util

    spec = cast(Any, importlib.util.spec_from_file_location("desk_data_client", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    missing = [f for f in DeskClientInterface.REQUIRED if not hasattr(mod, f)]
    if missing:
        raise Blocked(f"REFUSING: desk client lacks declared functions {missing}.")
    return mod


class DeskClientUniverseInterface:
    """DECLARED extra client methods. Not implemented here.

    pit_membership_sha256() -> str
    pit_membership() -> pd.DataFrame  columns: symbol, start_date_filled, end_date (NaT = open)
        PIT S&P 500 intervals incl. delisted/former members (effective at open of start;
        end exclusive, same semantics as the release sp500_membership).
    listing_status_sha256() -> str
    listing_status() -> pd.DataFrame  AV LISTING_STATUS rows (active + delisted):
        symbol, name, exchange, assetType, ipoDate, delistingDate (null = still listed), status
    """

    REQUIRED = ("pit_membership_sha256", "pit_membership", "listing_status_sha256", "listing_status")


def load_pinned_json(path: str | Path, expected_sha: str) -> dict[str, Any]:
    """Refuse unless the input file exists and matches its pin."""
    if not Path(path).is_file():
        raise Blocked(f"REFUSING: pinned input absent: {path}")
    actual = sha256_file(Path(path))
    if actual != expected_sha:
        raise Blocked(f"REFUSING: sha256({path}) = {actual} != pin {expected_sha}")
    with open(path) as f:
        return cast(dict[str, Any], json.load(f))


def _subtract(iv: tuple[Any, Any], cuts: list[tuple[Any, Any]]) -> list[tuple[Any, Any]]:
    """[s, e) minus a list of [cs, ce) intervals (Timestamps; e may be NaT = open)."""
    out = [iv]
    for cs, ce in cuts:
        nxt = []
        for s, e in out:
            e_ = e if pd.notna(e) else pd.Timestamp.max
            ce_ = ce if pd.notna(ce) else pd.Timestamp.max
            if ce_ <= s or cs >= e_:
                nxt.append((s, e))
                continue
            if cs > s:
                nxt.append((s, cs))
            if ce_ < e_:
                nxt.append((ce, e))
        out = nxt
    return out


def load_universe_v13a(
    client: Any,
    subind: pd.Series,
    sector: pd.Series,
    *,
    r18_path: str | None = None,
    r18_sha: str | None = None,
    m14_path: str | None = None,
    m14_sha: str | None = None,
    fill_input: str | None = None,
    lineage_excl: set[str] | None = None,
    dev_universe: pd.DataFrame | None = None,
    final_list: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict[str, Any]]:
    """PIT membership via client, clipped to AV listing windows, minus R18 original
    member periods, minus M14, minus ETFs. Returns (mem, subind, sector, receipt)."""
    if fill_input is not None or FILL_INPUT_PATH is not None:
        raise Blocked("REFUSING: fills are a future hook; not implemented.")
    missing = [f for f in DeskClientUniverseInterface.REQUIRED if not hasattr(client, f)]
    if missing:
        raise Blocked(f"REFUSING: desk client lacks declared universe methods {missing}.")
    if client.pit_membership_sha256() != PIN_PIT_MEMBERSHIP_SHA256:
        raise Blocked("REFUSING: PIT membership sha != PIN_PIT_MEMBERSHIP_SHA256.")
    if client.listing_status_sha256() != PIN_LISTING_STATUS_SHA256:
        raise Blocked("REFUSING: listing status sha != PIN_LISTING_STATUS_SHA256.")
    r18 = load_pinned_json(r18_path or R18_INPUT_PATH, r18_sha or R18_INPUT_SHA256)
    m14 = load_pinned_json(m14_path or M14_INPUT_PATH, m14_sha or M14_INPUT_SHA256)
    r18_cuts = {
        t["ticker"]: [(pd.Timestamp(a), pd.Timestamp(b) if b else pd.NaT) for a, b in t["original_member_periods"]]
        for t in r18["tickers"]
    }
    m14_set = {t["ticker"] for t in m14["tickers"]}
    ls = client.listing_status().copy()
    # listing overlap (symbol in both AV sources) fails closed unless excluded or treated.
    lineage_excl = set(lineage_excl or ())
    pm = client.pit_membership()
    both = set(ls.loc[ls["listing_source"] == "active", "symbol"]) & set(
        ls.loc[ls["listing_source"] == "delisted", "symbol"]
    )
    in_uni = both & set(pm["symbol"]) & (set(dev_universe) if dev_universe is not None else set(pm["symbol"]))
    fl_excl, fl_kept = dict((final_list or {}).get("excluded", {})), set((final_list or {}).get("kept", ()))
    in_uni -= set(r18_cuts) | m14_set | lineage_excl | ETFS | set(fl_excl)
    uncovered = sorted(in_uni - set(LISTING_OVERLAP_TREATMENT) - fl_kept)
    if uncovered:
        raise Blocked(
            f"REFUSING: {len(uncovered)} in-universe symbols in both AV listing sources with no "
            f"pinned treatment ({LISTING_OVERLAP_IN_UNIVERSE_SHA256[:8]}): {uncovered}"
        )
    ls["ipo"] = pd.to_datetime(ls["ipoDate"].replace({"null": None}), errors="coerce")
    ls["dl"] = pd.to_datetime(ls["delistingDate"].replace({"null": None}), errors="coerce")
    windows = {
        s: [(r.ipo, (r.dl + pd.Timedelta(days=1)) if pd.notna(r.dl) else pd.NaT) for r in g.itertuples()]
        for s, g in ls.groupby("symbol")
    }
    rows: list[dict[str, Any]] = []
    rec: dict[str, Any] = {
        "r18_removed": [],
        "m14_gap": [],
        "no_listing_record": [],
        "etf_rows_dropped": [],
        "listing_clipped": [],
        "lineage_excl_dropped": [],
        "final_list_sha256": (final_list or {}).get("sha256"),
        "final_list_excluded": [],
        "final_list_kept": sorted(fl_kept),
        "final_list_kept_covered_overlap": sorted(in_uni & fl_kept),
        "after_boundary_member_rows": sorted(pm.loc[pm["after_boundary"].astype(bool), "symbol"])
        if "after_boundary" in pm.columns
        else [],
    }
    for r in pm.itertuples():
        s = r.symbol
        if s in lineage_excl:
            rec["lineage_excl_dropped"].append(s)
            continue
        if s in fl_excl:  # reason read from FINAL_LIST only
            rec["final_list_excluded"].append({"symbol": s, "reason": fl_excl[s]})
            continue
        iv = (pd.Timestamp(r.start_date_filled), pd.Timestamp(r.end_date) if pd.notna(r.end_date) else pd.NaT)
        if s in ETFS:
            rec["etf_rows_dropped"].append(s)
            continue
        if s in m14_set:
            rec["m14_gap"].append(
                {"symbol": s, "start": str(iv[0].date()), "end": None if pd.isna(iv[1]) else str(iv[1].date())}
            )
            continue
        parts = [iv]
        if s in r18_cuts:
            parts = _subtract(iv, r18_cuts[s])
            if parts != [iv]:
                rec["r18_removed"].append(s)
        w = windows.get(s)
        if not w:
            if parts:
                rec["no_listing_record"].append(s)
            continue
        clipped = []
        for ps, pe in parts:
            for ws, we in w:
                s0 = max(ps, ws) if pd.notna(ws) else ps
                e_candidates = [x for x in (pe, we) if pd.notna(x)]
                e0 = min(e_candidates) if e_candidates else pd.NaT
                if pd.isna(e0) or s0 < e0:
                    clipped.append((s0, e0))
        if clipped != parts:
            rec["listing_clipped"].append(s)
        for cs, ce in clipped:
            rows.append({"symbol": s, "start_date_filled": cs, "end_date": ce if pd.notna(ce) else None})
    mem = pd.DataFrame(rows, columns=["symbol", "start_date_filled", "end_date"])
    rec.update(
        {
            "r18_input_sha256": r18_sha or R18_INPUT_SHA256,
            "m14_input_sha256": m14_sha or M14_INPUT_SHA256,
            "n_member_rows": int(len(mem)),
        }
    )
    return mem, subind, sector, rec


def has_print(px: float) -> bool:
    """The one last-print definition: a price is a print when it is present (not NaN) and > 0."""
    return bool(np.isfinite(px) and px > 0)


def printed_mask(PX: pd.DataFrame) -> pd.DataFrame:
    """Frame form of has_print: notna and price > 0."""
    return PX.notna() & PX.gt(0)


def last_print_index(PX: pd.DataFrame, s: str) -> int:
    """Row of the last print of s (has_print), or -1 when it never printed."""
    if s not in PX.columns:
        return -1
    idx = np.flatnonzero(printed_mask(PX[[s]])[s].to_numpy(dtype=bool))
    return int(idx[-1]) if len(idx) else -1


def h2_delisting_receipts(bars: dict[str, Any], positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pre-registered base for H2 on raw prices: a position whose name
    stops printing before its planned exit is closed at its last close (R is NaN after the
    last bar, so apply_costs_and_returns adds 0; no exit cost at a NaN price; the ETF hedge
    leg and short borrow run to the planned exit). Reporting only: this
    function changes no weight and no return. Supplied delisting returns: none (raw prices)."""
    out = []
    PX = bars["PX"]
    dates = PX.index
    for p in positions:
        s = p["sym"]
        if s not in PX.columns:
            continue
        last_i = last_print_index(PX, s)
        if last_i < 0:
            continue
        if p["entry_i"] <= last_i < p["exit_i"] - 1:
            out.append(
                {
                    "symbol": s,
                    "side": "long" if p["w_sym"] > 0 else "short",
                    "entry_session": str(dates[p["entry_i"]].date()),
                    "last_close_session": str(dates[last_i].date()),
                    "last_close": float(PX[s].iloc[last_i]),
                    "planned_exit_session": str(dates[min(p["exit_i"], len(dates) - 1)].date()),
                    "treatment": "base: closed at last close (null delisting return)",
                    "hedge_leg": p["etf"],
                    "hedge_held_to_planned_exit": True,
                }
            )
    return out


# Declared method -> real desk client function. None = MISSING.
# Phase A only; Phase B and acquirer closes are MISSING.
CLIENT_MAPPING = {
    "load_av_raw_with_factor": "load_av_raw_with_factor",  # Phase B: not in module -> MISSING
    "bar_file_sha256": "bar_file_sha256",  # Phase B: not in module -> MISSING
    "xnys_sessions": "xnys_sessions",
    "accepted_acquirer_closes": None,  # not in the client -> MISSING
    "pit_membership_sha256": "pit_membership_sha256",
    "pit_membership": "pit_membership",
    "listing_status_sha256": "listing_status_sha256",
    "listing_status": "listing_status",
}


def client_static_check(path: str | None = None, expected_sha: str | None = None) -> dict[str, Any]:
    """Static (AST) check of the pinned client: no import, no execution. Refuses while any
    declared method is MISSING (unmapped or absent from the client's top-level functions)."""
    path = DESK_CLIENT_PATH if path is None else path
    expected_sha = DESK_CLIENT_SHA256 if expected_sha is None else expected_sha
    if path == PENDING or sha256_file(Path(path)) != expected_sha:
        raise Blocked(f"REFUSING: desk client absent or sha mismatch at {path}.")
    import ast

    with open(path) as f:
        tree = ast.parse(f.read())
    defs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    status = {m: (real if real and real in defs else "MISSING") for m, real in CLIENT_MAPPING.items()}
    missing = sorted(m for m, v in status.items() if v == "MISSING")
    if missing:
        raise Blocked(f"REFUSING: desk client lacks declared methods (MISSING): {missing}")
    return status


def ddc_accepted_acquirer_closes(ddc: Any, acquirer_id: str, start: date, end: date) -> pd.Series:
    """Adapter: accepted_acquirer_closes -> ddc.get_daily_bars(..., adjustment='raw',
    allow_api=False). Local store only (no API); returns close indexed by session Timestamp."""
    df = ddc.get_daily_bars([acquirer_id], start, end, adjustment="raw", allow_api=False)
    if df is None or len(df) == 0:
        return pd.Series(dtype=float)
    df = df[df["symbol"] == acquirer_id]
    return pd.Series(
        df["close"].astype(float).values, index=pd.to_datetime(df["session_date"]), name=acquirer_id
    ).sort_index()


def _to_date(x: Any) -> date:
    """Adapter: pandas Timestamp / datetime / date -> datetime.date (client refuses datetime)."""
    if isinstance(x, pd.Timestamp):
        if x.tzinfo is not None:
            raise Blocked("REFUSING: tz-aware Timestamp passed to desk client adapter.")
        return x.date()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    raise Blocked(f"REFUSING: desk client adapter needs a date, got {type(x).__name__}.")


class DeskClientH1H2Adapter:
    """Adapter over the desk client (Phase A). Converts arguments to datetime.date, calls
    .to_pandas() on returned pa.Tables, keeps after_boundary for audit, converts xnys_sessions to a
    DatetimeIndex, and turns client "REFUSE ..." RuntimeErrors into Blocked.
    Phase B (load_av_raw_with_factor, bar_file_sha256) and accepted_acquirer_closes are not
    provided by the module; calling them refuses."""

    def __init__(self, mod: ModuleType) -> None:
        self._m = mod

    def _call(self, name: str, *a: Any) -> Any:
        f = getattr(self._m, name, None)
        if f is None:
            raise Blocked(f"REFUSING: desk client lacks {name} (MISSING).")
        try:
            return f(*a)
        except RuntimeError as e:
            if str(e).startswith("REFUSE "):
                raise Blocked(f"REFUSING: desk client {name}: {e}") from None
            raise

    @staticmethod
    def _df(t: Any) -> pd.DataFrame:
        if not hasattr(t, "to_pandas"):
            raise Blocked("REFUSING: desk client returned a non-Table object.")
        return cast(pd.DataFrame, t.to_pandas())

    def pit_membership_sha256(self) -> str:
        return cast(str, self._call("pit_membership_sha256"))

    def listing_status_sha256(self) -> str:
        return cast(str, self._call("listing_status_sha256"))

    def pit_membership(self) -> pd.DataFrame:
        return self._df(self._call("pit_membership"))

    def listing_status(self) -> pd.DataFrame:
        return self._df(self._call("listing_status"))

    def xnys_sessions(self, start: date | pd.Timestamp, end: date | pd.Timestamp) -> pd.DatetimeIndex:
        df = self._df(self._call("xnys_sessions", _to_date(start), _to_date(end)))
        return pd.DatetimeIndex(pd.to_datetime(df["session_date"]))

    def accepted_acquirer_closes(self, acquirer_id: str, start: date | pd.Timestamp, end: date | pd.Timestamp) -> Any:
        return self._call("accepted_acquirer_closes", acquirer_id, _to_date(start), _to_date(end))

    def bar_file_sha256(self) -> str:
        return cast(str, self._call("bar_file_sha256"))

    def load_av_raw_with_factor(self, start: date | pd.Timestamp, end: date | pd.Timestamp, **kw: Any) -> Any:
        return self._call("load_av_raw_with_factor", _to_date(start), _to_date(end))


def load_bars(filter_end: date, load_start: date = LOAD0, *, client: Any = None) -> dict[str, pd.DataFrame]:
    """AV raw close x desk factor via the desk client, read-time end filter.

    No hand-rolled reads of AV CSVs. No rows after filter_end.
    """
    assert_quarantine_untouched()
    if client is None:
        pins = require_data_pins()
        client = load_desk_client()
    else:
        pins = {
            "PIN_RECONCILIATION_SEAL_SHA256": PIN_RECONCILIATION_SEAL_SHA256,
            "PIN_CA_LEDGER_SHA256": PIN_CA_LEDGER_SHA256,
            "PIN_FACTOR_TABLE_SHA256": PIN_FACTOR_TABLE_SHA256,
            "PIN_AV_RAW_BARS_SHA256": PIN_AV_RAW_BARS_SHA256,
        }
    if client.bar_file_sha256() != pins["PIN_AV_RAW_BARS_SHA256"]:
        raise Blocked("REFUSING: AV raw bar file sha != PIN_AV_RAW_BARS_SHA256.")
    tr = client.load_av_raw_with_factor(
        load_start,
        filter_end,
        seal_sha=pins["PIN_RECONCILIATION_SEAL_SHA256"],
        ledger_sha=pins["PIN_CA_LEDGER_SHA256"],
        factor_sha=pins["PIN_FACTOR_TABLE_SHA256"],
    )
    tr = tr.copy()
    tr["session_date"] = pd.to_datetime(tr["session_date"])
    if (tr.session_date > pd.Timestamp(filter_end)).any():
        raise RuntimeError("holdout/leakage guard: client returned rows past filter_end")
    tr = tr.sort_values(["symbol", "session_date"])
    tr["px_adj"] = tr["close_raw"] * tr["desk_factor"]
    tr["ret_adj"] = tr.groupby("symbol")["px_adj"].pct_change(fill_method=None)
    tr.loc[tr["ffilled"].astype(bool), "ret_adj"] = np.nan
    tr = tr[(tr.session_date >= pd.Timestamp(load_start)) & (tr.session_date <= pd.Timestamp(filter_end))]
    # Belt-and-suspenders: drop anything past filter_end
    if (tr.session_date > pd.Timestamp(filter_end)).any():
        raise RuntimeError("holdout/leakage guard: rows past filter_end survived filters")
    return {
        "R": tr.pivot(index="session_date", columns="symbol", values="ret_adj"),
        "TRI": tr.pivot(index="session_date", columns="symbol", values="px_adj"),
        "PX": tr.pivot(index="session_date", columns="symbol", values="close_raw"),
        "VOL": tr.pivot(index="session_date", columns="symbol", values="volume_raw"),
        "FFILL": tr.pivot(index="session_date", columns="symbol", values="ffilled"),
    }


def _parquet_after_site() -> Any:
    """The ONE pyarrow.parquet import, local, only after verify_pyarrow_site
    has loaded pyarrow from the declared site; then pyarrow.parquet must resolve under that site."""
    _pa = sys.modules.get("pyarrow")
    if _pa is None or not os.path.realpath(cast(str, _pa.__file__)).startswith(
        os.path.realpath(PYARROW_SITE_APPROVED) + os.sep
    ):
        raise Blocked("REFUSING: parquet read before verify_pyarrow_site loaded the declared site.")
    import pyarrow.parquet

    if not os.path.realpath(pyarrow.parquet.__file__).startswith(os.path.realpath(PYARROW_SITE_APPROVED) + os.sep):
        raise Blocked(f"REFUSING: pyarrow.parquet resolved outside the declared site: {pyarrow.parquet.__file__}")
    return pyarrow.parquet


def load_bars_tr(filter_end: date, load_start: date = LOAD0) -> dict[str, pd.DataFrame]:
    """PRIMARY return source: the pre-registered total return, via the sealed DEV-only cut.

    Opens the DEV cut, never the parent file, with pq.read_table(...).to_pandas().
    All guards run before the cut is opened as parquet.
    """
    if filter_end > EMBARGO1:
        raise Blocked("REFUSING: TR source is the DEV cut only; no holdout TR source pinned.")
    verify_tr_cut_sums()
    if PENDING in (TR_DEV_CUT_PATH, TR_DEV_CUT_SHA256, TR_PARENT_SHA256):
        raise Blocked("REFUSING: TR pins PENDING (TR_DEV_CUT_PATH / TR_DEV_CUT_SHA256 / TR_PARENT_SHA256).")
    if f"`{TR_PARENT_SHA256}`" not in PREREG_PATH.read_text().splitlines()[PREREG_TR_PIN_LINE - 1]:
        raise Blocked("REFUSING: TR_PARENT_SHA256 is not the pre-registered total-return pin.")
    cut = Path(TR_DEV_CUT_PATH)
    if not cut.is_file() or sha256_file(cut) != TR_DEV_CUT_SHA256:
        raise Blocked(f"REFUSING: TR DEV cut absent or sha != TR_DEV_CUT_SHA256 at {cut}.")
    pq = _parquet_after_site()
    if len(pq.read_table(cut, columns=["session_date"], filters=[("session_date", ">", EMBARGO1)]).to_pandas()):
        raise Blocked("REFUSING: TR DEV cut holds rows after 2022-03-29 (not a DEV-only cut).")
    assert_quarantine_untouched()
    tr = pq.read_table(
        cut,
        columns=["symbol", "session_date", "close_raw", "volume_raw", "ret_total_best", "tr_index_best"],
        filters=[("session_date", "<=", filter_end)],
    ).to_pandas()
    tr["session_date"] = pd.to_datetime(tr["session_date"])
    tr = tr[(tr.session_date >= pd.Timestamp(load_start)) & (tr.session_date <= pd.Timestamp(filter_end))]
    # Belt-and-suspenders: drop anything past filter_end
    if (tr.session_date > pd.Timestamp(filter_end)).any():
        raise RuntimeError("holdout/leakage guard: rows past filter_end survived filters")
    return {
        "R": tr.pivot(index="session_date", columns="symbol", values="ret_total_best"),
        "TRI": tr.pivot(index="session_date", columns="symbol", values="tr_index_best"),
        "PX": tr.pivot(index="session_date", columns="symbol", values="close_raw"),
        "VOL": tr.pivot(index="session_date", columns="symbol", values="volume_raw"),
    }


def load_earnings(filter_end: date) -> pd.DataFrame:
    """Earnings with read-time announce_date_et filter."""
    if filter_end > EMBARGO1:
        raise Blocked("REFUSING: earnings source is the DEV cut only; no holdout source pinned.")
    if sha256_file(EARNINGS) != EARNINGS_SHA256:
        raise Blocked("REFUSING: earnings DEV cut sha != pin.")
    return cast(
        pd.DataFrame,
        _parquet_after_site()
        .read_table(
            EARNINGS,
            filters=[("announce_date_et", "<=", filter_end)],
        )
        .to_pandas(),
    )


def load_universe() -> tuple[None, pd.Series, pd.Series]:
    # no direct membership read (membership = client).
    if sha256_file(UNIVERSE_CUT) != UNIVERSE_CUT_SHA256:
        raise Blocked("REFUSING: universe DEV cut sha != pin.")
    uni = cast(pd.DataFrame, _parquet_after_site().read_table(UNIVERSE_CUT).to_pandas())
    if not {"symbol", "gics_sub_industry", "gics_sector"} <= set(uni.columns):
        raise Blocked("REFUSING: universe DEV cut lacks symbol/gics_sub_industry/gics_sector.")
    mem = None
    subind = uni.set_index("symbol").gics_sub_industry.dropna()
    sector = uni.set_index("symbol").gics_sector.dropna()
    return mem, subind, sector


def _verify_sums_dir(d: str, sums_sha: str) -> dict[str, str]:
    """Binding. sha256(d/SHA256SUMS) must equal the pin, then every listed file must match."""
    sums = Path(d) / "SHA256SUMS"
    if not sums.is_file() or sha256_file(sums) != sums_sha:
        raise Blocked(f"REFUSING: {sums} absent or sha != pin {sums_sha}.")
    listed = {}
    for line in sums.read_text().splitlines():
        h, name = line.split("  ", 1)
        if sha256_file(Path(d) / name) != h:
            raise Blocked(f"REFUSING: {d}/{name} sha != its SHA256SUMS entry.")
        listed[name] = h
    return listed


def bind_dev_inputs(path: str | Path) -> dict[str, Any]:
    """--dev-inputs. Accepts ONLY DEV_INPUTS_DIR with its pinned SHA256SUMS; binds ADDENDUM1_DIR
    the same way; returns the LINEAGE_EXCL_COUNT lineage exclusions (LINEAGE_EXCL_FILE, as is) and the
    DEV universe symbol set (union of DEV_UNIVERSE_FILES). Reads only these metadata files; no price data."""
    if not path or os.path.normpath(str(path)) != DEV_INPUTS_DIR:
        raise Blocked(f"REFUSING: --dev-inputs must be exactly {DEV_INPUTS_DIR}/ (got {path!r}).")
    import csv

    d_list = _verify_sums_dir(DEV_INPUTS_DIR, DEV_INPUTS_SUMS_SHA256)
    a_list = _verify_sums_dir(ADDENDUM1_DIR, ADDENDUM1_SUMS_SHA256)
    if a_list.get(LINEAGE_EXCL_FILE) != LINEAGE_EXCL_SHA256:
        raise Blocked("REFUSING: lineage exclusion file not pinned in addendum1 SUMS.")
    with open(Path(ADDENDUM1_DIR) / LINEAGE_EXCL_FILE, newline="") as f:
        lineage = {r["symbol"] for r in csv.DictReader(f, delimiter="\t")}
    if len(lineage) != LINEAGE_EXCL_COUNT:
        raise Blocked(f"REFUSING: expected {LINEAGE_EXCL_COUNT} lineage exclusions, got {len(lineage)}.")
    if not DEV_UNIVERSE_FILES:
        raise Blocked("REFUSING: DEV_UNIVERSE_FILES PENDING.")
    uni = set()
    for name in DEV_UNIVERSE_FILES:
        with open(Path(DEV_INPUTS_DIR) / name, newline="") as f:
            uni |= {r["symbol"] for r in csv.DictReader(f)}
    return {
        "lineage_excl": lineage,
        "dev_universe": uni,
        "receipt": {
            "dev_inputs_sums_sha256": DEV_INPUTS_SUMS_SHA256,
            "dev_inputs_files": len(d_list),
            "addendum1_sums_sha256": ADDENDUM1_SUMS_SHA256,
            "lineage_excl_n": len(lineage),
            "dev_universe_n": len(uni),
        },
    }


def verify_dev_cuts(
    cuts_dir: str | None = None, sums_path: str | None = None, sums_sha: str | None = None
) -> dict[str, Any]:
    """Binding. Hash only (never parse): OUT_SHA256SUMS must match its pin, every DEV_CUT_PINS
    entry must be listed there with the same sha, and each cut's raw bytes must match."""
    cuts_dir = DEV_CUTS_DIR if cuts_dir is None else cuts_dir
    sums_path = DEV_CUTS_SUMS_PATH if sums_path is None else sums_path
    sums_sha = DEV_CUTS_SUMS_SHA256 if sums_sha is None else sums_sha
    if not DEV_CUT_PINS:
        raise Blocked("REFUSING: DEV_CUT_PINS PENDING (no DEV cut pinned).")
    if not Path(sums_path).is_file() or sha256_file(Path(sums_path)) != sums_sha:
        raise Blocked(f"REFUSING: {sums_path} absent or sha != pin {sums_sha}.")
    listed = {}
    for line in Path(sums_path).read_text().splitlines():
        h, p = line.split("  ", 1)
        listed[p] = h
    for name, h in DEV_CUT_PINS.items():
        p = str(Path(cuts_dir) / name)
        if listed.get(p) != h:
            raise Blocked(f"REFUSING: {name} not listed in DEV cut SUMS with its pinned sha.")
        if sha256_file(Path(p)) != h:
            raise Blocked(f"REFUSING: sha256({p}) != pin.")
    return {"dev_cuts_sums_sha256": sums_sha, "n_cuts_verified": len(DEV_CUT_PINS)}


# ---- Shared ELIG / H7 helpers (card exact rules) ----


def build_elig(bars: dict[str, Any], mem: pd.DataFrame) -> pd.DataFrame:
    R, PX, VOL = bars["R"], bars["PX"], bars["VOL"]
    dates = R.index
    DV = PX * VOL
    ADV20 = DV.rolling(20, min_periods=10).mean()
    JUMP20 = (R.abs() > 0.40).rolling(20, min_periods=1).max().astype(bool)
    ZV = VOL == 0
    M = pd.DataFrame(False, index=dates, columns=R.columns)
    for _, r in mem.iterrows():
        if r.symbol not in M.columns:
            continue
        s = pd.Timestamp(r.start_date_filled)
        e = pd.Timestamp(r.end_date) if pd.notna(r.end_date) else dates[-1] + pd.Timedelta(days=1)
        M.loc[(dates >= s) & (dates < e), r.symbol] = True
    ELIG = M & (PX >= 5) & (ADV20 >= 2e7) & ~ZV & ~JUMP20 & R.notna()
    return cast(pd.DataFrame, ELIG & (R.rolling(252, min_periods=252).count() >= 252))


def earliest_possible_index(ev: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Map each earnings row to earliest-possible session index (pre-registered rule)."""
    ev = ev[ev.source != "nasdaq_scheduled"].copy()
    ev["d0"] = pd.to_datetime(ev.reaction_session.fillna(ev.first_tradable_session))
    _ann = pd.to_datetime(ev.announce_date_et)
    _unk = ev.timing_quality.astype(str).str.startswith("unknown")
    _fb = ev.source.astype(str).str.contains("fallback") | ev.timing_quality.astype(str).str.startswith("periodic")
    ev.loc[_unk, "d0"] = np.minimum(cast(np.ndarray, ev.loc[_unk, "d0"]), cast(np.ndarray, _ann[_unk]))
    ev["_ix"] = np.searchsorted(cast(np.ndarray, dates.values), cast(np.ndarray, ev.d0.values).astype("datetime64[ns]"))
    fb_ix = cast(np.ndarray, _fb.values)
    ev.loc[fb_ix, "_ix"] = (ev.loc[fb_ix, "_ix"] - 5).clip(lower=0)
    return ev


def make_evidx(ev: pd.DataFrame) -> dict[str, np.ndarray]:
    return {str(s): np.unique(cast(np.ndarray, g._ix.values)) for s, g in ev.groupby("symbol")}


def ev_in(evidx: dict[str, np.ndarray], s: str, a: int, b: int, margin: int = MARGIN) -> bool:
    x = evidx.get(s)
    if x is None:
        return False
    a, b = a - margin, b + margin
    k = np.searchsorted(x, a, side="right")
    return bool(k < len(x) and x[k] <= b)


def covered(evidx: dict[str, np.ndarray], s: str, i: int, lookback: int = 130) -> bool:
    x = evidx.get(s)
    if x is None:
        return False
    k = np.searchsorted(x, i, side="right")
    return bool(k > 0 and x[k - 1] >= i - lookback)


# ---- H1 primary (L=60, |z|>=1, 4 weeks, 2 leaders, min group 4, close_t1) ----


def signal_h1(
    bars: dict[str, Any],
    ELIG: pd.DataFrame,
    subind: pd.Series,
    evidx: dict[str, np.ndarray],
    *,
    L: int = 60,
    z_thr: float = 1.0,
    n_lead: int = 2,
    min_grp: int = 4,
    hold_weeks: int = 4,
    eval_start: date,
    eval_end: date,
    last_exit_i: int,
) -> tuple[pd.DataFrame, list[Any]]:
    """Build H1 target weights (sleeve fraction). A tranche formed on signal bar i (close t) is
    held from session i+1, the same entry as H2; with the caller's one-row lag it first earns
    i+1 -> i+2. Nothing is ever held on its own signal bar."""
    R = bars["R"]
    DV = bars["PX"] * bars["VOL"]
    MEDDV60 = DV.rolling(60, min_periods=40).median()
    dates = cast(pd.DatetimeIndex, R.index)
    wk = pd.DatetimeIndex(pd.Series(dates, index=dates).groupby(dates.to_period("W-FRI")).max().values)
    tranches: dict[Any, Any] = {}
    for jj, t in enumerate(wk):
        if t < pd.Timestamp(eval_start) - pd.Timedelta(days=40):
            continue
        if t > pd.Timestamp(eval_end):
            break
        i = cast(int, dates.get_loc(t))
        if i < 260:
            continue
        el = ELIG.loc[t]
        syms = [s for s in el.index[cast(np.ndarray, el.values)] if s in subind.index]
        g = pd.Series({s: subind[s] for s in syms})
        w: dict[str, float] = {}
        act = 0
        for _gname, members in g.groupby(g):
            ms = list(members.index)
            if len(ms) < min_grp:
                continue
            ms = sorted(ms, key=lambda s: -MEDDV60.at[t, s])
            Ld, F = ms[:n_lead], ms[n_lead:]
            win = R.iloc[i - 252 + 1 : i + 1]
            d = win[Ld].mean(axis=1) - win[F].mean(axis=1)
            G = d.iloc[-L:].sum()
            sd = d.iloc[:-L].std() * math.sqrt(L)
            if not (sd > 0):
                continue
            z = G / sd
            if abs(z) < z_thr:
                continue
            sgn = np.sign(z)
            ent = i + 1
            ex_i = cast(int, dates.get_loc(wk[jj + hold_weeks])) + 1 if jj + hold_weeks < len(wk) else len(dates) - 1
            if ex_i > last_exit_i:
                continue
            keep: Callable[[str], bool] = lambda s: covered(evidx, s, i) and not ev_in(evidx, s, ent, ex_i)
            F2 = [s for s in F if keep(s)]
            L2 = [s for s in Ld if keep(s)]
            if not F2 or not L2:
                continue
            F, Ld = F2, L2
            act += 1
            for s in F:
                w[s] = w.get(s, 0.0) + sgn * 0.5 / len(F)
            for s in Ld:
                w[s] = w.get(s, 0.0) - sgn * 0.5 / len(Ld)
        if act:
            w = {k: v / act for k, v in w.items()}
        tranches[t] = pd.Series(w, dtype=float)
    keys = list(tranches)
    rows = {}
    for j, t in enumerate(keys):
        book = (
            pd.concat([tranches[keys[m]] for m in range(max(0, j - hold_weeks + 1), j + 1)], axis=1)
            .fillna(0)
            .sum(axis=1)
            / hold_weeks
        )
        rows[t] = book
    Wk = pd.DataFrame(rows).T.fillna(0.0)
    W = Wk.reindex(dates).ffill().shift(1).fillna(0.0)  # held from i+1, never on the signal bar
    # Name cap (LIMITS H1): trim, do not reallocate
    W = W.clip(-NAME_CAP, NAME_CAP)
    return W, list(Wk.index)


# ---- H2 primary (H=40, |N|>=1.5, window 50, unit 0.5%, max 100, close_t1) ----


def _boundary_ambiguous(ts: Any) -> bool:
    """Exclude acceptance times within ±5 min of 09:30, 13:00, 16:00 ET."""
    if pd.isna(ts):
        return True
    t = pd.Timestamp(ts)
    # knowledge_time_utc → compare clock in ET
    if t.tzinfo is not None:
        t = t.tz_convert("America/New_York")
    minutes = t.hour * 60 + t.minute
    return any(abs(minutes - anchor) <= 5 for anchor in (9 * 60 + 30, 13 * 60, 16 * 60))


def signal_h2(
    bars: dict[str, Any],
    ELIG: pd.DataFrame,
    subind: pd.Series,
    sector: pd.Series,
    ev_all: pd.DataFrame,
    evidx: dict[str, np.ndarray],
    *,
    H: int = 40,
    thr: float = 1.5,
    unit: float = 0.005,
    gap_sessions: int = 50,
    NMAX: int = 100,
    eval_start: date,
    eval_end: date,
    last_exit_i: int,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Build H2 target weights including per-position hedge quantities (netted at execution)."""
    R = bars["R"]
    dates = R.index
    # Triggers: exact_acceptance_time only
    ev = ev_all[ev_all.timing_quality == "exact_acceptance_time"].copy()
    ev["d0"] = pd.to_datetime(ev.reaction_session.fillna(ev.first_tradable_session))
    if "knowledge_time_utc" in ev.columns:
        ev = ev[~ev.knowledge_time_utc.map(_boundary_ambiguous)]
    ev = ev[(ev.d0 >= pd.Timestamp(LOAD0)) & (ev.d0 <= pd.Timestamp(eval_end))]

    etf_of0 = {s: SECTOR_ETF.get(cast(str, sector.get(s))) for s in subind.index}

    def hedge_etf(s: Any, i: int) -> str:
        e = etf_of0.get(s)
        if e is None or e not in R.columns or R[e].iloc[max(0, i - 252) : i].notna().sum() < 252:
            return "SPY"
        return e

    # Positions: list of dicts for per-position hedge accounting
    positions: list[dict[str, Any]] = []  # {sym, etf, w_sym, w_etf, entry_i, exit_i, N}
    # Index already-reported earliest-possible sessions per symbol
    for d0_raw, grp in ev.groupby("d0"):
        d0 = cast(pd.Timestamp, d0_raw)
        if d0 < pd.Timestamp(eval_start) or d0 > pd.Timestamp(eval_end):
            continue
        i = cast(int, dates.get_loc(d0)) if d0 in dates else None
        if i is None or i < 252:
            continue
        # reporters by sub-industry
        reps = []
        for _, row in grp.iterrows():
            s = row.symbol
            if s not in ELIG.columns or i < 1 or not bool(ELIG.iloc[i - 1].get(s, False)):
                continue
            if s not in subind.index:
                continue
            reps.append(s)
        if not reps:
            continue
        by_g: dict[Any, list[Any]] = {}
        for s in reps:
            by_g.setdefault(subind[s], []).append(s)
        for gname, reporters in by_g.items():
            reactions = []
            for s in reporters:
                e = hedge_etf(s, i)
                win = R[[s, e]].iloc[i - 252 : i]
                if win.dropna().shape[0] < 200:
                    continue
                # β over 252 sessions before d0; residual on d0; σ last 60
                y = win[s].values
                x = win[e].values
                mask = np.isfinite(y) & np.isfinite(x)
                if mask.sum() < 200:
                    continue
                beta = np.polyfit(x[mask], y[mask], 1)[0]
                r0 = R.at[dates[i], s] - beta * R.at[dates[i], e]
                resid = y - beta * x
                sig = np.nanstd(resid[-60:])
                if not (sig > 0) or not np.isfinite(r0):
                    continue
                reactions.append((s, r0 / sig))
            if not reactions:
                continue
            N = float(np.mean([r for _, r in reactions]))
            if abs(N) < thr:
                continue
            # followers
            members = [
                s for s in subind.index[subind == gname] if s in ELIG.columns and bool(ELIG.iloc[i - 1].get(s, False))
            ]
            cands = []
            for s in members:
                if s in reporters:
                    continue
                # already reported in [d0-50, d0-2]
                x = evidx.get(s)
                if x is None:
                    continue
                lo, hi = i - gap_sessions, i - 2
                if not np.any((x >= lo) & (x <= hi)):
                    continue
                ent = i + 1
                ex_i = ent + H
                if ex_i > last_exit_i:
                    continue
                # no own row in [d0-1, exit+2]
                if ev_in(evidx, s, i - 1, ex_i, margin=0):
                    # stricter: any own row in [d0-1, exit+2] — use raw window with +2 already in ex
                    xx = evidx.get(s)
                    if xx is not None and np.any((xx >= i - 1) & (xx <= ex_i + 2)):
                        continue
                # follower β excludes d0
                e = hedge_etf(s, i)
                win = R[[s, e]].iloc[i - 252 : i]  # d0-252 .. d0-1
                y = win[s].values
                x_ = win[e].values
                mask = np.isfinite(y) & np.isfinite(x_)
                if mask.sum() < 200:
                    continue
                beta_f = float(np.polyfit(x_[mask], y[mask], 1)[0])
                cands.append((abs(N), s, e, beta_f))
            cands.sort(key=lambda t: (-t[0], t[1]))
            live = {p["sym"] for p in positions if p["entry_i"] <= i + 1 < p["exit_i"]}
            n_live = sum(1 for p in positions if p["entry_i"] <= i + 1 < p["exit_i"])
            for _, s, e, beta_f in cands:
                if s in live:
                    continue
                if n_live >= NMAX:
                    break
                sgn = np.sign(N)
                positions.append(
                    {
                        "sym": s,
                        "etf": e,
                        "w_sym": sgn * unit,
                        "w_etf": -sgn * beta_f * unit,
                        "entry_i": i + 1,
                        "exit_i": i + 1 + H,
                        "N": N,
                    }
                )
                live.add(s)
                n_live += 1

    # Build daily weight matrix with per-position hedge accounting; net at symbol level for orders
    W = pd.DataFrame(
        0.0, index=dates, columns=sorted(set([p["sym"] for p in positions] + [p["etf"] for p in positions]))
    )
    for p in positions:
        sl = slice(p["entry_i"], p["exit_i"])
        if p["sym"] in W.columns:
            W.iloc[sl, cast(int, W.columns.get_loc(p["sym"]))] += p["w_sym"]
        if p["etf"] in W.columns:
            W.iloc[sl, cast(int, W.columns.get_loc(p["etf"]))] += p["w_etf"]
    # Aggregate ETF notional cap 9.5% of equity; skip already applied at entry. Trim names.
    W = W.clip(-NAME_CAP, NAME_CAP)
    return W, positions


# ---- Returns path (gated; not invoked without acceptance hash) ----


def _fills(bars: dict[str, Any], W: pd.DataFrame) -> Iterator[tuple[Any, Any, pd.Series, list[Any], bool]]:
    """Walk the book session by session from the position actually held.

    W row k is the weight filled at close k (signals put it at their fill session, never the
    signal bar); it earns the next row's return, close k -> k+1. A fill at close k is priced,
    print-checked and ADV-capped on row k itself, never on the row whose return it then earns (so
    an exit at a name's real last print pays its cost there, and nothing fills on a no-print day).
    Participation cap: each session
    trades at most 1% of ADV20 shares toward the target, where ADV20 is the trailing 20-session
    mean dollar volume ending the session before the fill day (the fill day's own volume is never
    in it); the unfilled remainder carries to later sessions. A name with no ADV history has cap 0
    and can't trade until it has one (at least 10 sessions in the window). A name with no print can't trade, so it stays held. Once a name is past its last
    print and its target is flat, the held position is settled at its last close at no cost (null
    delisting return); the H1 terminal bound and the H2 delisting stress book their loss on that
    held amount. Yields (session, previous session, held after the fills, trades, capped), each
    trade as (symbol, side, px, shares, adv_shares)."""
    PX, VOL = bars["PX"], bars["VOL"]
    W_exec = W.shift(1).fillna(0.0)
    DV = PX * VOL
    ADV20 = DV.rolling(20, min_periods=10).mean().shift(1)  # row k: window ending k-1; read at the fill day
    last_print = {str(c): last_print_index(PX, str(c)) for c in PX.columns}
    pos = {d: i for i, d in enumerate(PX.index)}
    held = pd.Series(0.0, index=W_exec.columns)
    dates = W_exec.index
    for j in range(1, len(dates)):
        d = dates[j]
        fill_day = dates[j - 1]  # W_exec row j is the weight filled at close j-1: price, print and cap there
        target = W_exec.iloc[j]
        want = target - held
        fill = want.copy()
        trades: list[Any] = []
        capped = False
        for s, delta in want.items():
            if abs(delta) < 1e-15:
                continue
            px = float(PX.at[fill_day, s]) if s in PX.columns and fill_day in pos else float("nan")
            if not has_print(px):
                gone = pos.get(fill_day, len(PX.index)) > last_print.get(str(s), -1)
                if not (gone and abs(float(target.loc[str(s)])) < 1e-15):
                    fill.loc[str(s)] = 0.0  # no print: can't trade, the position stays held
                continue  # (or: past its last print with a flat target, settled at last close)
            adv = ADV20.at[fill_day, s] if s in ADV20.columns and fill_day in pos else np.nan
            adv_sh = (adv / px) if (isinstance(adv, float) and adv > 0) else None
            if adv_sh is None:
                fill.loc[str(s)] = 0.0  # no ADV history: cap 0, can't trade (never left uncapped)
                capped = True
                continue
            sh = abs(delta) * AUM / px
            # 1% ADV cap on the trade itself; the remainder carries
            if sh > PARTICIPATION_CAP * adv_sh:
                sh = PARTICIPATION_CAP * adv_sh
                fill.loc[str(s)] = math.copysign(sh * px / AUM, delta)
                capped = True
            trades.append((s, "buy" if delta > 0 else "sell", px, sh, adv_sh))
        held = held + fill
        yield d, dates[j - 1], held, trades, capped


def held_positions(bars: dict[str, Any], W: pd.DataFrame) -> pd.DataFrame:
    """Position actually held after each session's fills (row k earns row k's return); row 0 is flat."""
    rows = {W.index[0]: pd.Series(0.0, index=W.columns)} if len(W.index) else {}
    rows.update({d: held for d, _prev, held, _trades, _capped in _fills(bars, W)})
    return pd.DataFrame(rows, columns=W.index).T.reindex(columns=W.columns).astype(float)


def apply_costs_and_returns(bars: dict[str, Any], W: pd.DataFrame, cfg: Any, *, idea: str) -> dict[str, Any]:
    """Apply one-session execution lag, participation cap, borrow, and daily net returns.

    REQUIRED path must use cfg from build_cost_config('unknown_borrow_required').
    """
    if cfg.borrow_rate < BORROW_UNKNOWN_REQUIRED and cfg.is_pass_bar:
        raise RuntimeError("pass-bar config must have borrow_rate >= 10%/yr")
    if cfg.is_pass_bar and cfg.borrow_rate < 0.10:
        raise RuntimeError("required gate borrow_rate must be >= 0.10")

    R = bars["R"]
    rets = []
    capped_sessions = 0
    for d, prev, held, trades, capped in _fills(bars, W):
        trade_cost_frac = 0.0
        for s, side, px, sh, adv_sh in trades:
            sig = None
            c = one_way_bps(side, float(px), float(sh), adv_sh, sig, cfg=cfg, venue="close", symbol=s, etf_symbols=ETFS)
            trade_cost_frac += (sh * px / AUM) * c["bps"] / 1e4
        capped_sessions += capped
        w = held
        # asset return contribution, on the held position only
        rrow = R.loc[[d]].iloc[0].reindex(w.index).fillna(0.0) if d in R.index else 0.0
        gross = float((w * rrow).sum()) if not isinstance(rrow, float) else 0.0
        # borrow on short notional over the calendar days since the last close (weekends and
        # holidays accrue; 360-day convention)
        short_mv = float((-w.clip(upper=0)).sum() * AUM)
        days = float((d - prev).days)
        b = borrow_usd(short_mv, days=days, cfg=cfg)["usd"] / AUM
        net = gross - trade_cost_frac - b
        rets.append((d, net, gross, trade_cost_frac, b))
    df = pd.DataFrame(rets, columns=["session_date", "net", "gross", "tc", "borrow"]).set_index("session_date")
    # NOTE: caller evaluates gates; this function only builds the series.
    return {
        "idea": idea,
        "cost_path": cfg.label,
        "borrow_rate_used": cfg.borrow_rate,
        "is_pass_bar": cfg.is_pass_bar,
        "k_impact": cfg.k_impact,
        "n_sessions": int(len(df)),
        "n_sessions_adv_capped": int(capped_sessions),
        "daily": df,
    }


# ---- H1 adverse terminal bound ----


def load_h1_terminal_roster(path: str | None = None, expected_sha: str | None = None) -> list[Any]:
    path = H1_TERMINAL_ROSTER_PATH if path is None else path
    expected_sha = H1_TERMINAL_ROSTER_SHA256 if expected_sha is None else expected_sha
    if PENDING in (path, expected_sha):
        raise Blocked("BLOCK H1: terminal roster path/sha PENDING.")
    if not Path(path).is_file() or sha256_file(Path(path)) != expected_sha:
        raise Blocked("BLOCK H1: terminal roster absent or sha mismatch.")
    with open(path) as f:
        return cast(list[Any], json.load(f))


def _trusted(bars: dict[str, Any], s: str) -> pd.Series:
    """Trusted print: a print (has_print), volume > 0, not forward-filled."""
    tr: pd.Series = printed_mask(bars["PX"][[s]])[s] & (bars["VOL"][s] > 0)
    if "FFILL" in bars:
        tr &= ~bars["FFILL"][s].fillna(True).astype(bool)
    return tr


def _trusted_tau(bars: dict[str, Any], s: str) -> int | None:
    """tau = last trusted print (pinned bar file only): a print (has_print), volume > 0, not forward-filled."""
    if s not in bars["PX"].columns:
        return None
    idx = np.flatnonzero(_trusted(bars, s).to_numpy(dtype=bool))
    return int(idx[-1]) if len(idx) else None


def short_vmax(terms: dict[str, Any], tau_d: pd.Timestamp, h_d: pd.Timestamp, client: Any) -> float:
    """V_max = max_k (cash_k + ratio_k * max accepted acquirer close over [tau, h]); else BLOCK."""
    if terms.get("worthless_cancellation") is True:
        return 0.0
    alts = terms.get("alternatives") or []
    if not alts or terms.get("unaccepted_legs") or terms.get("unfiled_proration"):
        raise Blocked("BLOCK H1: short terms incomplete (V_max undefined).")
    sessions = client.xnys_sessions(tau_d, h_d)
    vals = []
    for a in alts:
        cash, ratio = float(a.get("cash", 0.0)), float(a.get("ratio", 0.0))
        if ratio == 0.0:
            vals.append(cash)
            continue
        if not a.get("acquirer_id") or a.get("acquirer_identity_accepted") is not True:
            raise Blocked("BLOCK H1: unaccepted acquirer identity (V_max undefined).")
        px = client.accepted_acquirer_closes(a["acquirer_id"], tau_d, h_d).reindex(sessions)
        if px.isna().any():
            raise Blocked("BLOCK H1: missing acquirer close in [tau, h] (V_max undefined).")
        vals.append(cash + ratio * float(px.max()))
    return float(max(vals))


def h1_terminal_bound(
    bars: dict[str, Any],
    W: pd.DataFrame,
    roster: list[Any],
    cfg: Any,
    *,
    client: Any = None,
    path: str = "A",
) -> tuple[pd.DataFrame, pd.Series, list[dict[str, Any]]]:
    """Apply the H1 adverse terminal rule to positions stranded in unresolved terminal rows.

    Returns (W_adj, overlay, receipts). W_adj zeroes the stranded leg from tau+1 (no print there,
    so it can't fill: no exit-cost credit); overlay[d] is the fractional
    equity charge booked at tau+1 (long: -100% of marked value; short: max(P_tau, V_max)
    liability) plus borrow from tau+1 to max(frozen exit, h). The bound applies to the position
    actually held into tau+1 (after the ADV cap), not the target: a capped exit still holding at
    delisting is bound on what is left. Fails closed (Blocked).
    """
    if path not in H1_TERMINAL_PATHS:
        raise ValueError(path)
    dates = W.index
    W_adj = W.copy()
    overlay = pd.Series(0.0, index=dates)
    receipts = []
    held = held_positions(bars, W) if roster else None
    for row in roster:
        s = row["symbol"]
        if s not in W.columns or not (W[s].abs() > 0).any():
            continue  # never held: no payoff to replace (no exclusion by future fate)
        if row.get("identity_ok") is not True:
            raise Blocked(f"BLOCK H1: identity gate (axis I) not passed for {s}.")
        t = _trusted_tau(bars, s)
        if t is None:
            raise Blocked(f"BLOCK H1: no trusted print for held roster row {s}.")
        tau_d = dates[t]
        if (
            row.get("ledger_last_session_status") == "observed_last_trading_session"
            and pd.Timestamp(row.get("ledger_last_session")) != tau_d
        ):
            raise Blocked(f"BLOCK H1: tau != ledger last_session for {s}.")
        if row.get("economic_event_date") and pd.Timestamp(row["economic_event_date"]) < tau_d:
            raise Blocked(f"BLOCK H1: source-bound economic date < tau for {s}.")
        # suspension gaps before tau: a held session without trusted print before tau
        held_pre = W[s].iloc[:t].abs() > 0
        trusted = _trusted(bars, s)
        if (held_pre & ~trusted.iloc[:t]).any():
            raise Blocked(
                f"BLOCK H1: suspension gap before tau for {s} (worse-of-prints "
                "exit not representable in frozen weight path; fail closed)."
            )
        assert held is not None
        if t + 1 >= len(dates):
            continue  # not open after tau within window
        # held after the fills at close tau (the last fill it can get); this is what reaches tau+1
        w = float(held[s].iloc[t + 1])
        if abs(w) < 1e-15:
            continue
        book_i = t + 1
        p_tau = float(bars["PX"][s].iloc[t])
        rec = {
            "symbol": s,
            "sid": row.get("sid"),
            "instrument_id": row.get("instrument_id"),
            "side": "long" if w > 0 else "short",
            "weight": w,
            "target_weight": float(W[s].iloc[t]),
            "entry_session": str(dates[int(np.flatnonzero((W[s].abs() > 0).values)[0])].date()),
            "tau": str(tau_d.date()),
            "booking_session": str(dates[book_i].date()),
            "P_tau": p_tau,
            "path": path,
        }
        if w > 0:
            overlay.iloc[book_i] -= w  # terminal value 0: -100%
        else:
            terms = row.get("short_terms")
            if not terms or not terms.get("h"):
                raise Blocked(f"BLOCK H1: short terms/h missing for {s} (whole run blocked).")
            if client is None:
                raise Blocked("BLOCK H1: desk client required for short V_max.")
            h_d = pd.Timestamp(terms["h"])
            vmax = short_vmax(terms, tau_d, h_d, client)
            liab = max(p_tau, vmax)
            overlay.iloc[book_i] -= abs(w) * (liab / p_tau - 1.0)
            post = W[s].iloc[t + 1 :]
            ex_rel = np.flatnonzero((post == 0).values)
            frozen_exit_i = t + 1 + int(ex_rel[0]) if len(ex_rel) else len(dates) - 1
            h_i = int(np.searchsorted(dates.values, h_d.to_datetime64(), side="right")) - 1
            end_i = min(max(frozen_exit_i, h_i), len(dates) - 1)
            rate = max(cfg.borrow_rate, float(terms.get("borrow_rate_source", 0.0)))
            per_day = borrow_usd(abs(w) * AUM, days=1.0, cfg=cfg)["usd"] / AUM
            per_day *= rate / cfg.borrow_rate if cfg.borrow_rate > 0 else 1.0
            for j in range(book_i, end_i + 1):
                overlay.iloc[j] -= per_day * (dates[j] - dates[j - 1]).days  # calendar days, weekends accrue
            rec.update(
                {
                    "h": str(h_d.date()),
                    "V_max": vmax,
                    "liability": liab,
                    "borrow_rate": rate,
                    "source_hashes": terms.get("source_hashes"),
                }
            )
        # flat from tau+1: the stranded amount is never traded at tau (no exit-cost credit)
        W_adj.iloc[t + 1 :, cast(int, W_adj.columns.get_loc(s))] = 0.0
        receipts.append(rec)
    # Path B: identical charge as an equity overlay; the runner has no stop / basket-stop / H8-H9 /
    # NAV-sizing code, so what the risk logic "sees" cannot differ: A and B coincide here.
    return W_adj, overlay, receipts


def sharpe_ann(daily_net: pd.Series) -> float:
    mu = daily_net.mean()
    sd = daily_net.std(ddof=1)
    if not (sd > 0):
        return float("nan")
    return float(mu / sd * math.sqrt(252))


def h2_delisting_stress(
    bars: dict[str, Any],
    W: pd.DataFrame,
    positions: list[dict[str, Any]],
    supplied_delist_returns: dict[str, Any] | None = None,
) -> tuple[pd.Series, list[dict[str, Any]]]:
    """Pre-registered counted stress for H2, pure computation: on any NULL delisting return,
    -30% for longs and 0% for shorts. Applied to every position h2_delisting_receipts flags (name
    stops printing before its planned exit). The charge is the position actually held over the
    session after the last close (after the ADV cap, not the target) times the shock, booked at
    last+1 as an equity overlay added to daily net. A supplied (non-null) delisting return gets no stress.
    Returns (overlay indexed like W, receipts)."""
    sup = supplied_delist_returns or {}
    dates = W.index
    overlay = pd.Series(0.0, index=dates)
    out = []
    held: pd.DataFrame | None = None
    for r in h2_delisting_receipts(bars, positions):
        s = r["symbol"]
        if sup.get(s) is not None:
            out.append(dict(r, stress="not applied: supplied (non-null) delisting return"))
            continue
        li = int(cast(int, dates.get_loc(pd.Timestamp(r["last_close_session"]))))
        if li + 1 >= len(dates):
            continue
        if held is None:
            held = held_positions(bars, W)
        w = float(held[s].iloc[li + 1]) if s in held.columns else 0.0  # after the last fill (close li)
        shock = H2_DELISTING_STRESS_LONG if w > 0 else H2_DELISTING_STRESS_SHORT
        charge = w * shock if w > 0 else 0.0
        overlay.iloc[li + 1] += charge
        out.append(
            dict(
                r,
                stress="counted: null delisting return",
                stress_weight=w,
                stress_shock=shock,
                stress_charge=charge,
                stress_booking_session=str(dates[li + 1].date()),
            )
        )
    return overlay, out


# ---- CLI ----


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backtest_h1_h2_v1_3a.py",
        description="H1/H2 Stage A / sealed-holdout runner v1.3a DRAFT (pre-registration v3).",
    )
    p.add_argument(
        "--stage", choices=["dev", "holdout"], help="dev = Stage A window; holdout = sealed 2022-03-30..2026-10-28."
    )
    p.add_argument(
        "--acceptance-hash",
        default=None,
        help="sha256 of the pre-registration; REQUIRED for holdout and for any return run.",
    )
    p.add_argument("--idea", choices=["H1", "H2", "both"], default="both")
    p.add_argument(
        "--dev-inputs",
        default=None,
        help=f"REQUIRED for --stage dev: exactly {DEV_INPUTS_DIR}/ (SHA256SUMS sha pinned).",
    )
    p.add_argument(
        "--delisting-stress",
        action="store_true",
        help="H2 only: counted delisting-stress rerun (-30%% long / 0%% short on null delisting return).",
    )
    p.add_argument(
        "--av-factor-sensitivity",
        action="store_true",
        help="DECLARED SENSITIVITY, off by default: AV raw x desk factor returns instead of the "
        "pre-registered total return. Never primary, never gates; refused until its own pins exist.",
    )
    p.add_argument(
        "--cost-path",
        default="unknown_borrow_required",
        help="costs_original path name (default=required >=10%%/yr borrow).",
    )
    p.add_argument("--unit", type=float, default=0.005, help="H2 unit (primary 0.5%%; neighbours 0.4/0.6).")
    p.add_argument(
        "--syntax-check", action="store_true", help="Import/check only; compute no returns and load no market data."
    )
    p.add_argument(
        "--dry-run-signals",
        action="store_true",
        help="Build signals only (no P&L/Sharpe). Still requires acceptance on holdout.",
    )
    p.add_argument("--out", type=str, default=None, help="Optional JSON output path under out/.")
    p.add_argument(
        "--pyarrow-site", default=None, help=f"REQUIRED for any stage: declared site path ({PYARROW_SITE_APPROVED})."
    )
    p.add_argument(
        "--pyarrow-site-sha",
        default=None,
        help="REQUIRED: sha256 of <site>/" + PYARROW_RECORD_REL + " (must equal pin).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(argv)

    if args.syntax_check or not args.stage:
        # Safe path: no data, no returns.
        _ = build_cost_config("unknown_borrow_required")
        assert K_IMPACT_BASE == cm.K_IMPACT_DEFAULT == 1.0
        assert K_IMPACT_LIGHTER == 0.75
        assert BORROW_UNKNOWN_REQUIRED >= 0.10
        print("backtest_h1_h2_v1_3a.py syntax-check OK")
        print(f"  PREREG: {PREREG_PATH}")
        print(f"  prereg_sha256: {sha256_file(PREREG_PATH)}")
        print(f"  K_IMPACT_BASE={K_IMPACT_BASE} (model base); K_IMPACT_LIGHTER={K_IMPACT_LIGHTER}")
        print(f"  required borrow_rate>={BORROW_UNKNOWN_REQUIRED:.0%} (ETF hedges included)")
        print(f"  early-close assumptions: {sorted(EARLY_CLOSE_DAYS_2026)}")
        print(f"  quarantine path present={QUARANTINE.exists()} (contents unread)")
        return 0

    stage = args.stage
    # Holdout always requires acceptance-hash. Dev return runs do too.
    # dry-run-signals on dev may proceed without hash ONLY if we still refuse holdout rows;
    # The prereg says no DEV return trial before acceptance — signal-only on DEV is already
    # covered by turnover_dev.py. This runner requires the hash for both stages.
    prereg_sha = require_acceptance_hash(args.acceptance_hash, stage)
    pyarrow_record_sha = verify_pyarrow_site(args.pyarrow_site, args.pyarrow_site_sha)
    if stage != "dev":
        raise Blocked("REFUSING: this runner binds DEV-only inputs; no holdout inputs are pinned.")
    if args.delisting_stress and args.idea != "H2":
        raise Blocked("REFUSING: --delisting-stress is H2 only (H1 stress withdrawn); pass --idea H2.")
    if args.delisting_stress and args.av_factor_sensitivity:
        raise Blocked(
            "REFUSING: --delisting-stress is a counted rerun on the PRIMARY (TR) source, not on the AV sensitivity."
        )
    dev = bind_dev_inputs(args.dev_inputs)
    dev["receipt"].update(verify_dev_cuts())
    data_pins = require_data_pins(av_factor_sensitivity=args.av_factor_sensitivity)
    verify_b1c_accepted()
    verify_final_list_sha()  # pre-check before any loader (at-use re-check kept below)
    client_mapping = client_static_check()

    filter_end, eval_start, eval_end = stage_date_bounds(stage)
    if stage == "dev" and filter_end >= HOLDOUT0:
        raise RuntimeError("DEV filter_end must be before holdout start")
    if stage == "holdout" and eval_start != HOLDOUT0:
        raise RuntimeError("holdout must start 2022-03-30")

    cfg = build_cost_config(args.cost_path)
    if stage == "holdout" and not cfg.is_pass_bar and args.cost_path.startswith("unknown"):
        pass  # ok
    # Load with read-time filters
    if args.av_factor_sensitivity:
        bars = load_bars(filter_end)  # AV raw x desk factor = DECLARED SENSITIVITY only
    else:
        bars = load_bars_tr(filter_end)  # PRIMARY = pre-registered total return (DEV cut)
    # Extra guard: no holdout rows in DEV
    if stage == "dev" and (bars["R"].index >= pd.Timestamp(HOLDOUT0)).any():
        raise RuntimeError("DEV leakage: holdout rows present after filters")
    _mem_v12_unused, subind, sector = load_universe()  # GICS only (release store; deviation)
    final_list = load_final_list()  # re-checked at use, fail closed
    mem, subind, sector, universe_receipt = load_universe_v13a(
        DeskClientH1H2Adapter(load_desk_client()),
        subind,
        sector,
        lineage_excl=dev["lineage_excl"],
        dev_universe=dev["dev_universe"],
        final_list=final_list,
    )
    ELIG = build_elig(bars, mem)
    ev_raw = load_earnings(filter_end)
    ev = earliest_possible_index(ev_raw, cast(pd.DatetimeIndex, bars["R"].index))
    evidx = make_evidx(ev)
    dates = bars["R"].index
    # last exit index: within eval window minus H7 margin
    eval_dates = dates[(dates >= pd.Timestamp(eval_start)) & (dates <= pd.Timestamp(eval_end))]
    last_exit_i = int(cast(int, dates.get_loc(eval_dates[-1]))) - MARGIN

    results = {
        "stage": stage,
        "prereg_sha256": prereg_sha,
        "cost_path": cfg.label,
        "borrow_rate_used": cfg.borrow_rate,
        "is_pass_bar": cfg.is_pass_bar,
        "k_impact": cfg.k_impact,
        "filter_end": str(filter_end),
        "eval": [str(eval_start), str(eval_end)],
        "generated": datetime.now().isoformat(timespec="seconds"),
        "returns_computed": False,
        "runner_version": "1.3a-draft",
        "pyarrow_record_sha256": pyarrow_record_sha,
        "data_pins": data_pins,
        "universe_receipt": universe_receipt,
        "client_mapping": client_mapping,
    }
    results["v13b"] = {
        "runner": "1.3b-draft",
        "dev_inputs_receipt": dev["receipt"],
        "delisting_stress": bool(args.delisting_stress),
    }
    results["v13c"] = {
        "runner": "1.3c-draft",
        "primary": not args.av_factor_sensitivity,
        "return_source": (
            "SENSITIVITY (declared): AV raw x desk factor; not primary; never gates"
            if args.av_factor_sensitivity
            else "PRIMARY: pre-registered total return, DEV cut"
        ),
        "tr_dev_cut_sha256": TR_DEV_CUT_SHA256,
        "tr_parent_sha256": TR_PARENT_SHA256,
    }
    if args.delisting_stress:
        results["v13b"]["trial_accounting"] = {
            "mode": "H2 delisting-stress rerun (counted)",
            "prereg": "pre-registered per-idea delisting-stress rerun (5 x 2 = 10)",
            "N_effect": "inside N = 212 (v3) / 214 (with H1 v0.2); no increment for this one counted run; any repeat adds to N and is logged in §12",
            "H1": "not run: H1 stress withdrawn",
        }

    ideas = ["H1", "H2"] if args.idea == "both" else [args.idea]
    for idea in ideas:
        if idea == "H1":
            W, _ = signal_h1(
                bars, ELIG, subind, evidx, eval_start=eval_start, eval_end=eval_end, last_exit_i=last_exit_i
            )
        else:
            W, h2_positions = signal_h2(
                bars,
                ELIG,
                subind,
                sector,
                ev_raw,
                evidx,
                unit=args.unit,
                eval_start=eval_start,
                eval_end=eval_end,
                last_exit_i=last_exit_i,
            )
            results["H2_delisting_receipts"] = h2_delisting_receipts(bars, h2_positions)
            if args.delisting_stress:
                stress_overlay, results["H2_delisting_stress_receipts"] = h2_delisting_stress(bars, W, h2_positions)
        h1_paths: list[Any] = [None]
        if idea == "H1" and not args.dry_run_signals:
            roster = load_h1_terminal_roster()
            client = DeskClientH1H2Adapter(load_desk_client())
            h1_paths = []
            for pth in H1_TERMINAL_PATHS:
                W_adj, overlay, receipts = h1_terminal_bound(bars, W, roster, cfg, client=client, path=pth)
                h1_paths.append((pth, W_adj, overlay, receipts))
        if args.dry_run_signals:
            results[idea] = {
                "signal_only": True,
                "n_days_nonzero": int((W.abs().sum(axis=1) > 0).sum()),
                "avg_gross": float(W.abs().sum(axis=1).mean()),
            }
            continue
        for item in h1_paths:
            key = idea if item is None else f"{idea}_path{item[0]}"
            if idea == "H2" and args.delisting_stress:
                key = "H2_delisting_stress"
            if args.av_factor_sensitivity:
                key = f"SENSITIVITY_av_factor_{key}"
            W_run = W if item is None else item[1]
            # Returns path
            out = apply_costs_and_returns(bars, W_run, cfg, idea=idea)
            daily = out.pop("daily")
            if item is not None:
                daily["net"] = daily["net"] + item[2].reindex(daily.index).fillna(0.0)
                out["terminal_receipts"] = item[3]
            if idea == "H2" and args.delisting_stress:
                daily["net"] = daily["net"] + stress_overlay.reindex(daily.index).fillna(0.0)
            out["net_sharpe_ann"] = sharpe_ann(daily["net"])
            out["gross_sharpe_ann"] = sharpe_ann(daily["gross"])
            # Do not print full daily series by default
            results[key] = {k: v for k, v in out.items() if k != "daily"}
            results["returns_computed"] = True
            if args.av_factor_sensitivity:
                results[key]["label"] = "SENSITIVITY (declared): AV raw x desk factor; not primary; never gates"
            # Required gate note
            if cfg.is_pass_bar and not args.av_factor_sensitivity:
                sr = out["net_sharpe_ann"]
                results[key]["required_borrow_gate"] = "PASS" if (isinstance(sr, float) and sr > 0) else "FAIL on costs"

    if args.out:
        outp = Path(args.out)
        if not str(outp).startswith(str(OUT_DIR)):
            outp = OUT_DIR / outp.name
        outp.parent.mkdir(parents=True, exist_ok=True)
        with open(outp, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"wrote {outp}")
    else:
        print(json.dumps({k: v for k, v in results.items() if k != "daily"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
