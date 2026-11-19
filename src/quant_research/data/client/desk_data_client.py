"""desk_data_client: shared, local-first access to desk market data + a cross-process throttled Alpaca client.

Owner: the data owner (Data Engineer). Dependencies: stdlib + requests + pandas + pyarrow only (works from any venv).

    import sys; sys.path.insert(0, "$QR_DATA_DIR/lib")
    import desk_data_client as ddc
    df = ddc.get_daily_bars(["AAPL", "SPY"], "2024-01-01", "2026-10-29")   # local store first, API only past coverage

Rules
- History is read from the local parquet store ($QR_DATA_DIR/bars/daily/{adjusted,raw}). The API is used only for
  dates after the store's coverage end (and for symbols that are not in the store at all). History on disk is never re-fetched.
- EVERY live Alpaca market-data request (data.alpaca.markets) goes through `alpaca_get()` / `alpaca_get_paginated()`:
    * one global token bucket shared by all processes on the box (fcntl lock + JSON state in
      $QR_DATA_DIR/.cache/ratelimit/), default 150 req/min, burst 10 (env DESK_ALPACA_RPM / DESK_ALPACA_BURST);
    * exponential backoff with full jitter on 429 / 5xx / network errors, honoring Retry-After and X-RateLimit-Reset.
      A 429 (or X-RateLimit-Remaining near 0) pauses ALL processes until the reset time, not just the caller;
    * on-disk response cache ($QR_DATA_DIR/.cache/http/) keyed by URL + params, with a TTL. Requests whose
      `end` is more than 1 day in the past are cached indefinitely.
- Credentials: env ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY, sent only as request headers. They are never logged,
  printed, cached or written: cache keys/files contain only the URL and query params, and errors carry only status + body.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import random
import tempfile
import threading
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import IO, Any, cast
from urllib.parse import urlparse

import pandas as pd
import pyarrow.parquet as pq

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

try:  # only needed for live API calls; local-store reads work without it
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]  # requests is optional; live calls raise if it is missing

__all__ = [
    "AlpacaError",
    "RateLimiter",
    "alpaca_get",
    "alpaca_get_paginated",
    "get_daily_bars",
    "get_hour_bars",
    "get_intraday_bars",
    "get_minute_bars",
    "purge_cache",
    "store_coverage",
    "throttle",
]

DATA_DIR = Path(os.environ.get("CIO_DATA_DIR", f"{_QR.DATA_DIR}"))
BARS_DIR = DATA_DIR / "bars" / "daily"
CACHE_DIR = Path(os.environ.get("DESK_DATA_CACHE_DIR", str(DATA_DIR / ".cache")))
RATE_DIR = CACHE_DIR / "ratelimit"
HTTP_CACHE_DIR = CACHE_DIR / "http"
DATA_URL = "https://data.alpaca.markets"

DEFAULT_RPM = float(os.environ.get("DESK_ALPACA_RPM", "150"))  # shared across ALL processes; free plan cap is 200
DEFAULT_BURST = float(os.environ.get("DESK_ALPACA_BURST", "10"))
DEFAULT_TTL = float(
    os.environ.get("DESK_ALPACA_CACHE_TTL", "300")
)  # seconds, for windows that are not yet "historical"
HISTORICAL_AGE = dt.timedelta(days=1)  # end older than this -> cache forever
SIP_DELAY = dt.timedelta(minutes=16)  # free plan: the last 15 min of SIP is blocked
REQUEST_LOG_MAX_BYTES = 5_000_000

log = logging.getLogger("desk_data_client")
if not log.handlers:
    log.addHandler(logging.NullHandler())


class AlpacaError(RuntimeError):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status


# --------------------------------------------------------------------------------------------------------------------
# Cross-process token bucket
# --------------------------------------------------------------------------------------------------------------------
class RateLimiter:
    """Token bucket whose state lives in a JSON file guarded by an exclusive fcntl lock, so every process on the box
    that uses the same `name` shares one budget. Also holds a shared `blocked_until` (epoch s) set after 429s."""

    def __init__(
        self,
        name: str = "alpaca_data",
        rpm: float = DEFAULT_RPM,
        burst: float = DEFAULT_BURST,
        directory: Path = RATE_DIR,
    ):
        self.rate = rpm / 60.0
        self.burst = max(1.0, burst)
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.dir / f"{name}.lock"
        self.state_path = self.dir / f"{name}.state.json"
        self.log_path = self.dir / f"{name}.requests.log"
        self._tlock = threading.Lock()  # also serialise threads inside one process

    # -- state helpers (call only while holding the file lock) --
    def _read(self, now: float) -> dict[str, float]:
        try:
            st = json.loads(self.state_path.read_text())
            return {
                "tokens": float(st.get("tokens", self.burst)),
                "ts": float(st.get("ts", now)),
                "blocked_until": float(st.get("blocked_until", 0.0)),
            }
        except (OSError, ValueError):
            return {"tokens": self.burst, "ts": now, "blocked_until": 0.0}

    def _write(self, st: dict[str, float]) -> None:
        tmp = self.state_path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(st))
        os.replace(tmp, self.state_path)

    def _locked(self) -> IO[str]:
        f = open(self.lock_path, "a+")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return f

    def acquire(self, tag: str = "") -> float:
        """Block until one request token is available. Returns seconds waited."""
        waited = 0.0
        with self._tlock:
            while True:
                f = self._locked()
                try:
                    now = time.time()
                    st = self._read(now)
                    elapsed = max(0.0, now - st["ts"])
                    tokens = min(self.burst, st["tokens"] + elapsed * self.rate)
                    if now < st["blocked_until"]:
                        # paused (429 / key budget spent): no refill while blocked, so clients restart at the steady
                        # rate instead of stampeding with a full burst the moment the server window resets
                        wait = st["blocked_until"] - now
                        self._write({"tokens": 0.0, "ts": now, "blocked_until": st["blocked_until"]})
                    elif tokens >= 1.0:
                        self._write({"tokens": tokens - 1.0, "ts": now, "blocked_until": st["blocked_until"]})
                        self._log(now, tag)
                        return waited
                    else:
                        wait = (1.0 - tokens) / self.rate
                        self._write({"tokens": tokens, "ts": now, "blocked_until": st["blocked_until"]})
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    f.close()
                wait = max(wait, 0.005)
                time.sleep(wait)
                waited += wait

    def block_until(self, epoch: float, drain: bool = True) -> None:
        """Pause every process sharing this limiter until `epoch` (e.g. after a 429 / X-RateLimit-Reset)."""
        f = self._locked()
        try:
            now = time.time()
            st = self._read(now)
            tokens = min(self.burst, st["tokens"] + max(0.0, now - st["ts"]) * self.rate)
            self._write(
                {"tokens": 0.0 if drain else tokens, "ts": now, "blocked_until": max(st["blocked_until"], epoch)}
            )
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

    def _log(self, now: float, tag: str) -> None:
        # Request ledger (epoch, pid, path). Contains no params values beyond the path and never any header.
        try:
            if self.log_path.exists() and self.log_path.stat().st_size > REQUEST_LOG_MAX_BYTES:
                os.replace(self.log_path, self.log_path.with_suffix(".log.1"))
            with open(self.log_path, "a") as fh:
                fh.write(f"{now:.3f} {os.getpid()} {tag}\n")
        except OSError:
            pass


_LIMITER: RateLimiter | None = None


def throttle() -> RateLimiter:
    """The process-wide handle on the shared Alpaca market-data limiter. Use `throttle().acquire()` before any
    Alpaca data request you cannot route through alpaca_get() (e.g. inside an existing pipeline's own get())."""
    global _LIMITER
    if _LIMITER is None:
        _LIMITER = RateLimiter()
    return _LIMITER


# --------------------------------------------------------------------------------------------------------------------
# On-disk response cache
# --------------------------------------------------------------------------------------------------------------------
def _full_url(path_or_url: str) -> str:
    return path_or_url if path_or_url.startswith("http") else DATA_URL + "/" + path_or_url.lstrip("/")


def _cache_key(url: str, params: dict[str, Any] | None) -> str:
    norm = json.dumps(
        {"url": url, "params": {k: str(v) for k, v in sorted((params or {}).items()) if v is not None}}, sort_keys=True
    )
    return hashlib.sha256(norm.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return HTTP_CACHE_DIR / key[:2] / f"{key}.json"


def _parse_ts(x: Any) -> pd.Timestamp | None:
    if x is None or x == "":
        return None
    try:
        t = pd.Timestamp(x)
    except (ValueError, TypeError):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _auto_ttl(params: dict[str, Any] | None) -> float | None:
    """None = cache forever. A request is 'historical' when its `end` is more than 1 day ago."""
    end = _parse_ts((params or {}).get("end"))
    if end is not None and end < pd.Timestamp.now(tz="UTC") - HISTORICAL_AGE:
        return None
    return DEFAULT_TTL


def _cache_read(key: str, ttl: float | None) -> Any | None:
    p = _cache_path(key)
    try:
        rec = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if ttl is not None and time.time() - rec.get("fetched_at", 0) > ttl:
        return None
    return rec.get("body")


def _cache_write(key: str, url: str, params: dict[str, Any] | None, body: Any) -> None:
    p = _cache_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "fetched_at": time.time(),
        "url": url,
        "params": {k: str(v) for k, v in (params or {}).items()},
        "body": body,
    }
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(rec, fh)
        os.replace(tmp, p)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def purge_cache(older_than_days: float = 30.0) -> int:
    """Delete cached responses older than N days. Returns the number of files removed."""
    cutoff, n = time.time() - older_than_days * 86400, 0
    for p in HTTP_CACHE_DIR.glob("*/*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


# --------------------------------------------------------------------------------------------------------------------
# Throttled GET
# --------------------------------------------------------------------------------------------------------------------
_SESSION = threading.local()


def _session() -> requests.Session:
    if requests is None:
        raise ImportError(
            "desk_data_client: live Alpaca calls need `requests` in this venv "
            f"(local-store reads do not). pip install requests, or run with {_QR.DATA_DIR}/.venv"
        )
    s = getattr(_SESSION, "s", None)
    if s is None:
        s = _SESSION.s = requests.Session()
    return s


def _auth_headers() -> dict[str, str]:
    k, s = os.environ.get("ALPACA_API_KEY_ID"), os.environ.get("ALPACA_API_SECRET_KEY")
    if not k or not s:
        missing = [n for n, v in (("ALPACA_API_KEY_ID", k), ("ALPACA_API_SECRET_KEY", s)) if not v]
        raise RuntimeError(f"missing env vars: {missing}")  # names only, never values
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s, "Accept": "application/json"}


def _server_wait(r: requests.Response) -> float | None:
    """Seconds the server asked us to wait (Retry-After or X-RateLimit-Reset epoch), if any."""
    ra = r.headers.get("Retry-After")
    if ra:
        try:
            return max(0.0, float(ra))
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime

                return max(0.0, parsedate_to_datetime(ra).timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    reset = r.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            return max(0.0, float(reset) - time.time())
        except ValueError:
            pass
    return None


def alpaca_get(
    path_or_url: str,
    params: dict[str, Any] | None = None,
    *,
    ttl: float | str | None = "auto",
    use_cache: bool = True,
    max_retries: int = 8,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    timeout: float = 60.0,
    max_total_wait: float = 900.0,
) -> Any:
    """Throttled, cached GET of one Alpaca market-data endpoint. Returns parsed JSON.
    ttl: "auto" (forever if params['end'] is >1 day ago, else DESK_ALPACA_CACHE_TTL=300 s), a number of seconds,
         or None (forever). use_cache=False bypasses both read and write.
    Retries: network errors / 5xx up to `max_retries`; 429s keep retrying (paced by the server's reset time) until
    `max_total_wait` seconds have passed, because on a shared key a 429 usually means someone else spent the budget."""
    url = _full_url(path_or_url)
    params = {k: v for k, v in (params or {}).items() if v is not None}
    key = _cache_key(url, params)
    eff_ttl: float | None = _auto_ttl(params) if ttl == "auto" else cast(float | None, ttl)
    if use_cache:
        hit = _cache_read(key, eff_ttl)
        if hit is not None:
            return hit
    lim = throttle()
    tag = urlparse(url).path
    deadline = time.time() + max_total_wait
    attempt = n429 = 0
    while attempt < max_retries and time.time() < deadline:
        lim.acquire(tag)
        sess = _session()
        try:
            r = sess.get(url, headers=_auth_headers(), params=params, timeout=timeout)
        except requests.RequestException as e:
            wait = random.uniform(0, min(max_delay, base_delay * 2**attempt))
            log.warning("network error %s on %s (attempt %d), retry in %.1fs", type(e).__name__, tag, attempt + 1, wait)
            attempt += 1
            time.sleep(wait)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            k = n429 if r.status_code == 429 else attempt
            backoff = random.uniform(0, min(max_delay, base_delay * 2**k))  # exponential, full jitter
            srv = _server_wait(r)
            wait = max(backoff, (srv or 0.0) + random.uniform(0, 1.0))
            if r.status_code == 429:
                n429 += 1
                lim.block_until(time.time() + wait)  # everyone pauses, not just this process
            else:
                attempt += 1
            log.warning(
                "HTTP %s on %s (429s=%d, other retries=%d), retry in %.1fs", r.status_code, tag, n429, attempt, wait
            )
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise AlpacaError(r.status_code, tag, r.text)
        rem = r.headers.get("X-RateLimit-Remaining")
        try:
            if rem is not None and int(rem) <= 3:  # key budget nearly spent (other users of the same key)
                srv = _server_wait(r)
                if srv:
                    log.info(
                        "key budget nearly spent (X-RateLimit-Remaining=%s); pausing all clients %.1fs",
                        rem,
                        min(srv, max_delay),
                    )
                    lim.block_until(time.time() + min(srv, max_delay))
        except ValueError:
            pass
        body = r.json()
        if use_cache:
            _cache_write(key, url, params, body)
        return body
    raise AlpacaError(
        429 if n429 else -1, tag, f"giving up after {attempt} retries / {n429} x 429 ({max_total_wait:.0f}s budget)"
    )


def alpaca_get_paginated(
    path_or_url: str, params: dict[str, Any] | None = None, items_key: str = "bars", **kw: Any
) -> Any:
    """Follow next_page_token until exhausted. Each page is cached separately (page_token is part of the key).
    Merges `items_key`: dict-of-lists (multi-symbol endpoints) is concatenated per key; a list is concatenated."""
    params = dict(params or {})
    merged: Any = None
    while True:
        j = alpaca_get(path_or_url, params, **kw)
        items = j.get(items_key) if isinstance(j, dict) else None
        if isinstance(items, dict):
            merged = merged if isinstance(merged, dict) else {}
            for k, v in items.items():
                merged.setdefault(k, []).extend(v or [])
        elif isinstance(items, list):
            merged = merged if isinstance(merged, list) else []
            merged.extend(items)
        elif merged is None and items is not None:
            merged = items
        tok = j.get("next_page_token") if isinstance(j, dict) else None
        if not tok:
            break
        params["page_token"] = tok
    return merged if merged is not None else {}


# --------------------------------------------------------------------------------------------------------------------
# Bars
# --------------------------------------------------------------------------------------------------------------------
_COLS = {
    "t": "timestamp_utc",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "n": "trade_count",
    "vw": "vwap",
}
_ADJ_DIR = {"all": "adjusted", "raw": "raw"}
_coverage: dict[str, dt.date] = {}


def _norm_symbols(symbols: str | Iterable[str]) -> list[str]:
    if isinstance(symbols, str):
        symbols = symbols.split(",")
    return list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))


def _iso_utc(t: pd.Timestamp) -> str:
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _sip_cap(t: pd.Timestamp) -> pd.Timestamp:
    """Cap at now-16min (free-plan SIP), floored to 5 min so repeated 'up to now' calls share a cache key."""
    cap = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(SIP_DELAY)).floor("5min")
    return min(t, cap)


def store_coverage(adjustment: str = "all") -> dt.date | None:
    """Last session in the local store (max session_date of SPY, which trades every session)."""
    if adjustment in _coverage:
        return _coverage[adjustment]
    p = BARS_DIR / _ADJ_DIR[adjustment] / "SPY.parquet"
    try:
        d = pq.read_table(p, columns=["session_date"]).column("session_date").to_pandas().max()
    except (OSError, ValueError):
        return None
    covered = cast(dt.date, d)
    _coverage[adjustment] = covered
    return covered


def _bars_to_df(sym: str, bars: list[dict[str, Any]], adjustment: str, feed: str) -> pd.DataFrame:
    df = pd.DataFrame(bars).rename(columns=_COLS)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df.insert(0, "symbol", sym)
    df["adjustment"] = adjustment
    df["feed"] = feed
    return df


def _fetch_bars(
    symbols: Sequence[str],
    timeframe: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    adjustment: str,
    feed: str,
    batch: int = 100,
    asof: str | None = None,
    **kw: Any,
) -> pd.DataFrame:
    end = _sip_cap(end)
    if end <= start or not symbols:
        return pd.DataFrame()
    frames = []
    for i in range(0, len(symbols), batch):
        p = {
            "symbols": ",".join(symbols[i : i + batch]),
            "timeframe": timeframe,
            "start": _iso_utc(start),
            "end": _iso_utc(end),
            "adjustment": adjustment,
            "feed": feed,
            "limit": 10000,
            "sort": "asc",
            "asof": asof,
        }
        bars = alpaca_get_paginated("/v2/stocks/bars", p, "bars", **kw)
        for s, b in (bars or {}).items():
            if b:
                frames.append(_bars_to_df(s, b, adjustment, feed))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "timestamp_utc"], ignore_index=True)


def _read_local(sym: str, adjustment: str, start: dt.date, end: dt.date) -> pd.DataFrame | None:
    p = BARS_DIR / _ADJ_DIR[adjustment] / f"{sym}.parquet"
    if not p.exists():
        return None
    return cast(pd.DataFrame, pq.read_table(p).to_pandas())


def get_daily_bars(
    symbols: str | Iterable[str],
    start: Any,
    end: Any = None,
    adjustment: str = "all",
    *,
    feed: str = "sip",
    allow_api: bool = True,
    include_partial: bool = False,
) -> pd.DataFrame:
    """Daily bars, long format (one row per symbol x session), local store first.

    adjustment: 'all' (split+dividend adjusted, bars/daily/adjusted) or 'raw' (as traded, bars/daily/raw).
    start/end: dates (inclusive, America/New_York session dates). end=None -> today.
    API fallback (throttled + cached) only for:
      * sessions after the store's coverage end (store_coverage()), for symbols whose local series reaches that end;
      * symbols that have no local file at all (full requested window).
    Symbols whose local series stops before the coverage end (delisted / former members, mapped with `asof`) are NOT
    extended from the API, because Alpaca may map the ticker to a different, later company.
    Partial bars for today's still-open session are dropped unless include_partial=True.
    Output column `source` is 'local' or 'api'. df.attrs['warnings'] lists adjustment mismatches at the seam.
    """
    if adjustment not in _ADJ_DIR:
        raise ValueError("adjustment must be 'all' or 'raw'")
    syms = _norm_symbols(symbols)
    d0 = pd.Timestamp(start).date()
    d1 = pd.Timestamp(end).date() if end is not None else pd.Timestamp.now(tz="America/New_York").date()
    cov = store_coverage(adjustment)
    frames, warnings, tail_syms, missing_syms = [], [], [], []
    seam_close: dict[str, float] = {}
    for s in syms:
        df = _read_local(s, adjustment, d0, d1)
        if df is None or df.empty:
            missing_syms.append(s)
            continue
        last = df["session_date"].max()
        if cov is not None and last >= cov and d1 > cov:
            tail_syms.append(s)
            seam_close[s] = float(df.loc[df["session_date"] == last, "close"].iloc[-1])
        df = df[(df["session_date"] >= d0) & (df["session_date"] <= d1)].copy()
        df["source"] = "local"
        frames.append(df)

    if allow_api and (tail_syms or missing_syms):
        ny = "America/New_York"
        groups = []
        if tail_syms and cov is not None:
            # include the last stored session (seam) to detect a restated adjustment, then drop it
            groups.append((tail_syms, pd.Timestamp(cov).tz_localize(ny)))
        if missing_syms:
            groups.append((missing_syms, pd.Timestamp(d0).tz_localize(ny)))
        t_end = (pd.Timestamp(d1) + pd.Timedelta(days=1)).tz_localize(ny)
        for gsyms, t_start in groups:
            api = _fetch_bars(gsyms, "1Day", t_start, t_end, adjustment, feed)
            if api.empty:
                continue
            api["session_date"] = api["timestamp_utc"].dt.tz_convert(ny).dt.date
            for s, close in seam_close.items():
                seam = api[(api["symbol"] == s) & (api["session_date"] == cov)]
                if len(seam) and abs(seam["close"].iloc[0] / close - 1) > 1e-6:
                    warnings.append(
                        f"{s}: API close on {cov} differs from local ({seam['close'].iloc[0]} vs {close}); "
                        "adjustment likely restated (new corporate action). Pipeline full re-pull pending."
                    )
            if cov is not None:
                api = api[~((api["symbol"].isin(tail_syms)) & (api["session_date"] <= cov))]
            api = api[(api["session_date"] >= d0) & (api["session_date"] <= d1)]
            if not include_partial:
                final_after = pd.to_datetime(api["session_date"].astype(str)).dt.tz_localize(ny) + pd.Timedelta(
                    hours=20
                )
                api = api[(final_after <= pd.Timestamp.now(tz=ny)).to_numpy()]
            api["zero_volume"] = api["volume"].fillna(0) == 0
            api["source"] = "api"
            api["fetched_at_utc"] = pd.Timestamp.now(tz="UTC")
            frames.append(api)

    if not frames:
        out = pd.DataFrame(
            columns=[
                "symbol",
                "session_date",
                "timestamp_utc",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "vwap",
                "adjustment",
                "feed",
                "source",
            ]
        )
    else:
        frames = [f.dropna(axis=1, how="all") if len(frames) > 1 else f for f in frames if len(f)]
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if len(out):
            out = out.sort_values(["symbol", "session_date"], ignore_index=True)
    out.attrs["warnings"] = warnings
    for w in warnings:
        log.warning(w)
    return out


def get_intraday_bars(
    symbols: str | Iterable[str],
    start: Any,
    end: Any = None,
    timeframe: str = "1Min",
    adjustment: str = "raw",
    *,
    feed: str = "sip",
    tz: str = "America/New_York",
    batch: int = 100,
    **kw: Any,
) -> pd.DataFrame:
    """Intraday bars (e.g. '1Min', '5Min', '15Min', '1Hour') from Alpaca, through the shared throttle + cache.
    start/end: anything pd.Timestamp parses; naive values are interpreted in `tz` (default New York). A bare date as
    `end` means the end of that day. `end` is capped at now-16 min (free-plan SIP restriction).
    Includes pre/post-market bars (Alpaca default); filter on time of day for regular hours."""
    syms = _norm_symbols(symbols)
    t0 = pd.Timestamp(start)
    t0 = t0.tz_localize(tz) if t0.tzinfo is None else t0
    if end is None:
        t1 = pd.Timestamp.now(tz="UTC")
    else:
        t1 = pd.Timestamp(end)
        is_date = t1 == t1.normalize() and (
            (isinstance(end, (dt.date,)) and not isinstance(end, dt.datetime))
            or (isinstance(end, str) and len(end) <= 10)
        )
        t1 = t1.tz_localize(tz) if t1.tzinfo is None else t1
        if is_date:
            t1 = t1 + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    df = _fetch_bars(syms, timeframe, t0.tz_convert("UTC"), t1.tz_convert("UTC"), adjustment, feed, batch=batch, **kw)
    if len(df):
        df["timestamp_local"] = df["timestamp_utc"].dt.tz_convert(tz)
        df["timeframe"] = timeframe
    return df


def get_minute_bars(
    symbols: str | Iterable[str], start: Any, end: Any = None, adjustment: str = "raw", **kw: Any
) -> pd.DataFrame:
    return get_intraday_bars(symbols, start, end, "1Min", adjustment, **kw)


def get_hour_bars(
    symbols: str | Iterable[str], start: Any, end: Any = None, adjustment: str = "raw", **kw: Any
) -> pd.DataFrame:
    return get_intraday_bars(symbols, start, end, "1Hour", adjustment, **kw)


# ====================================================================================================================
# FRED / ALFRED (api.stlouisfed.org). Own cross-process throttle, separate from Alpaca's.
# The key is read from env FRED_API_KEY, else ~/.secrets/fred_api_key. It is sent only as the api_key query
# param and is stripped from cache keys, cached records, the ledger, logs and error messages.
# ====================================================================================================================
FRED_URL = "https://api.stlouisfed.org/fred/"
FRED_KEY_FILE = Path(os.environ.get("FRED_API_KEY_FILE", f"{_QR.HOME_DIR}/.secrets/fred_api_key"))
FRED_RPM = float(os.environ.get("DESK_FRED_RPM", "100"))  # FRED allows 120/min per key
FRED_BURST = float(os.environ.get("DESK_FRED_BURST", "10"))
FRED_TTL = float(os.environ.get("DESK_FRED_CACHE_TTL", "3600"))
ALFRED_MAX_VINTAGES = 1900  # FRED limit per request (output_type=1)
FRED_OPEN_END = "9999-12-31"
_SECRET_PARAMS = {"api_key"}
_FRED_LIMITER: RateLimiter | None = None


class FredError(RuntimeError):
    def __init__(self, status: int, endpoint: str, body: str):
        super().__init__(f"FRED HTTP {status} for {endpoint}: {_redact(body)[:300]}")
        self.status = status


class _RedactFilter(logging.Filter):
    """Scrubs the FRED key from log records of third-party loggers (urllib3 logs full request URLs at DEBUG, and FRED
    only accepts the key as a query parameter)."""

    def __init__(self, secret: str):
        super().__init__()
        self.secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if self.secret in msg:
            record.msg, record.args = msg.replace(self.secret, "<redacted>"), None
        return True


_REDACT_INSTALLED = False


def _install_redaction(secret: str) -> None:
    global _REDACT_INSTALLED
    if _REDACT_INSTALLED:
        return
    f = _RedactFilter(secret)
    for name in ("urllib3", "urllib3.connectionpool", "requests", "desk_data_client"):
        logging.getLogger(name).addFilter(f)
    _REDACT_INSTALLED = True


def _fred_key() -> str:
    k = os.environ.get("FRED_API_KEY")
    if not k:
        try:
            k = FRED_KEY_FILE.read_text().strip()
        except OSError:
            k = ""
    if not k:
        raise RuntimeError("FRED key not found: set env FRED_API_KEY or create the key file (value never logged)")
    _install_redaction(k)
    return k


def _redact(text: str) -> str:
    try:
        k = _fred_key()
    except RuntimeError:
        return text
    return text.replace(k, "<redacted>") if k and text else text


def fred_throttle() -> RateLimiter:
    """Shared FRED limiter (own bucket/state: .cache/ratelimit/fred.*), default 100 req/min, burst 10."""
    global _FRED_LIMITER
    if _FRED_LIMITER is None:
        _FRED_LIMITER = RateLimiter(name="fred", rpm=FRED_RPM, burst=FRED_BURST)
    return _FRED_LIMITER


def _fred_auto_ttl(params: dict[str, Any]) -> float | None:
    """Forever if the request is fully historical: realtime_end (or, without realtime params, observation_end) is
    more than 1 day ago. Vintage data for a closed real-time window never changes."""
    for k in ("realtime_end", "observation_end"):
        if k in params:
            if k == "observation_end" and "realtime_end" not in params:
                return FRED_TTL  # latest-vintage values for old dates can still be revised
            end = _parse_ts(params[k]) if str(params[k]) != FRED_OPEN_END else None
            if end is not None and end < pd.Timestamp.now(tz="UTC") - HISTORICAL_AGE:
                return None
    return FRED_TTL


def fred_get(
    endpoint: str,
    params: dict[str, Any] | None = None,
    *,
    ttl: float | str | None = "auto",
    use_cache: bool = True,
    max_retries: int = 8,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    timeout: float = 60.0,
    max_total_wait: float = 900.0,
) -> Any:
    """Throttled, cached GET of one FRED/ALFRED endpoint (e.g. 'series/observations'). Returns parsed JSON.
    Cache key = endpoint URL + params WITHOUT api_key. 4xx other than 429 raise FredError (message redacted)."""
    url = FRED_URL + endpoint.lstrip("/")
    params = {k: v for k, v in (params or {}).items() if v is not None and k not in _SECRET_PARAMS}
    params.setdefault("file_type", "json")
    key = _cache_key(url, params)
    eff_ttl: float | None = _fred_auto_ttl(params) if ttl == "auto" else cast(float | None, ttl)
    if use_cache:
        hit = _cache_read(key, eff_ttl)
        if hit is not None:
            return hit
    lim = fred_throttle()
    tag = "/fred/" + endpoint.lstrip("/")
    deadline = time.time() + max_total_wait
    attempt = n429 = 0
    while attempt < max_retries and time.time() < deadline:
        lim.acquire(tag)
        sess = _session()
        try:
            r = sess.get(url, params={**params, "api_key": _fred_key()}, timeout=timeout)
        except requests.RequestException as e:  # exception text can contain the URL -> log type only
            wait = random.uniform(0, min(max_delay, base_delay * 2**attempt))
            log.warning("network error %s on %s (attempt %d), retry in %.1fs", type(e).__name__, tag, attempt + 1, wait)
            attempt += 1
            time.sleep(wait)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            k = n429 if r.status_code == 429 else attempt
            backoff = random.uniform(0, min(max_delay, base_delay * 2**k))
            srv = _server_wait(r)
            wait = max(backoff, (srv or 0.0) + random.uniform(0, 1.0))
            if r.status_code == 429:
                n429 += 1
                wait = max(wait, 20.0)  # FRED's window is per minute; 429 body has no reset header
                lim.block_until(time.time() + wait)
            else:
                attempt += 1
            log.warning(
                "FRED HTTP %s on %s (429s=%d, other retries=%d), retry in %.1fs",
                r.status_code,
                tag,
                n429,
                attempt,
                wait,
            )
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise FredError(r.status_code, tag, r.text)
        body = r.json()
        if use_cache:
            _cache_write(key, url, params, body)  # params never include api_key
        return body
    raise FredError(429 if n429 else -1, tag, f"giving up after {attempt} retries / {n429} x 429")


def fred_get_all(
    endpoint: str, params: dict[str, Any], items_key: str, page_limit: int = 100000, **kw: Any
) -> list[dict[str, Any]]:
    """Offset/limit pagination for FRED list endpoints."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        j = fred_get(endpoint, {**params, "limit": page_limit, "offset": offset}, **kw)
        items = j.get(items_key) or []
        out.extend(items)
        count = int(j.get("count", len(out)))
        offset += len(items)
        if not items or offset >= count:
            return out


def _fred_values(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace(".", None), errors="coerce")  # '.' = missing (e.g. holiday) -> NaN


def fred_series_info(series_id: str, **kw: Any) -> dict[str, Any]:
    j = fred_get("series", {"series_id": series_id}, **kw)
    return cast(dict[str, Any], (j.get("seriess") or [{}])[0])


def fred_series(series_id: str, start: Any = None, end: Any = None, **kw: Any) -> pd.DataFrame:
    """Latest-vintage observations: columns series_id, observation_date, value (NaN for FRED '.')."""
    p = {
        "series_id": series_id,
        "observation_start": pd.Timestamp(start).date().isoformat() if start is not None else None,
        "observation_end": pd.Timestamp(end).date().isoformat() if end is not None else None,
    }
    obs = fred_get_all("series/observations", p, "observations", **kw)
    df = pd.DataFrame(obs, columns=["date", "value"])
    return pd.DataFrame(
        {
            "series_id": series_id,
            "observation_date": pd.to_datetime(df["date"]).dt.date,
            "value": _fred_values(df["value"]),
        }
    )


def fred_vintage_dates(series_id: str, **kw: Any) -> list[str]:
    return [
        str(d)
        for d in fred_get_all("series/vintagedates", {"series_id": series_id}, "vintage_dates", page_limit=10000, **kw)
    ]


def alfred_vintages(series_id: str, start: Any = None, end: Any = None, **kw: Any) -> pd.DataFrame:
    """Every vintage of every observation (ALFRED, output_type=1 = observations by real-time period).
    Columns: series_id, observation_date, value, realtime_start, realtime_end (date; 9999-12-31 = still current).
    FRED allows <= 2000 vintage dates per request, so the real-time axis is split on the series' vintage dates and
    rows that continue across a chunk boundary with the same value are merged back into one real-time interval."""
    vds = fred_vintage_dates(series_id, **kw)
    if not vds:
        return pd.DataFrame(columns=["series_id", "observation_date", "value", "realtime_start", "realtime_end"])
    obs_p = {
        "series_id": series_id,
        "output_type": 1,
        "observation_start": pd.Timestamp(start).date().isoformat() if start is not None else None,
        "observation_end": pd.Timestamp(end).date().isoformat() if end is not None else None,
    }
    rows: list[dict[str, Any]] = []
    chunks = [vds[i : i + ALFRED_MAX_VINTAGES] for i in range(0, len(vds), ALFRED_MAX_VINTAGES)]
    for ci, ch in enumerate(chunks):
        last = ci == len(chunks) - 1
        # the last chunk is left open-ended so it also returns the current vintage (realtime_end 9999-12-31)
        rt_end = FRED_OPEN_END if last else (pd.Timestamp(chunks[ci + 1][0]) - pd.Timedelta(days=1)).date().isoformat()
        rows.extend(
            fred_get_all(
                "series/observations", {**obs_p, "realtime_start": ch[0], "realtime_end": rt_end}, "observations", **kw
            )
        )
    df = pd.DataFrame(rows, columns=["date", "value", "realtime_start", "realtime_end"])
    df["value"] = _fred_values(df["value"])
    df = df.sort_values(["date", "realtime_start"], ignore_index=True)
    # merge chunk-boundary splits: same obs, same value (NaN==NaN), contiguous real-time
    prev_end = pd.to_datetime(df["realtime_end"].where(df["realtime_end"] != FRED_OPEN_END), errors="coerce")
    same_obs = df["date"].eq(df["date"].shift())
    same_val = df["value"].eq(df["value"].shift()) | (df["value"].isna() & df["value"].shift().isna())
    contiguous = pd.to_datetime(df["realtime_start"]).eq(prev_end.shift() + pd.Timedelta(days=1))
    grp = (~(same_obs & same_val & contiguous)).cumsum()
    m = df.groupby(grp, sort=False).agg(
        date=("date", "first"),
        value=("value", "first"),
        realtime_start=("realtime_start", "first"),
        realtime_end=("realtime_end", "last"),
    )
    out = pd.DataFrame(
        {
            "series_id": series_id,
            "observation_date": pd.to_datetime(m["date"]).dt.date.values,
            "value": m["value"].values,
            "realtime_start": pd.to_datetime(m["realtime_start"]).dt.date.values,
            "realtime_end": [
                dt.date(9999, 12, 31) if x == FRED_OPEN_END else pd.Timestamp(x).date() for x in m["realtime_end"]
            ],
        }
    )
    return out.sort_values(["observation_date", "realtime_start"], ignore_index=True)


def fred_release_dates(
    release_id: int,
    start: Any = None,
    end: Any = None,
    include_empty: bool = True,
    **kw: Any,
) -> pd.DataFrame:
    """Release dates for a FRED release (e.g. 18 = H.15 Selected Interest Rates). Columns release_id, date."""
    p = {
        "release_id": release_id,
        "include_release_dates_with_no_data": str(include_empty).lower(),
        "realtime_start": pd.Timestamp(start).date().isoformat() if start is not None else "1776-07-04",
        "realtime_end": pd.Timestamp(end).date().isoformat() if end is not None else FRED_OPEN_END,
        "sort_order": "asc",
    }
    rows = fred_get_all("release/dates", p, "release_dates", page_limit=10000, **kw)
    df = pd.DataFrame(rows, columns=["release_id", "date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


# ---- point-in-time view over the local ALFRED store ------------------------------------------------------------------
FRED_STORE_DIRS = [
    DATA_DIR / "macro" / "treasury",
    DATA_DIR / "macro" / "carry" / "g10_3m",
    DATA_DIR / "sentiment" / "credit",
]


def _local_vintage_file(series_id: str) -> Path | None:
    """Newest frozen vintages file (…_vintages_YYYYMMDD.parquet) in the FRED store dirs that contains series_id."""
    cands = []
    for d in FRED_STORE_DIRS:
        cands += sorted(d.glob("*_vintages_*.parquet"))
    for p in sorted(cands, key=lambda p: p.stem.rsplit("_", 1)[-1], reverse=True):
        try:
            ids = pq.read_table(p, columns=["series_id"]).column("series_id").unique().to_pylist()
        except (OSError, ValueError):
            continue
        if series_id in ids:
            return p
    return None


def alfred_store(series_id: str) -> pd.DataFrame:
    """All stored vintages of a series with availability columns (available_at_et / available_at_sgt, …).
    Falls back to a live ALFRED pull (throttled, cached) with a conservative end-of-day availability if not stored."""
    p = _local_vintage_file(series_id)
    if p is not None:
        return pd.read_parquet(p, filters=[("series_id", "==", series_id)])
    log.info("%s not in local FRED store; pulling ALFRED vintages live", series_id)
    df = alfred_vintages(series_id)
    t = pd.to_datetime(df["realtime_start"].astype(str)).dt.tz_localize("America/New_York") + pd.Timedelta(
        hours=23, minutes=59
    )
    df["available_at_et"] = t
    df["available_at_sgt"] = t.dt.tz_convert("Asia/Singapore")
    df["availability_method"] = "realtime_start_end_of_day_et_live"
    return df


def alfred_asof(series_id: str, asof: Any, start: Any = None, end: Any = None) -> pd.DataFrame:
    """Point-in-time view: for each observation, the value as it was known at `asof` (naive = America/New_York).
    Uses only vintages with available_at_et <= asof. Columns: observation_date, value, realtime_start, available_at_et,
    vintage_count_to_date. Observations not yet published at `asof` are absent."""
    t = pd.Timestamp(asof)
    t = t.tz_localize("America/New_York") if t.tzinfo is None else t.tz_convert("America/New_York")
    v = alfred_store(series_id)
    v = v[v["available_at_et"] <= t]
    if start is not None:
        v = v[v["observation_date"] >= pd.Timestamp(start).date()]
    if end is not None:
        v = v[v["observation_date"] <= pd.Timestamp(end).date()]
    v = v.sort_values(["observation_date", "available_at_et"])
    n = v.groupby("observation_date").size().rename("vintage_count_to_date")
    out = v.groupby("observation_date", as_index=False).tail(1).merge(n, on="observation_date")
    cols = [
        "series_id",
        "observation_date",
        "value",
        "realtime_start",
        "available_at_et",
        "available_at_sgt",
        "availability_method",
        "vintage_count_to_date",
    ]
    return out[[c for c in cols if c in out.columns]].reset_index(drop=True)


def alfred_first_available(series_id: str) -> pd.DataFrame:
    """'As first available' view: the first published value of each observation and when it became available."""
    v = alfred_store(series_id).sort_values(["observation_date", "realtime_start"])
    return v.groupby("observation_date", as_index=False).head(1).reset_index(drop=True)
