from __future__ import annotations

import csv
import datetime
import hashlib
import os
import sys
import time
import urllib.error
import urllib.request

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

R = f"{_QR.DATA_DIR}/av_returns_events_20261111"
KEY = os.environ.get("ALPHAVANTAGE_API_KEY")
if not KEY:
    print("STOP no key")
    sys.exit(2)
rows = list(csv.reader(open(f"{_QR.DATA_DIR}/av_sentiment_20261110/clean/MANIFEST.tsv"), delimiter="\t"))
syms = sorted({r[0] for r in rows[1:]} - {"QQQ"})
assert len(syms) == 51 and "SPY" in syms
stocks = [s for s in syms if s != "SPY"]
assert len(stocks) == 50
jobs = (
    [("TIME_SERIES_DAILY_ADJUSTED", "daily", s, "&outputsize=full") for s in syms]
    + [("EARNINGS", "earnings", s, "") for s in stocks]
    + [("OVERVIEW", "overview", s, "") for s in stocks]
)
assert len(jobs) == 151
for _f, d, s, _x in jobs:
    if os.path.exists(f"{R}/raw/{d}/{s}.json"):
        print("STOP exists", d, s)
        sys.exit(5)
log = os.open(f"{R}/CALLS.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o644)


def L(*a: object) -> None:
    os.write(log, ("\t".join(map(str, a)) + "\n").encode())


L("ts_utc", "function", "symbol", "attempt", "http", "bytes", "sha256", "class")


def classify(f: str, b: bytes) -> str:
    if len(b) < 4096:
        if b"Thank you for using Alpha Vantage" in b or b"call frequency" in b or b"rate limit" in b.lower():
            return "throttle"
        if b'"Information"' in b:
            return "information"
        if b'"Note"' in b:
            return "note"
        if b"Error Message" in b:
            return "error"
        if b.strip() in (b"{}", b""):
            return "empty"
    if f == "OVERVIEW" and b'"Symbol"' not in b:
        return "suspect"
    return "ok"


last: float = 0
failed: list[tuple[str, str, str]] = []
counts: dict[tuple[str, str], int] = {}
for f, d, s, x in jobs:
    for att in (1, 2):
        w = 1.5 - (time.time() - last)
        if w > 0:
            time.sleep(w)
        last = time.time()
        code: str | int = "NA"
        b = b""
        try:
            with urllib.request.urlopen(
                f"https://www.alphavantage.co/query?function={f}&symbol={s}{x}&apikey={KEY}", timeout=60
            ) as r:
                code = r.status
                b = r.read()
            c = classify(f, b) if code == 200 else "http"
        except Exception as e:
            c = "neterr:" + type(e).__name__
        p = f"{R}/raw/{d}/{s}.json" if att == 1 else f"{R}/raw/{d}/{s}.attempt2.json"
        if b:
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.write(fd, b)
            os.close(fd)
        L(
            datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            f,
            s,
            att,
            code,
            len(b),
            hashlib.sha256(b).hexdigest(),
            c,
        )
        if c in ("throttle", "information"):
            print("STOP", c, f, s)
            sys.exit(3)
        if c in ("ok", "empty", "suspect", "note"):
            break
        if att == 1:
            time.sleep(60)
    counts[(f, c)] = counts.get((f, c), 0) + 1
    if c != "ok":
        failed.append((f, s, c))
    if len([z for z in failed if z[2] not in ("ok",)]) > 5:
        print("STOP >5 failed", failed)
        sys.exit(4)
print("DONE", sorted(counts.items()))
print("nonok", failed)
