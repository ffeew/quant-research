"""Required v2 tests. Run from equity/earnings_events/: python v2/validate_v2.py"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import hashlib, os, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
V1="d568a60d19348ad2948083df6a95f64e501f25615d773cdac14ebd9629216d2e"
OLD="d07358318c6b0016afa9b5e3d885b1ce508bdd5af83328e692bcba2653a9fe5f"
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda: f.read(1<<20), b""): h.update(c)
    return h.hexdigest()
assert sha("earnings_events_8k202.parquet")==V1
assert sha(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet")==OLD
v1=pd.read_parquet("earnings_events_8k202.parquet")
v2=pd.read_parquet("v2/earnings_events_8k202_v2.parquet")
old=pd.read_parquet(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet")
recon=pd.read_parquet("v2/old_to_new_reconciliation.parquet")
keys=pd.read_parquet("v2/symbol_accession_key_reconciliation.parquet")
assert v2.accession.is_unique and len(v2)==len(v1)
assert set(v1.accession)==set(v2.accession)  # no deletes, no restores into table
m=v2.set_index("accession").acceptance_utc
assert (m==v1.set_index("accession").acceptance_utc).all()
assert recon.old_accession.is_unique and len(recon)==old.accession.nunique()
assert (recon.status=="unresolved_absent").sum()==0
assert (recon.status=="excluded_outside_membership_aa_post_split").sum()==44
assert (recon.status=="excluded_before_membership_evhc_holdings").sum()==5
assert (recon.status=="cluster_member").sum()==397
assert int((v2.cluster_availability_flag=="ex99_deferred_to_sibling").sum())==9
# 131 dual-cik join rows auditable
j=old.merge(v2[["accession","cik","cik_components"]], on="accession", how="inner", suffixes=("_old",""))
mm=j[j.cik_old!=j.cik]
assert len(mm)==131
assert mm.apply(lambda r: str(int(r.cik_old)) in str(r.cik_components).split(","), axis=1).all()
nonexact=keys[keys.category!="exact_symbol_accession_match"]
assert len(nonexact)==920
assert (keys.category=="unresolved_display_key").sum()==0
print("VALIDATE OK", sha("v2/earnings_events_8k202_v2.parquet"))
