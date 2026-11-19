#!/usr/bin/env python3
"""Daily updater for Cboe VIX + VIX3M history (data-owned).

Run:
    $QR_DATA_DIR/.venv/bin/python $QR_DATA_DIR/pipelines/update_vix_vix3m.py

Primary source: Cboe official daily history CSVs
  https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
  https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv
(redirect to cdn-api.cboe.com; HTTP 200 required after redirects; modest retries).
Yahoo ^VIX / ^VIX3M are optional cross-checks only — never substituted into Cboe values.

Behavior
  1. Reads sentiment/vix/LATEST.json or bootstraps from the frozen 20261030 builds.
     Never modifies or deletes existing parquet snapshots.
  2. Target = last COMPLETED XNYS session (after 16:15 America/New_York). Never appends
     a partial/intraday day. Advances only through sessions actually present in Cboe
     (contiguous prefix); if Cboe lags the completed target, writes what is published
     and/or exits pending — never invents rows.
  3. Keeps non-XNYS Cboe VIX holiday/GTH prints flagged (is_xnys_session=False), matching
     the original build. VIX3M is left null on those rows.
  4. Frozen overlap rows are carried unchanged; Cboe restatements on overlap are reported
     explicitly (not silently applied, not silently dropped).
  5. Writes NEW read-only files:
       vix_vix3m_daily_<YYYYMMDD>.parquet
       vix_daily_<YYYYMMDD>.parquet
     plus LATEST.json, SHA256SUMS_vix_<YYYYMMDD>.txt, and a dated QA log under data/qa/.
  6. Records staleness via lib/staleness.py (never changes exit code).

Exit codes
  0  ok / already up to date (no change)
  2  validation failed
  3  source pending (Cboe has not published a needed completed session)
  4  output conflict (dated file exists with different sha256)
  5  fetch error
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import traceback
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import exchange_calendars as xc
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ET, SGT, UTC = "America/New_York", "Asia/Singapore", "UTC"
CLOSE_KNOWN = pd.Timedelta(hours=16, minutes=15)  # VIX/VIX3M official close
SESSION_OPEN = pd.Timedelta(hours=9, minutes=30)
WINDOW_START = dt.date(2005, 1, 3)
VIX3M_START = dt.date(2009, 9, 18)
BOOTSTRAP_COMBO = "vix_vix3m_daily_20261030.parquet"
BOOTSTRAP_VIX = "vix_daily_20261030.parquet"
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
CBOE_VIX3M_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv"
UA = {"User-Agent": "Mozilla/5.0 (cio-desk vix-vix3m updater)"}
SOURCE = "cboe_daily_prices_csv"
SOURCE_VIX_ONLY = "cboe_vix_history_csv"
KNOTE = (
    "VIX official close (and day OHLC) known after 16:15 ET on session_date; "
    "use for decisions at/after next session open"
)
YAHOO_CLOSE_TOL = 0.05
HTTP_RETRIES = 4
HTTP_BACKOFF = 2.0


class Fail(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)


def atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    atomic_write_bytes(path, text.encode(), mode=mode)


def last_completed_session(cal: Any, now_utc: pd.Timestamp) -> dt.date:
    """Last XNYS session whose 16:15 ET official VIX close has passed."""
    now_et = now_utc.tz_convert(ET)
    d = pd.Timestamp(now_et.date())
    s = d if cal.is_session(d) else cal.date_to_session(d, direction="previous")
    if s == d and now_et < (d.tz_localize(ET) + CLOSE_KNOWN):
        s = cal.previous_session(s)
    return s.date()


def http_get(url: str, timeout: int = 90) -> requests.Response:
    """GET with redirects, strict final HTTP 200, modest retries on 429/5xx/network."""
    delay = HTTP_BACKOFF
    last_err: Exception | None = None
    for _attempt in range(HTTP_RETRIES):
        try:
            r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        except requests.RequestException as e:
            last_err = e
            time.sleep(delay)
            delay = min(delay * 2, 30)
            continue
        # Reject non-200 final status (after redirects). 3xx without final 200 is a failure.
        if r.status_code in (429,) or r.status_code >= 500:
            last_err = RuntimeError(f"HTTP {r.status_code} for {url}")
            time.sleep(delay)
            delay = min(delay * 2, 30)
            continue
        if r.status_code != 200:
            raise Fail(5, f"HTTP {r.status_code} for {url} (final URL {r.url}); refusing non-200 body")
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "csv" not in ctype and "text/plain" not in ctype and "octet-stream" not in ctype:
            # Cboe serves text/csv; reject HTML error pages that slipped through as 200
            head = r.content[:200].lstrip().lower()
            if head.startswith(b"<!doctype") or head.startswith(b"<html"):
                raise Fail(5, f"HTTP 200 but HTML body for {url} (Content-Type={ctype!r})")
        return r
    raise Fail(5, f"fetch failed for {url} after {HTTP_RETRIES} attempts: {last_err}")


def parse_last_modified(resp: requests.Response) -> pd.Timestamp | None:
    lm = resp.headers.get("Last-Modified")
    if not lm:
        return None
    try:
        t = parsedate_to_datetime(lm)
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.UTC)
        return pd.Timestamp(t).tz_convert(ET)
    except Exception:
        return None


def load_cboe_csv(content: bytes, label: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Parse Cboe OHLC CSV. Official files are oldest→newest (verified); we sort defensively."""
    text = content.decode("utf-8-sig")
    df = pd.read_csv(io.StringIO(text))
    cols = {c.upper(): c for c in df.columns}
    for need in ("DATE", "OPEN", "HIGH", "LOW", "CLOSE"):
        if need not in cols:
            raise Fail(5, f"{label} CSV missing column {need}; got {list(df.columns)}")
    out = pd.DataFrame(
        {
            "session_date": pd.to_datetime(df[cols["DATE"]], format="%m/%d/%Y").dt.date,
            "open": pd.to_numeric(df[cols["OPEN"]], errors="coerce"),
            "high": pd.to_numeric(df[cols["HIGH"]], errors="coerce"),
            "low": pd.to_numeric(df[cols["LOW"]], errors="coerce"),
            "close": pd.to_numeric(df[cols["CLOSE"]], errors="coerce"),
        }
    )
    info: dict[str, Any] = {
        "rows_raw": int(len(out)),
        "date_min": str(out.session_date.min()) if len(out) else None,
        "date_max": str(out.session_date.max()) if len(out) else None,
        "monotonic_ascending": bool(pd.Series(out.session_date).is_monotonic_increasing),
        "monotonic_descending": bool(pd.Series(out.session_date).is_monotonic_decreasing),
        "duplicate_dates_raw": int(out.session_date.duplicated().sum()),
    }
    # Dedupe: sort by date then file order, keep last per date (original rule; removes nothing when clean)
    out = out.reset_index(drop=True)
    out["_ord"] = np.arange(len(out))
    out = out.sort_values(["session_date", "_ord"]).drop_duplicates("session_date", keep="last")
    out = out.drop(columns=["_ord"]).sort_values("session_date").reset_index(drop=True)
    info["rows_after_dedupe"] = int(len(out))
    info["duplicate_dates_removed"] = info["rows_raw"] - info["rows_after_dedupe"]
    return out, info


def fetch_yahoo_closes(symbol: str, start: dt.date, end: dt.date) -> pd.Series | None:
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        h = t.history(start=str(start), end=str(end + dt.timedelta(days=1)), auto_adjust=False)
        if h is None or h.empty:
            return None
        s = h["Close"].copy()
        s.index = pd.to_datetime(s.index).tz_localize(None).date
        s.name = symbol
        return s  # type: ignore[no-any-return]  # yfinance Close series
    except Exception as e:
        print(f"WARNING: Yahoo {symbol} fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def ohlc_inconsistent(o: Any, h: Any, l: Any, c: Any) -> bool:
    if any(pd.isna(x) for x in (o, h, l, c)):
        return True
    return bool((l > h) or (l > o + 1e-9) or (l > c + 1e-9) or (h < o - 1e-9) or (h < c - 1e-9))


def next_session_open(cal: Any, session_date: dt.date) -> pd.Timestamp:
    d = pd.Timestamp(session_date)
    if cal.is_session(d):
        nxt = cal.next_session(d)
    else:
        # holiday print: first usable is the next session's open
        nxt = cal.date_to_session(d, direction="next")
        if nxt.date() == session_date:
            nxt = cal.next_session(nxt)
    return pd.Timestamp(nxt.date()).tz_localize(ET) + SESSION_OPEN


def close_available_ts(session_date: dt.date) -> pd.Timestamp:
    return pd.Timestamp(session_date).tz_localize(ET) + CLOSE_KNOWN


def _num(value: Any) -> float:
    return float(value)


def flag_join(parts: list[str]) -> str:
    return ";".join(p for p in parts if p)


def build_new_combo_rows(
    dates: list[dt.date],
    vix: pd.DataFrame,
    vix3m: pd.DataFrame,
    cal: Any,
    yahoo_vix: pd.Series | None,
    yahoo_vix3m: pd.Series | None,
    fetched_vix: pd.Timestamp,
    fetched_vix3m: pd.Timestamp,
) -> pd.DataFrame:
    vix_m = vix.set_index("session_date")
    v3_m = vix3m.set_index("session_date")
    rows = []
    for d in dates:
        if d not in vix_m.index:
            raise Fail(2, f"internal: requested date {d} missing from VIX map")
        vr = vix_m.loc[d]
        is_xnys = bool(cal.is_session(pd.Timestamp(d)))
        parts = []
        if not is_xnys:
            parts.append("non_nyse_date_cboe_gth_or_holiday_print")
        v3 = v3_m.loc[d] if d in v3_m.index else None
        if v3 is None:
            parts.append("vix3m_missing")
            v3o = v3h = v3l = v3c = np.nan
        else:
            v3o, v3h, v3l, v3c = _num(v3.open), _num(v3.high), _num(v3.low), _num(v3.close)
        if ohlc_inconsistent(vr.open, vr.high, vr.low, vr.close):
            parts.append("vix_ohlc_inconsistent")
        if v3 is not None and ohlc_inconsistent(v3o, v3h, v3l, v3c):
            parts.append("vix3m_ohlc_inconsistent")
        yv = _num(yahoo_vix.loc[d]) if yahoo_vix is not None and d in yahoo_vix.index else np.nan
        y3 = _num(yahoo_vix3m.loc[d]) if yahoo_vix3m is not None and d in yahoo_vix3m.index else np.nan
        if pd.notna(yv) and abs(_num(vr.close) - yv) > YAHOO_CLOSE_TOL:
            parts.append("vix_close_vs_yahoo_gt0.05")
        if pd.notna(y3) and pd.notna(v3c) and abs(v3c - y3) > YAHOO_CLOSE_TOL:
            parts.append("vix3m_close_vs_yahoo_gt0.05")
        # ratios: null before VIX3M / on non-NYSE / when vix3m missing (matches original)
        if is_xnys and pd.notna(v3c) and _num(v3c) != 0.0:
            ratio = _num(vr.close) / _num(v3c)
            ratio_o = _num(vr.open) / _num(v3o) if pd.notna(v3o) and _num(v3o) != 0.0 else np.nan
        else:
            ratio = np.nan
            ratio_o = np.nan
        ca = close_available_ts(d)
        fu = next_session_open(cal, d)
        rows.append(
            {
                "session_date": d,
                "is_xnys_session": is_xnys,
                "vix_open": _num(vr.open),
                "vix_high": _num(vr.high),
                "vix_low": _num(vr.low),
                "vix_close": _num(vr.close),
                "vix3m_open": v3o,
                "vix3m_high": v3h,
                "vix3m_low": v3l,
                "vix3m_close": v3c,
                "vix_vix3m": ratio,
                "vix_vix3m_open": ratio_o,
                "qa_flag": flag_join(parts),
                "vix_yahoo_close": yv,
                "vix3m_yahoo_close": y3,
                "close_available_et": ca,
                "close_available_utc": ca.tz_convert(UTC),
                "close_available_sgt": ca.tz_convert(SGT),
                "close_available_et_str": ca.strftime("%Y-%m-%d %H:%M %Z"),
                "close_available_sgt_str": ca.tz_convert(SGT).strftime("%Y-%m-%d %H:%M SGT"),
                "first_usable_session_open_et": fu,
                "source": SOURCE,
                "fetched_at_utc": fetched_vix,
                "vix3m_fetched_at_utc": fetched_vix3m,
                "csv_update_observed_et": pd.NaT,
            }
        )
    return pd.DataFrame(rows)


def build_new_vix_daily_rows(
    dates: list[dt.date],
    vix: pd.DataFrame,
    cal: Any,
    yahoo_vix: pd.Series | None,
    fetched_vix: pd.Timestamp,
) -> pd.DataFrame:
    vix_m = vix.set_index("session_date")
    rows = []
    for d in dates:
        vr = vix_m.loc[d]
        is_xnys = bool(cal.is_session(pd.Timestamp(d)))
        parts = []
        if not is_xnys:
            parts.append("non_nyse_date_cboe_gth_or_holiday_print")
        if ohlc_inconsistent(vr.open, vr.high, vr.low, vr.close):
            parts.append("ohlc_inconsistent")
        # open_equals_prev_close is history-only artifact; not re-derived for new rows unless true vs prior
        yv = _num(yahoo_vix.loc[d]) if yahoo_vix is not None and d in yahoo_vix.index else np.nan
        xdiff = (_num(vr.close) - yv) if pd.notna(yv) else np.nan
        if pd.notna(xdiff) and abs(xdiff) > YAHOO_CLOSE_TOL:
            parts.append("close_vs_yahoo_gt0.05")
        ca = close_available_ts(d)
        rows.append(
            {
                "session_date": d,
                "open": _num(vr.open),
                "high": _num(vr.high),
                "low": _num(vr.low),
                "close": _num(vr.close),
                "source": SOURCE_VIX_ONLY,
                "knowledge_time_utc": ca.tz_convert(UTC),
                "knowledge_time_note": KNOTE,
                "yahoo_close": yv,
                "xcheck_close_diff_vs_yahoo": xdiff,
                "is_xnys_session": is_xnys,
                "qa_flag": flag_join(parts),
                "fetched_at_utc": fetched_vix,
            }
        )
    return pd.DataFrame(rows)


def validate_frame(combo: pd.DataFrame, cal: Any, last: dt.date, available: dt.date, want: dt.date) -> dict[str, Any]:
    v: dict[str, Any] = {
        "target_completed": str(want),
        "available_through": str(available),
        "checks": {},
        "warnings": [],
        "failures": [],
    }
    # duplicates
    dups = combo.session_date[combo.session_date.duplicated()].tolist()
    v["checks"]["duplicate_dates"] = [str(x) for x in dups]
    # nonnegativity / non-positive
    for prefix, cols in (
        ("vix", ["vix_open", "vix_high", "vix_low", "vix_close"]),
        ("vix3m", ["vix3m_open", "vix3m_high", "vix3m_low", "vix3m_close"]),
    ):
        sub = combo[cols]
        bad = combo.index[((sub <= 0) & sub.notna()).any(axis=1)].tolist()
        v["checks"][f"{prefix}_nonpositive_rows"] = [str(combo.loc[i, "session_date"]) for i in bad]
    # OHLC bounds
    vix_bad = []
    v3_bad = []
    for r in combo.itertuples():
        if ohlc_inconsistent(r.vix_open, r.vix_high, r.vix_low, r.vix_close):
            # known historical exception kept flagged
            if str(r.session_date) != "2006-02-08":
                vix_bad.append(str(r.session_date))
        if pd.notna(r.vix3m_close) and ohlc_inconsistent(r.vix3m_open, r.vix3m_high, r.vix3m_low, r.vix3m_close):  # type: ignore[arg-type]  # vix3m cells are numeric
            v3_bad.append(str(r.session_date))
    v["checks"]["vix_ohlc_inconsistent_new_or_unflagged"] = vix_bad
    v["checks"]["vix3m_ohlc_inconsistent"] = v3_bad
    # missing XNYS sessions inside window through available
    sessions = [s.date() for s in cal.sessions_in_range(str(WINDOW_START), str(available))]
    have = set(combo.loc[combo.is_xnys_session, "session_date"])
    miss = [str(s) for s in sessions if s not in have]
    v["checks"]["missing_nyse_sessions"] = miss
    # ratio sanity on XNYS rows with both closes
    both = combo[combo.is_xnys_session & combo.vix3m_close.notna()].copy()
    if len(both):
        calc = both.vix_close / both.vix3m_close
        bad_r = both.index[(both.vix_vix3m - calc).abs() > 1e-9].tolist()
        v["checks"]["ratio_mismatch_rows"] = [str(combo.loc[i, "session_date"]) for i in bad_r]
        v["checks"]["ratio_min"] = float(both.vix_vix3m.min())
        v["checks"]["ratio_max"] = float(both.vix_vix3m.max())
        v["checks"]["ratio_median"] = float(both.vix_vix3m.median())
    else:
        v["checks"]["ratio_mismatch_rows"] = []
    # new-session coverage
    new = combo[combo.session_date > last]
    v["checks"]["new_rows"] = int(len(new))
    v["checks"]["new_xnys_sessions"] = [str(x) for x in new.loc[new.is_xnys_session, "session_date"]]
    v["checks"]["new_non_xnys_rows"] = [str(x) for x in new.loc[~new.is_xnys_session, "session_date"]]
    pending = [str(s.date()) for s in cal.sessions_in_range(str(available), str(want))][1:] if available < want else []
    v["checks"]["pending_completed_sessions"] = pending

    fails = []
    if v["checks"]["duplicate_dates"]:
        fails.append(f"duplicate dates {v['checks']['duplicate_dates']}")
    if v["checks"]["vix_nonpositive_rows"] or v["checks"]["vix3m_nonpositive_rows"]:
        fails.append("non-positive OHLC values present")
    if v["checks"]["missing_nyse_sessions"]:
        fails.append(f"missing NYSE sessions ({len(v['checks']['missing_nyse_sessions'])})")
    if v["checks"]["ratio_mismatch_rows"]:
        fails.append(f"ratio mismatch {v['checks']['ratio_mismatch_rows']}")
    # OHLC inconsistent on NEW rows (not the known 2006-02-08) is a hard fail
    new_ohlc = [d for d in vix_bad if d > str(last)] + [d for d in v3_bad if d > str(last)]
    if new_ohlc:
        fails.append(f"OHLC inconsistent on new rows {new_ohlc}")
    v["failures"] = fails
    v["status"] = "FAIL" if fails else "PASS"
    return v


def compare_overlap(base: pd.DataFrame, vix: pd.DataFrame, vix3m: pd.DataFrame) -> dict[str, Any]:
    """Report Cboe restatements vs frozen overlap (informational; history kept unchanged)."""
    b = base.copy()
    b["session_date"] = pd.to_datetime(b["session_date"]).dt.date
    vm = vix.set_index("session_date")
    v3m = vix3m.set_index("session_date")
    rest: list[dict[str, Any]] = []
    for r in b.itertuples():
        d = r.session_date
        if d not in vm.index:
            rest.append({"session_date": str(d), "field": "vix", "kind": "missing_from_cboe_now"})
            continue
        cur = vm.loc[d]  # type: ignore[index]  # session_date cells are dates
        for col, src in (("vix_open", "open"), ("vix_high", "high"), ("vix_low", "low"), ("vix_close", "close")):
            old, new = float(getattr(r, col)), float(getattr(cur, src))
            if abs(old - new) > 1e-6:
                rest.append({"session_date": str(d), "field": col, "frozen": old, "cboe_now": new, "diff": new - old})
        if pd.notna(r.vix3m_close):  # type: ignore[arg-type]  # vix3m close cells are numeric
            if d not in v3m.index:
                rest.append({"session_date": str(d), "field": "vix3m", "kind": "missing_from_cboe_now"})
            else:
                cur3 = v3m.loc[d]  # type: ignore[index]  # session_date cells are dates
                for col, src in (
                    ("vix3m_open", "open"),
                    ("vix3m_high", "high"),
                    ("vix3m_low", "low"),
                    ("vix3m_close", "close"),
                ):
                    old, new = float(getattr(r, col)), float(getattr(cur3, src))
                    if abs(old - new) > 1e-6:
                        rest.append(
                            {"session_date": str(d), "field": col, "frozen": old, "cboe_now": new, "diff": new - old}
                        )
    return {"restatement_count": len(rest), "restatements": rest[:50], "restatements_truncated": max(0, len(rest) - 50)}


def write_parquet_atomic(
    df: pd.DataFrame, schema: pa.Schema, path: Path, meta_key: bytes, meta_obj: dict[str, Any]
) -> str:
    # Align column order to schema; cast via pandas→arrow using schema
    df = df[[f.name for f in schema]]
    tbl = pa.Table.from_pandas(df, schema=schema.remove_metadata(), preserve_index=False)
    md = dict(schema.metadata or {})
    md[meta_key] = json.dumps(meta_obj, default=str).encode()
    tbl = tbl.replace_schema_metadata(md)
    buf = pa.BufferOutputStream()
    pq.write_table(tbl, buf)
    data = buf.getvalue().to_pybytes()
    digest = sha256_bytes(data)
    if path.exists():
        existing = sha256_file(path)
        if existing == digest:
            return digest
        raise Fail(4, f"{path} already exists with different sha256 ({existing}); not overwriting")
    atomic_write_bytes(path, data, mode=0o444)
    assert sha256_file(path) == digest
    return digest


def determine_available(
    cal: Any,
    last: dt.date,
    want: dt.date,
    vix: pd.DataFrame,
    vix3m: pd.DataFrame,
) -> tuple[dt.date | None, list[dt.date], str | None]:
    """Return (available_through, dates_to_add, pending_reason).

    Dates to add = all Cboe VIX dates in (last, available] (includes non-XNYS prints),
    where available is the latest date <= want such that every XNYS session in (last, available]
    has VIX (and VIX3M if date >= VIX3M_START). Contiguous — no skipping holes.
    """
    vix_dates = set(vix.session_date)
    v3_dates = set(vix3m.session_date)
    need = [s.date() for s in cal.sessions_in_range(str(last), str(want))][1:]
    if not need:
        return None, [], None
    available = last
    for s in need:
        if s not in vix_dates:
            reason = f"Cboe VIX missing completed session {s} (have through {max(vix_dates) if vix_dates else None})"
            if available == last:
                return None, [], reason
            break
        if s >= VIX3M_START and s not in v3_dates:
            reason = f"Cboe VIX3M missing completed session {s} (have through {max(v3_dates) if v3_dates else None})"
            if available == last:
                return None, [], reason
            break
        available = s
    if available == last:
        return None, [], f"no new Cboe sessions at or before completed target {want}"
    # include non-XNYS VIX prints with last < d <= available
    extra = sorted(d for d in vix_dates if last < d <= available and not cal.is_session(pd.Timestamp(d)))
    xnys_add = [s for s in need if last < s <= available]
    dates = sorted(set(xnys_add) | set(extra))
    # never silently drop a Cboe VIX row in the window
    cboe_in_window = sorted(d for d in vix_dates if last < d <= available)
    if cboe_in_window != dates:
        # dates should equal all vix dates in window
        missing = sorted(set(cboe_in_window) - set(dates))
        if missing:
            raise Fail(2, f"refusing to drop valid Cboe VIX rows in window: {missing}")
        dates = cboe_in_window
    return available, dates, None


def write_qa_log(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        f"# VIX/VIX3M QA {payload.get('available_through')} (built {payload.get('built_at_sgt')})",
        "",
        f"- target completed session: `{payload.get('target_completed')}`",
        f"- available through (Cboe): `{payload.get('available_through')}`",
        f"- combo path: `{payload.get('combo_path')}`",
        f"- combo sha256: `{payload.get('combo_sha256')}`",
        f"- vix_daily path: `{payload.get('vix_daily_path')}`",
        f"- vix_daily sha256: `{payload.get('vix_daily_sha256')}`",
        f"- rows: {payload.get('rows')} (prior {payload.get('prior_rows')}; new {payload.get('new_rows')})",
        f"- coverage: {payload.get('coverage_start')} .. {payload.get('coverage_end')}",
        f"- CSV order VIX: ascending={payload.get('vix_csv_info', {}).get('monotonic_ascending')} "
        f"range {payload.get('vix_csv_info', {}).get('date_min')}..{payload.get('vix_csv_info', {}).get('date_max')} "
        f"(official file is oldest→newest; verified)",
        f"- CSV order VIX3M: ascending={payload.get('vix3m_csv_info', {}).get('monotonic_ascending')} "
        f"range {payload.get('vix3m_csv_info', {}).get('date_min')}..{payload.get('vix3m_csv_info', {}).get('date_max')}",
        f"- VIX CSV sha256: `{payload.get('vix_csv_sha256')}` Last-Modified ET: {payload.get('vix_last_modified_et')}",
        f"- VIX3M CSV sha256: `{payload.get('vix3m_csv_sha256')}` Last-Modified ET: {payload.get('vix3m_last_modified_et')}",
        "",
        "## Validation",
        f"- status: **{payload.get('validation', {}).get('status')}**",
        f"- checks: `{json.dumps(payload.get('validation', {}).get('checks', {}), default=str)}`",
        f"- failures: {payload.get('validation', {}).get('failures')}",
        f"- warnings: {payload.get('validation', {}).get('warnings')}",
        "",
        "## Overlap vs prior snapshot (restatements)",
        f"- restatement_count: {payload.get('overlap', {}).get('restatement_count')}",
        f"- sample: `{json.dumps(payload.get('overlap', {}).get('restatements', []), default=str)[:2000]}`",
        "",
        "## Yahoo cross-check (optional)",
        f"- {payload.get('yahoo_xcheck')}",
        "",
        "## Pending",
        f"- {payload.get('validation', {}).get('checks', {}).get('pending_completed_sessions')}",
        "",
    ]
    atomic_write_text(path, "\n".join(lines) + "\n")


def record_staleness() -> None:
    try:
        sys.path.insert(0, f"{_QR.DATA_DIR}/lib")
        from quant_research.data.client import staleness

        staleness.record("vix_vix3m")
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=sys.stderr)


def run_update(dir_path: Path, now_utc: pd.Timestamp, skip_yahoo: bool = False) -> int:
    cal = xc.get_calendar("XNYS", start="1990-01-01")
    latest_p = dir_path / "LATEST.json"
    if latest_p.exists():
        L = json.loads(latest_p.read_text())
        base_path = Path(L["path"])
        if sha256_file(base_path) != L["sha256"]:
            raise Fail(2, f"LATEST.json sha256 does not match {base_path}")
        vix_daily_base = Path(L.get("vix_daily_path") or (dir_path / BOOTSTRAP_VIX))
        if (
            L.get("vix_daily_sha256")
            and vix_daily_base.exists()
            and sha256_file(vix_daily_base) != L["vix_daily_sha256"]
        ):
            raise Fail(2, f"LATEST.json vix_daily sha256 does not match {vix_daily_base}")
    else:
        base_path = dir_path / BOOTSTRAP_COMBO
        vix_daily_base = dir_path / BOOTSTRAP_VIX
        L = None
        if not base_path.exists():
            raise Fail(2, f"missing bootstrap {base_path}")

    base_tbl = pq.read_table(base_path)
    schema = base_tbl.schema
    B = base_tbl.to_pandas()
    B["session_date"] = pd.to_datetime(B["session_date"]).dt.date
    last = max(B.session_date)

    vix_daily_tbl = pq.read_table(vix_daily_base) if vix_daily_base.exists() else None
    vix_daily_schema = vix_daily_tbl.schema if vix_daily_tbl is not None else None
    VD = vix_daily_tbl.to_pandas() if vix_daily_tbl is not None else None
    if VD is not None:
        VD["session_date"] = pd.to_datetime(VD["session_date"]).dt.date

    want = last_completed_session(cal, now_utc)
    hist = (L or {}).get("history", [])
    if L is None:
        L = {
            "path": str(base_path),
            "sha256": sha256_file(base_path),
            "last_session_date": str(last),
            "vix_daily_path": str(vix_daily_base) if vix_daily_base.exists() else None,
            "vix_daily_sha256": sha256_file(vix_daily_base) if vix_daily_base.exists() else None,
            "built_at_utc": None,
            "validation": {"status": "PASS", "note": "original 2026-10-30 build; see README_vix_vix3m_20261030.md"},
        }

    # ---- fetch Cboe (always; needed to detect pending vs no-change and restatements)
    try:
        rv = http_get(CBOE_VIX_URL)
        r3 = http_get(CBOE_VIX3M_URL)
    except Fail:
        raise
    except Exception as e:
        raise Fail(5, f"Cboe fetch error: {type(e).__name__}: {e}")
    fetched_vix = pd.Timestamp.now(tz="UTC").floor("s")
    fetched_vix3m = pd.Timestamp.now(tz="UTC").floor("s")
    vix_csv_sha = sha256_bytes(rv.content)
    vix3m_csv_sha = sha256_bytes(r3.content)
    vix_lm = parse_last_modified(rv)
    vix3m_lm = parse_last_modified(r3)
    vix, vix_info = load_cboe_csv(rv.content, "VIX")
    vix3m, vix3m_info = load_cboe_csv(r3.content, "VIX3M")
    # window filter for primary series (match original)
    vix_w = vix[vix.session_date >= WINDOW_START].copy()
    vix3m_w = vix3m[vix3m.session_date >= VIX3M_START].copy()

    available, dates_to_add, pending_reason = determine_available(cal, last, want, vix_w, vix3m_w)

    if available is None or not dates_to_add:
        # nothing to add
        if not latest_p.exists():
            NL = dict(L)
            NL["updated_at_utc"] = now_utc.isoformat()
            NL["history"] = [{k: L[k] for k in ("path", "sha256", "last_session_date") if k in L}]
            NL["cboe_vix_csv_sha256"] = vix_csv_sha
            NL["cboe_vix3m_csv_sha256"] = vix3m_csv_sha
            NL["cboe_vix_max"] = vix_info["date_max"]
            NL["cboe_vix3m_max"] = vix3m_info["date_max"]
            NL["target_completed"] = str(want)
            atomic_write_text(latest_p, json.dumps(NL, indent=1, default=str) + "\n")
        if want > last:
            raise Fail(
                3,
                f"source not updated yet: {pending_reason}; "
                f"snapshot last={last}, completed target={want}, "
                f"Cboe VIX max={vix_info['date_max']}, VIX3M max={vix3m_info['date_max']}",
            )
        print(f"{L['path']} {L['sha256']} {L['last_session_date']} (already up to date; last completed session {want})")
        return 0

    # ---- yahoo optional
    yahoo_vix = yahoo_vix3m = None
    yahoo_note: Any = "skipped"
    if not skip_yahoo:
        yahoo_vix = fetch_yahoo_closes("^VIX", WINDOW_START, available)
        yahoo_vix3m = fetch_yahoo_closes("^VIX3M", VIX3M_START, available)
        yahoo_note = {
            "vix_rows": None if yahoo_vix is None else int(len(yahoo_vix)),
            "vix3m_rows": None if yahoo_vix3m is None else int(len(yahoo_vix3m)),
        }

    overlap = compare_overlap(B, vix_w, vix3m_w)
    if overlap["restatement_count"]:
        print(
            f"WARNING: Cboe restatements vs frozen overlap: {overlap['restatement_count']} field-level diffs "
            f"(frozen history rows kept unchanged)",
            file=sys.stderr,
        )

    new_combo = build_new_combo_rows(
        dates_to_add, vix_w, vix3m_w, cal, yahoo_vix, yahoo_vix3m, fetched_vix, fetched_vix3m
    )
    # open_equals_prev_close style flag for vix_daily continuity only; combo keeps yahoo flags

    A = pd.concat([B, new_combo], ignore_index=True).sort_values("session_date").reset_index(drop=True)
    if A.session_date.duplicated().any():
        raise Fail(2, "duplicate session_date after append")

    # csv_update_observed_et only on last row (clear any prior last-row value carried from bootstrap)
    A["csv_update_observed_et"] = pd.Series([pd.NaT] * len(A), dtype="datetime64[ns, America/New_York]")
    if vix_lm is not None:
        A.loc[A.index[-1], "csv_update_observed_et"] = vix_lm

    validation = validate_frame(A, cal, last, available, want)
    if overlap["restatement_count"]:
        validation["warnings"].append(
            f"Cboe vs frozen overlap restatements: {overlap['restatement_count']} (history unchanged)"
        )
    validation["overlap_vs_prior"] = overlap
    validation["cboe"] = {
        "vix_url": CBOE_VIX_URL,
        "vix3m_url": CBOE_VIX3M_URL,
        "vix_csv_sha256": vix_csv_sha,
        "vix3m_csv_sha256": vix3m_csv_sha,
        "vix_last_modified_et": None if vix_lm is None else str(vix_lm),
        "vix3m_last_modified_et": None if vix3m_lm is None else str(vix3m_lm),
        "vix_csv_info": vix_info,
        "vix3m_csv_info": vix3m_info,
    }
    validation["yahoo"] = yahoo_note
    if validation["status"] != "PASS":
        raise Fail(2, "VALIDATION FAILED: " + " | ".join(validation["failures"]))

    out_combo = dir_path / f"vix_vix3m_daily_{available:%Y%m%d}.parquet"
    meta_combo = {
        "parent_file": str(base_path),
        "parent_sha256": sha256_file(base_path),
        "built_at_utc": pd.Timestamp.now(tz="UTC").floor("s").isoformat(),
        "sources": {"VIX": CBOE_VIX_URL, "VIX3M": CBOE_VIX3M_URL},
        "vix_csv_sha256": vix_csv_sha,
        "vix3m_csv_sha256": vix3m_csv_sha,
        "validation": validation,
    }
    combo_sha = write_parquet_atomic(A, schema, out_combo, b"vix_vix3m_meta", meta_combo)

    # ---- vix_daily companion
    vix_daily_path = vix_daily_sha = None
    if VD is not None and vix_daily_schema is not None:
        new_vd = build_new_vix_daily_rows(dates_to_add, vix_w, cal, yahoo_vix, fetched_vix)
        # flag open_equals_prev_close relative to appended history
        VD2 = pd.concat([VD, new_vd], ignore_index=True).sort_values("session_date").reset_index(drop=True)
        if VD2.session_date.duplicated().any():
            raise Fail(2, "duplicate session_date in vix_daily after append")
        # preserve prior qa flags; for brand-new rows, add open_equals_prev_close when applicable
        nm = VD2.session_date > last
        prev_close = VD2.close.shift()
        eq = nm & (VD2.open == prev_close)
        VD2.loc[eq, "qa_flag"] = VD2.loc[eq, "qa_flag"].apply(
            lambda s: flag_join([s, "open_equals_prev_close"]) if s else "open_equals_prev_close"
        )
        out_vd = dir_path / f"vix_daily_{available:%Y%m%d}.parquet"
        meta_vd = {
            "source": CBOE_VIX_URL,
            "fetched_at_utc": fetched_vix.isoformat(),
            "csv_sha256": vix_csv_sha,
            "parent_file": str(vix_daily_base),
            "parent_sha256": sha256_file(vix_daily_base),
            "validation": {"status": validation["status"], "new_rows": int(nm.sum())},
        }
        vix_daily_sha = write_parquet_atomic(VD2, vix_daily_schema, out_vd, b"vix_meta", meta_vd)
        vix_daily_path = str(out_vd)

    b_utc = pd.Timestamp.now(tz="UTC").floor("s")
    b_sgt = b_utc.tz_convert(SGT).strftime("%Y-%m-%d %H:%M:%S SGT")
    hist = hist or [{"path": L["path"], "sha256": L["sha256"], "last_session_date": L["last_session_date"]}]
    hist.append({"path": str(out_combo), "sha256": combo_sha, "last_session_date": str(available)})

    qa_name = f"vix_vix3m_qa_{available:%Y%m%d}.md"
    # Prefer shared data/qa when running against the live sentiment/vix tree; else sandbox-local.
    live_qa = Path(f"{_QR.DATA_DIR}/qa")
    qa_path = (
        (live_qa / qa_name)
        if dir_path.resolve() == Path(f"{_QR.DATA_DIR}/sentiment/vix").resolve()
        else (dir_path / "qa" / qa_name)
    )
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_completed": str(want),
        "available_through": str(available),
        "combo_path": str(out_combo),
        "combo_sha256": combo_sha,
        "vix_daily_path": vix_daily_path,
        "vix_daily_sha256": vix_daily_sha,
        "rows": len(A),
        "prior_rows": len(B),
        "new_rows": len(new_combo),
        "coverage_start": str(min(A.session_date)),
        "coverage_end": str(max(A.session_date)),
        "vix_csv_info": vix_info,
        "vix3m_csv_info": vix3m_info,
        "vix_csv_sha256": vix_csv_sha,
        "vix3m_csv_sha256": vix3m_csv_sha,
        "vix_last_modified_et": None if vix_lm is None else str(vix_lm),
        "vix3m_last_modified_et": None if vix3m_lm is None else str(vix3m_lm),
        "validation": validation,
        "overlap": overlap,
        "yahoo_xcheck": yahoo_note,
        "built_at_sgt": b_sgt,
    }
    write_qa_log(qa_path, payload)

    sums_path = dir_path / f"SHA256SUMS_vix_{available:%Y%m%d}.txt"
    sum_lines = [f"{combo_sha}  {out_combo.name}\n"]
    if vix_daily_path:
        sum_lines.append(f"{vix_daily_sha}  {Path(vix_daily_path).name}\n")
    sum_lines.append(f"{vix_csv_sha}  VIX_History.csv\n")
    sum_lines.append(f"{vix3m_csv_sha}  VIX3M_History.csv\n")
    atomic_write_text(sums_path, "".join(sum_lines))

    # save raw CSV evidence (read-only dated copies; do not clobber)
    raw_dir = dir_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    for name, content, digest in (
        (f"VIX_History_{available:%Y%m%d}.csv", rv.content, vix_csv_sha),
        (f"VIX3M_History_{available:%Y%m%d}.csv", r3.content, vix3m_csv_sha),
    ):
        rp = raw_dir / name
        if rp.exists():
            if sha256_file(rp) != digest:
                raise Fail(4, f"raw evidence conflict {rp}")
        else:
            atomic_write_bytes(rp, content, mode=0o444)

    NL = {
        "path": str(out_combo),
        "sha256": combo_sha,
        "last_session_date": str(available),
        "rows": len(A),
        "coverage": {"start": str(min(A.session_date)), "end": str(max(A.session_date))},
        "vix_daily_path": vix_daily_path,
        "vix_daily_sha256": vix_daily_sha,
        "built_at_utc": b_utc.isoformat(),
        "built_at_sgt": b_sgt,
        "target_completed": str(want),
        "pending_completed_sessions": validation["checks"]["pending_completed_sessions"],
        "validation": validation,
        "qa_log": str(qa_path),
        "sha256sums": str(sums_path),
        "cboe_vix_csv_sha256": vix_csv_sha,
        "cboe_vix3m_csv_sha256": vix3m_csv_sha,
        "history": hist,
    }
    atomic_write_text(latest_p, json.dumps(NL, indent=1, default=str) + "\n")
    print(f"{out_combo} {combo_sha} {available}")
    if vix_daily_path:
        print(f"{vix_daily_path} {vix_daily_sha} {available}")
    if validation["checks"]["pending_completed_sessions"]:
        print(
            f"NOTE: still pending completed sessions {validation['checks']['pending_completed_sessions']} "
            f"(Cboe not published yet); wrote latest published through {available}",
            file=sys.stderr,
        )
    return 0


def self_test(dir_path: Path) -> int:
    """Unit tests: no-op, missing/partial Cboe, staleness helper. Uses a temp sandbox."""
    import shutil
    from unittest import mock

    _cal = xc.get_calendar("XNYS", start="1990-01-01")
    failures = []

    # --- staleness helper command on VIX ---
    print("SELFTEST staleness helper…", flush=True)
    import subprocess

    r = subprocess.run(
        [f"{_QR.DATA_DIR}/.venv/bin/python", f"{_QR.DATA_DIR}/lib/staleness.py", "vix_vix3m"],
        capture_output=True,
        text=True,
    )
    # may be STALE (exit 1) or FRESH (0) depending on data; both prove the command works
    if "STALENESS vix_vix3m:" not in (r.stderr + r.stdout):
        failures.append(f"staleness helper did not print status: rc={r.returncode} stderr={r.stderr!r}")
    else:
        print(f"  ok: {r.stderr.strip() or r.stdout.strip()} (exit {r.returncode})")

    # sandbox with copies of bootstrap
    sandbox = Path(tempfile.mkdtemp(prefix="vix_selftest_", dir=None))
    try:
        for name in (BOOTSTRAP_COMBO, BOOTSTRAP_VIX):
            src = dir_path / name
            dst = sandbox / name
            shutil.copy2(src, dst)
            os.chmod(dst, 0o444)

        # --- no-op: now just after 2026-10-28 close, already at last ---
        print("SELFTEST no-op…", flush=True)

        # Build a tiny fake Cboe response ending at 2026-10-28 so determine_available yields nothing new
        def fake_get_noop(url: str, **kw: Any) -> requests.Response:
            if "VIX3M" in url:
                # minimal CSV with last row 10/28/2026 — use real cached if present else synthesize from parquet
                body = Path("/tmp/VIX3M_History.csv").read_bytes() if Path("/tmp/VIX3M_History.csv").exists() else None
                if body is None or b"10/28/2026" not in body:
                    raise RuntimeError("need /tmp/VIX3M_History.csv from prior fetch")
                # truncate to <= 10/28/2026
                df, _ = load_cboe_csv(body, "VIX3M")
                df = df[df.session_date <= dt.date(2026, 10, 28)]
                buf = io.StringIO()
                buf.write("DATE,OPEN,HIGH,LOW,CLOSE\n")
                for row in df.itertuples():
                    buf.write(f"{row.session_date:%m/%d/%Y},{row.open},{row.high},{row.low},{row.close}\n")
                content = buf.getvalue().encode()
            else:
                body = Path("/tmp/VIX_History.csv").read_bytes()
                df, _ = load_cboe_csv(body, "VIX")
                df = df[df.session_date <= dt.date(2026, 10, 28)]
                buf = io.StringIO()
                buf.write("DATE,OPEN,HIGH,LOW,CLOSE\n")
                for row in df.itertuples():
                    buf.write(f"{row.session_date:%m/%d/%Y},{row.open},{row.high},{row.low},{row.close}\n")
                content = buf.getvalue().encode()
            resp = requests.Response()
            resp.status_code = 200
            resp._content = content
            resp.url = url
            resp.headers["Content-Type"] = "text/csv"
            resp.headers["Last-Modified"] = "Wed, 28 Oct 2026 21:11:02 GMT"
            return resp

        with mock.patch("requests.get", side_effect=lambda *a, **k: fake_get_noop(a[0] if a else k.get("url"))):
            # patch http_get to use our fake via requests.get — actually http_get calls requests.get
            rc = run_update(sandbox, pd.Timestamp("2026-10-28T21:00:00Z"), skip_yahoo=True)
        if rc != 0:
            failures.append(f"no-op expected exit 0, got {rc}")
        else:
            # should not have created a new dated parquet beyond bootstrap
            news = [p for p in sandbox.glob("vix_vix3m_daily_*.parquet") if p.name != BOOTSTRAP_COMBO]
            news += [p for p in sandbox.glob("vix_daily_*.parquet") if p.name != BOOTSTRAP_VIX]
            if news:
                failures.append(f"no-op created unexpected files {[p.name for p in news]}")
            else:
                print("  ok: exit 0, no new snapshot")

        # --- missing/partial: completed target 2026-10-29 but Cboe still ends 2026-10-28 ---
        print("SELFTEST missing/partial (pending)…", flush=True)
        # fresh sandbox without LATEST from previous
        for p in sandbox.glob("LATEST.json"):
            p.unlink()
        try:
            with mock.patch(
                "requests.get",
                side_effect=lambda *a, **k: fake_get_noop(a[0] if a else k.get("url")),
            ):
                run_update(sandbox, pd.Timestamp("2026-10-29T21:00:00Z"), skip_yahoo=True)
            failures.append("pending case expected Fail/exit 3, but returned success")
        except Fail as e:
            if e.code != 3:
                failures.append(f"pending expected code 3, got {e.code}: {e}")
            else:
                print(f"  ok: exit 3 pending — {e}")

        # --- partial: Cboe has 2026-10-29 VIX but missing VIX3M for that day ---
        print("SELFTEST partial VIX3M gap…", flush=True)
        for p in sandbox.glob("LATEST.json"):
            p.unlink()

        def fake_get_partial(url: str, **kw: Any) -> requests.Response:
            if "VIX3M" in url:
                return fake_get_noop(url)
            # VIX includes 10/29
            body = Path("/tmp/VIX_History.csv").read_bytes()
            df, _ = load_cboe_csv(body, "VIX")
            df = df[df.session_date <= dt.date(2026, 10, 29)]
            buf = io.StringIO()
            buf.write("DATE,OPEN,HIGH,LOW,CLOSE\n")
            for row in df.itertuples():
                buf.write(f"{row.session_date:%m/%d/%Y},{row.open},{row.high},{row.low},{row.close}\n")
            resp = requests.Response()
            resp.status_code = 200
            resp._content = buf.getvalue().encode()
            resp.url = url
            resp.headers["Content-Type"] = "text/csv"
            resp.headers["Last-Modified"] = "Thu, 29 Oct 2026 21:11:02 GMT"
            return resp

        try:
            with mock.patch(
                "requests.get",
                side_effect=lambda *a, **k: fake_get_partial(a[0] if a else k.get("url")),
            ):
                run_update(sandbox, pd.Timestamp("2026-10-29T21:00:00Z"), skip_yahoo=True)
            failures.append("partial VIX3M gap expected exit 3")
        except Fail as e:
            if e.code != 3:
                failures.append(f"partial gap expected code 3, got {e.code}: {e}")
            else:
                print(f"  ok: exit 3 on VIX3M gap — {e}")

        # --- strict HTTP non-200 ---
        print("SELFTEST HTTP non-200…", flush=True)
        try:
            with mock.patch("requests.get") as m:
                resp = requests.Response()
                resp.status_code = 404
                resp._content = b"missing"
                resp.url = CBOE_VIX_URL
                m.return_value = resp
                http_get(CBOE_VIX_URL)
            failures.append("HTTP 404 should raise Fail 5")
        except Fail as e:
            if e.code != 5:
                failures.append(f"HTTP 404 expected code 5, got {e.code}")
            else:
                print(f"  ok: HTTP 404 → {e}")

    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    if failures:
        print("SELFTEST FAILURES:", file=sys.stderr)
        for f in failures:
            print(" -", f, file=sys.stderr)
        return 2
    print("SELFTEST PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=f"{_QR.DATA_DIR}/sentiment/vix")
    ap.add_argument("--now-utc", default=None, help="override clock (testing), e.g. 2026-11-06T00:00Z")
    ap.add_argument("--skip-yahoo", action="store_true", help="skip optional Yahoo cross-check")
    ap.add_argument("--self-test", action="store_true", help="run no-op / pending / staleness unit tests")
    a = ap.parse_args(argv)
    d = Path(a.dir)
    if a.self_test:
        return self_test(d)
    now = pd.Timestamp(a.now_utc) if a.now_utc else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    return run_update(d, now, skip_yahoo=a.skip_yahoo)


if __name__ == "__main__":
    try:
        rc = main()
    except Fail as e:
        print(f"ERROR (exit {e.code}): {e}", file=sys.stderr)
        record_staleness()
        sys.exit(e.code)
    except Exception as e:
        print(f"ERROR (exit 5): {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        record_staleness()
        sys.exit(5)
    record_staleness()
    sys.exit(rc)
