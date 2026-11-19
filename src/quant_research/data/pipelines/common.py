"""Shared helpers for desk data pipelines. Credentials are read ONLY from env vars
ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY and are never logged or written."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

DATA = Path(os.environ.get("CIO_DATA_DIR", f"{_QR.DATA_DIR}"))
DATA_URL = "https://data.alpaca.markets"
TRADING_URL = "https://paper-api.alpaca.markets"
START = "2016-01-01"
UA = {"User-Agent": "Mozilla/5.0 (cio-desk research data pipeline)"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")

_sess = requests.Session()


def _headers() -> dict[str, str]:
    k, s = os.environ.get("ALPACA_API_KEY_ID"), os.environ.get("ALPACA_API_SECRET_KEY")
    missing = [n for n, v in (("ALPACA_API_KEY_ID", k), ("ALPACA_API_SECRET_KEY", s)) if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {missing}")
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}  # type: ignore[dict-item]  # falsy keys already raised


_MIN_INTERVAL = float(
    os.environ.get("DESK_ALPACA_MIN_INTERVAL_S", "0.6")
)  # <= ~100 req/min (shared key; desk agents share 200/min)
_last_call = [0.0]


def get(url: str, params: dict[str, Any] | None = None, max_retries: int = 8) -> Any:
    """GET with client-side throttle (<= ~100 req/min), retry/backoff on 429/5xx/network errors. Never logs headers."""
    delay = 2.0
    for attempt in range(max_retries):
        wait = _MIN_INTERVAL - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        try:
            r = _sess.get(url, headers=_headers(), params=params, timeout=60)
        except requests.RequestException as e:
            log.warning("network error %s (attempt %d)", type(e).__name__, attempt)
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            reset = r.headers.get("X-RateLimit-Reset")
            wait = max(delay, (int(reset) - time.time()) if reset else delay)
            log.warning("HTTP %s, sleeping %.1fs", r.status_code, wait)
            time.sleep(min(wait, 60))
            delay = min(delay * 2, 60)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}: {r.text[:300]}")
        rem = r.headers.get("X-RateLimit-Remaining")
        if rem is not None and int(rem) < 5:
            time.sleep(2)
        return r.json()
    raise RuntimeError(f"giving up on {url} after {max_retries} attempts")


def calendar(start: str = START, end: str | None = None) -> pd.DataFrame:
    end = end or (dt.date.today() + dt.timedelta(days=7)).isoformat()
    cal = pd.DataFrame(get(TRADING_URL + "/v2/calendar", {"start": start, "end": end}))
    cal["date"] = pd.to_datetime(cal["date"]).dt.date
    return cal


def last_completed_session(cal: pd.DataFrame | None = None) -> dt.date:
    """Latest NYSE session whose 16:00 ET (or early) close + 20min has passed."""
    cal = cal if cal is not None else calendar((dt.date.today() - dt.timedelta(days=15)).isoformat())
    now_et = pd.Timestamp.now(tz="America/New_York")
    for _, row in cal.sort_values("date", ascending=False).iterrows():
        close = pd.Timestamp(f"{row['date']} {row['close']}", tz="America/New_York")
        if close + pd.Timedelta(minutes=20) <= now_et:
            return row["date"]  # type: ignore[no-any-return]  # calendar date column is datetime.date
    raise RuntimeError("no completed session found")


def write_parquet(df: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)  # atomic


def update_manifest(name: str, info: dict[str, Any]) -> None:
    p = DATA / "manifest.json"
    m = json.loads(p.read_text()) if p.exists() else {}
    info["updated_at_utc"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    m[name] = info
    p.write_text(json.dumps(m, indent=2, default=str))
