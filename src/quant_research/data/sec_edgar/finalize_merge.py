"""Merge extractor checkpoint + worker shards (de-duplicated on accession, keep the latest-written record),
attach ex-post QA period label + XBRL validation, and report coverage of the v1.3 spine. No returns.
Run ONLY after all extraction workers have exited (shard parquet writes are not atomic)."""
import json, sys, subprocess
import pandas as pd
from quant_research.data.sec_edgar import common; from quant_research.data.sec_edgar import eps8k_extract as X; from quant_research.data.sec_edgar import run_extract_full as R

OUT = common.OUT
ev = R.load_events()
parts = []
for p in [OUT / "eps8k_full.checkpoint.parquet"] + sorted(OUT.glob("eps8k_shard_*.parquet")):
    d = pd.read_parquet(p); d["_part"] = p.name; parts.append(d)
df = pd.concat(parts, ignore_index=True)
n_raw = len(df)
df = df.drop_duplicates("accession", keep="last")
missing = sorted(set(ev.accession) - set(df.accession))
extra = sorted(set(df.accession) - set(ev.accession))
allow_partial = "--partial" in sys.argv
if missing and not allow_partial:
    raise SystemExit(f"{len(missing)} spine accessions not yet extracted; refusing to finalize")
df = df[df.accession.isin(ev.accession)]
# authoritative event fields from the v1.3 spine (by accession)
keep = ["accession", "reaction_session", "is_preannouncement", "event_type", "ex99_rule", "ex99_type"]
df = df.drop(columns=[c for c in keep[1:] if c in df.columns]).merge(ev[keep], on="accession", how="left")
xq = pd.read_parquet(OUT / "xbrl_eps_quarterly.parquet")
df = X.assign_fiscal_period(df, xq)            # ex-post label: QA ONLY (renamed in sue_build)
v = X.validate(df, xq)
v.to_parquet(OUT / "eps8k_full_with_validation.parquet", index=False)
log = {"spine_events": int(len(ev)), "raw_rows": n_raw, "merged_rows": int(len(v)), "missing_from_spine": len(missing),
       "extra_not_in_spine": len(extra), "parts": {p: int(n) for p, n in v._part.value_counts().items()},
       "top_errors": int(v.parse_notes.fillna("").str.startswith("top_error").sum()),
       "eps_basis": v.eps_basis.value_counts(dropna=False).to_dict(), "partial": allow_partial}
json.dump(log, open(OUT / "eps8k_merge.log.json", "w"), indent=1, default=str)
print(json.dumps(log, indent=1, default=str))
