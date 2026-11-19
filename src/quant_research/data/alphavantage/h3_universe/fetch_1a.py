#!/usr/bin/env python3
"""H3 Stage 1a: 3 LISTING_STATUS calls. Key from env only, never written. Exits: 0 ok, 2 no key, 3 bad/throttle body (stop), 5 target exists, 7 exception (type only)."""

from __future__ import annotations

import datetime
import hashlib
import os
import sys
import time
import urllib.request

CALLS = [
    ("1a-i_active_20210226.csv", "date=2021-02-26&state=active"),
    ("1a-ii_delisted_current.csv", "state=delisted"),
    ("1a-iii_active_current.csv", "state=active"),
]
HDR = b"symbol,name,exchange,assetType,ipoDate,delistingDate,status"


def main() -> int:
    k = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not k:
        print("NO_KEY")
        return 2
    for f, _ in CALLS:
        if os.path.exists(os.path.join("raw/1a", f)):
            print("EXISTS", f)
            return 5
    log = open("CALLS_1a.log", "x")
    for i, (f, q) in enumerate(CALLS):
        if i:
            time.sleep(1.5)
        url = f"https://www.alphavantage.co/query?function=LISTING_STATUS&{q}&apikey=" + k
        b = urllib.request.urlopen(url, timeout=120).read()
        first = b.split(b"\n", 1)[0].strip()
        ok = first == HDR
        n = b.count(b"\n")
        log.write(
            f"{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\t{f}\t{q}\tbytes={len(b)}\tlines={n}\t{'ok' if ok else 'BAD'}\t{hashlib.sha256(b).hexdigest()}\n"
        )
        log.flush()
        fd = os.open(os.path.join("raw/1a", f), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        os.write(fd, b)
        os.close(fd)
        if not ok:
            print("BAD_BODY", f, "bytes", len(b))
            return 3
    print("ALL_OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("EXC", type(e).__name__)
        sys.exit(7)
