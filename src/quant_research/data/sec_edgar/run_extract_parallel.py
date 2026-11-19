"""Parallel EX-99 extract: N workers, shard by hash(accession)%N, merge into checkpoint. Resume-safe."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.data.sec_edgar import common
from quant_research.data.sec_edgar import eps8k_extract as X

N = int(os.environ.get("EXTRACT_WORKERS", "4"))
WID = int(sys.argv[1])  # 0..N-1
CKPT = common.OUT / f"eps8k_shard_{WID}.parquet"
LOG = common.OUT / f"extract_shard_{WID}.log"


def load_events() -> pd.DataFrame:
    from quant_research.data.sec_edgar import run_extract_full as R

    return R.load_events()


def main() -> None:
    ev = load_events()
    # also merge already-done from main checkpoint + all shards
    done = set()
    for p in [common.OUT / "eps8k_full.checkpoint.parquet", *list(common.OUT.glob("eps8k_shard_*.parquet"))]:
        if p.exists():
            done |= set(pd.read_parquet(p, columns=["accession"]).accession)
    todo = ev[~ev.accession.isin(done)].copy()
    # ensure url
    if "url" in todo.columns:
        m = todo.ex99_url.isna()
        todo.loc[m, "ex99_url"] = todo.loc[m, "url"]
    todo = todo[todo.ex99_url.notna()]
    # shard
    h = todo.accession.map(lambda a: int(hashlib.md5(a.encode()).hexdigest(), 16) % N)
    todo = todo[h == WID].sort_values("acceptance_et")
    print(f"worker {WID}/{N} todo={len(todo)} already_global={len(done)}", flush=True)
    rows: list[dict[str, Any]] = []
    if CKPT.exists():
        prev = pd.read_parquet(CKPT)
        done_w = set(prev.accession)
        rows = cast(list[dict[str, Any]], prev.to_dict("records"))
        todo = todo[~todo.accession.isin(done_w)]
        print(f"worker {WID} resume local={len(done_w)} remaining={len(todo)}", flush=True)
    t0 = time.time()
    for i, r in enumerate(todo.to_dict("records"), 1):
        try:
            rec = X.extract_one(cast(dict[str, Any], r))
            for k in ("is_preannouncement", "event_type", "reaction_session", "ex99_rule"):
                rec[k] = r.get(k)
            rows.append(rec)
        except Exception as e:
            rows.append(
                dict(
                    accession=r["accession"],
                    cik=r["cik"],
                    ticker=r.get("ticker"),
                    acceptance_et=r.get("acceptance_et"),
                    session_date=r.get("session_date"),
                    eps_diluted_reported=np.nan,
                    eps_basis="none",
                    eps_adjusted=np.nan,
                    parse_confidence="none",
                    parse_notes=f"top_error: {type(e).__name__}: {e}"[:300],
                    is_preannouncement=r.get("is_preannouncement"),
                    event_type=r.get("event_type"),
                    reaction_session=r.get("reaction_session"),
                    ex99_rule=r.get("ex99_rule"),
                )
            )
        if i % 50 == 0 or i == len(todo):
            pd.DataFrame(rows).to_parquet(CKPT, index=False)
            print(f"w{WID} {i}/{len(todo)} saved={len(rows)} elapsed={time.time() - t0:.0f}s", flush=True)
    pd.DataFrame(rows).to_parquet(CKPT, index=False)
    print(f"w{WID} DONE {len(rows)}", flush=True)


if __name__ == "__main__":
    main()
