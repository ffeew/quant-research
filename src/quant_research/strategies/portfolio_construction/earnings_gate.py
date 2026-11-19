"""Earnings gate for construct.py (LIMITS.md H7; current LIMITS header, v0.3.7 at 02:28 SGT; Risk decision 2026-10-30 02:27). Read-only use of the data owner's calendar + next_earnings sidecar.

DEFAULT POLICY = "risk_ruling_20261030_0227" (Risk, risk/decisions-log.md row 2026-10-30 02:27, "H7 earnings gate:
estimated dates and recently reported names: RULING: ACCEPTED WITH CONDITIONS"):
  (1) CONFIRMED next dates (sidecar status 'confirmed' with company/source evidence ONLY): standard H7 - flag within 10
      trading days; no hold through the release (shorts no exceptions); no new/added risk if release <= horizon end.
      Main-calendar nasdaq_scheduled / other forecasts are NEVER confirmed. edgar_8k_2.02 is a realised release
      record (last 8-K for decision 3), not advance confirmation of a future next date.
  (2) ESTIMATED dates: flag window opens 15 sessions before the EARLIEST candidate (= earliest - 5-session buffer - 10).
      Shorts must be closed BEFORE the window opens (close_by_short = session before window_open); nothing new opened or
      increased once the window opens within the holding horizon (window_open <= horizon end -> in_window). Longs: no
      hold through the buffered release (close_by_long = session before earliest - 5 sessions).
  (3) 'known, not in window' (estimated) ONLY if the last 8-K Item 2.02 is <= 45 calendar days old AND window_open is
      after the horizon end; otherwise the name stays UNKNOWN (tradable: no new/increased short; shadow: flagged).
  (4) FULL FAIL-SAFE (treated as reporting inside the window: in_window, close_by = execution session, shorts and longs
      closed, no adds; CIO long exceptions still honoured) for any single stock with no date row (no unreleased main-
      calendar event and no sidecar row), and for every single stock relying on a file that is > 1 US trading day stale
      (main calendar: all single stocks; sidecar: names without a main-calendar date), unreadable, or fails its pinned sha256.
  (5) EARLIEST date seen across the CURRENT (newest) sidecar file applies: min over duplicate rows and, for estimated
      rows, over every candidate date listed in `notes`; also min with the main calendar's next unreleased event. An
      estimate that moves earlier on a refresh therefore applies at once (newest file auto-selected).
Optional policy "strict" (CLI --earnings_policy strict; the pre-decision behaviour): main calendar + sidecar CONFIRMED rows
are known; estimated rows and names without a date are UNKNOWN (tradable no new/increased short; shadow flag); a stale
or missing calendar makes all single stocks UNKNOWN (not full fail-safe).

--- pre-decision (strict) documentation follows ---

Source (read-only, the data owner, $QR_DATA_DIR/README.md §6):
  $QR_DATA_DIR/earnings/earnings_events.parquet  - one row per event: symbol, announce_date_et, timing (BMO/AMC/
      INTRADAY/UNKNOWN), source (edgar_8k_2.02 | nasdaq_reported_or_past | nasdaq_scheduled), knowledge_time_utc
  $QR_DATA_DIR/earnings/nasdaq_calendar.parquet  - Nasdaq calendar pull; fetched_at_utc = calendar freshness
We use announce_date_et + timing only (NOT first_tradable_session: the validator found the DURING_MKT alignment defect).

Rules (LIMITS H7 + CIO 2026-10-30 01:58):
  * SHORTS are never held through their own release: if the next release falls before the end of the holding horizon
    (execution session + horizon sessions), the name may not be short (w >= 0) in either book; a held short is
    covered. close_by = last session that ends before the release (BMO on D -> D-1 close; AMC/INTRADAY/UNKNOWN on D ->
    D-1 close as well, conservative: UNKNOWN timing could be BMO).
  * LONGS (no unplanned hold through earnings): no new/added long into a release inside the horizon; a held long is
    closed by close_by unless the CIO logged an exception (--earnings_hold_exceptions; LIMITS requires a 3x stop-gap
    stress, which is the CIO's sign-off, not ours).
  * FAIL-SAFE unknown date: a single stock with no known next release (no upcoming event in a fresh calendar, or the
    calendar missing/stale) may not be opened or increased SHORT in the tradable book (w >= min(0, w_held)); the
    shadow book is not constrained but flags it.
  * ETFs (universe role 'etf' or in the caller's ETF set) have no earnings and are exempt.
  * Calendar freshness: max(fetched_at_utc) older than 1 US trading day (same rule as Risk's state files) -> stale ->
    every single stock is 'unknown' (fail safe); missing/unreadable files likewise.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import glob
import hashlib
import os
import re
from collections.abc import Iterable
from typing import Any, cast
from zoneinfo import ZoneInfo

import pandas as pd

from quant_research.strategies.portfolio_construction.risk_state import is_session, us_trading_days_between
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

ET = ZoneInfo("America/New_York")
EARN_DIR = f"{_QR.DATA_DIR}/earnings"
NEXT_DIR = f"{EARN_DIR}/next_earnings"
POLICY_RULING = "risk_ruling_20261030_0227"
POLICY_STRICT = "strict"
POLICIES = (POLICY_RULING, POLICY_STRICT)
# sha256 pins of sidecar files verified by Risk / the CIO brief.
# Require an EXACT accepted hash for the basename; missing/unknown basename OR mismatch -> FULL FAIL-SAFE.
# next_earnings_20261105.parquet accepted by the signed risk decision of 2026-11-06; any other file/hash remains unauthorized -> fail-closed.
PINNED_SHA256 = {
    "next_earnings_20261030.parquet": desk_pin(
        "strategies.portfolio_construction.earnings_gate", "PINNED_SHA256.next_earnings_20261030.parquet"
    ),
    "next_earnings_20261105.parquet": desk_pin(
        "strategies.portfolio_construction.earnings_gate", "PINNED_SHA256.next_earnings_20261105.parquet"
    ),  # Risk manager AUTHORIZED 2026-11-06
}
# Main-calendar next-date status: forecasts and realised EDGAR rows are NEVER "confirmed" next dates.
# Confirmed next dates come only from sidecar status=confirmed (company/IR evidence).
# edgar_8k_2.02 feeds last_8k_202, not advance confirmation of a future next date.
FORECAST_OR_REALISED_SOURCES = frozenset(
    {
        "nasdaq_scheduled",
        "nasdaq_reported_or_past",
        "edgar_10q10k_fallback",
        "edgar_8k_2.02",
    }
)
CONFIRMED_FLAG_SESSIONS = 10  # H7 flag
EST_BUFFER_SESSIONS = 5  # decision (2)
RECENT_8K_DAYS = 45  # decision (3)


def calendar_next_status(source: str | None) -> str:
    """Status for a main-calendar row used as a *next-date* candidate (decision 2026-10-30 02:27).
    nasdaq_* forecasts and edgar realised releases are estimated for next-date purposes; never confirmed."""
    src = str(source or "")
    if src in FORECAST_OR_REALISED_SOURCES or src.startswith("nasdaq_"):
        return "estimated"
    return "estimated"  # unknown sources: fail closed to estimated (never silently confirm)


def next_sessions(d: dt.date, n: int) -> list[dt.date]:
    """d (date) and the following sessions; returns list of the next n sessions strictly after d."""
    out: list[dt.date] = []
    x = d
    while len(out) < n:
        x += dt.timedelta(days=1)
        if is_session(x):
            out.append(x)
    return out


def prev_session(d: dt.date) -> dt.date:
    x = d - dt.timedelta(days=1)
    while not is_session(x):
        x -= dt.timedelta(days=1)
    return x


def execution_session(now: dt.datetime) -> dt.date:
    """Session the targets would trade in: today ET if a session and before 16:00 ET, else the next session."""
    t = now.astimezone(ET)
    d = t.date()
    if is_session(d) and t.hour < 16:
        return d
    return next_sessions(d, 1)[0]


def load_calendar(now: dt.datetime, earn_dir: str = EARN_DIR, max_age_days: int = 1) -> Any:
    """Returns (events DataFrame or None, info dict). Stale/missing -> events None."""
    info = dict(source=f"{earn_dir}/earnings_events.parquet (+ nasdaq_calendar.parquet fetched_at_utc)", fresh=False)
    try:
        ev = pd.read_parquet(
            f"{earn_dir}/earnings_events.parquet",
            columns=["symbol", "announce_date_et", "timing", "source", "knowledge_time_utc"],
        )
        nq = pd.read_parquet(f"{earn_dir}/nasdaq_calendar.parquet", columns=["report_date", "fetched_at_utc"])
    except Exception as e:
        info.update(
            reason=f"calendar unreadable/missing ({type(e).__name__}: {e}) -> FAIL-SAFE all single stocks unknown"
        )
        return None, info
    fetched = pd.to_datetime(nq["fetched_at_utc"], utc=True).max()
    cover_to = pd.to_datetime(nq["report_date"]).max().date()
    age = us_trading_days_between(fetched.to_pydatetime(), now)
    info.update(fetched_at_utc=fetched.isoformat(), coverage_through=str(cover_to), age_us_trading_days=age)
    if age > max_age_days:
        info.update(
            reason=f"calendar stale ({age} US sessions old > {max_age_days}) -> FAIL-SAFE all single stocks unknown"
        )
        return None, info
    ev = ev.copy()
    ev["d"] = pd.to_datetime(ev["announce_date_et"]).dt.date
    info.update(fresh=True, reason="fresh", coverage_through=str(max(cover_to, ev["d"].max())))
    return ev, info


def released(row: Any, now: dt.datetime) -> bool:
    """True if the event is already public at `now` (knowledge time passed, or BMO/INTRADAY on today's/earlier date)."""
    t = now.astimezone(ET)
    d = row["d"]
    if d < t.date():
        return True
    if d > t.date():
        return False
    kt = row.get("knowledge_time_utc")
    try:
        if (
            pd.notna(kt)
            and pd.Timestamp(kt).tz_convert("UTC") <= pd.Timestamp(now).tz_convert("UTC")
            and row.get("source") == "edgar_8k_2.02"
        ):
            return True
    except Exception:
        pass
    # AMC / UNKNOWN / INTRADAY today: treat as still to come (conservative)
    return row["timing"] == "BMO" and t.hour >= 9


def gate(
    names: list[str],
    now: dt.datetime,
    horizon_sessions: int,
    etfs: set[str],
    exceptions: tuple[str, ...] = (),
    earn_dir: str = EARN_DIR,
    events: pd.DataFrame | None = None,
    info: dict[str, Any] | None = None,
) -> Any:
    """Per-name earnings status. Returns (status dict, info). status[s] = dict(kind, next, timing, close_by, in_window,
    no_short, no_long_add, close_long, unknown)."""
    if events is None and info is None:
        events, info = load_calendar(now, earn_dir)
    exe = execution_session(now)
    end = next_sessions(exe, horizon_sessions)[-1] if horizon_sessions > 0 else exe
    info = dict(
        cast(dict[str, Any], info),
        execution_session=str(exe),
        horizon_sessions=horizon_sessions,
        horizon_end_session=str(end),
    )
    out = {}
    for s in names:
        if s in etfs:
            out[s] = dict(
                kind="etf_exempt",
                next=None,
                unknown=False,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
            )
            continue
        if events is None:
            out[s] = dict(
                kind="unknown_calendar",
                next=None,
                unknown=True,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
            )
            continue
        upcoming = events[(events["symbol"] == s) & (events["d"] >= exe - dt.timedelta(days=7))].sort_values("d")
        upcoming_rows = [r for _, r in upcoming.iterrows() if not released(r, now)]
        if not upcoming_rows:
            out[s] = dict(
                kind="unknown_no_upcoming_date",
                next=None,
                unknown=True,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
            )
            continue
        r = upcoming_rows[0]
        d = r["d"]
        inw = d <= end  # release on/before the last horizon session -> would be held through it
        # AMC on D -> must be flat by D's close; BMO/INTRADAY/UNKNOWN on D -> by D-1's close (UNKNOWN treated as BMO)
        close_by = d if r["timing"] == "AMC" else prev_session(d)
        exc = s in set(exceptions)
        out[s] = dict(
            kind="known",
            next=str(d),
            timing=str(r["timing"]),
            source=str(r["source"]),
            close_by=str(close_by),
            unknown=False,
            in_window=bool(inw),
            no_short=bool(inw),
            no_long_add=bool(inw and not exc),
            close_long=bool(inw and not exc),
            long_exception=exc,
        )
    return out, info


# =====================================================================================================================
# Risk decision 2026-10-30 02:27 (default policy)
# =====================================================================================================================
def sessions_before(d: dt.date, n: int) -> dt.date:
    """The session n sessions strictly before d (n >= 1)."""
    x, k = d, 0
    while k < n:
        x -= dt.timedelta(days=1)
        if is_session(x):
            k += 1
    return x


def newest_next_file(next_dir: str = NEXT_DIR) -> str | None:
    fs = sorted(
        glob.glob(os.path.join(next_dir, "next_earnings_*.parquet")),
        key=lambda f: (re.findall(r"next_earnings_(\d{8})", os.path.basename(f)) or ["0"])[0],
    )
    return fs[-1] if fs else None


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")

_CAND = re.compile(r"(\d{4}-\d{2}-\d{2})\s+[A-Za-z_/-]+\s*\[")  # 'YYYY-MM-DD <timing> [source]' entries only


def _candidates(row: Any) -> list[dt.date]:
    """Earliest-date set for a sidecar row: next_earnings_date plus, for ESTIMATED rows only, every
    'YYYY-MM-DD <timing> [source]' entry in the 'Candidates:' list of notes (up to 'Spread'/end of sentence list).
    Free-text dates (e.g. 'CAT reported Q3 2026 on 2026-10-29') are NOT candidates, and any candidate on/before the
    row's last_earnings_date (already released) is dropped. Confirmed rows: the company date only."""
    out = []
    with contextlib.suppress(Exception):
        out.append(pd.Timestamp(row["next_earnings_date"]).date())
    if str(row.get("status")) == "estimated":
        n = str(row.get("notes") or "")
        if "Candidates:" in n:
            seg = re.split(r"\bSpread\b", n.split("Candidates:", 1)[1], maxsplit=1)[0]
            for x in _CAND.findall(seg):
                with contextlib.suppress(ValueError):
                    out.append(dt.date.fromisoformat(x))
    try:
        last = pd.Timestamp(row.get("last_earnings_date")).date() if pd.notna(row.get("last_earnings_date")) else None
    except Exception:
        last = None
    return [d for d in out if last is None or d > last]


def load_next(
    now: dt.datetime,
    next_dir: str = NEXT_DIR,
    path: str | None = None,
    max_age_days: int = 1,
    pinned: dict[str, str] | None = None,
) -> Any:
    """Newest next_earnings_*.parquet (or `path`). Returns (dict symbol -> record, info). Invalid -> (None, info)."""
    pinned = PINNED_SHA256 if pinned is None else pinned
    path = path or newest_next_file(next_dir)
    info: dict[str, Any] = dict(path=path, fresh=False, usable=False)
    if not path or not os.path.exists(path):
        info.update(reason="no next_earnings_*.parquet found -> names without a main-calendar date: FULL FAIL-SAFE")
        return None, info
    sha = _sha(path)
    base = os.path.basename(path)
    pin = pinned.get(base)
    info.update(sha256=sha, sha256_pinned=pin, sha256_ok=(pin is not None and pin == sha))
    if pin is None:
        info.update(
            reason=f"no accepted pin for {base!r} (not in PINNED_SHA256 / pinned map) -> FULL FAIL-SAFE for names relying on it"
        )
        return None, info
    if pin != sha:
        info.update(reason=f"sha256 mismatch ({sha} != pinned {pin}) -> FULL FAIL-SAFE for names relying on it")
        return None, info
    try:
        df = pd.read_parquet(path)
        need = {"symbol", "next_earnings_date", "status", "fetched_at_utc"}
        if not need <= set(df.columns):
            raise ValueError(f"missing columns {sorted(need - set(df.columns))}")
    except Exception as e:
        info.update(reason=f"unreadable ({type(e).__name__}: {e}) -> FULL FAIL-SAFE for names relying on it")
        return None, info
    fetched = pd.to_datetime(df["fetched_at_utc"], utc=True).max()
    age = us_trading_days_between(fetched.to_pydatetime(), now)
    info.update(
        fetched_at_utc=fetched.isoformat(),
        age_us_trading_days=age,
        n_rows=int(len(df)),
        n_confirmed=int((df["status"] == "confirmed").sum()),
        n_estimated=int((df["status"] == "estimated").sum()),
    )
    if age > max_age_days:
        info.update(reason=f"stale ({age} US sessions > {max_age_days}) -> FULL FAIL-SAFE for names relying on it")
        return None, info
    rec: dict[str, Any] = {}
    for _, r in df.iterrows():
        s = str(r["symbol"])
        st = str(r["status"])
        if st not in ("confirmed", "estimated"):
            st = "estimated"  # unknown status label -> treat as estimate
        c = _candidates(r)
        if not c:
            continue
        last8k = None
        with contextlib.suppress(Exception):
            last_raw = r.get("last_earnings_date")
            last8k = pd.Timestamp(cast(Any, last_raw)).date() if pd.notna(last_raw) else None
        cur = rec.get(s)
        new = dict(
            status=st,
            earliest=min(c),
            row_date=str(r["next_earnings_date"]),
            candidates=sorted({str(x) for x in c}),
            timing=str(r.get("timing") or "unknown"),
            source=str(r.get("source") or ""),
            last_8k_202=last8k,
        )
        if cur is None:
            rec[s] = new
        else:  # duplicate rows: earliest date wins; estimated status if either is estimated (conservative)
            earliest_dt = min(cur["earliest"], new["earliest"])
            rec[s] = dict(
                cur if cur["earliest"] <= new["earliest"] else new,
                earliest=earliest_dt,
                status="estimated" if "estimated" in (cur["status"], new["status"]) else "confirmed",
                candidates=sorted(
                    set(cast(Iterable[str], cur["candidates"])) | set(cast(Iterable[str], new["candidates"]))
                ),
                last_8k_202=max(
                    [x for x in (cast(Any, cur["last_8k_202"]), cast(Any, new["last_8k_202"])) if x] or [None]
                ),
            )
    info.update(fresh=True, usable=True, reason="fresh", n_symbols=len(rec))
    return rec, info


def _last_8k(events: pd.DataFrame | None, s: str, today: dt.date) -> dt.date | None:
    if events is None:
        return None
    e = events[(events["symbol"] == s) & (events["source"] == "edgar_8k_2.02") & (events["d"] <= today)]
    return e["d"].max() if len(e) else None


def gate_policy(
    names: list[str],
    now: dt.datetime,
    horizon_sessions: int,
    etfs: set[str],
    exceptions: Any = (),
    events: pd.DataFrame | None = None,
    info: dict[str, Any] | None = None,
    nxt: Any = None,
    ninfo: dict[str, Any] | None = None,
    policy: str = POLICY_RULING,
) -> Any:
    """Earnings status per name under `policy`. Same keys as gate() plus close_by_short / close_by_long, window_open,
    status_basis, h7_flag, last_8k_202, rule. events/info from load_calendar; nxt/ninfo from load_next."""
    if policy not in POLICIES:
        raise ValueError(f"unknown earnings policy {policy!r}")
    exe = execution_session(now)
    end = next_sessions(exe, horizon_sessions)[-1] if horizon_sessions > 0 else exe
    today = now.astimezone(ET).date()
    info = dict(
        info or {},
        execution_session=str(exe),
        horizon_sessions=horizon_sessions,
        horizon_end_session=str(end),
        policy=policy,
        next_earnings=ninfo,
    )
    exc = set(exceptions)
    out = {}

    def unknown(kind: str, rule: str, **kw: Any) -> dict[str, Any]:
        return dict(
            dict(
                kind=kind,
                next=None,
                timing=None,
                close_by=None,
                close_by_short=None,
                close_by_long=None,
                unknown=True,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
                long_exception=False,
                rule=rule,
            ),
            **kw,
        )

    def failsafe(kind: str, rule: str) -> dict[str, Any]:  # decision (4): treated as reporting inside the window
        return dict(
            kind=kind,
            next=None,
            timing=None,
            window_open=None,
            close_by=str(exe),
            close_by_short=str(exe),
            close_by_long=str(exe),
            unknown=True,
            in_window=True,
            no_short=True,
            no_long_add=True,
            close_long=True,
            long_exception=False,
            h7_flag=True,
            rule=rule,
        )

    for s in names:
        if s in etfs:
            out[s] = dict(
                kind="etf_exempt",
                next=None,
                timing=None,
                close_by=None,
                unknown=False,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
                rule="ETF exempt",
            )
            continue
        # main calendar: next unreleased event
        m = None
        if events is not None:
            upcoming = events[(events["symbol"] == s) & (events["d"] >= exe - dt.timedelta(days=7))].sort_values("d")
            upcoming_rows = [r for _, r in upcoming.iterrows() if not released(r, now)]
            if upcoming_rows:
                m = upcoming_rows[0]
        n = (nxt or {}).get(s)
        if n is not None and n["status"] == "confirmed" and n["earliest"] < today:
            n = None  # past confirmed date: released, no next date in this row
        if events is None:  # main calendar stale/missing
            if policy == POLICY_RULING:
                out[s] = failsafe(
                    "failsafe_calendar_stale_or_missing", "decision(4): main calendar stale/missing -> full fail-safe"
                )
                continue
            out[s] = unknown("unknown_calendar", "strict: calendar stale/missing -> unknown")
            continue
        # candidate dates (decision 5: earliest across sources)
        cand = []
        if m is not None:
            # Stored announce_date_et is unbuffered; buffer applies only in estimated branch below.
            cand.append(("calendar", m["d"], str(m["timing"]), calendar_next_status(m["source"]), str(m["source"])))
        if n is not None and not (policy == POLICY_STRICT and n["status"] != "confirmed"):
            cand.append(("next_earnings", n["earliest"], n["timing"], n["status"], n["source"]))
        if not cand:
            if policy == POLICY_RULING:
                if nxt is None and ninfo is not None:
                    out[s] = failsafe(
                        "failsafe_next_file_unusable",
                        f"decision(4): no main-calendar date and next_earnings file unusable ({ninfo.get('reason')})",
                    )
                else:
                    out[s] = failsafe(
                        "failsafe_no_row",
                        "decision(4): no date row in main calendar or next_earnings -> full fail-safe",
                    )
                continue
            kind = "unknown_estimated_only" if (nxt or {}).get(s) else "unknown_no_upcoming_date"
            out[s] = unknown(
                kind,
                "strict: no confirmed date -> unknown (tradable no new/increased short; shadow flag)",
                estimated_next=str(nxt[s]["earliest"]) if (nxt or {}).get(s) else None,
            )
            continue
        # Earliest date wins. Prefer confirmed only on the *same* date when true company evidence exists.
        # Do NOT let a later main-calendar forecast override an earlier sidecar estimate.
        src, d, timing, status, source = min(cand, key=lambda c: (c[1], 0 if c[3] == "confirmed" else 1, c[0]))
        # Same-date estimated→confirmed promotion ONLY if a confirmed candidate shares that exact date
        # (sidecar company confirmation). Main-calendar forecasts never supply that confirmed candidate.
        if status == "estimated" and any(c[1] == d and c[3] == "confirmed" for c in cand):
            src, d, timing, status, source = next(c for c in cand if c[1] == d and c[3] == "confirmed")
        last8 = max([x for x in (_last_8k(events, s, today), (n or {}).get("last_8k_202")) if x] or [None])
        if status == "confirmed":
            inw = d <= end
            close_by = d if timing == "AMC" else prev_session(d)
            out[s] = dict(
                kind="known",
                status_basis=f"confirmed ({src})",
                next=str(d),
                timing=timing,
                source=source,
                window_open=str(sessions_before(d, CONFIRMED_FLAG_SESSIONS)),
                close_by=str(close_by),
                close_by_short=str(close_by),
                close_by_long=str(close_by),
                unknown=False,
                in_window=bool(inw),
                no_short=bool(inw),
                no_long_add=bool(inw and s not in exc),
                close_long=bool(inw and s not in exc),
                long_exception=s in exc,
                h7_flag=bool(sessions_before(d, CONFIRMED_FLAG_SESSIONS) <= exe),
                last_8k_202=str(last8) if last8 else None,
                rule="decision(1)/H7 confirmed date" if policy == POLICY_RULING else "strict: confirmed date",
            )
            continue
        # ESTIMATED (decision policy only)
        wopen = sessions_before(d, CONFIRMED_FLAG_SESSIONS + EST_BUFFER_SESSIONS)
        buffered = sessions_before(d, EST_BUFFER_SESSIONS)
        cbs, cbl = prev_session(wopen), prev_session(buffered)
        inw = wopen <= end
        recent = last8 is not None and (today - last8).days <= RECENT_8K_DAYS
        base: dict[str, Any] = dict(
            status_basis=f"estimated ({src}; earliest of {', '.join((n or {}).get('candidates') or [str(d)])})",
            next=str(d),
            timing=timing,
            source=source,
            window_open=str(wopen),
            buffered_release=str(buffered),
            close_by=str(cbs),
            close_by_short=str(cbs),
            close_by_long=str(cbl),
            long_exception=s in exc,
            h7_flag=bool(wopen <= exe),
            last_8k_202=str(last8) if last8 else None,
            last_8k_age_days=(today - last8).days if last8 else None,
        )
        if inw:
            out[s] = dict(
                base,
                kind="known_estimated_in_window",
                unknown=False,
                in_window=True,
                no_short=True,
                no_long_add=s not in exc,
                close_long=bool(buffered <= end and s not in exc),
                rule="decision(2): estimated; buffered window opens within horizon -> shorts closed before window_open, no new/added risk",
            )
        elif recent:
            out[s] = dict(
                base,
                kind="known_estimated_outside_window",
                unknown=False,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
                rule="decision(3): 8-K 2.02 <= 45d and window_open after horizon -> known, not in window",
            )
        else:
            out[s] = dict(
                base,
                kind="unknown_estimated_no_recent_8k",
                unknown=True,
                in_window=False,
                no_short=False,
                no_long_add=False,
                close_long=False,
                rule="decision(3) not met (8-K 2.02 missing or > 45d) -> unknown",
            )
    return out, info


def close_by_for(g: Any, sign: Any) -> Any:
    """Side-specific exit session: shorts (sign < 0) close_by_short, longs close_by_long, flat -> earliest of the two."""
    cs, cl = g.get("close_by_short", g.get("close_by")), g.get("close_by_long", g.get("close_by"))
    if sign < 0:
        return cs
    if sign > 0:
        return cl
    return min(x for x in (cs, cl) if x) if (cs or cl) else None
