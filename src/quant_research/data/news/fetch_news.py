"""Fetch Alpaca v1beta1/news for a symbol list, month by month, resumable.
Credentials: handled by desk_data_client (env ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY, never printed).
All requests go through $QR_DATA_DIR/lib/desk_data_client.py (desk rule 5, shared 150/min throttle).
Output: raw/YYYY-MM.jsonl (id, created_at, headline, summary, symbols, source). A month is
written atomically only when fully paged, so re-running skips finished months.
Usage: python fetch_news.py [--symbols symbols.txt] [--start 2016-01] [--end 2026-10] [--workers 2]
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ap = argparse.ArgumentParser()
ap.add_argument("--symbols", default="symbols.txt")
ap.add_argument("--start", default="2016-01")
ap.add_argument("--end", default="2026-10")
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--out", default="raw")  # rate is set desk-wide by ddc (DESK_ALPACA_RPM), not here
a = ap.parse_args()
SYMS = [s.strip() for s in open(a.symbols) if s.strip()]
CH = [SYMS[i : i + 120] for i in range(0, len(SYMS), 120)]  # keep URL length sane
# DESK RULE 5 (2026-10-30): all live Alpaca calls go through Dmitri's shared, cross-process throttled client
# (one 150 req/min budget for the whole desk). No private HTTP code or private rate limit here.
import sys

sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
from quant_research.data.client import desk_data_client as ddc

npg = [0]
lock = threading.Lock()


def get(q: dict[str, Any]) -> Any:
    # one page per call so progress is logged and the month is written only when fully paged;
    # use_cache=False: raw/YYYY-MM.jsonl is our store, avoid duplicating ~GBs of pages in the shared cache
    return ddc.alpaca_get("/v1beta1/news", q, use_cache=False)


def months() -> Iterator[tuple[int, int]]:
    y, m = map(int, a.start.split("-"))
    ye, me = map(int, a.end.split("-"))
    while (y, m) <= (ye, me):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def _do(ym: tuple[int, int]) -> tuple[str, int]:
    y, m = ym
    fn = f"{a.out}/{y:04d}-{m:02d}.jsonl"
    if os.path.exists(fn):
        return fn, -1
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    seen = {}
    for ch in CH:
        tok = None
        while True:
            q = {
                "symbols": ",".join(ch),
                "start": f"{y:04d}-{m:02d}-01T00:00:00Z",
                "end": f"{ny:04d}-{nm:02d}-01T00:00:00Z",
                "limit": 50,
                "sort": "asc",
                "include_content": "false",
            }
            if tok:
                q["page_token"] = tok
            d = get(q)
            for x in d.get("news", []):
                seen[x["id"]] = {
                    k: x.get(k)
                    for k in ("id", "created_at", "updated_at", "headline", "summary", "symbols", "source", "author")
                }
            tok = d.get("next_page_token")
            with lock:
                npg[0] += 1
            if npg[0] % 100 == 0:
                print(time.strftime("%H:%M:%S"), "pages", npg[0], f"{y}-{m:02d}", len(seen), flush=True)
            if not tok:
                break
    with open(fn + ".tmp", "w") as f:
        for x in seen.values():
            f.write(json.dumps(x) + "\n")
    os.replace(fn + ".tmp", fn)
    return fn, len(seen)


def do(ym: tuple[int, int]) -> tuple[str, int | None]:
    try:
        return _do(ym)
    except Exception as e:  # e.g. ddc gave up after its wait budget; month stays unwritten and a rerun resumes it
        print(time.strftime("%H:%M:%S"), "FAILED", ym, type(e).__name__, str(e)[:200], flush=True)
        return f"{ym}", None


os.makedirs(a.out, exist_ok=True)
ms = list(months())[::-1]  # newest first
with ThreadPoolExecutor(a.workers) as ex:
    for fn, n in ex.map(do, ms):  # results print in month order
        print(time.strftime("%H:%M:%S"), fn, n, flush=True)
