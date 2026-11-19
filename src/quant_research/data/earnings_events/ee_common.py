from __future__ import annotations

import gzip
import json
import os
import re
from typing import Any

import pandas as pd

RAW = "raw/sec"
STOP = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "the",
    "and",
    "group",
    "holdings",
    "holding",
    "de",
    "nv",
    "sa",
    "llc",
    "lp",
    "trust",
    "new",
    "class",
    "a",
    "b",
    "c",
    "cl",
    "com",
    "of",
    "ag",
}


def norm_tokens(s: object) -> set[str]:
    s = re.sub(r"\(.*?\)|/[a-z]{2,3}/", " ", str(s).lower()).replace("&", " and ")
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in STOP}


def name_score(a: object, b: object) -> float:
    A, B = norm_tokens(a), norm_tokens(b)
    if not A or not B:
        return 0.0
    return len(A & B) / min(len(A), len(B))


def load_sub(cik: int) -> tuple[dict[str, Any] | None, pd.DataFrame | None]:
    p = f"{RAW}/CIK{int(cik):010d}.json.gz"
    if not os.path.exists(p):
        return None, None
    j = json.load(gzip.open(p))
    frames = [pd.DataFrame(j["filings"]["recent"])]
    for fl in j["filings"].get("files", []):
        q = f"{RAW}/{fl['name']}.gz"
        if os.path.exists(q):
            frames.append(pd.DataFrame(json.load(gzip.open(q))))
    f = pd.concat(frames, ignore_index=True).drop_duplicates("accessionNumber")
    return j, f
