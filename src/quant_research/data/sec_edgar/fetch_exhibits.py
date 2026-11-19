"""Fill missing EX-99.1 URLs for accessions not in Ethan's header cache.
Uses sec_http (cached, <=8 req/s). Resume-safe: rewrites out/exhibits.parquet periodically.
"""
import json, time
from pathlib import Path
import pandas as pd
from quant_research.data.sec_edgar import common; from quant_research.data.sec_edgar import eps8k_extract as X

OUT = common.OUT / "exhibits.parquet"
SRC = common.OUT / "exhibits_from_ethan_cache.parquet"

def main():
    ex = pd.read_parquet(SRC if not OUT.exists() else OUT)
    if "primary_doc_url" not in ex.columns and SRC.exists():
        base = pd.read_parquet(SRC)
        ex = ex.merge(base[["accession", "primary_doc_url"]], on="accession", how="left", suffixes=("", "_y"))
    miss = ex[ex.ex99_url.isna() | (ex.ex99_rule == "header_cache_miss")].copy()
    print(f"to_resolve={len(miss)} already_have={ex.ex99_url.notna().sum()}", flush=True)
    t0 = time.time()
    updates = {}
    for i, r in enumerate(miss.itertuples(index=False), 1):
        try:
            url, typ = X.find_ex99(r.cik, r.accession)
            if url:
                updates[r.accession] = dict(ex99_url=url, ex99_type=typ, ex99_filename=url.rsplit("/", 1)[-1],
                                            ex99_rule="index.htm via sec_http", exhibit_count=None)
            else:
                # fall back to primary doc as 8-K body
                pud = getattr(r, "primary_doc_url", None)
                updates[r.accession] = dict(ex99_url=pud if isinstance(pud, str) else None,
                                            ex99_type="8-K body (no EX-99)",
                                            ex99_filename=None,
                                            ex99_rule="no EX-99; primary_doc fallback",
                                            exhibit_count=0)
        except Exception as e:
            pud = getattr(r, "primary_doc_url", None)
            updates[r.accession] = dict(ex99_url=pud if isinstance(pud, str) else None,
                                        ex99_type="error",
                                        ex99_filename=None,
                                        ex99_rule=f"find_ex99 error: {type(e).__name__}: {e}"[:200],
                                        exhibit_count=None)
        if i % 200 == 0 or i == len(miss):
            for acc, d in updates.items():
                m = ex.accession == acc
                for k, v in d.items():
                    ex.loc[m, k] = v
            updates.clear()
            ex.to_parquet(OUT, index=False)
            print(f"{i}/{len(miss)} elapsed={time.time()-t0:.0f}s have_url={ex.ex99_url.notna().sum()}", flush=True)
    # final write if any leftover
    if updates:
        for acc, d in updates.items():
            m = ex.accession == acc
            for k, v in d.items():
                ex.loc[m, k] = v
    ex.to_parquet(OUT, index=False)
    log = {"n": len(ex), "has_ex99_url": int(ex.ex99_url.notna().sum()),
           "ex99_rule": ex.ex99_rule.value_counts().to_dict()}
    json.dump(log, open(common.OUT / "exhibits.log.json", "w"), indent=1)
    print(json.dumps(log, indent=1), flush=True)

if __name__ == "__main__":
    main()
