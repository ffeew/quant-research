#!/usr/bin/env python3
"""Pilot NEWS_SENTIMENT, EARNINGS, EARNINGS_CALENDAR, EARNINGS_CALL_TRANSCRIPT.
Rate <=40/min. Never logs API key. Resumable. Run AFTER options pull.
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
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = Path(f"{_QR.DATA_DIR}/alphavantage")
NEWS_ROOT = ROOT / "news"
TRANS_ROOT = ROOT / "transcripts"
LOG_DIR = ROOT / "logs"
PILOT = [
    "AAPL",
    "NVDA",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "AVGO",
    "LLY",
    "BRK.B",
    "WMT",
    "JPM",
    "V",
    "MU",
    "AMD",
    "XOM",
    "JNJ",
    "MA",
    "ABBV",
    "COST",
]
MAX_RPM = 40
MIN_INTERVAL = 60.0 / MAX_RPM
MAX_RETRIES = 8
BASE_BACKOFF = 2.0
USER_AGENT = "EthanDeskNews/1.0"
# AV NEWS_SENTIMENT time format: YYYYMMDDTHHMM
NEWS_START = "20080101T0000"  # probe as far back as coverage goes
NEWS_END = None  # set at runtime to now


def redact(s: str, key: str) -> str:
    return (s or "").replace(key, "REDACTED")


def log(msg: str, key: str, logfile: Path) -> None:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {redact(str(msg), key)}\n"
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with open(logfile, "a", encoding="utf-8") as f:
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


def atomic_write_bytes(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(raw).hexdigest()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        Path(tmp).write_bytes(raw)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return sha


def classify(data: Any) -> str:
    if not isinstance(data, dict):
        return "OK_RAW"
    if "Error Message" in data:
        msg = str(data["Error Message"]).lower()
        if "invalid" in msg and "key" in msg:
            return "INVALID_KEY"
        if "premium" in msg:
            return "PREMIUM"
        return "ERROR"
    if "Information" in data:
        info = str(data["Information"]).lower()
        if "premium" in info:
            return "PREMIUM"
        return "THROTTLE"
    if "Note" in data:
        return "THROTTLE"
    return "OK"


def av_get(params: dict[str, Any], key: str, bucket: TokenBucket, logf: Path) -> tuple[str, bytes, object]:
    params = dict(params)
    params["apikey"] = key
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(params)
    url_safe = redact(url, key)
    for attempt in range(MAX_RETRIES):
        bucket.wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            # try json
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                # CSV or other
                return "OK_RAW", raw, None
            kind = classify(data)
            if kind in ("INVALID_KEY", "PREMIUM"):
                log(f"FATAL {kind} params={ {k: v for k, v in params.items() if k != 'apikey'} }", key, logf)
                return "FATAL", raw, data
            if kind == "THROTTLE":
                wait = BASE_BACKOFF * (2**attempt) + 5
                log(f"THROTTLE attempt={attempt} wait={wait:.1f} url={url_safe}", key, logf)
                time.sleep(wait)
                continue
            if kind == "ERROR":
                log(f"ERR attempt={attempt} {redact(str(data.get('Error Message')), key)}", key, logf)
                time.sleep(BASE_BACKOFF * (2**attempt))
                continue
            return "OK", raw, data
        except urllib.error.HTTPError as e:
            log(f"HTTP {e.code} attempt={attempt} {url_safe}", key, logf)
            if e.code in (401, 403):
                return "FATAL", b"", None
            time.sleep(BASE_BACKOFF * (2**attempt) + 2)
        except Exception as e:
            log(f"EXC attempt={attempt} {redact(str(e), key)}", key, logf)
            time.sleep(BASE_BACKOFF * (2**attempt) + 2)
    return "FAIL", b"", None


def ensure_csv_manifest(path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()


def append_csv(path: Path, fields: list[str], row: dict[str, Any]) -> None:
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=fields).writerow(row)


# ---------- NEWS_SENTIMENT ----------
def fetch_news_for_ticker(ticker: str, key: str, bucket: TokenBucket, logf: Path) -> dict[str, Any]:
    """Page through time with limit=1000; split windows that hit the cap."""
    out_dir = NEWS_ROOT / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    man_path = NEWS_ROOT / "NEWS_MANIFEST.csv"
    fields = [
        "ticker",
        "window_from",
        "window_to",
        "path",
        "sha256",
        "articles",
        "status",
        "hit_cap",
        "fetched_at_utc",
        "coverage_note",
    ]
    ensure_csv_manifest(man_path, fields)

    # load done windows
    done = set()
    with open(man_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"] == ticker and row["status"] in ("OK", "EMPTY"):
                done.add((row["window_from"], row["window_to"]))

    now = datetime.now(UTC)
    _end_str = now.strftime("%Y%m%dT%H%M")
    # Strategy: walk forward from NEWS_START in ~90-day windows with sort=EARLIEST;
    # if a window returns 1000, bisect until <1000 or min window (~1 day).
    # Also try a probe for earliest article.

    summary: dict[str, Any] = {
        "ticker": ticker,
        "windows": 0,
        "articles_raw": 0,
        "articles_dedup": 0,
        "hit_cap_windows": 0,
        "earliest": None,
        "latest": None,
        "urls": set(),
    }

    def parse_tf(s: str) -> datetime:
        return datetime.strptime(s[:13], "%Y%m%dT%H%M").replace(tzinfo=UTC)

    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M")

    def fetch_window(t_from: str, t_to: str) -> tuple[str, list[Any], bytes]:
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "time_from": t_from,
            "time_to": t_to,
            "limit": "1000",
            "sort": "EARLIEST",
        }
        status, raw, data = av_get(params, key, bucket, logf)
        if status == "FATAL":
            return "FATAL", [], raw
        if status != "OK" or not isinstance(data, dict):
            return status, [], raw
        feed = data.get("feed") or []
        return "OK", feed, raw

    def save_window(t_from: str, t_to: str, feed: list[Any], raw: bytes, hit_cap: bool) -> None:
        if (t_from, t_to) in done:
            return
        fname = f"{t_from}_{t_to}.json.gz"
        path = out_dir / fname
        # wrap feed with meta for reproducibility
        payload = json.dumps(
            {"time_from": t_from, "time_to": t_to, "ticker": ticker, "items": len(feed), "feed": feed},
            separators=(",", ":"),
        ).encode()
        # Prefer saving the raw AV response when available & parseable as our structure;
        # store our normalized payload for consistent schema.
        sha = atomic_write_gz(path, payload)
        status = "EMPTY" if len(feed) == 0 else "OK"
        note = ""
        append_csv(
            man_path,
            fields,
            {
                "ticker": ticker,
                "window_from": t_from,
                "window_to": t_to,
                "path": str(path),
                "sha256": sha,
                "articles": len(feed),
                "status": status,
                "hit_cap": int(hit_cap),
                "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "coverage_note": note,
            },
        )
        done.add((t_from, t_to))
        summary["windows"] += 1
        summary["articles_raw"] += len(feed)
        if hit_cap:
            summary["hit_cap_windows"] += 1
        for a in feed:
            _url = a.get("url") or a.get("banner_image") or ""
            # prefer url
            u = a.get("url")
            if u:
                summary["urls"].add(u)
            ts = a.get("time_published")
            if ts:
                if summary["earliest"] is None or ts < summary["earliest"]:
                    summary["earliest"] = ts
                if summary["latest"] is None or ts > summary["latest"]:
                    summary["latest"] = ts

    def walk(t_from: datetime, t_to: datetime) -> str:
        if t_from >= t_to:
            return "OK"
        fs, ts = fmt(t_from), fmt(t_to)
        if (fs, ts) in done:
            # still need to count? skip
            return "OK"
        status, feed, raw = fetch_window(fs, ts)
        if status == "FATAL":
            return "FATAL"
        if status == "FAIL":
            log(f"NEWS_FAIL {ticker} {fs}-{ts}", key, logf)
            append_csv(
                man_path,
                fields,
                {
                    "ticker": ticker,
                    "window_from": fs,
                    "window_to": ts,
                    "path": "",
                    "sha256": "",
                    "articles": 0,
                    "status": "FAIL",
                    "hit_cap": 0,
                    "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "coverage_note": "give_up",
                },
            )
            return "FAIL"
        hit = len(feed) >= 1000
        if hit:
            # bisect if window > 1 day
            span = t_to - t_from
            if span > timedelta(days=1):
                mid = t_from + span / 2
                log(f"NEWS_SPLIT {ticker} {fs}-{ts} n=1000 -> bisect", key, logf)
                r1 = walk(t_from, mid)
                if r1 == "FATAL":
                    return "FATAL"
                return walk(mid, t_to)
            # min window still capped — save and flag
            save_window(fs, ts, feed, raw, True)
            return "OK"
        save_window(fs, ts, feed, raw, False)
        return "OK"

    # Initial coarse windows of 180 days from 2019 (AV news often starts ~2022; still probe earlier)
    # Start from 2019-01-01 to save calls on known-empty early years; also one probe 2008-2018.
    probe_from = parse_tf("20080101T0000")
    probe_to = parse_tf("20190101T0000")
    # single probe for pre-2019
    log(f"NEWS_PROBE_PRE2019 {ticker}", key, logf)
    st = walk(probe_from, probe_to)
    if st == "FATAL":
        summary["articles_dedup"] = len(summary["urls"])
        return {"fatal": True, **{k: (len(v) if k == "urls" else v) for k, v in summary.items()}}

    cursor = parse_tf("20190101T0000")
    end = now
    while cursor < end:
        nxt = min(cursor + timedelta(days=180), end)
        st = walk(cursor, nxt)
        if st == "FATAL":
            summary["fatal"] = True
            break
        cursor = nxt

    summary["articles_dedup"] = len(summary["urls"])
    # write per-ticker coverage note
    cov = {
        "ticker": ticker,
        "earliest_time_published": summary["earliest"],
        "latest_time_published": summary["latest"],
        "windows": summary["windows"],
        "articles_raw_sum": summary["articles_raw"],
        "articles_unique_url": summary["articles_dedup"],
        "hit_cap_windows": summary["hit_cap_windows"],
    }
    (out_dir / "COVERAGE.json").write_text(json.dumps(cov, indent=2), encoding="utf-8")
    log(
        f"NEWS_DONE {ticker} windows={summary['windows']} raw={summary['articles_raw']} uniq={summary['articles_dedup']} earliest={summary['earliest']}",
        key,
        logf,
    )
    return {k: (len(v) if k == "urls" else v) for k, v in summary.items()}


# ---------- EARNINGS ----------
def fetch_earnings(ticker: str, key: str, bucket: TokenBucket, logf: Path) -> dict[str, Any]:
    out_dir = NEWS_ROOT / "earnings_history"
    out_dir.mkdir(parents=True, exist_ok=True)
    man = NEWS_ROOT / "EARNINGS_MANIFEST.csv"
    fields = ["ticker", "path", "sha256", "annual_rows", "quarterly_rows", "status", "fetched_at_utc"]
    ensure_csv_manifest(man, fields)
    # skip if done
    with open(man, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"] == ticker and row["status"] == "OK":
                return {"ticker": ticker, "status": "SKIP", "quarterly_rows": int(row["quarterly_rows"] or 0)}

    # try BRK-B if BRK.B fails later
    symbols = [ticker]
    if ticker == "BRK.B":
        symbols = ["BRK.B", "BRK-B"]

    for sym in symbols:
        status, raw, data = av_get({"function": "EARNINGS", "symbol": sym}, key, bucket, logf)
        if status == "FATAL":
            return {"ticker": ticker, "status": "FATAL"}
        if status != "OK" or not isinstance(data, dict):
            continue
        annual = data.get("annualEarnings") or []
        quarterly = data.get("quarterlyEarnings") or []
        if not annual and not quarterly:
            continue
        path = out_dir / f"{ticker}.json.gz"
        sha = atomic_write_gz(path, raw)
        append_csv(
            man,
            fields,
            {
                "ticker": ticker,
                "path": str(path),
                "sha256": sha,
                "annual_rows": len(annual),
                "quarterly_rows": len(quarterly),
                "status": "OK",
                "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        log(f"EARNINGS_OK {ticker} via={sym} annual={len(annual)} quarterly={len(quarterly)}", key, logf)
        return {
            "ticker": ticker,
            "status": "OK",
            "annual_rows": len(annual),
            "quarterly_rows": len(quarterly),
            "symbol_used": sym,
        }
    # empty
    path = out_dir / f"{ticker}.EMPTY.json.gz"
    payload = json.dumps({"symbol": ticker, "annualEarnings": [], "quarterlyEarnings": []}).encode()
    sha = atomic_write_gz(path, payload)
    append_csv(
        man,
        fields,
        {
            "ticker": ticker,
            "path": str(path),
            "sha256": sha,
            "annual_rows": 0,
            "quarterly_rows": 0,
            "status": "EMPTY",
            "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return {"ticker": ticker, "status": "EMPTY", "annual_rows": 0, "quarterly_rows": 0}


def fetch_earnings_calendar(key: str, bucket: TokenBucket, logf: Path) -> dict[str, Any]:
    out_dir = NEWS_ROOT / "earnings_calendar"
    out_dir.mkdir(parents=True, exist_ok=True)
    man = NEWS_ROOT / "EARNINGS_CALENDAR_MANIFEST.csv"
    fields = ["horizon", "path", "sha256", "rows", "status", "fetched_at_utc", "note"]
    ensure_csv_manifest(man, fields)
    results = []
    for horizon in ("3month", "6month", "12month"):
        # skip if done
        skip = False
        with open(man, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["horizon"] == horizon and row["status"] == "OK":
                    skip = True
                    results.append({"horizon": horizon, "status": "SKIP", "rows": int(row["rows"] or 0)})
        if skip:
            continue
        status, raw, _data = av_get(
            {
                "function": "EARNINGS_CALENDAR",
                "horizon": horizon,
            },
            key,
            bucket,
            logf,
        )
        # EARNINGS_CALENDAR returns CSV
        if status == "FATAL":
            return {"fatal": True, "results": results}
        if status == "FAIL":
            append_csv(
                man,
                fields,
                {
                    "horizon": horizon,
                    "path": "",
                    "sha256": "",
                    "rows": 0,
                    "status": "FAIL",
                    "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "note": "forward-looking calendar",
                },
            )
            results.append({"horizon": horizon, "status": "FAIL"})
            continue
        text = raw.decode("utf-8", errors="replace")
        # count CSV rows
        lines = [ln for ln in text.splitlines() if ln.strip()]
        nrows = max(0, len(lines) - 1)
        path = out_dir / f"earnings_calendar_{horizon}.csv"
        sha = atomic_write_bytes(path, raw)
        append_csv(
            man,
            fields,
            {
                "horizon": horizon,
                "path": str(path),
                "sha256": sha,
                "rows": nrows,
                "status": "OK" if nrows > 0 else "EMPTY",
                "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "note": "FORWARD-LOOKING; not historical event dates",
            },
        )
        log(f"EARNINGS_CAL {horizon} rows={nrows}", key, logf)
        results.append({"horizon": horizon, "status": "OK", "rows": nrows, "sha": sha})
    # also write a note file
    (out_dir / "README.md").write_text(
        "# EARNINGS_CALENDAR (Alpha Vantage)\n\n"
        "**Forward-looking only.** Horizons 3month / 6month / 12month as offered by AV.\n"
        "For historical reported dates/EPS use `../earnings_history/` from function=EARNINGS.\n",
        encoding="utf-8",
    )
    return {"results": results}


# ---------- TRANSCRIPTS ----------
def fetch_transcripts(ticker: str, key: str, bucket: TokenBucket, logf: Path) -> dict[str, Any]:
    out_dir = TRANS_ROOT / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    man = TRANS_ROOT / "TRANSCRIPTS_MANIFEST.csv"
    fields = ["ticker", "quarter", "path", "sha256", "chars", "status", "fetched_at_utc"]
    ensure_csv_manifest(man, fields)

    done = set()
    with open(man, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["ticker"] == ticker and row["status"] in ("OK", "EMPTY"):
                done.add(row["quarter"])

    # Probe earliest: try from 2010Q1 forward; AV often has ~2010s+
    # Generate quarters from 2010Q1 through current
    now = datetime.now(UTC)
    quarters = []
    for y in range(2010, now.year + 1):
        for q in (1, 2, 3, 4):
            if y == now.year and q > ((now.month - 1) // 3 + 1):
                break
            quarters.append(f"{y}Q{q}")

    # Find earliest available with a coarse probe (sample every year Q1) then fill
    summary: dict[str, Any] = {"ticker": ticker, "ok": 0, "empty": 0, "fail": 0, "earliest_ok": None, "latest_ok": None}

    def one(qtr: str) -> str:
        if qtr in done:
            return "SKIP"
        # BRK.B symbol variants
        symbols = [ticker]
        if ticker == "BRK.B":
            symbols = ["BRK.B", "BRK-B"]
        for sym in symbols:
            status, raw, data = av_get(
                {
                    "function": "EARNINGS_CALL_TRANSCRIPT",
                    "symbol": sym,
                    "quarter": qtr,
                },
                key,
                bucket,
                logf,
            )
            if status == "FATAL":
                return "FATAL"
            if status != "OK" or not isinstance(data, dict):
                continue
            # AV returns transcript in "transcript" key or similar; empty if missing
            transcript = data.get("transcript")
            if transcript is None and "Error Message" not in data:
                # sometimes top-level list or different schema
                if not data or set(data.keys()) <= {"symbol", "quarter"}:
                    transcript = ""
                else:
                    # has content
                    transcript = data.get("transcript") or json.dumps(data)
            if not transcript:
                # check for empty-ish
                if not data.get("transcript") and len(json.dumps(data)) < 200:
                    path = out_dir / f"{qtr}.json.gz"
                    sha = atomic_write_gz(path, raw if raw else b"{}")
                    append_csv(
                        man,
                        fields,
                        {
                            "ticker": ticker,
                            "quarter": qtr,
                            "path": str(path),
                            "sha256": sha,
                            "chars": 0,
                            "status": "EMPTY",
                            "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    )
                    done.add(qtr)
                    summary["empty"] += 1
                    return "EMPTY"
            text = transcript if isinstance(transcript, str) else json.dumps(transcript)
            if len(text) < 50:
                path = out_dir / f"{qtr}.json.gz"
                sha = atomic_write_gz(path, raw)
                append_csv(
                    man,
                    fields,
                    {
                        "ticker": ticker,
                        "quarter": qtr,
                        "path": str(path),
                        "sha256": sha,
                        "chars": len(text),
                        "status": "EMPTY",
                        "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                )
                done.add(qtr)
                summary["empty"] += 1
                return "EMPTY"
            path = out_dir / f"{qtr}.json.gz"
            sha = atomic_write_gz(path, raw)
            append_csv(
                man,
                fields,
                {
                    "ticker": ticker,
                    "quarter": qtr,
                    "path": str(path),
                    "sha256": sha,
                    "chars": len(text),
                    "status": "OK",
                    "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            done.add(qtr)
            summary["ok"] += 1
            if summary["earliest_ok"] is None:
                summary["earliest_ok"] = qtr
            summary["latest_ok"] = qtr
            log(f"TRANS_OK {ticker} {qtr} chars={len(text)} via={sym}", key, logf)
            return "OK"
        # all symbols failed / empty
        path = out_dir / f"{qtr}.json.gz"
        payload = json.dumps({"symbol": ticker, "quarter": qtr, "transcript": ""}).encode()
        sha = atomic_write_gz(path, payload)
        append_csv(
            man,
            fields,
            {
                "ticker": ticker,
                "quarter": qtr,
                "path": str(path),
                "sha256": sha,
                "chars": 0,
                "status": "EMPTY",
                "fetched_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        done.add(qtr)
        summary["empty"] += 1
        return "EMPTY"

    # Coarse probe: yearly Q2 first to find start, then fill all from first hit-1 year
    first_hit = None
    for y in range(2010, now.year + 1):
        qtr = f"{y}Q2"
        st = one(qtr)
        if st == "FATAL":
            summary["fatal"] = True
            return summary
        if st == "OK":
            first_hit = y
            break
    start_y = max(2010, (first_hit or now.year) - 1)
    for qtr in quarters:
        y = int(qtr[:4])
        if y < start_y:
            # mark remaining early as EMPTY without calling if we never hit
            if qtr not in done and first_hit is None:
                continue  # skip remote past if nothing ever found — actually still record?
            if qtr not in done:
                continue
        if qtr in done:
            continue
        st = one(qtr)
        if st == "FATAL":
            summary["fatal"] = True
            break

    (out_dir / "COVERAGE.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"TRANS_DONE {ticker} ok={summary['ok']} empty={summary['empty']} earliest={summary['earliest_ok']}", key, logf)
    return summary


def main() -> int:
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    if len(key) != 16:
        print("FATAL: key missing/bad length", file=sys.stderr)
        return 2
    logf = LOG_DIR / "news_earnings_transcripts.log"
    bucket = TokenBucket(MAX_RPM)
    log(f"START pilot={len(PILOT)} rpm={MAX_RPM}", key, logf)

    # 1) earnings calendar (3 calls)
    cal = fetch_earnings_calendar(key, bucket, logf)
    if cal.get("fatal"):
        return 3

    # 2) historical earnings per ticker
    for t in PILOT:
        r = fetch_earnings(t, key, bucket, logf)
        if r.get("status") == "FATAL":
            return 3

    # 3) news sentiment (heavy)
    for t in PILOT:
        r = fetch_news_for_ticker(t, key, bucket, logf)
        if r.get("fatal"):
            return 3

    # 4) transcripts
    for t in PILOT:
        r = fetch_transcripts(t, key, bucket, logf)
        if r.get("fatal"):
            return 3

    log("ALL_PILOT_DONE", key, logf)
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
