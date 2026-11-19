"""Weekly decision calendar from a list of trading sessions (no calendar library needed)."""
from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def decision_dates(
    sessions: Sequence[str], window: int, coverage_start: str, end: str
) -> tuple[list[str], dict[str, str], list[str]]:
    """Decision dates are the last session of each ISO week with ``window`` full sessions after the first session on
    or after ``coverage_start`` and on or before ``end``. Returns ``(usable, next_decision, straddle)`` where a
    decision whose next decision falls after ``end`` is dropped as straddling the boundary."""
    s = sorted(sessions)
    last = {}
    for d in s:
        last[dt.date.fromisoformat(d).isocalendar()[:2]] = d
    weekly = sorted(last.values())
    ix = {d: i for i, d in enumerate(s)}
    first = next(i for i, d in enumerate(s) if d >= coverage_start)
    decs = [d for d in weekly if ix[d] - window >= first and d <= end]
    pos = {d: i for i, d in enumerate(weekly)}
    nxt = {d: weekly[pos[d] + 1] for d in decs if pos[d] + 1 < len(weekly)}
    usable = [d for d in decs if d in nxt and nxt[d] <= end]
    straddle = [d for d in decs if d not in usable]
    return usable, {d: nxt[d] for d in usable}, straddle


def cutoff(day: str, hhmm: tuple[int, int] = (15, 30)) -> float:
    """Epoch seconds of ``day`` at ``hhmm`` New York time."""
    y, m, d = map(int, day.split("-"))
    return dt.datetime(y, m, d, hhmm[0], hhmm[1], tzinfo=NY).timestamp()


def month_set(start_ep: float, end_ep: float) -> set[str]:
    """YYYY-MM months touched by ``[start - 1 day, end + 1 day]`` in New York dates."""
    a = dt.datetime.fromtimestamp(start_ep, NY).date() - dt.timedelta(days=1)
    b = dt.datetime.fromtimestamp(end_ep, NY).date() + dt.timedelta(days=1)
    out, x = set(), a.replace(day=1)
    while x <= b:
        out.add(f"{x.year}-{x.month:02d}")
        x = (x + dt.timedelta(days=32)).replace(day=1)
    return out
