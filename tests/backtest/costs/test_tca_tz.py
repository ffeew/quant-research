#!/usr/bin/env python3
"""Offline test of desk time handling (no network, no keys). Run: python3 test_tz.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quant_research.backtest.costs import tca

cases = [  # (Alpaca UTC timestamp, expected ET wall clock, expected ET abbrev, expected SGT wall clock)
    ("2026-10-29T16:51:45.626331422Z", "2026-10-29 12:51:45", "EDT", "2026-10-30 00:51:45"),  # before DST ends (UTC-4)
    ("2026-11-02T17:51:00Z", "2026-11-02 12:51:00", "EST", "2026-11-03 01:51:00"),  # after DST ends (UTC-5)
    ("2026-11-01T05:59:59Z", "2026-11-01 01:59:59", "EDT", "2026-11-01 13:59:59"),  # last second of EDT
    (
        "2026-11-01T06:00:00Z",
        "2026-11-01 01:00:00",
        "EST",
        "2026-11-01 14:00:00",
    ),  # first second of EST (01:00 repeats)
]
for s, et_exp, abbr, sgt_exp in cases:
    d = tca.ts(s)
    assert d is not None
    off = d.utcoffset()
    assert off is not None and off.total_seconds() == 0, d
    e = tca.et(d)
    assert e is not None
    assert e.strftime("%Y-%m-%d %H:%M:%S") == et_exp and e.tzname() == abbr, (s, e, e.tzname())
    assert tca.sgt(d) == f"{sgt_exp} SGT", (s, tca.sgt(d))
    print(f"ok  {s:32s} -> {tca.et_str(d)} | {tca.sgt(d)}")

# Same 12:51 ET wall clock maps to different UTC/SGT across the change
dst, standard, open_et, pre_et, midnight_edt, midnight_est = (
    tca.ts("2026-10-29T16:51:00Z"),
    tca.ts("2026-11-02T17:51:00Z"),
    tca.ts("2026-11-02T14:35:00Z"),
    tca.ts("2026-11-02T13:35:00Z"),
    tca.ts("2026-10-29T04:00:00Z"),
    tca.ts("2026-11-02T05:00:00Z"),
)
assert None not in (dst, standard, open_et, pre_et, midnight_edt, midnight_est)
assert dst is not None and standard is not None and open_et is not None and pre_et is not None
assert midnight_edt is not None and midnight_est is not None
assert tca.tod_bucket(dst) == tca.tod_bucket(standard) == "midday 11:30-14:00 ET"
assert tca.tod_bucket(open_et) == "open 09:30-10:00 ET"  # 09:35 EST
assert tca.tod_bucket(pre_et) == "pre-market"  # 08:35 EST (would be 09:35 with a fixed -4)
# Daily bar timestamps (04:00Z/05:00Z = midnight ET) map to the right New York date
assert str(tca.et_date(midnight_edt)) == "2026-10-29"
assert str(tca.et_date(midnight_est)) == "2026-11-02"
# Naive timestamps are refused
try:
    tca.ts("2026-10-29T16:51:45")
    raise AssertionError("naive accepted")
except ValueError:
    pass
print("test_tz: all passed")
