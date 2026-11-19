"""v2.1 validation. Run: python v2.1/validate_v2_1.py from equity/earnings_events/."""

from __future__ import annotations

import hashlib
import os

import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

# The v2 review document lives outside the repo; its location is a required input with no default.
REVIEW_DOC_ENV = "QR_V2_1_REVIEW_DOC"
REVIEW_DOC = _QR.required_env(REVIEW_DOC_ENV, "the path of the v2 review document pinned by VALIDATION_SHA")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
V1 = desk_pin("data.earnings_events.v2_1.validate_v2_1", "V1")
V2 = desk_pin("data.earnings_events.v2_1.validate_v2_1", "V2")
OLD = desk_pin("data.earnings_events.v2_1.validate_v2_1", "OLD")
VALIDATION_SHA = desk_pin("data.earnings_events.v2_1.validate_v2_1", "VALIDATION_SHA")
DATA_SHA = desk_pin("data.earnings_events.v2_1.validate_v2_1", "DATA_SHA")


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


assert sha("earnings_events_8k202.parquet") == V1
assert sha("v2/earnings_events_8k202_v2.parquet") == V2
assert sha("v2.1/earnings_events_8k202_v2.parquet") == V2
assert sha("v2/SHA256SUMS") == sha("v2.1/PARENT_V2_SHA256SUMS")
assert sha(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet") == OLD
assert sha(REVIEW_DOC) == VALIDATION_SHA
assert sha(f"{_QR.DATA_DIR}/derived/earnings_events_8k202_v1_reconciliation/DECISION.md") == DATA_SHA

v2 = pd.read_parquet("v2.1/earnings_events_8k202_v2.parquet")
ins = v2[v2.in_sp500]
assert int(ins.ex99_url.notna().sum()) == 24635
assert int(ins.ex99_url.isna().sum()) == 328
assert int((ins.cluster_availability_flag == "no_ex99_in_sp500").sum()) == 321
assert int((ins.cluster_availability_flag == "no_ex99_in_cluster").sum()) == 7
assert int(((v2.cluster_availability_flag == "ex99_deferred_to_sibling") & v2.in_sp500).sum()) == 7
assert int((v2.cluster_availability_flag == "ex99_deferred_to_sibling").sum()) == 9

# §6 chronology
d = v2[v2.ex99_available_utc.notna()]
assert (d.acceptance_utc <= d.ex99_available_utc).all()
defer = v2[v2.cluster_availability_flag == "ex99_deferred_to_sibling"]
assert (defer.acceptance_utc < defer.ex99_available_utc).all()

cm = pd.read_parquet("v2.1/audit/cluster_members_397_audit.parquet")
assert len(cm) == 397
assert int(cm.is_amendment_8ka.sum()) == 132
d9 = pd.read_parquet("v2.1/audit/deferred9_content_scan.parquet")
assert len(d9) == 18 and d9.fetch_status.isin(["fetched", "cache_hit"]).all()
post = pd.read_parquet("v2.1/audit/ethan_only_post2015_338_lineage.parquet")
assert len(post) == 338

# docs mention as-of
assert (
    "ex99_available_utc ≤ T" in open("v2.1/README_V2_1.md").read()
    or "ex99_available_utc" in open("v2.1/README_V2_1.md").read()
)
assert "PENDING" in open("v2.1/COVERAGE_V2_1.md").read()

print("VALIDATE_V2_1 OK")
print("coverage_status=PENDING_amendment_bodies_132")
print("event_parquet_sha", V2)
