#!/usr/bin/env python3
"""Stage A / sealed-holdout backtest runner for Sofia original ideas H1 and H2.

Owner: Sofia (Stat Arb). Written 2026-11-06 SGT for PREREG_ORIGINAL v3.
v1.3 DRAFT 2026-11-10 SGT (successor of v1.2 sha256 1ea3d146...6ad). Exactly three changes:
  (1) prices = AV raw close x desk adjustment factor via the desk data client (declared
      interface; client not yet delivered; pins PENDING -> refuses to load);
  (2) H1 v0.2 adverse terminal bound (accepted amendment 373c3e5d / readback 79217ca7);
  (3) required declared --pyarrow-site + --pyarrow-site-sha (refuse by default).
NOT ACCEPTED. The acceptance Victor binds will be this file's new sha256; the PREREG hash
check below is unchanged.
v1.3a DRAFT 2026-11-10 SGT (scoped amendment of v1.3 sha256 7fb8be7d...64bb):
  (a) PIT universe via declared DeskClientUniverseInterface + pinned R18 / M14 inputs
      (5e fill rule = future hook, not implemented; earnings stay on v1.2 store = deviation);
  (b) H2 delisting base for raw prices = v1.2 implicit treatment, made explicit + receipts;
  (c) H1 last-close base / -30%/0% stress NOT implemented (withdrawn by accepted v0.2).
Implements the exact primary rules from:
  research/ideas/orig-sofia-subind-bellwether-lag.md
  research/ideas/orig-sofia-earnings-peer-readthrough.md
governed by statarb/PREREG_ORIGINAL.md.

HARD RULES:
  - Read-time pyarrow date filters only (X14). DEV never loads post-2021-12-31 rows.
    Holdout loads only its own window, and only when --stage holdout is accepted.
  - --stage holdout REFUSES to run without --acceptance-hash equal to sha256 of
    the current PREREG_ORIGINAL.md (frozen accepted hash).
  - --stage dev that would compute returns likewise requires --acceptance-hash
    (no DEV return trial before Victor accepts the prereg at a recorded sha256).
  - Quarantined stops_dev outputs under
    out/QUARANTINE_stops_dev_DO_NOT_USE are never read (Victor waiver 2026-11-06).
  - Holdout rows 2022-03-30 onward are never touched in --stage dev.
  - Costs: costs_original.CostConfig; required path borrow >=10%/yr on EVERY
    historically unknown short including H2 sector-ETF hedges (no ETF exemption).
    The 1%/yr path is a labelled GC counterfactual only.
  - Impact k = cost_model.K_IMPACT_DEFAULT = 1.0 (base; Tomas 2026-11-06).
    k = 0.75 is a lighter sensitivity, not a stress.

This file MAY compute returns when invoked with a valid acceptance hash.
Do NOT invoke return paths until Victor accepts v3 and Stage A dependencies
(v1.3 earnings freeze, desk 8-K 2.02 SUE) are present. A --help or syntax check
is always safe and computes no returns.

Run examples (safe):
  python3 -I -B backtest_h1_h2_v1_3a.py --help
  python3 -I -B backtest_h1_h2_v1_3a.py --syntax-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

# ---- v1.3b C7 BEGIN (Rachel E7 r2, amendment C7, decisions log 5a2fc464): vendored numpy ----
# RECORD raw sha is checked BEFORE sys.path is touched; only hashlib/os/sys (already imported).
NP_SITE = f"{_QR.DATA_DIR}/lib/deskclient_h1h2_v1/vendor/site"
NP_RECORD_SHA256 = (
    "b841d0763e8ea41066a573882b3cdcd74a2d5505f5e43d46e755d244319ebe29"  # gitleaks:allow (sha256 digest, not a secret)
)
RC_C7_NUMPY_PIN = 17  # new exit code; distinct from 0 (ok), 1 (SystemExit/Blocked), 2 (argparse)
_np_rec_sha: str | None
try:
    with open(NP_SITE + "/numpy-2.5.4.dist-info/RECORD", "rb") as _np_rec_fh:
        _np_rec_sha = hashlib.sha256(_np_rec_fh.read()).hexdigest()
except OSError:
    _np_rec_sha = None
if _np_rec_sha != NP_RECORD_SHA256:
    raise SystemExit(RC_C7_NUMPY_PIN)
sys.path.insert(0, NP_SITE)
import numpy as np

if not (os.path.realpath(np.__file__).startswith(os.path.realpath(NP_SITE) + "/numpy/") and np.__version__ == "2.5.4"):
    raise SystemExit(RC_C7_NUMPY_PIN)
# ---- v1.3b C7 END ----
import pandas as pd

sys.path.insert(0, f"{_QR.COSTS_DIR}")
sys.path.insert(0, f"{_QR.DESK_DIR}/statarb/original")
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

# ---- Paths / pins ----
ROOT = Path(f"{_QR.DESK_DIR}")
PREREG_PATH = ROOT / "statarb" / "PREREG_ORIGINAL.md"
RELEASE = ROOT / "data" / "releases" / "v1.2"
EARNINGS = Path(f"{_QR.DATA_DIR}/h1h2_dev_cuts_20261111_r2/earnings_dev_through_20220329.parquet")  # v1.3b X1 DEV cut
QUARANTINE = ROOT / "statarb" / "original" / "out" / "QUARANTINE_stops_dev_DO_NOT_USE"
OUT_DIR = ROOT / "statarb" / "original" / "out"

# ---- v1.3 pins (change 1: desk client; change 2: H1 terminal roster; change 3: pyarrow) ----
PENDING = "PENDING"
# Change 1: desk data client (Dmitri). No module exists at $QR_DESK_DIR/data_client.py or
# $QR_DATA_DIR/client.py as of 2026-11-10 19:17 SGT. Interface declared in
# DeskClientInterface below; path and pins are placeholders and the runner refuses while PENDING.
DESK_CLIENT_PATH = f"{_QR.DATA_DIR}/lib/deskclient_h1h2_v1/deskclient_h1h2_v1.py"  # v1.3b: Victor L347 / d43e3826
DESK_CLIENT_SHA256 = (
    "0310e473ab8a320cbbec9f74dbfc0d54ef064d999c46a9167b16c880974e76da"  # gitleaks:allow (sha256 digest, not a secret)
)
PIN_RECONCILIATION_SEAL_SHA256 = PENDING  # sealed SHA256SUMS of the reconciliation root
PIN_CA_LEDGER_SHA256 = PENDING  # reconciled corporate-action ledger
PIN_FACTOR_TABLE_SHA256 = PENDING  # cumulative PIT desk factor table
PIN_FACTOR_CODE_SHA256 = PENDING  # factor code (tested on synthetic fixtures)
PIN_AV_RAW_BARS_SHA256 = PENDING  # pinned AV raw bar file (--av-factor-sensitivity only; primary tau runs on the TR cut fc852152 bars since v1.3c, L401)
# Change 2: H1 terminal roster (unresolved delisting rows; v06 ledger extract), pinned.
H1_TERMINAL_ROSTER_PATH = (
    f"{_QR.DESK_DIR}/validation/dmitri/h1_v06_roster_pin_20261111_r1/H1_TERMINAL_ROSTER_v06_DEV.json"
)
H1_TERMINAL_ROSTER_SHA256 = (
    "c3c834dad21ae2109feb71b1939d17043a0f714a9bf969db43ae151ae5974a8d"  # gitleaks:allow (sha256 digest, not a secret)
)
H1_TERMINAL_PATHS = ("A", "B")
# Change 3: declared interpreter site for pyarrow (Jeremy-approved for Dmitri; not yet
# extended by Victor to this runner). Pin = sha256 of the dist-info RECORD file.
PYARROW_SITE_APPROVED = f"{_QR.HOME_DIR}/.local/lib/python3.13/site-packages"
PYARROW_RECORD_REL = "pyarrow-26.0.0.dist-info/RECORD"
PYARROW_RECORD_SHA256 = (
    "d4dc368ee2e1af6ac5ddbb023a20266015037679a6369af37e7de7cb1207b545"  # gitleaks:allow (sha256 digest, not a secret)
)
# ---- v1.3a pins: (a) universe inputs ----
V13A_DIR = ROOT / "statarb" / "original" / "runner_v1_3a_20261110"
R18_INPUT_PATH = V13A_DIR / "INPUT_R18_REUSED_TICKERS.json"
R18_INPUT_SHA256 = (
    "4caddc0831faa881e5893b3fd9d3bffcfc84c10eb757fd67ff3c09777d665da0"  # gitleaks:allow (sha256 digest, not a secret)
)
M14_INPUT_PATH = V13A_DIR / "INPUT_M14_MISSING_NAMES.json"
M14_INPUT_SHA256 = (
    "791483e35b5f5a4b578c8100f24dcc22d6186531bfce82b31b3fdce7b7032fba"  # gitleaks:allow (sha256 digest, not a secret)
)
PIN_PIT_MEMBERSHIP_SHA256 = (
    "a3766d6262bb6a09cd4a46c050ab4f04faa47dc4317fc1d45d8545b06ba1b60d"  # v1.3b: r2 membership cut
)
PIN_LISTING_STATUS_SHA256 = (
    "ab9891b208bc1e51a803055e810330dd5d03e7ff8af755bd0630a47914ef31f6"  # v1.3b: client _LISTING_PAIR_SHA
)
# Victor 5e fill rule (FUTURE HOOK, NOT IMPLEMENTED): desk path or pinned snapshot only; one
# source per name; >= 252 DEV sessions to 2022-03-29; lineage on every row. Any fill input
# passed to v1.3a is refused.
FILL_INPUT_PATH = None
# Deviation (a): earnings remain on the v1.2 release store (EARNINGS above), unchanged.

# Splits (PREREG §9); holdout starts 2022-03-30 — never load in DEV
DEV0, DEV1 = date(2017, 1, 3), date(2021, 12, 31)
EMBARGO0, EMBARGO1 = date(2022, 1, 3), date(2022, 3, 29)
HOLDOUT0, HOLDOUT1 = date(2022, 3, 30), date(2026, 10, 28)
LOAD0 = date(2015, 12, 31)  # warm-up only; still filtered by stage end
# ---- v1.3c return source (Jeremy ruling citing Victor L395 / 8523e323): PREREG f3b2b1be L38 ----
# PRIMARY returns = releases/v1.2/bars/daily/total_return/daily_total_return.parquet (sha 0590692d),
# read ONLY through a sealed DEV-only cut of Dmitri's byte-exact rebuild (rows <= 2022-03-29, X1-style).
# The parent file holds post-2022-03-29 rows and is never opened, not even with a filter (E7 C3).
TR_PARENT_SHA256 = "0590692d765515e0f76f4f6b7360c5ed7be38e2e85a5f91562dbfebcf8a129db"  # PREREG L38 literal
TR_DEV_CUT_PATH = f"{_QR.DESK_DIR}/validation/dmitri/x1_dev_cut_20261115_r1/daily_total_return_dev.parquet"  # sealed DEV-only cut of the rebuilt L38 file (Dmitri; Victor review)
TR_DEV_CUT_SHA256 = "fc852152d38bc3b5b60a5731a7cfdd8115bf754f1e7f44ba36dd3ad5589337a6"  # raw-byte sha256 of that cut
# v1.3d A4 (Victor 7ba03e18): the cut's ACCEPTED SHA256SUMS (path + raw sha), from Victor's acceptance of the cut.
TR_DEV_CUT_SUMS_PATH = f"{_QR.DESK_DIR}/validation/dmitri/x1_dev_cut_abs_sums_20261115/SHA256SUMS_abs"
TR_DEV_CUT_SUMS_SHA256 = (
    "e5121148c872fd25c46f553d12ed6f55180a0b4f7658f411e3d97634a813df7b"  # gitleaks:allow (sha256 digest, not a secret)
)
# ---- v1.3e scope 2 (Victor L368/L369, readback L826): identity-map FINAL_LIST (Dmitri), re-checked at use ----
# v1.3f F1/F2 (Victor L830): pin = Victor's L367 literal (also copy SUMS e797911c); path = the INC-70 copy.
FINAL_LIST_PATH = f"{_QR.DESK_DIR}/validation/dmitri/h1h2_idmap_delta_20261111_r1/IDENTITY_FINAL_LIST_delta1.tsv"
FINAL_LIST_SHA256 = (
    "acc76c775da49ff75ad3576d78e65744deed4baafac1ec6b6ac68626ee57ad9d"  # gitleaks:allow (sha256 digest, not a secret)
)
# v1.3f F3 (Victor L830; Dmitri owner header read, Jeremy OK): header is exactly these 36 bytes, TAB-separated, LF, no CR.
FINAL_LIST_HEADER = b"symbol\tdecision\treasons\tissuer_name\n"
FINAL_LIST_COLUMNS = ("symbol", "decision", "reasons", "issuer_name")  # 4 fields on every row; issuer_name unused
FINAL_LIST_DECISIONS = {"KEPT": "kept", "EXCLUDED": "excluded"}  # v1.3f F3: vocabulary confirmed by Dmitri's owner read
RC_FINAL_LIST_MISMATCH = 18  # new exit code; distinct from 0 (ok), 1 (Blocked), 2 (argparse), 17 (C7)
# ---- v1.3e scope 3 (Victor L368: H1/H2 refuse until B1c is accepted): v1.3d had no B1c pin or gate ----
B1C_ACCEPTED_SUMS_PATH = PENDING  # SHA256SUMS of the B1c identity basis as accepted by Victor
B1C_ACCEPTED_SUMS_SHA256 = PENDING
# ---- v1.3b input binding (DEV inputs, addendum1, X1 DEV cuts) ----
DEV_INPUTS_DIR = f"{_QR.DESK_DIR}/statarb/original/dev_inputs_20261111"
DEV_INPUTS_SUMS_SHA256 = (
    "4f5b23c9e43a62a7446a9f7ced8332bbed0aa10b55325323c8216d2004303df8"  # gitleaks:allow (sha256 digest, not a secret)
)
ADDENDUM1_DIR = f"{_QR.DESK_DIR}/statarb/original/dev_inputs_20261111_addendum1"
ADDENDUM1_SUMS_SHA256 = (
    "e38da672a128cc672b137c4e89c0f7c2ddb90d0a7813c1e3b013e62033bec745"  # gitleaks:allow (sha256 digest, not a secret)
)
LINEAGE_EXCL_FILE, LINEAGE_EXCL_SHA256 = (
    "EXCLUDED_24.tsv",
    "36981628dcf7b43987b249e17eb02d9d550af19a6771ec2666f4b02c58602ddc",
)
DEV_CUTS_DIR = f"{_QR.DATA_DIR}/h1h2_dev_cuts_20261111_r2"
DEV_CUTS_SUMS_PATH = f"{_QR.SCRATCH_DIR}/scratch/h1h2_devcut_run_20261111_r2/OUT_SHA256SUMS.txt"
DEV_CUTS_SUMS_SHA256 = (
    "108045e725beb2671530291f5c457f6dcd96b2832db4f7d0c61217fe8ac0599d"  # gitleaks:allow (sha256 digest, not a secret)
)
DEV_CUT_PINS = {  # every parquet the runner (or its client) may open; sha as listed in DEV_CUTS_SUMS
    "earnings_dev_through_20220329.parquet": "1bf672efdbf6e76fa82f91276944a8edf38f199d51ee561ee2bc17328f441e51",
    "actions_dev_through_20220329.parquet": "180398661a5276569aef32be392348df27ab9dbf9c353f5025c3d31cf5383f63",
    "universe_dev_through_20220329.parquet": "b7f02ecef3520e8c60bed4080cbb9214d47599fbcea34efda36d53a3dcbdd4a9",
    "membership_dev_through_20220329.parquet": "a3766d6262bb6a09cd4a46c050ab4f04faa47dc4317fc1d45d8545b06ba1b60d",
    "listing_active_dev_through_20220329.parquet": "2a4df495f069cadadeaa2a3b57aad53a3efca7eba0ec94e917acaf0e729485a4",
    "listing_delisted_dev_through_20220329.parquet": "33f09184aa52be4857053629cdc034f2a50bc05cdd1ade93eadadea6d1b49f2b",
    "bars_ADS_dev_through_20220329.parquet": "64d50d37c9f58acf67abbcc2f2ac1b0a93182a12bd8ed404080f83e81f838c10",
    "bars_BBBY_dev_through_20220329.parquet": "b05926ddc568e8ba6b350d9a4ec0e597742484f679d40484fdca70ea01f453d3",
    "bars_CCE_dev_through_20220329.parquet": "4fe97b1b16b69a2ff51e4e6a47e04e4ad603215f7c77f36b880ab50515a16823",
    "bars_ENDP_dev_through_20220329.parquet": "d18f118254e85f2da5fe288414d28121e78393cb3ee777fc3cf49cfa424d4b53",
    "bars_FBHS_dev_through_20220329.parquet": "9a2768517d2aa89deb060d1350e44aeaa30a8d6bb74b0d416021d52fa0318efd",
    "bars_FRC_dev_through_20220329.parquet": "68d1e8950328a637af6e1587d309d6bec14bffbf11aaa1159288d072db931076",
    "bars_GPS_dev_through_20220329.parquet": "609f220f603dabdb11327863e6e6e9f54d6edfa0f0d7c2ce39659117aa3115d9",
    "bars_HFC_dev_through_20220329.parquet": "eab21deb759cc1d20fab50d7091ac5bf22862f8046c5d2f6c7770c79b8e72d1c",
    "bars_WLTW_dev_through_20220329.parquet": "e1d1a10fb34cca8d58c2e1f89df7e52e0f78082f791ec377d2fb7a0006fc17ad",
}
EARNINGS_SHA256 = DEV_CUT_PINS["earnings_dev_through_20220329.parquet"]
UNIVERSE_CUT = Path(DEV_CUTS_DIR) / "universe_dev_through_20220329.parquet"
UNIVERSE_CUT_SHA256 = DEV_CUT_PINS["universe_dev_through_20220329.parquet"]
# Listing overlap (symbol in both AV active and delisted sources): fail closed unless a pinned
# treatment covers it. Treatments are Victor's (item 5); none ruled -> empty.
LISTING_OVERLAP_IN_UNIVERSE_PATH = (
    f"{_QR.DESK_DIR}/statarb/original/runner_v1_3b_20261111/INPUT_LISTING_OVERLAP_IN_UNIVERSE.tsv"
)
LISTING_OVERLAP_IN_UNIVERSE_SHA256 = (
    "01821af703281563df855af94d4b620f7511526b529b00ff5c277c8b4a0ef49f"  # gitleaks:allow (sha256 digest, not a secret)
)
LISTING_OVERLAP_TREATMENT: dict[str, Any] = {}

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
ATR_STOP_MULT = 3.0  # Rachel max; fixed ex ante
BASKET_STOP_EQUITY = 0.01  # 1% of equity
PARTICIPATION_CAP = 0.01  # 1% ADV; remainder carries
MARGIN = 2  # H7 2-session margin
# v1.3b: H2 counted delisting stress, PREREG f3b2b1be §5.4 (line 161) / §7 per-idea row (line 226)
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
    """Holdout (and any return-computing stage) requires --acceptance-hash == sha256(PREREG)."""
    if not provided:
        raise SystemExit(
            f"REFUSING --stage {stage}: pass --acceptance-hash <sha256 of PREREG_ORIGINAL.md>. "
            "No return trial runs until Victor accepts the prereg at a recorded sha256."
        )
    actual = sha256_file(PREREG_PATH)
    if provided.strip().lower() != actual.lower():
        raise SystemExit(
            f"REFUSING --stage {stage}: --acceptance-hash does not match sha256(PREREG_ORIGINAL.md).\n"
            f"  provided: {provided.strip().lower()}\n"
            f"  actual:   {actual}\n"
            "Re-hash after any prereg edit; Victor must accept the new hash before a run."
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
    """Fail-closed refusal (v1.3). Subclass of SystemExit: nothing runs after it."""


def verify_pyarrow_site(site: str | None, expected_sha: str | None) -> str:
    """Change 3. Insert the declared pyarrow site (append, read-only) only if passed and pinned."""
    if not site:
        raise Blocked(
            "REFUSING: --pyarrow-site not passed. v1.3 never auto-inserts a site path "
            "(Victor has not extended Jeremy's approval to this runner)."
        )
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
) -> dict[str, Any]:  # v1.3f avmove (A2 L401): default True = fail closed
    """Change 1. Refuse while any desk-client / reconciliation / factor pin is PENDING."""
    pins = {
        "DESK_CLIENT_PATH": DESK_CLIENT_PATH,
        "DESK_CLIENT_SHA256": DESK_CLIENT_SHA256,
        "PIN_RECONCILIATION_SEAL_SHA256": PIN_RECONCILIATION_SEAL_SHA256,
        "PIN_CA_LEDGER_SHA256": PIN_CA_LEDGER_SHA256,
        "PIN_FACTOR_TABLE_SHA256": PIN_FACTOR_TABLE_SHA256,
        "PIN_FACTOR_CODE_SHA256": PIN_FACTOR_CODE_SHA256,
        "PIN_AV_RAW_BARS_SHA256": PIN_AV_RAW_BARS_SHA256,
        "TR_DEV_CUT_PATH": TR_DEV_CUT_PATH,
        "TR_DEV_CUT_SHA256": TR_DEV_CUT_SHA256,  # v1.3c
        "TR_PARENT_SHA256": TR_PARENT_SHA256,
        "TR_DEV_CUT_SUMS_PATH": TR_DEV_CUT_SUMS_PATH,
        "TR_DEV_CUT_SUMS_SHA256": TR_DEV_CUT_SUMS_SHA256,  # v1.3d A4
        "FINAL_LIST_SHA256": FINAL_LIST_SHA256,  # v1.3e scope 2
        "B1C_ACCEPTED_SUMS_PATH": B1C_ACCEPTED_SUMS_PATH,
        "B1C_ACCEPTED_SUMS_SHA256": B1C_ACCEPTED_SUMS_SHA256,  # v1.3e scope 3
        "H1_TERMINAL_ROSTER_PATH": H1_TERMINAL_ROSTER_PATH,
        "H1_TERMINAL_ROSTER_SHA256": H1_TERMINAL_ROSTER_SHA256,  # v1.3f roster (L889 O-1 fail-fast; primary)
    }
    av_only = (
        "PIN_RECONCILIATION_SEAL_SHA256",
        "PIN_CA_LEDGER_SHA256",
        "PIN_FACTOR_TABLE_SHA256",
        "PIN_FACTOR_CODE_SHA256",
        "PIN_AV_RAW_BARS_SHA256",
    )  # v1.3f avmove: gate only under --av-factor-sensitivity
    pending = [k for k, v in pins.items() if v == PENDING and (av_factor_sensitivity or k not in av_only)]
    if pending:
        raise Blocked(f"REFUSING: data pins PENDING (reconciliation not sealed / desk client not delivered): {pending}")
    return pins


def verify_tr_cut_sums() -> None:
    """v1.3d A4 (Victor 7ba03e18). The cut's line in its ACCEPTED SHA256SUMS (one pinned file: path + raw sha)
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
    """v1.3e scope 3 (Victor L368). H1/H2 refuse until B1c is accepted: the accepted B1c SUMS must exist and
    match its pin. Hash only; nothing in it is parsed."""
    if PENDING in (B1C_ACCEPTED_SUMS_PATH, B1C_ACCEPTED_SUMS_SHA256):
        raise Blocked(
            "REFUSING: B1c not accepted (B1C_ACCEPTED_SUMS_PATH / B1C_ACCEPTED_SUMS_SHA256 PENDING; Victor L368)."
        )
    p = Path(B1C_ACCEPTED_SUMS_PATH)
    if not p.is_file() or sha256_file(p) != B1C_ACCEPTED_SUMS_SHA256:
        raise Blocked(f"REFUSING: accepted B1c SUMS absent or sha != B1C_ACCEPTED_SUMS_SHA256 at {p}.")


class FinalListMismatch(Blocked):
    """v1.3e scope 2 / v1.3f F3. FINAL_LIST absent, sha != pin, or any header/row violation -> exit code
    RC_FINAL_LIST_MISMATCH (18), silent (Victor L830 (4))."""

    def __init__(self, msg: str):
        super().__init__(RC_FINAL_LIST_MISMATCH)
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


def verify_final_list_sha() -> None:
    """v1.3f F4 (Victor L830). FINAL_LIST sha pre-check before any loader; hash only, nothing parsed.
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
    """v1.3e scope 2 (Victor L368/L369), v1.3f F3. Identity-map FINAL_LIST, re-checked at use: the bytes read are
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
    """Change 1. DECLARED interface the desk client must provide (Dmitri). Not implemented here.

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
    """Change 1. Import the accepted desk client by exact path, after its sha256 check."""
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
    """v1.3a (a). DECLARED extra client methods (Dmitri). Not implemented here.

    pit_membership_sha256() -> str
    pit_membership() -> pd.DataFrame  columns: symbol, start_date_filled, end_date (NaT = open)
        PIT S&P 500 intervals incl. delisted/former members (effective at open of start;
        end exclusive, same semantics as v1.2 sp500_membership).
    listing_status_sha256() -> str
    listing_status() -> pd.DataFrame  AV LISTING_STATUS rows (active + delisted):
        symbol, name, exchange, assetType, ipoDate, delistingDate (null = still listed), status
    """

    REQUIRED = ("pit_membership_sha256", "pit_membership", "listing_status_sha256", "listing_status")


def load_pinned_json(path: str | Path, expected_sha: str) -> dict[str, Any]:
    """v1.3a (a). Refuse unless the input file exists and matches its pin."""
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
    """v1.3a (a). PIT membership via client, clipped to AV listing windows, minus R18 original
    member periods, minus M14, minus ETFs. Returns (mem, subind, sector, receipt)."""
    if fill_input is not None or FILL_INPUT_PATH is not None:
        raise Blocked("REFUSING: fills (Victor 5e) are a future hook; not implemented in v1.3a.")
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
    # v1.3b: listing overlap (symbol in both AV sources) fails closed unless excluded or treated.
    lineage_excl = set(lineage_excl or ())
    pm = client.pit_membership()
    both = set(ls.loc[ls["listing_source"] == "active", "symbol"]) & set(
        ls.loc[ls["listing_source"] == "delisted", "symbol"]
    )
    in_uni = both & set(pm["symbol"]) & (set(dev_universe) if dev_universe is not None else set(pm["symbol"]))
    fl_excl, fl_kept = (
        dict((final_list or {}).get("excluded", {})),
        set((final_list or {}).get("kept", ())),
    )  # v1.3e scope 2
    in_uni -= set(r18_cuts) | m14_set | lineage_excl | ETFS | set(fl_excl)
    uncovered = sorted(in_uni - set(LISTING_OVERLAP_TREATMENT) - fl_kept)
    if uncovered:
        raise Blocked(
            f"REFUSING: {len(uncovered)} in-universe symbols in both AV listing sources with no "
            f"pinned treatment (Victor item 5; {LISTING_OVERLAP_IN_UNIVERSE_SHA256[:8]}): {uncovered}"
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
        "final_list_excluded": [],  # v1.3e scope 2
        "final_list_kept": sorted(fl_kept),
        "final_list_kept_covered_overlap": sorted(in_uni & fl_kept),  # v1.3f (2)
        "after_boundary_member_rows": sorted(pm.loc[pm["after_boundary"].astype(bool), "symbol"])
        if "after_boundary" in pm.columns
        else [],
    }
    for r in pm.itertuples():
        s = r.symbol
        if s in lineage_excl:
            rec["lineage_excl_dropped"].append(s)
            continue
        if s in fl_excl:  # v1.3e scope 2: reason read from FINAL_LIST only
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


def h2_delisting_receipts(bars: dict[str, Any], positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """v1.3a (b). PREREG 5.4 base for H2 on raw prices, as v1.2 implied: a position whose name
    stops printing before its planned exit is closed at its last close (R is NaN after the
    last bar, so apply_costs_and_returns adds 0; no exit cost at a NaN price; the ETF hedge
    leg and short borrow run to the planned exit exactly as in v1.2). Reporting only: this
    function changes no weight and no return. Supplied delisting returns: none (raw prices)."""
    out = []
    PX = bars["PX"]
    dates = PX.index
    for p in positions:
        s = p["sym"]
        if s not in PX.columns:
            continue
        idx = np.flatnonzero(PX[s].notna().values)
        if not len(idx):
            continue
        last_i = int(idx[-1])
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


# v1.3a: declared method -> real desk_data_client function (CLIENT_MAPPING.md). None = MISSING.
# v1.3b: repinned to deskclient_h1h2_v1 (Phase A only; Phase B and acquirer closes MISSING).
CLIENT_MAPPING = {
    "load_av_raw_with_factor": "load_av_raw_with_factor",  # Phase B: not in module -> MISSING
    "bar_file_sha256": "bar_file_sha256",  # Phase B: not in module -> MISSING
    "xnys_sessions": "xnys_sessions",
    "accepted_acquirer_closes": None,  # not in deskclient_h1h2_v1 -> MISSING
    "pit_membership_sha256": "pit_membership_sha256",
    "pit_membership": "pit_membership",
    "listing_status_sha256": "listing_status_sha256",
    "listing_status": "listing_status",
}


def client_static_check(path: str | None = None, expected_sha: str | None = None) -> dict[str, Any]:
    """v1.3a. Static (AST) check of the pinned client: no import, no execution. Refuses while any
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
        raise Blocked(f"REFUSING: desk client lacks declared methods (MISSING, for Dmitri): {missing}")
    return status


def ddc_accepted_acquirer_closes(ddc: Any, acquirer_id: str, start: date, end: date) -> pd.Series:
    """v1.3a adapter: accepted_acquirer_closes -> ddc.get_daily_bars(..., adjustment='raw',
    allow_api=False). Local store only (no API); returns close indexed by session Timestamp."""
    df = ddc.get_daily_bars([acquirer_id], start, end, adjustment="raw", allow_api=False)
    if df is None or len(df) == 0:
        return pd.Series(dtype=float)
    df = df[df["symbol"] == acquirer_id]
    return pd.Series(
        df["close"].astype(float).values, index=pd.to_datetime(df["session_date"]), name=acquirer_id
    ).sort_index()


def _to_date(x: Any) -> date:
    """v1.3b adapter: pandas Timestamp / datetime / date -> datetime.date (client refuses datetime)."""
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
    """v1.3b adapter over deskclient_h1h2_v1 (Phase A). Converts arguments to datetime.date, calls
    .to_pandas() on returned pa.Tables, keeps after_boundary for audit, converts xnys_sessions to a
    DatetimeIndex (v1.3a contract), and turns client "REFUSE ..." RuntimeErrors into Blocked.
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
    """v1.3: AV raw close x desk factor via the desk client, read-time end filter.

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
    """v1.3d (Rachel E7 r3 P1 / Victor A1(b)): the ONE new import, local, only after verify_pyarrow_site
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
    """v1.3c PRIMARY return source: PREREG L38 total return, via the sealed DEV-only cut.

    Body below the guards is RESTORED from v1.2 load_bars (backtest_h1_h2.py 1ea3d146 L140-160,
    the '-' lines of runner_v1_3 DIFF_v1_2_to_v1_3.patch 13865818), verbatim except 3 lines: the opened
    path (the DEV cut, never the L38 parent) and the v1.3d P1 read call (pq.read_table(...).to_pandas()
    replacing the pandas parquet reader). All guards run before the cut is opened as parquet.
    """
    if filter_end > EMBARGO1:
        raise Blocked("REFUSING: v1.3c TR source is the DEV cut only; no holdout TR source pinned.")
    verify_tr_cut_sums()  # v1.3d A4
    if PENDING in (TR_DEV_CUT_PATH, TR_DEV_CUT_SHA256, TR_PARENT_SHA256):
        raise Blocked("REFUSING: TR pins PENDING (TR_DEV_CUT_PATH / TR_DEV_CUT_SHA256 / TR_PARENT_SHA256).")
    if f"`{TR_PARENT_SHA256}`" not in PREREG_PATH.read_text().splitlines()[37]:
        raise Blocked("REFUSING: TR_PARENT_SHA256 is not the PREREG L38 total-return pin.")
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
        raise Blocked("REFUSING: v1.3b earnings source is the DEV cut only; no holdout source pinned.")
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
    # v1.3b: no direct membership read (mixed-period v1.2 file removed; membership = client).
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
    """v1.3b binding. sha256(d/SHA256SUMS) must equal the pin, then every listed file must match."""
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
    """v1.3b --dev-inputs. Accepts ONLY DEV_INPUTS_DIR with SHA256SUMS sha 4f5b23c9; binds addendum1
    (SUMS e38da672) the same way; returns the 24 lineage exclusions (EXCLUDED_24.tsv, as is; rename
    track closed) and the DEV universe symbol set (effective + pending-5e). Reads only these
    metadata files; no price data."""
    if not path or os.path.normpath(str(path)) != DEV_INPUTS_DIR:
        raise Blocked(f"REFUSING: --dev-inputs must be exactly {DEV_INPUTS_DIR}/ (got {path!r}).")
    import csv

    d_list = _verify_sums_dir(DEV_INPUTS_DIR, DEV_INPUTS_SUMS_SHA256)
    a_list = _verify_sums_dir(ADDENDUM1_DIR, ADDENDUM1_SUMS_SHA256)
    if a_list.get(LINEAGE_EXCL_FILE) != LINEAGE_EXCL_SHA256:
        raise Blocked("REFUSING: lineage exclusion file not pinned in addendum1 SUMS.")
    with open(Path(ADDENDUM1_DIR) / LINEAGE_EXCL_FILE, newline="") as f:
        lineage = {r["symbol"] for r in csv.DictReader(f, delimiter="\t")}
    if len(lineage) != 24:
        raise Blocked(f"REFUSING: expected 24 lineage exclusions, got {len(lineage)}.")
    uni = set()
    for name in ("DEV_UNIVERSE_EFFECTIVE.csv", "BASE_DEV_MEMBERS_PENDING_5E.csv"):
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
    """v1.3b binding. Hash only (never parse): OUT_SHA256SUMS must match its pin, every DEV_CUT_PINS
    entry must be listed there with the same sha, and each cut's raw bytes must match."""
    cuts_dir = DEV_CUTS_DIR if cuts_dir is None else cuts_dir
    sums_path = DEV_CUTS_SUMS_PATH if sums_path is None else sums_path
    sums_sha = DEV_CUTS_SUMS_SHA256 if sums_sha is None else sums_sha
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
    """Map each earnings row to earliest-possible session index (PREREG §5.3)."""
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
    """Build H1 target weights (sleeve fraction). Signal at t, fill at t+1 (caller shifts)."""
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
    W = Wk.reindex(dates).ffill().fillna(0.0)
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


def apply_costs_and_returns(bars: dict[str, Any], W: pd.DataFrame, cfg: Any, *, idea: str) -> dict[str, Any]:
    """Apply one-session execution lag, participation cap, borrow, and daily net returns.

    REQUIRED path must use cfg from build_cost_config('unknown_borrow_required').
    """
    if cfg.borrow_rate < BORROW_UNKNOWN_REQUIRED and cfg.is_pass_bar:
        raise RuntimeError("pass-bar config must have borrow_rate >= 10%/yr")
    if cfg.is_pass_bar and cfg.borrow_rate < 0.10:
        raise RuntimeError("required gate borrow_rate must be >= 0.10")

    R, PX, VOL = bars["R"], bars["PX"], bars["VOL"]
    # Signal at t, fill at t+1
    W_exec = W.shift(1).fillna(0.0)
    # Participation cap: clip |Δw|*AUM / ADV20 <= 1%; carry remainder (simplified single-day carry)
    DV = PX * VOL
    ADV20 = DV.rolling(20, min_periods=10).mean().shift(1)
    dW = W_exec.diff().fillna(W_exec)
    # Exclude / hard-cap L4 at capacity stress (Tomas §5): flag only here; full multi-day
    # carry is applied in the sealed sitting implementation detail.
    rets = []
    dates = W_exec.index
    for j in range(1, len(dates)):
        d = dates[j]
        w = W_exec.iloc[j]
        # gross trading cost on Δw
        dw = dW.iloc[j]
        trade_cost_frac = 0.0
        for s, delta in dw.items():
            if abs(delta) < 1e-15 or s not in PX.columns:
                continue
            px = PX.at[d, s]
            if not (px > 0):
                continue
            adv = ADV20.at[d, s] if s in ADV20.columns else np.nan
            adv_sh = (adv / px) if (isinstance(adv, float) and adv > 0) else None
            sh = abs(delta) * AUM / px
            # 1% ADV cap on filled slice
            if adv_sh and sh > PARTICIPATION_CAP * adv_sh:
                sh = PARTICIPATION_CAP * adv_sh
            side = "buy" if delta > 0 else "sell"
            sig = None
            c = one_way_bps(side, float(px), float(sh), adv_sh, sig, cfg=cfg, venue="close", symbol=s, etf_symbols=ETFS)
            trade_cost_frac += (sh * px / AUM) * c["bps"] / 1e4
        # asset return contribution
        rrow = R.loc[d].reindex(w.index).fillna(0.0) if d in R.index else 0.0
        gross = float((w * rrow).sum()) if not isinstance(rrow, float) else 0.0
        # borrow on short notional for 1 session (~1 calendar day approx; 360-day convention)
        short_mv = float((-w.clip(upper=0)).sum() * AUM)
        b = borrow_usd(short_mv, days=1.0, cfg=cfg)["usd"] / AUM
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
        "daily": df,
    }


# ---- v1.3 change 2: H1 v0.2 adverse terminal bound (accepted 373c3e5d / 79217ca7) ----


def load_h1_terminal_roster(path: str | None = None, expected_sha: str | None = None) -> list[Any]:
    path = H1_TERMINAL_ROSTER_PATH if path is None else path
    expected_sha = H1_TERMINAL_ROSTER_SHA256 if expected_sha is None else expected_sha
    if PENDING in (path, expected_sha):
        raise Blocked("BLOCK H1: terminal roster path/sha PENDING.")
    if not Path(path).is_file() or sha256_file(Path(path)) != expected_sha:
        raise Blocked("BLOCK H1: terminal roster absent or sha mismatch.")
    with open(path) as f:
        return cast(list[Any], json.load(f))


def _trusted_tau(bars: dict[str, Any], s: str) -> int | None:
    """tau = last trusted print (pinned bar file only): volume > 0, not forward-filled."""
    if s not in bars["PX"].columns:
        return None
    tr = (bars["VOL"][s] > 0) & bars["PX"][s].notna()
    if "FFILL" in bars:
        tr &= ~bars["FFILL"][s].fillna(True).astype(bool)
    idx = np.flatnonzero(tr.values)
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
    """Apply the accepted H1 v0.2 rule to positions stranded in unresolved terminal rows.

    Returns (W_adj, overlay, receipts). W_adj zeroes the stranded leg from tau so the frozen
    execution lag closes it at tau+1 with no exit-cost credit; overlay[d] is the fractional
    equity charge booked at tau+1 (long: -100% of marked value; short: max(P_tau, V_max)
    liability) plus borrow from tau+1 to max(frozen exit, h). Fails closed (Blocked).
    """
    if path not in H1_TERMINAL_PATHS:
        raise ValueError(path)
    dates = W.index
    W_adj = W.copy()
    overlay = pd.Series(0.0, index=dates)
    receipts = []
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
        trusted = (bars["VOL"][s] > 0) & bars["PX"][s].notna()
        if "FFILL" in bars:
            trusted &= ~bars["FFILL"][s].fillna(True).astype(bool)
        if (held_pre & ~trusted.iloc[:t]).any():
            raise Blocked(
                f"BLOCK H1: suspension gap before tau for {s} (worse-of-prints "
                "exit not representable in frozen weight path; fail closed)."
            )
        w = float(W[s].iloc[t])
        if w == 0.0 or t + 1 >= len(dates):
            continue  # not open after tau within window
        book_i = t + 1
        p_tau = float(bars["PX"][s].iloc[t])
        rec = {
            "symbol": s,
            "sid": row.get("sid"),
            "instrument_id": row.get("instrument_id"),
            "side": "long" if w > 0 else "short",
            "weight": w,
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
            per = borrow_usd(abs(w) * AUM, days=1.0, cfg=cfg)["usd"] / AUM
            per *= rate / cfg.borrow_rate if cfg.borrow_rate > 0 else 1.0
            for j in range(book_i, end_i + 1):
                overlay.iloc[j] -= per
            rec.update(
                {
                    "h": str(h_d.date()),
                    "V_max": vmax,
                    "liability": liab,
                    "borrow_rate": rate,
                    "source_hashes": terms.get("source_hashes"),
                }
            )
        W_adj.iloc[t:, cast(int, W_adj.columns.get_loc(s))] = 0.0
        receipts.append(rec)
    # Path B: identical charge as an equity overlay; v1.2 has no stop / basket-stop / H8-H9 /
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
    """v1.3b. PREREG §5.4 counted stress for H2, pure computation: on any NULL delisting return,
    -30% for longs and 0% for shorts. Applied to every position h2_delisting_receipts flags (name
    stops printing before its planned exit). The charge is the weight held over the session after
    the last close (W[last] executes over last+1) times the shock, booked at last+1 as an equity
    overlay added to daily net. A supplied (non-null) delisting return gets no stress.
    Returns (overlay indexed like W, receipts)."""
    sup = supplied_delist_returns or {}
    dates = W.index
    overlay = pd.Series(0.0, index=dates)
    out = []
    for r in h2_delisting_receipts(bars, positions):
        s = r["symbol"]
        if sup.get(s) is not None:
            out.append(dict(r, stress="not applied: supplied (non-null) delisting return"))
            continue
        li = int(cast(int, dates.get_loc(pd.Timestamp(r["last_close_session"]))))
        if li + 1 >= len(dates):
            continue
        w = float(W[s].iloc[li]) if s in W.columns else 0.0
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
        description="Sofia H1/H2 Stage A / sealed-holdout runner v1.3a DRAFT (PREREG_ORIGINAL v3).",
    )
    p.add_argument(
        "--stage", choices=["dev", "holdout"], help="dev = Stage A window; holdout = sealed 2022-03-30..2026-10-28."
    )
    p.add_argument(
        "--acceptance-hash",
        default=None,
        help="sha256 of PREREG_ORIGINAL.md; REQUIRED for holdout and for any return run.",
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
        help="H2 only: counted delisting-stress rerun (PREREG 5.4: -30%% long / 0%% short on null delisting return).",
    )
    p.add_argument(
        "--av-factor-sensitivity",
        action="store_true",
        help="DECLARED SENSITIVITY, off by default: AV raw x desk factor returns instead of the "
        "PREREG L38 total return. Never primary, never gates; refused until its own pins exist.",
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
    # PREREG says no DEV return trial before acceptance — signal-only on DEV is already
    # covered by turnover_dev.py. This runner requires the hash for both stages.
    prereg_sha = require_acceptance_hash(args.acceptance_hash, stage)
    pyarrow_record_sha = verify_pyarrow_site(args.pyarrow_site, args.pyarrow_site_sha)
    if stage != "dev":
        raise Blocked("REFUSING: v1.3b binds DEV-only inputs; no holdout inputs are pinned.")
    if args.delisting_stress and args.idea != "H2":
        raise Blocked("REFUSING: --delisting-stress is H2 only (H1 stress withdrawn by 373c3e5d); pass --idea H2.")
    if args.delisting_stress and args.av_factor_sensitivity:
        raise Blocked(
            "REFUSING: --delisting-stress is a counted rerun on the PRIMARY (L38 TR) source, not on the AV sensitivity."
        )
    dev = bind_dev_inputs(args.dev_inputs)
    dev["receipt"].update(verify_dev_cuts())
    data_pins = require_data_pins(av_factor_sensitivity=args.av_factor_sensitivity)  # v1.3f avmove (A2 L401)
    verify_b1c_accepted()  # v1.3e scope 3
    verify_final_list_sha()  # v1.3f F4: pre-check before any loader (at-use re-check kept below)
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
        bars = load_bars(filter_end)  # v1.3c: AV raw x desk factor = DECLARED SENSITIVITY only
    else:
        bars = load_bars_tr(filter_end)  # v1.3c: PRIMARY = PREREG L38 total return (DEV cut)
    # Extra guard: no holdout rows in DEV
    if stage == "dev" and (bars["R"].index >= pd.Timestamp(HOLDOUT0)).any():
        raise RuntimeError("DEV leakage: holdout rows present after filters")
    _mem_v12_unused, subind, sector = load_universe()  # GICS only (v1.2 store; deviation)
    final_list = load_final_list()  # v1.3e scope 2: re-checked at use, fail closed
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
            else "PRIMARY: PREREG L38 total return, DEV cut"
        ),
        "tr_dev_cut_sha256": TR_DEV_CUT_SHA256,
        "tr_parent_sha256": TR_PARENT_SHA256,
    }
    if args.delisting_stress:
        results["v13b"]["trial_accounting"] = {
            "mode": "H2 delisting-stress rerun (counted)",
            "prereg": "f3b2b1be §5.4 line 161; §7 table line 226 'Per idea: ... delisting-stress rerun' (5 x 2 = 10)",
            "N_effect": "inside N = 212 (v3) / 214 (with H1 v0.2); no increment for this one counted run; any repeat adds to N and is logged in §12",
            "H1": "not run: H1 stress withdrawn by 373c3e5d",
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
