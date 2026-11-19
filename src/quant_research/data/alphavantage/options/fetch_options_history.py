#!/usr/bin/env python3
"""Resumable AV HISTORICAL_OPTIONS for SPY/QQQ (QQQQ pre-rename).
Victor 63d3073d: OOS (>=2016-06-01) -> oos_holdout/; no content inspect/print.
Rate <=40/min. Never print/log API key.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = Path(f"{_QR.DATA_DIR}/alphavantage")
OPTIONS_ROOT = ROOT / "options"
LOG_DIR = ROOT / "logs"
MANIFEST = OPTIONS_ROOT / "MANIFEST.csv"
RUN_LOG = LOG_DIR / "options_fetch.log"
PROGRESS = LOG_DIR / "options_progress.json"
START = "2008-01-02"
END = "2026-11-09"
OOS_START = "2016-06-01"
QQQ_RENAME = "2011-03-23"  # QQQQ through day before; QQQ from this date
MAX_RPM = 40
MAX_RETRIES = 8
BASE_BACKOFF = 2.0
USER_AGENT = "EthanDeskOptions/1.0"

MANIFEST_FIELDS = [
    "symbol",
    "date",
    "source_symbol",
    "partition",
    "path",
    "sha256",
    "rows",
    "status",
    "fetched_at_utc",
]


def redact(s: str, key: str) -> str:
    return (s or "").replace(key, "REDACTED")


def log(msg: str, key: str) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {redact(str(msg), key)}\n"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


class TokenBucket:
    def __init__(self, rpm: float):
        self.min_interval = 60.0 / rpm
        self.next_ok = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self.next_ok:
            time.sleep(self.next_ok - now)
        self.next_ok = time.monotonic() + self.min_interval


def trading_days(start: str, end: str) -> list[str]:
    import pandas_market_calendars as mcal

    cal = mcal.get_calendar("NYSE")
    sched = cal.schedule(start_date=start, end_date=end)
    return [d.strftime("%Y-%m-%d") for d in sched.index]


def source_symbol(logical: str, date: str) -> str:
    if logical == "QQQ" and date < QQQ_RENAME:
        return "QQQQ"
    return logical


def partition_for(date: str) -> str:
    return "OOS" if date >= OOS_START else "DEV"


def out_path(logical: str, date: str) -> Path:
    if date >= OOS_START:
        return OPTIONS_ROOT / logical / "oos_holdout" / f"{date}.json.gz"
    return OPTIONS_ROOT / logical / f"{date}.json.gz"


def load_manifest_done() -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not MANIFEST.exists():
        return done
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") in ("OK", "EMPTY"):
                done.add((row["symbol"], row["date"]))
    return done


def ensure_manifest_header() -> None:
    OPTIONS_ROOT.mkdir(parents=True, exist_ok=True)
    if not MANIFEST.exists():
        with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=MANIFEST_FIELDS).writeheader()
        return
    # ensure columns exist
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)
    if list(fields) != MANIFEST_FIELDS:
        with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in MANIFEST_FIELDS})


def append_manifest(row: dict[str, Any]) -> None:
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=MANIFEST_FIELDS).writerow(row)


def classify_payload(data: Any) -> tuple[str, str]:
    if not isinstance(data, dict):
        return "ERROR", "non-dict"
    if "Error Message" in data:
        msg = str(data["Error Message"]).lower()
        if "invalid" in msg and "key" in msg:
            return "INVALID_KEY", data["Error Message"]
        if "premium" in msg:
            return "PREMIUM", data["Error Message"]
        return "ERROR", data["Error Message"]
    if "Information" in data:
        info = str(data["Information"])
        low = info.lower()
        if "premium" in low:
            return "PREMIUM", info
        return "THROTTLE", info
    if "Note" in data:
        return "THROTTLE", data["Note"]
    if "data" in data:
        rows = data["data"]
        if isinstance(rows, list) and len(rows) == 0:
            return "EMPTY", "empty list"
        if isinstance(rows, list):
            return "OK", f"n={len(rows)}"
        return "ERROR", "data not list"
    return "UNKNOWN", "no data key"


def fetch_one(src_sym: str, date: str, key: str, bucket: TokenBucket, oos: bool) -> tuple[str, Any, bytes | None]:
    """Returns (status, data_or_none, raw_or_none).
    For OOS: never log/print row content — status and len only.
    """
    params = f"function=HISTORICAL_OPTIONS&symbol={src_sym}&date={date}&datatype=json&apikey={key}"
    url = f"https://www.alphavantage.co/query?{params}"
    url_safe = redact(url, key)

    for attempt in range(MAX_RETRIES):
        bucket.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                log(f"JSON_ERR src={src_sym} {date} attempt={attempt} {e} url={url_safe}", key)
                time.sleep(BASE_BACKOFF * (2**attempt))
                continue
            kind, detail = classify_payload(data)
            # OOS: redact detail that might contain payload snippets
            safe_detail = redact(detail, key)
            if oos and kind in ("OK", "EMPTY"):
                safe_detail = f"len={len(data.get('data') or [])}" if kind == "OK" else "empty"
            if kind in ("INVALID_KEY", "PREMIUM"):
                log(f"FATAL {kind} src={src_sym} {date} {safe_detail}", key)
                return "FATAL", data, None
            if kind == "THROTTLE":
                wait = BASE_BACKOFF * (2**attempt) + 5
                log(f"THROTTLE src={src_sym} {date} attempt={attempt} wait={wait:.1f}s", key)
                time.sleep(wait)
                continue
            if kind == "OK":
                return "OK", data, raw
            if kind == "EMPTY":
                return "EMPTY", data, raw
            log(f"RETRY {kind} src={src_sym} {date} attempt={attempt} {safe_detail[:160]}", key)
            time.sleep(BASE_BACKOFF * (2**attempt))
        except urllib.error.HTTPError as e:
            log(f"HTTP {e.code} src={src_sym} {date} attempt={attempt}", key)
            if e.code in (401, 403):
                return "FATAL", {"Error Message": f"HTTP {e.code}"}, None
            time.sleep(BASE_BACKOFF * (2**attempt) + 2)
        except Exception as e:
            log(f"EXC src={src_sym} {date} attempt={attempt} {redact(str(e), key)}", key)
            time.sleep(BASE_BACKOFF * (2**attempt) + 2)
    return "FAIL", None, None


def atomic_write_gz(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(raw).hexdigest()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        with gzip.open(tmp_path, "wb", compresslevel=6) as gzf:
            gzf.write(raw)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return sha


def file_valid_minimal(path: Path) -> tuple[bool, int]:
    """Validate without printing any row content. Returns (ok, nrows)."""
    try:
        with gzip.open(path, "rb") as f:
            raw = f.read()
        data = json.loads(raw)
        kind, _ = classify_payload(data)
        if kind == "OK":
            return True, len(data["data"])
        if kind == "EMPTY":
            return True, 0
        return False, 0
    except Exception:
        return False, 0


def write_progress(done: int, total: int, last: str) -> None:
    PROGRESS.write_text(
        json.dumps(
            {
                "done": done,
                "total": total,
                "last": last,
                "updated_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )


def main() -> int:
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    if len(key) != 16:
        print("FATAL: ALPHAVANTAGE_API_KEY missing or unexpected length", file=sys.stderr)
        return 2

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ensure_manifest_header()
    days = trading_days(START, END)
    logicals = ["SPY", "QQQ"]
    tasks = [(sym, d) for sym in logicals for d in days]
    total = len(tasks)
    done_set = load_manifest_done()

    # Resume: existing valid files
    skip_existing = 0
    for sym, d in tasks:
        if (sym, d) in done_set:
            continue
        p = out_path(sym, d)
        # also accept legacy path if OOS file was wrongly saved at DEV path (shouldn't after restart)
        if not p.exists() and d < OOS_START:
            pass
        if p.exists():
            ok, nrows = file_valid_minimal(p)
            if ok:
                with gzip.open(p, "rb") as f:
                    raw = f.read()
                sha = hashlib.sha256(raw).hexdigest()
                status = "OK" if nrows > 0 else "EMPTY"
                append_manifest(
                    {
                        "symbol": sym,
                        "date": d,
                        "source_symbol": source_symbol(sym, d),
                        "partition": partition_for(d),
                        "path": str(p),
                        "sha256": sha,
                        "rows": nrows,
                        "status": status,
                        "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                )
                done_set.add((sym, d))
                skip_existing += 1

    remaining = [(s, d) for s, d in tasks if (s, d) not in done_set]
    log(
        f"START total={total} already_done={len(done_set)} skip_backfill={skip_existing} "
        f"remaining={len(remaining)} rpm={MAX_RPM} oos_start={OOS_START} qqq_rename={QQQ_RENAME}",
        key,
    )

    bucket = TokenBucket(MAX_RPM)
    completed = len(done_set)

    for i, (sym, d) in enumerate(remaining):
        src = source_symbol(sym, d)
        oos = d >= OOS_START
        out = out_path(sym, d)
        status, data, raw = fetch_one(src, d, key, bucket, oos=oos)  # type: ignore[assignment]  # earlier raw in main is file bytes
        if status == "FATAL":
            log(f"STOP_FATAL after {sym} src={src} {d}", key)
            write_progress(completed, total, f"FATAL {sym} {d}")
            return 3
        if status == "FAIL":
            log(f"FAIL_GIVE_UP {sym} src={src} {d}", key)
            append_manifest(
                {
                    "symbol": sym,
                    "date": d,
                    "source_symbol": src,
                    "partition": partition_for(d),
                    "path": "",
                    "sha256": "",
                    "rows": 0,
                    "status": "FAIL",
                    "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
            completed += 1
            write_progress(completed, total, f"FAIL {sym} {d}")
            continue

        assert raw is not None
        # Minimal validation only — for OOS do not touch row fields beyond len
        nrows = len((data or {}).get("data") or [])
        # Never print a row; log status/len only
        sha = atomic_write_gz(out, raw)
        mstatus = "OK" if status == "OK" else "EMPTY"
        append_manifest(
            {
                "symbol": sym,
                "date": d,
                "source_symbol": src,
                "partition": partition_for(d),
                "path": str(out),
                "sha256": sha,
                "rows": nrows,
                "status": mstatus,
                "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        completed += 1
        if completed % 25 == 0 or i < 3:
            log(
                f"{mstatus} {sym} src={src} {d} partition={partition_for(d)} "
                f"rows={nrows} sha={sha[:12]}… progress={completed}/{total}",
                key,
            )
        write_progress(completed, total, f"{mstatus} {sym} src={src} {d} rows={nrows}")

    log(f"DONE completed={completed}/{total}", key)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
        tb = traceback.format_exc()
        if key:
            tb = tb.replace(key, "REDACTED")
        sys.stderr.write(tb)
        raise
