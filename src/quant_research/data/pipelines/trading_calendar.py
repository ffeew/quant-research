"""U-CAL: SPY/NYSE trading-day calendar for the DEV window -> calendars/ucal_dev_spy.csv (+ pinned check).

Build: the sorted, de-duplicated session dates of SPY daily bars (data/bars/daily/raw/SPY.parquet, column
session_date) from the first session on or after dev_start through the last session strictly before
holdout_start. Only the session_date column is read, and rows on or after holdout_start are filtered out at read
time, so no holdout values are ever loaded into the calendar.
Output format: ASCII, header line "date", one YYYY-MM-DD per line, trailing newline.

Check: every call re-hashes the calendar file and refuses it if the sha256 differs from the pin, then refuses the
whole request on the first item that is outside the window (before dev_start, or on/after holdout_start) or is not
a session in the calendar. Nothing is truncated or silently dropped.

Configuration (configs/datasets.toml, [datasets.trading-calendar]): bars, calendar (relative to $QR_DATA_DIR),
dev_start, holdout_start, sha256 / sha256_env. Env overrides: QR_UCAL_PATH (calendar file), QR_UCAL_SHA256 (pin).
CLI: python -m quant_research.data.pipelines.trading_calendar [--bars PATH] [--out PATH]
     (or `qr build-data trading-calendar`); prints the session count and the new file's sha256 to pin.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import DATA, log
from quant_research.utils import config as _cfg

DATASET = "trading-calendar"
HEADER = "date"

Settings = dict[str, Any]
PathArg = str | os.PathLike[str]


def load_settings() -> Settings:
    """The [datasets.trading-calendar] block of configs/datasets.toml, with dates parsed."""
    with (_cfg.CONFIG_DIR / "datasets.toml").open("rb") as fh:
        s = dict(tomllib.load(fh)["datasets"][DATASET])
    s["dev_start"] = dt.date.fromisoformat(str(s["dev_start"]))
    s["holdout_start"] = dt.date.fromisoformat(str(s["holdout_start"]))
    if s["holdout_start"] <= s["dev_start"]:
        raise ValueError("U-CAL: holdout_start must be after dev_start")
    return s


def calendar_path(settings: Settings | None = None) -> Path:
    s = settings or load_settings()
    return Path(os.environ.get("QR_UCAL_PATH") or DATA / s["calendar"])


def pinned_sha256(settings: Settings | None = None) -> str:
    """Pin from env (sha256_env) or config; raise if neither is set (fail closed)."""
    s = settings or load_settings()
    pin = (os.environ.get(s.get("sha256_env", "QR_UCAL_SHA256")) or s.get("sha256") or "").strip().lower()
    if len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin):
        raise ValueError(
            "U-CAL: no valid calendar sha256 pin configured (set %s)" % s.get("sha256_env", "QR_UCAL_SHA256")
        )
    return pin


# ---------------------------------------------------------------- build


def build_sessions(session_dates: Iterable[object], dev_start: dt.date, holdout_start: dt.date) -> list[dt.date]:
    """Sorted unique session dates d with dev_start <= d < holdout_start."""
    out: set[dt.date] = set()
    for x in session_dates:
        d = pd.Timestamp(x).date()  # type: ignore[arg-type]
        if dev_start <= d < holdout_start:
            out.add(d)
    if not out:
        raise ValueError("U-CAL: no sessions inside the DEV window")
    days = sorted(out)
    if any(d.weekday() >= 5 for d in days):
        raise ValueError("U-CAL: weekend date in bars; refusing to build")
    return days


def read_bar_sessions(bars_path: PathArg, holdout_start: dt.date) -> list[object]:
    """session_date values strictly before holdout_start (filtered at read time; no other columns)."""
    df = pd.read_parquet(bars_path, columns=["session_date"], filters=[("session_date", "<", holdout_start)])
    return list(df["session_date"])


def render(days: list[dt.date]) -> bytes:
    return ("\n".join([HEADER] + [d.isoformat() for d in days]) + "\n").encode("ascii")


def write_calendar(days: list[dt.date], path: PathArg) -> str:
    """Atomic write; returns the sha256 of the written bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = render(days)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    return hashlib.sha256(raw).hexdigest()


def build(
    bars_path: PathArg | None = None, out_path: PathArg | None = None, settings: Settings | None = None
) -> tuple[Path, int, str]:
    s = settings or load_settings()
    bars = Path(bars_path) if bars_path else DATA / s["bars"]
    out = Path(out_path) if out_path else calendar_path(s)
    days = build_sessions(read_bar_sessions(bars, s["holdout_start"]), s["dev_start"], s["holdout_start"])
    sha = write_calendar(days, out)
    log.info("U-CAL: %d sessions %s..%s -> %s sha256=%s", len(days), days[0], days[-1], out, sha)
    return out, len(days), sha


# ---------------------------------------------------------------- check


def _parse(item: object) -> dt.date:
    if isinstance(item, dt.datetime):
        raise ValueError("U-CAL: datetime not accepted, pass a date or YYYY-MM-DD string: %r" % (item,))
    if isinstance(item, dt.date):
        return item
    if not isinstance(item, str) or len(item) != 10:
        raise ValueError("U-CAL: unparseable date: %r" % (item,))
    try:
        d = dt.date.fromisoformat(item)
    except ValueError:
        raise ValueError("U-CAL: unparseable date: %r" % (item,)) from None
    if d.isoformat() != item:
        raise ValueError("U-CAL: unparseable date: %r" % (item,))
    return d


def load_calendar(
    path: PathArg | None = None, expected_sha256: str | None = None, settings: Settings | None = None
) -> list[dt.date]:
    """Sorted session dates; ValueError if the bytes do not match the pin or the file leaves the window."""
    s = settings or load_settings()
    cal = Path(path) if path else calendar_path(s)
    pin = (expected_sha256 or pinned_sha256(s)).lower()
    raw = cal.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != pin:
        raise ValueError("U-CAL: calendar sha256 mismatch for %s" % cal.name)
    lines = raw.decode("ascii").splitlines()
    if len(lines) < 2 or lines[0] != HEADER:
        raise ValueError("U-CAL: calendar header or body missing")
    days = [dt.date.fromisoformat(x) for x in lines[1:]]
    if days != sorted(set(days)):
        raise ValueError("U-CAL: calendar not strictly ascending")
    if days[0] < s["dev_start"] or days[-1] >= s["holdout_start"]:
        raise ValueError("U-CAL: calendar outside the DEV window")
    return days


def check_dev_dates(
    dates: Iterable[object],
    path: PathArg | None = None,
    expected_sha256: str | None = None,
    settings: Settings | None = None,
) -> int:
    """Return the count when every item is a DEV session; raise ValueError naming the first bad item."""
    if isinstance(dates, (str, bytes, dt.date)):
        raise ValueError("U-CAL: pass an iterable of dates, not a single value: %r" % (dates,))
    s = settings or load_settings()
    items = list(dates)
    sessions = frozenset(load_calendar(path, expected_sha256, s))
    for item in items:
        d = _parse(item)
        if d >= s["holdout_start"]:
            raise ValueError("U-CAL: holdout date refused (on or after %s): %r" % (s["holdout_start"], item))
        if d < s["dev_start"]:
            raise ValueError("U-CAL: date before the window start %s: %r" % (s["dev_start"], item))
        if d not in sessions:
            raise ValueError("U-CAL: not a DEV trading session: %r" % (item,))
    return len(items)


def require_full_session_range(
    start: object,
    end: object,
    path: PathArg | None = None,
    expected_sha256: str | None = None,
    settings: Settings | None = None,
) -> list[dt.date]:
    """Every session in [start, end]; refuse the whole range if it leaves the DEV window."""
    s = settings or load_settings()
    a, b = _parse(start), _parse(end)
    if b < a:
        raise ValueError("U-CAL: range end before start: %r..%r" % (start, end))
    if a < s["dev_start"]:
        raise ValueError("U-CAL: range starts before the window start %s: %r" % (s["dev_start"], start))
    if b >= s["holdout_start"]:
        raise ValueError("U-CAL: range crosses the holdout bound %s: %r..%r" % (s["holdout_start"], start, end))
    return [d for d in load_calendar(path, expected_sha256, s) if a <= d <= b]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "U-CAL").splitlines()[0])
    ap.add_argument("--bars", help="SPY daily bars parquet (default: $QR_DATA_DIR/<bars>)")
    ap.add_argument("--out", help="calendar CSV (default: $QR_UCAL_PATH or $QR_DATA_DIR/<calendar>)")
    a = ap.parse_args(argv)
    _out, n, sha = build(a.bars, a.out)
    print(f"U-CAL sessions={n} sha256={sha} -> pin with QR_UCAL_SHA256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
