from __future__ import annotations

import json

# Read-only fetch of daily bars (SIP, adjustment=all) for universe U from quant.py. No orders.
import os
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any, cast

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

H = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY_ID"], "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET_KEY"]}
src = open(f"{_QR.DESK_DIR}/quant.py").read()
_universe = cast(re.Match[str], re.search(r'U="([^"]+)"', src))
U = _universe.group(1).split()
START = "2016-01-01"
END = "2026-10-28T23:59:00Z"  # last COMPLETE session = 2026-10-28 (10-29 in progress at fetch time)


def get(q: Mapping[str, str | int]) -> dict[str, Any]:
    for k in range(6):
        try:
            r = urllib.request.Request(
                "https://data.alpaca.markets/v2/stocks/bars?" + urllib.parse.urlencode(q), headers=H
            )
            return cast(dict[str, Any], json.load(urllib.request.urlopen(r, timeout=60)))
        except Exception as e:
            print("retry", k, e, flush=True)
            time.sleep(3 * (k + 1))
    raise SystemExit("fetch failed")


out: dict[str, list[Any]] = {}
feed_used: dict[str, str] = {}
for feed in ["sip"]:
    for i in range(0, len(U), 5):
        syms = ",".join(U[i : i + 5])
        tok: str | None = None
        while True:
            q: dict[str, str | int] = {
                "symbols": syms,
                "timeframe": "1Day",
                "start": START,
                "end": END,
                "adjustment": "all",
                "feed": feed,
                "limit": 10000,
            }
            if tok:
                q["page_token"] = tok
            d = get(q)
            for s, b in d["bars"].items():
                out.setdefault(s, []).extend(b)
                feed_used[s] = feed
            tok = d.get("next_page_token")
            print(i, syms, sum(len(v) for v in out.values()), flush=True)
            if not tok:
                break
missing = [s for s in U if s not in out]
print("got", len(out), "missing", missing)
json.dump({"bars": out, "feed": feed_used, "U": U, "start": START, "end": END}, open("data/bars_sip.json", "w"))
for s in U:
    if s in out:
        print(s, len(out[s]), out[s][0]["t"][:10], out[s][-1]["t"][:10])
