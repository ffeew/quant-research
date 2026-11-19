"""Regenerate rich old_to_new_reconciliation (v2 pinned schema) into --output-dir.
Does not modify the reviewed v2 parquet. Use --check-reproduction to compare to pinned artefacts.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

V1_HASH = "d568a60d19348ad2948083df6a95f64e501f25615d773cdac14ebd9629216d2e"
OLD_HASH = "d07358318c6b0016afa9b5e3d885b1ce508bdd5af83328e692bcba2653a9fe5f"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.join(ROOT, "v2")


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def build_recon(v2: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    member_to_kept = {}
    for acc, ca in zip(v2.accession, v2.cluster_accessions):
        for a in str(ca).split(";"):
            if a:
                member_to_kept[a] = acc
    cluster_members = set(member_to_kept)
    v1_acc = set(v2.accession)
    old_g = old.groupby("accession").agg(
        old_ciks=("cik", lambda s: sorted({int(x) for x in s})),
        old_symbols=("symbol", lambda s: sorted(set(s))),
        old_sec_name=("sec_name", "first"),
        old_acceptance_utc=("acceptance_datetime_utc", "first"),
        n_old_rows=("cik", "size"),
    )
    v2i = v2.set_index("accession")
    recs = []
    for raw_a, r in old_g.iterrows():
        a = cast(str, raw_a)
        if a in v1_acc:
            v = v2i.loc[a]
            vc = int(cast(int, v.cik))
            _comps = [int(x) for x in str(v.cik_components).split(",") if x]
            if vc not in r.old_ciks:
                status = "dual_cik_alias_other_canonical"
                reason = f"old_ciks={r.old_ciks} old_symbols={r.old_symbols}; v2 canonical={vc} components={v.cik_components}"
            elif len(r.old_ciks) > 1 or int(cast(int, v.n_component_ciks)) > 1:
                status = "dual_cik_components_preserved"
                reason = f"old_ciks={r.old_ciks} old_symbols={r.old_symbols}; v2 canonical={vc} components={v.cik_components}"
            else:
                status, reason = "kept_exact", "accession present with same CIK"
            recs.append(
                dict(
                    old_accession=a,
                    old_ciks=",".join(map(str, r.old_ciks)),
                    old_symbols=",".join(r.old_symbols),
                    old_sec_name=r.old_sec_name,
                    n_old_rows=int(r.n_old_rows),
                    new_accession=a,
                    new_cik=vc,
                    new_cik_components=v.cik_components,
                    status=status,
                    reason=reason,
                    old_acceptance_utc=r.old_acceptance_utc,
                    new_acceptance_utc=v.acceptance_utc,
                )
            )
        elif a in cluster_members:
            kept = member_to_kept[a]
            v = v2i.loc[kept]
            recs.append(
                dict(
                    old_accession=a,
                    old_ciks=",".join(map(str, r.old_ciks)),
                    old_symbols=",".join(r.old_symbols),
                    old_sec_name=r.old_sec_name,
                    n_old_rows=int(r.n_old_rows),
                    new_accession=kept,
                    new_cik=int(v.cik),
                    new_cik_components=v.cik_components,
                    status="cluster_member",
                    reason=f"absorbed into cluster kept accession {kept}",
                    old_acceptance_utc=r.old_acceptance_utc,
                    new_acceptance_utc=v.acceptance_utc,
                )
            )
        elif 1675149 in r.old_ciks:
            recs.append(
                dict(
                    old_accession=a,
                    old_ciks=",".join(map(str, r.old_ciks)),
                    old_symbols=",".join(r.old_symbols),
                    old_sec_name=r.old_sec_name,
                    n_old_rows=int(r.n_old_rows),
                    new_accession=None,
                    new_cik=None,
                    new_cik_components=None,
                    status="excluded_outside_membership_aa_post_split",
                    reason="Alcoa Corp post-split; AA membership ended 2016-11-01",
                    old_acceptance_utc=r.old_acceptance_utc,
                    new_acceptance_utc=None,
                )
            )
        elif 1578318 in r.old_ciks:
            recs.append(
                dict(
                    old_accession=a,
                    old_ciks=",".join(map(str, r.old_ciks)),
                    old_symbols=",".join(r.old_symbols),
                    old_sec_name=r.old_sec_name,
                    n_old_rows=int(r.n_old_rows),
                    new_accession=None,
                    new_cik=None,
                    new_cik_components=None,
                    status="excluded_before_membership_evhc_holdings",
                    reason="Envision Healthcare Holdings filings before EVHC membership start 2016-12-02",
                    old_acceptance_utc=r.old_acceptance_utc,
                    new_acceptance_utc=None,
                )
            )
        else:
            raise RuntimeError(f"unresolved {a}")
    return pd.DataFrame(recs)


def df_equal(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, str]:
    if list(a.columns) != list(b.columns):
        return False, f"columns differ: {list(a.columns)} vs {list(b.columns)}"
    if len(a) != len(b):
        return False, f"len {len(a)} vs {len(b)}"
    a2 = a.sort_values("old_accession").reset_index(drop=True)
    b2 = b.sort_values("old_accession").reset_index(drop=True)
    # normalize timestamps to UTC ns for compare
    for c in a2.columns:
        if pd.api.types.is_datetime64_any_dtype(a2[c]) or pd.api.types.is_datetime64_any_dtype(b2[c]):
            a2[c] = pd.to_datetime(a2[c], utc=True)
            b2[c] = pd.to_datetime(b2[c], utc=True)
        a2[c] = a2[c].astype(object).where(a2[c].notna(), None)
        b2[c] = b2[c].astype(object).where(b2[c].notna(), None)
        # stringify for stable equality of mixed nulls
        av = a2[c].map(lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x))
        bv = b2[c].map(lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else str(x))
        if not av.equals(bv):
            bad = (av != bv).sum()
            return False, f"col {c} mismatches {bad}"
    return True, "dataframe_equality_ok"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", required=True)
    ap.add_argument(
        "--check-reproduction",
        action="store_true",
        help="compare regenerated recon to pinned v2/old_to_new_reconciliation.parquet",
    )
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    assert sha(os.path.join(ROOT, "earnings_events_8k202.parquet")) == V1_HASH
    assert sha(os.path.join(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet")) == OLD_HASH
    v2 = pd.read_parquet(os.path.join(V2, "earnings_events_8k202_v2.parquet"))
    old = pd.read_parquet(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet")
    recon = build_recon(v2, old)
    out_pq = os.path.join(args.output_dir, "old_to_new_reconciliation.parquet")
    out_csv = os.path.join(args.output_dir, "old_to_new_reconciliation.csv")
    recon.to_parquet(out_pq, index=False)
    recon.to_csv(out_csv, index=False)
    print("wrote", out_pq, "rows", len(recon))
    print(recon.status.value_counts().to_string())
    if args.check_reproduction:
        pinned = pd.read_parquet(os.path.join(V2, "old_to_new_reconciliation.parquet"))
        ok, msg = df_equal(recon, pinned)
        print("DATAFRAME_COMPARE:", msg)
        b1, b2 = sha(out_pq), sha(os.path.join(V2, "old_to_new_reconciliation.parquet"))
        print("PARQUET_BYTES:", "IDENTICAL" if b1 == b2 else f"DIFFER regenerated={b1} pinned={b2}")
        if b1 != b2:
            print("NOTE: parquet byte diffs may be pyarrow serialization; dataframe equality is the pin test.")
        if not ok:
            sys.exit(2)
        print("REPRODUCTION_OK")


if __name__ == "__main__":
    main()
