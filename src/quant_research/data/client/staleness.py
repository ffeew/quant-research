"""Minimal staleness records: one JSON per dataset in $QR_DATA_DIR/staleness/<dataset>.json.
Pipelines call record(name) after committing data. Check all: python lib/staleness.py  (exit 1 if any STALE/MISSING).
latest_observation = max of an observation column read from the parquet (not mtime). No local scheduler exists on this box.

File selection (important): DATASETS globs are NOT trusted as lexicographic "latest filename wins".
Frozen one-offs were sometimes named by build day (e.g. vix_vix3m_daily_20261030 with obs through 2026-10-28)
while updaters name by last_session (…_20261104). Lex sort can therefore prefer an older build over a
newer session file once dates collide oddly, or the reverse hazard when a build-dated file sorts after a
session-dated one. Prefer optional SOURCE_FILES → LATEST.json (path+sha256) when present; otherwise pick
the candidate whose observation column actually maximizes. Keep DATASETS tuples backwards-compatible.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, cast

import exchange_calendars as xc
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

DATA = Path(f"{_QR.DATA_DIR}")
OUT = DATA / "staleness"
SGT, ET = dt.timezone(dt.timedelta(hours=8)), "America/New_York"
# name: (path or glob, obs column, expectation, mechanism)
#   expectation: "session"=last XNYS session completed by cutoff ET hh:mm; "session_lag1"=prior session; "snapshot_et_today"=snapshot date
#   ET >= today's ET date at/after cutoff on sessions
DATASETS = {
    "index_sp500": (
        "index/sp500/sp500_index_daily_*.parquet",
        "session_date",
        ("session", "16:50"),
        "Grok Bot routine 16:50 ET (update_sp500_index.py)",
    ),
    "bars_daily": (
        "bars/daily/adjusted/SPY.parquet",
        "session_date",
        ("session", "19:30"),
        "manual daily_bars.py; no scheduler",
    ),
    "total_return": (
        "bars/daily/total_return/daily_total_return.parquet",
        "session_date",
        ("session", "19:30"),
        "manual total_return.py; no scheduler",
    ),
    "vix_vix3m": (
        "sentiment/vix/vix_vix3m_daily_*.parquet",
        "session_date",
        ("session", "19:30"),
        "manual update_vix_vix3m.py; no scheduler",
    ),
    "credit_oas": (
        "sentiment/credit/credit_vintages_*.parquet",
        "observation_date",
        ("session_lag1", "10:30"),
        "manual alfred_store.py credit; no scheduler",
    ),
    "earnings_forward": (
        "earnings/forward/snapshots/*.parquet",
        "snapshot_date_utc",
        ("snapshot_et_today", "06:30"),
        "Grok Bot routine 06:30 ET (earnings_forward.py)",
    ),
    "earnings_next_sidecar": (
        "earnings/next_earnings/next_earnings_2*.parquet",
        "asof_session_et",
        ("session", "19:30"),
        "manual earnings/next_earnings/raw_<date>/{fetch,scrape,ic,ir,build_nasdaq_hits,build}.py; no scheduler",
    ),
    "assets_borrow": (
        "assets/snapshots/assets_*.parquet",
        "snapshot_date_et",
        ("snapshot_et_today", "08:00"),
        "Grok Bot routine 08:00 ET (assets_snapshot.py)",
    ),
    "earnings_gate_calendar": (
        "earnings/gate/nasdaq_calendar_*.parquet",
        "fetched_at_utc",
        ("session", "06:30"),
        "Grok Bot routine 06:30 ET (pipelines/earnings_gate_refresh.py)",
    ),
}
# Optional: relative path to a LATEST.json written by the dataset's updater (path + sha256).
# When present and valid, that exact file is used. Datasets without an entry keep glob fallback.
SOURCE_FILES = {
    "index_sp500": "index/sp500/LATEST.json",
    "vix_vix3m": "sentiment/vix/LATEST.json",
    "earnings_next_sidecar": "earnings/next_earnings/LATEST.json",
    "earnings_gate_calendar": "earnings/gate/LATEST_STALENESS.json",
}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _expected(kind: str, cutoff: str, now: dt.datetime) -> tuple[str, str]:
    cal = xc.get_calendar("XNYS")
    n = pd.Timestamp(now).tz_convert(ET)
    hh, mm = map(int, cutoff.split(":"))
    d = n.normalize().tz_localize(None)
    if kind == "snapshot_et_today":
        return (d if n.time() >= dt.time(hh, mm) else d - pd.Timedelta(days=1)).date().isoformat(), f"daily {cutoff} ET"
    s = cal.sessions_in_range(d - pd.Timedelta(days=14), d)
    if s[-1] == d and n.time() < dt.time(hh, mm):
        s = s[:-1]
    if kind == "session_lag1":
        s = s[:-1]
    return s[-1].date().isoformat(), f"{cutoff} ET after session close"


def _us_trading_days_between_et(t0: pd.Timestamp | dt.datetime, t1: pd.Timestamp | dt.datetime) -> int:
    """Count XNYS sessions in (ET-date(t0), ET-date(t1)] — same contract as portfolio/risk_state.us_trading_days_between."""
    cal = xc.get_calendar("XNYS")
    d0 = pd.Timestamp(t0).tz_convert(ET).date()
    d1 = pd.Timestamp(t1).tz_convert(ET).date()
    if d1 <= d0:
        return 0
    s = cal.sessions_in_range(pd.Timestamp(d0) + pd.Timedelta(days=1), pd.Timestamp(d1))
    return int(len(s))


def _obs_max(p: Path, col: str) -> str:
    """Max observation date from parquet column.
    For fetched_at_utc timestamps, convert to America/New_York before taking .date()
    so early-UTC next calendar day still maps to the prior ET session date (aligns with
    portfolio/risk_state.us_trading_days_between). Other columns keep naive/UTC .date().
    """
    v = pd.read_parquet(p, columns=[col])[col]
    ts = pd.to_datetime(v.astype(str), utc=(col == "fetched_at_utc"), format="mixed")
    if col == "fetched_at_utc":
        return str(ts.max().tz_convert(ET).date())
    return str(ts.max().date())


def _under_data(p: Path) -> bool:
    try:
        p.resolve().relative_to(DATA.resolve())
        return True
    except ValueError:
        return False


def _from_latest(name: str, col: str) -> tuple[Path, str, str, dict[str, Any]] | None:
    """Return (path, sha, latest_obs, meta) from SOURCE_FILES LATEST.json, or None if unusable."""
    rel = SOURCE_FILES.get(name)
    if not rel:
        return None
    lp = DATA / rel
    if not lp.is_file():
        return None
    L = json.loads(lp.read_text())
    raw = L.get("path")
    expect_sha = L.get("sha256")
    if not raw or not expect_sha:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = DATA / p
    if not _under_data(p):
        raise ValueError(f"LATEST path escapes DATA: {p}")
    if not p.is_file():
        raise FileNotFoundError(f"LATEST path missing: {p}")
    got = _sha(p)
    if got != expect_sha:
        raise ValueError(f"LATEST sha256 mismatch for {p}: latest={expect_sha} file={got}")
    lo = _obs_max(p, col)
    meta = {
        "source": "LATEST.json",
        "latest_json": str(lp),
        "latest_last_session_date": L.get("last_session_date"),
        "pending_completed_sessions": L.get("pending_completed_sessions")
        or (L.get("validation") or {}).get("checks", {}).get("pending_completed_sessions")
        or [],
        "target_completed": L.get("target_completed")
        or (L.get("validation") or {}).get("target_completed")
        or (L.get("validation") or {}).get("target"),
    }
    return p, got, lo, meta


def _from_glob(pat: str, col: str) -> tuple[Path, str, str, dict[str, Any]]:
    """Fallback: among glob matches, pick the file with the greatest observation (not lex name)."""
    files = sorted(DATA.glob(pat))
    if not files:
        raise FileNotFoundError(pat)
    best_p: Path | None = None
    best_lo: str | None = None
    for p in files:
        lo = _obs_max(p, col)
        if best_p is None or best_lo is None or lo > best_lo or (lo == best_lo and p.name > best_p.name):
            best_p, best_lo = p, lo
    chosen = cast(Path, best_p)
    return chosen, _sha(chosen), cast(str, best_lo), {"source": "glob_max_observation", "candidates": len(files)}


def record(name: str, now: dt.datetime | None = None) -> dict[str, Any]:
    pat, col, (kind, cutoff), mech = DATASETS[name]
    now = now or dt.datetime.now(dt.UTC)
    r: dict[str, Any] = {
        "dataset": name,
        "mechanism": mech,
        "checked_at_utc": now.isoformat(timespec="seconds"),
        "checked_at_sgt": now.astimezone(SGT).strftime("%Y-%m-%d %H:%M:%S SGT"),
    }
    try:
        exp, dl = _expected(kind, cutoff, now)
        r.update(expected_latest=exp, expected_by=dl)
        resolved = _from_latest(name, col)
        if resolved is None:
            resolved = _from_glob(pat, col)
        p, digest, lo, meta = resolved
        r.update(
            path=str(p), sha256=digest, latest_observation=lo, status="FRESH" if lo >= exp else "STALE", selection=meta
        )
        pending = meta.get("pending_completed_sessions") or []
        if pending:
            r["pending_completed_sessions"] = pending
            r["warnings"] = [
                *r.get("warnings", []),
                f"Cboe/source pending completed sessions {pending} "
                f"(cutoff {cutoff} ET may still show FRESH on prior session; after cutoff expect STALE until published)",
            ]
        # Informational gate age (does NOT flip FRESH/STALE; gate fail-safe uses age>1).
        if name == "earnings_gate_calendar" and r.get("status") in ("FRESH", "STALE") and p is not None:
            try:
                fet = pd.to_datetime(
                    pd.read_parquet(p, columns=["fetched_at_utc"])["fetched_at_utc"], utc=True, format="mixed"
                ).max()
                age = _us_trading_days_between_et(fet, now)
                r["gate_age_us_trading_days"] = age
                r["gate_fetched_at_utc"] = fet.isoformat()
                r["gate_stale_threshold"] = 1
                if age > 1:
                    r.setdefault("warnings", []).append(
                        f"gate load_calendar would FAIL-SAFE (age_us_trading_days={age} > 1); "
                        f"staleness expected source-session uses scheduled {cutoff} ET retrieval; expected={exp}; NOT Risk permission"
                    )
            except Exception as ge:
                r.setdefault("warnings", []).append(f"gate age calc failed: {type(ge).__name__}: {ge}")
        # Surface target vs available lag even when FRESH under a conservative pre-cutoff expected.
        tc = meta.get("target_completed")
        if tc and lo < str(tc):
            r.setdefault("warnings", []).append(
                f"latest_observation {lo} behind target_completed {tc} (publication lag; not treated as invented)"
            )
    except Exception as e:
        r.update(path=str(DATA / pat), latest_observation=None, status="MISSING", error=f"{type(e).__name__}: {e}")
    OUT.mkdir(exist_ok=True)
    tmp = OUT / f".{name}.tmp"
    tmp.write_text(json.dumps(r, indent=1))
    tmp.replace(OUT / f"{name}.json")
    print(
        f"STALENESS {name}: {r['status']} latest={r.get('latest_observation')} expected={r.get('expected_latest')} ({r['checked_at_sgt']})",
        file=sys.stderr,
    )
    return r


if __name__ == "__main__":
    rs = [record(n) for n in (sys.argv[1:] or DATASETS)]
    sys.exit(1 if any(r["status"] != "FRESH" for r in rs) else 0)
