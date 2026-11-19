"""Stage 2: fetch SEC submissions JSON (+ 'files' history pages overlapping 2014-01-01..) for a list of CIKs.
SEC fair access: declared User-Agent with contact, <= 8 req/s (limit is 10). Raw responses saved gzip'd, write-once,
with a manifest line per file (url, sha256, retrieved_at_utc, http status). Not an Alpaca call."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import sys
import time
from typing import Any, cast

import pandas as pd
import requests

UA = os.environ.get("SEC_USER_AGENT", "CIO-Paper-Desk earnings-events research research-contact@example.com")
RAW = "raw/sec"
MAN = "raw/sec/MANIFEST.jsonl"
MIN_INTERVAL = 1 / 8.0
PAGE_FROM = "2014-01-01"
_last = [0.0]
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})


def get(url: str, path: str) -> dict[str, Any] | None:
    if os.path.exists(path):
        return cast(dict[str, Any], json.load(gzip.open(path)))
    for attempt in range(6):
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = S.get(url, timeout=60)
        if r.status_code == 200:
            break
        if r.status_code == 404:
            _log(url, path, 404, None)
            return None
        time.sleep(2**attempt + 1)  # 403/429/5xx: back off
    else:
        _log(url, path, r.status_code, None)
        raise RuntimeError(f"{url} -> {r.status_code}")
    body = r.content
    tmp = path + ".tmp"
    with gzip.open(tmp, "wb") as f:
        f.write(body)
    os.replace(tmp, path)
    _log(url, path, 200, hashlib.sha256(body).hexdigest())
    return cast(dict[str, Any], json.loads(body))


def _log(url: str, path: str, status: int, sha: str | None) -> None:
    with open(MAN, "a") as f:
        f.write(
            json.dumps(
                dict(
                    url=url, path=path, status=status, sha256=sha, retrieved_at_utc=dt.datetime.now(dt.UTC).isoformat()
                )
            )
            + "\n"
        )


def fetch_cik(cik: int) -> int:
    c = f"{int(cik):010d}"
    j = get(f"https://data.sec.gov/submissions/CIK{c}.json", f"{RAW}/CIK{c}.json.gz")
    if j is None:
        return 0
    n = 1
    for fl in j.get("filings", {}).get("files", []):
        if fl.get("filingTo", "9999") >= PAGE_FROM:
            get(f"https://data.sec.gov/submissions/{fl['name']}", f"{RAW}/{fl['name']}.gz")
            n += 1
    return n


if __name__ == "__main__":
    os.makedirs(RAW, exist_ok=True)
    ciks = (
        sorted({int(x) for x in sys.argv[1:]})
        if len(sys.argv) > 1
        else sorted(pd.read_parquet("work/member_cik_segments.parquet").cik.unique())
    )
    t0 = time.time()
    tot = 0
    for i, c in enumerate(ciks):
        try:
            tot += fetch_cik(c)
        except Exception as e:
            print("ERR", c, e, flush=True)
        if i % 50 == 0:
            print(i, len(ciks), tot, round(time.time() - t0), flush=True)
    print("done", len(ciks), "ciks", tot, "files", round(time.time() - t0), "s")
