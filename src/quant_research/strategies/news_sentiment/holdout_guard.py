"""Hold-out guard for the Benzinga/Alpaca news archive (validation decisions 2026-10-30: interim #4 and final X1).

Rules enforced in code:
  * SECTOR-LM itself (news_signal.py / prereg_run.py) has its own lock: months < 2025-06 open only with
    NEWS_OOS_UNLOCK == sha256(PREREG_sector_lm_5d.md) == first token of PREREG_sector_lm_5d.sha256 (written at freeze).
  * EVERY OTHER design / card script (revision-breadth, spillover, hype-fade, any tone exploration) may not load
    archive articles mapping to sessions before 2025-06-02 until BOTH
      (a) PREREG_sector_lm_5d.sha256 exists and matches sha256(PREREG_sector_lm_5d.md), AND
      (b) the single gating sector-LM run is logged in PREREG_sector_lm_5d.RUNLOG.json carrying that same hash
          (written only by prereg_run.py on completion of the gating run),
    OR a joint unseal is declared in JOINT_UNSEAL.json listing the sha256 of all four frozen specs (each must match).
Call require_archive_access(first_session, who) before reading any raw/ or raw_alias/ month, and filter_months()
to drop locked months. Metadata-only audits (counts, timestamps; no text/tone/returns) may pass metadata_only=True.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence

import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

NS = f"{_QR.DESK_DIR}/equity/news_sentiment"
PREREG = f"{NS}/PREREG_sector_lm_5d.md"
PREREG_SHA = f"{NS}/PREREG_sector_lm_5d.sha256"
RUNLOG = f"{NS}/PREREG_sector_lm_5d.RUNLOG.json"
JOINT = f"{NS}/JOINT_UNSEAL.json"
SEEN_START = pd.Timestamp("2025-06-02")  # first session of the already-seen sample


class HoldoutLocked(RuntimeError):
    pass


def _sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def prereg_frozen() -> bool:
    return os.path.exists(PREREG_SHA) and open(PREREG_SHA).read().split()[0] == _sha(PREREG)


def sector_lm_run_logged() -> bool:
    if not (prereg_frozen() and os.path.exists(RUNLOG)):
        return False
    log = json.load(open(RUNLOG))
    return bool(log.get("prereg_sha256") == _sha(PREREG) and log.get("status") == "complete")


def joint_unseal() -> bool:
    if not os.path.exists(JOINT):
        return False
    j = json.load(open(JOINT))
    specs = j.get("specs", {})
    return len(specs) >= 4 and all(os.path.exists(p) and _sha(p) == h for p, h in specs.items())


def unlocked() -> bool:
    return sector_lm_run_logged() or joint_unseal()


def require_archive_access(first_session: str | pd.Timestamp, who: str, metadata_only: bool = False) -> bool:
    """Raise HoldoutLocked if `who` wants archive data before 2025-06-02 while the hold-out is sealed."""
    if metadata_only or pd.Timestamp(first_session) >= SEEN_START or unlocked():
        return True
    raise HoldoutLocked(
        f"{who}: archive sessions before {SEEN_START.date()} are sealed (sector-LM hold-out). "
        f"Requires frozen PREREG ({PREREG_SHA}) + logged gating run ({RUNLOG}), or {JOINT}. "
        f"Requested start {pd.Timestamp(first_session).date()}."
    )


def filter_months(months: Sequence[str], who: str) -> list[str]:
    """Drop YYYY-MM month keys whose sessions precede SEEN_START unless unlocked. Prints what it skipped."""
    if unlocked():
        return list(months)
    keep = [m for m in months if m >= SEEN_START.strftime("%Y-%m")]
    if len(keep) != len(months):
        print(
            f"HOLDOUT GUARD ({who}): skipping {len(months) - len(keep)} sealed months < {SEEN_START.strftime('%Y-%m')}",
            flush=True,
        )
    return keep


if __name__ == "__main__":
    print(dict(prereg_frozen=prereg_frozen(), sector_lm_run_logged=sector_lm_run_logged(), joint_unseal=joint_unseal()))
    for d in ("2016-01-05", "2021-01-04", "2025-06-02"):
        try:
            require_archive_access(d, "selftest")
            print(d, "allowed")
        except HoldoutLocked:
            print(d, "LOCKED")
