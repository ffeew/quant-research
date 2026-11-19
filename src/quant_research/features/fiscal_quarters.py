"""Fiscal-quarter mapping: assign earnings rows to (fiscal year, quarter n) bins given a fiscal-year-end month.

Generic port of the H2-C fiscal mapping. Rows are dicts with ``f`` (fiscalDateEnding) and ``r`` (reportedDate)
as ``datetime.date``. A fiscal year is "interior" when every quarter end lies inside ``[d_lo, d_hi]`` with ``lag`` days
of reporting slack; interior years must have exactly four unique rows with Q4 within 7 days of the fiscal-year end.
Edge years are binned per quarter (one row per bin).
"""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Any

Row = dict[str, Any]


def month_end(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def quarter_end(fiscal_year: int, fye_month: int, n: int) -> dt.date:
    """End date of fiscal quarter ``n`` (1..4) of the fiscal year ending in ``fye_month`` of ``fiscal_year``."""
    k = fye_month - 3 * (4 - n)
    return month_end(fiscal_year if k > 0 else fiscal_year - 1, (k - 1) % 12 + 1)


def map_fiscal_year(
    rows: list[Row], fye_month: int, fiscal_year: int, d_lo: dt.date, d_hi: dt.date, lag: int = 100
) -> tuple[dict[int, Row | None], str]:
    """Return ``({n: row or None}, why)`` for quarters 1..4 of one symbol's fiscal year."""
    a0, a1 = month_end(fiscal_year - 1, fye_month), month_end(fiscal_year, fye_month)
    slack = dt.timedelta(7)
    b = [a0 + slack] + [quarter_end(fiscal_year, fye_month, n) + slack for n in (1, 2, 3)] + [a1 + slack]
    q = sorted([x for x in rows if b[0] < x["f"] <= b[4]], key=lambda x: x["f"])
    interior = all(
        quarter_end(fiscal_year, fye_month, n) >= d_lo
        and quarter_end(fiscal_year, fye_month, n) + dt.timedelta(lag) <= d_hi
        for n in range(1, 5)
    )
    empty: dict[int, Row | None] = dict.fromkeys(range(1, 5))
    if interior:
        if len(q) != 4:
            return empty, f"closed_rows_{len(q)}"
        if abs((q[-1]["f"] - a1).days) > 7:
            return empty, "q4_not_within_7d_of_annual"
        if len({x["f"] for x in q}) != 4:
            return empty, "closed_rows_not_unique"
    out: dict[int, Row | None] = {}
    why: list[str] = []
    for n in range(1, 5):
        qn = [x for x in q if b[n - 1] < x["f"] <= b[n]]
        if len(qn) != 1:
            out[n] = None
            why.append(f"Q{n}_rows_{len(qn)}")
            continue
        if qn[0]["r"] is None or not (0 <= (qn[0]["r"] - qn[0]["f"]).days <= lag):
            out[n] = None
            why.append(f"Q{n}_lag")
            continue
        out[n] = qn[0]
    return out, ";".join(why)
