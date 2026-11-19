"""SEC EDGAR fetcher for the derivatives researcher's derived controls: stdlib only, cached, rate-limited.

- User-Agent from env SEC_USER_AGENT ("<Org> <contact email>", per SEC fair-access policy).
  The default matches the desk pipeline convention (data/pipelines/earnings.py).
- Rate limit: a token bucket shared by every process using this module (fcntl lock).
  Default 8 req/s, burst 4, i.e. under SEC's 10 req/s.
- Raw responses are cached under raw/sec/<host>/<path> and never re-fetched unless refresh=True.
- Retries 429/5xx with exponential backoff.
"""

from __future__ import annotations

import fcntl
import gzip
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw" / "sec"
STATE = HERE / "cache" / "sec_rate.state.json"
LEDGER = HERE / "cache" / "sec_requests.log"
UA = os.environ.get("SEC_USER_AGENT", "CIO-Desk-Research research-data@example.com")
RPS = float(os.environ.get("RESEARCH_SEC_RPS", "8"))
BURST = 4.0


def _acquire() -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    while True:
        with open(STATE, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                st = json.loads(f.read() or "{}")
            except json.JSONDecodeError:
                st = {}
            now = time.time()
            tokens = min(BURST, st.get("tokens", BURST) + (now - st.get("t", now)) * RPS)
            if tokens >= 1:
                st = {"tokens": tokens - 1, "t": now}
                f.seek(0)
                f.truncate()
                f.write(json.dumps(st))
                return
            wait = (1 - tokens) / RPS
        time.sleep(wait)


def cache_path(url: str) -> Path:
    u = url.split("://", 1)[1]
    p = RAW / u.replace("?", "_q_")
    if u.endswith("/"):
        p = p / "_index"
    return p


def get(url: str, refresh: bool = False, tries: int = 6) -> bytes:
    """Return bytes for url, from the cache if present."""
    p = cache_path(url)
    if p.exists() and not refresh:
        return p.read_bytes()
    for i in range(tries):
        _acquire()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
            with open(LEDGER, "a") as lg:
                lg.write(f"{time.time():.3f}\t{os.getpid()}\t200\t{url}\n")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
            return cast(bytes, b)
        except urllib.error.HTTPError as e:
            with open(LEDGER, "a") as lg:
                lg.write(f"{time.time():.3f}\t{os.getpid()}\t{e.code}\t{url}\n")
            if e.code == 404:
                raise
            if e.code in (403, 429) or e.code >= 500:
                time.sleep(min(60, 2**i + random.random()))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(min(60, 2**i + random.random()))
    raise RuntimeError(f"SEC fetch failed after {tries} tries: {url}")


def get_json(url: str, refresh: bool = False) -> Any:
    return json.loads(get(url, refresh).decode("utf-8", "replace"))
