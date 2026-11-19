"""stat-arb researcher H1/H2 Alpha Vantage DATA REBUILD (data only; no returns/signals/backtests).
Key: read from env ALPHAVANTAGE_API_KEY only; never printed/logged/written. All messages redacted.
Limiter: <=15 requests per rolling 60s AND >=4.1s spacing (this pull's share of the 75/min key limit).
No-overwrite: skip if any file for symbol exists; write temp then os.link (atomic EXCL) to final."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

KEY = os.environ.get("ALPHAVANTAGE_API_KEY") or ""
ROOT = Path(f"{_QR.DESK_DIR}")
EQ = ROOT / "data/alphavantage/equity"
REF = ROOT / "data/alphavantage/reference"
LOGS = ROOT / "data/alphavantage/logs"
WORK = ROOT / "statarb/av_rebuild_20261110"
TS = sys.argv[1]
MEMBERSHIP = ROOT / "data/universe/sp500_membership.parquet"
MEMBERSHIP_SHA = desk_pin("data.alphavantage.daily_adjusted.fetch_av_h1h2", "MEMBERSHIP_SHA")
LOAD0, HOLD1 = pd.Timestamp("2015-12-31"), pd.Timestamp("2026-10-28")
ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "SPY", "AGG", "BND"]
HEADER = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "adjusted_close",
    "volume",
    "dividend_amount",
    "split_coefficient",
]
LOGF = LOGS / f"sofia_equity_fetch_{TS}.log"


def redact(s: object) -> str:
    s = str(s)
    if KEY:
        s = s.replace(KEY, "***REDACTED***").replace(urllib.parse.quote(KEY), "***REDACTED***")
    return re.sub(r"apikey=[^&\s]+", "apikey=***REDACTED***", s)


def log(msg: object) -> None:
    line = f"{datetime.now(UTC).isoformat()} {redact(msg)}"
    print(line, flush=True)
    with open(LOGF, "a") as f:
        f.write(line + "\n")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def utc() -> str:
    return datetime.now(UTC).isoformat()


class Limiter:
    def __init__(self, per_min: int = 15, spacing: float = 4.1) -> None:
        self.q: deque[float] = deque()
        self.per = per_min
        self.spacing = spacing
        self.last = 0.0
        self.count = 0

    def wait(self) -> None:
        while True:
            now = time.monotonic()
            while self.q and now - self.q[0] >= 60.5:
                self.q.popleft()
            gap = self.last + self.spacing - now
            full = (self.q[0] + 60.5 - now) if len(self.q) >= self.per else 0
            w = max(gap, full, 0)
            if w <= 0:
                break
            time.sleep(w)
        self.last = time.monotonic()
        self.q.append(self.last)
        self.count += 1


L = Limiter()


class Fatal(Exception):
    pass


def call(params: dict[str, str]) -> tuple[str, bytes | None, str]:
    """Returns (kind, bytes|None, detail). kind in DATA, ERROR_MESSAGE, FAILED. Throttle handled here."""
    q = dict(params)
    q["apikey"] = KEY
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(q)
    backoff = 20.0
    for attempt in range(7):
        L.wait()
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                body = r.read()
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
            body = b""
            if code == 429:
                log(f"HTTP429 attempt={attempt} backoff={backoff}s")
                time.sleep(backoff)
                backoff *= 2
                continue
            return "FAILED", None, redact(f"HTTP {code}")
        except Exception as e:
            log(f"NETWORK {type(e).__name__}: {redact(e)} attempt={attempt}")
            time.sleep(backoff)
            backoff *= 2
            continue
        head = body.lstrip()[:1]
        if head == b"{":
            try:
                j = json.loads(body)
            except Exception:
                return "FAILED", None, "UNPARSEABLE_JSON"
            if "Error Message" in j:
                return "ERROR_MESSAGE", None, redact(j["Error Message"])[:300]
            msg = redact(j.get("Note") or j.get("Information") or "")
            if "Note" in j or "Information" in j:
                low = msg.lower()
                if any(
                    t in low
                    for t in (
                        "frequency",
                        "per minute",
                        "rate limit",
                        "spread out",
                        "requests per",
                        "call frequency",
                        "burst",
                    )
                ):
                    log(f"THROTTLE_NOTICE attempt={attempt} backoff={backoff}s")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise Fatal("NON_THROTTLE_INFORMATION: " + msg[:300])
            return "FAILED", None, "UNEXPECTED_JSON_KEYS:" + ",".join(sorted(j))[:200]
        return "DATA", body, f"HTTP {code}"
    return "FAILED", None, "RETRIES_EXHAUSTED_THROTTLE_OR_NETWORK"


def excl_write(final: Path, data: bytes) -> bool:
    """Temp in same dir, then hard-link (fails if final exists: atomic no-clobber)."""
    tmp = final.parent / f".{final.name}.research.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, final)
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink()


def validate_series(body: bytes) -> tuple[int, str, str]:
    text = body.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != HEADER:
        raise ValueError("BAD_HEADER")
    data = rows[1:]
    if not data:
        raise ValueError("NO_ROWS")
    dates = []
    for r in data:
        if len(r) != 9:
            raise ValueError("BAD_ROW_WIDTH")
        dates.append(datetime.strptime(r[0], "%Y-%m-%d").date())
        [float(x) for x in r[1:]]
    if len(set(dates)) != len(dates):
        raise ValueError("DUPLICATE_DATES")
    return len(data), min(dates).isoformat(), max(dates).isoformat()


def existing_for(sym: str) -> list[str]:
    want = {sym.upper(), sym.upper().replace(".", "-"), sym.upper().replace(".", "_"), sym.upper().replace(".", "")}
    hits: list[str] = []
    for p in EQ.rglob("*"):  # includes other desks' subdirectories (e.g. daily_adjusted_full_20261110/)
        if p.name.startswith(".") or not p.is_file():
            continue
        n = p.name.upper()
        stem = n
        for ext in (".CSV.GZ", ".JSON.GZ", ".CSV", ".JSON", ".PARQUET"):
            if n.endswith(ext):
                stem = n[: -len(ext)]
                break
        if stem in want:
            hits.append(str(p.relative_to(EQ)))
    return sorted(hits)


def main() -> None:
    for folder in (EQ, REF, LOGS):
        folder.mkdir(parents=True, exist_ok=True)
    assert KEY, "key missing"
    mb = MEMBERSHIP.read_bytes()
    assert sha(mb) == MEMBERSHIP_SHA
    sources = {
        str(p): sha(Path(p).read_bytes())
        for p in [
            MEMBERSHIP,
            ROOT / "statarb/PREREG_ORIGINAL.md",
            ROOT / "statarb/original/backtest_h1_h2.py",
            ROOT / "statarb/INPUT_CONTRACT.md",
        ]
    }
    m = pd.read_parquet(MEMBERSHIP)
    e = pd.to_datetime(m.end_date)
    s = pd.to_datetime(m.start_date_filled)
    u = m[(e.isna() | (e > LOAD0)) & (s <= HOLD1)].copy()
    # LISTING_STATUS once each (resume-safe: reuse saved raw if this TS already fetched it)
    listing: dict[str, pd.DataFrame] = {}
    for state in ("active", "delisted"):
        out = REF / f"LISTING_STATUS_{state}_SOFIA_{TS}.csv"
        if not out.exists():
            kind, body, det = call(dict(function="LISTING_STATUS", state=state))
            if kind != "DATA":
                raise Fatal(f"LISTING_STATUS {state} {kind} {det}")
            payload = cast(bytes, body)
            hdr = payload.decode().splitlines()[0]
            if hdr != "symbol,name,exchange,assetType,ipoDate,delistingDate,status":
                raise Fatal("LISTING_HEADER " + hdr[:100])
            assert excl_write(out, payload)
            log(f"LISTING_STATUS {state} saved sha={sha(payload)} bytes={len(payload)}")
        listing[state] = pd.read_csv(out, keep_default_na=False, dtype=str)
    act, dl = listing["active"], listing["delisted"]

    def avsym(x: str) -> str:
        return x.replace(".", "-")

    rows: list[dict[str, Any]] = []
    for sym, g in u.groupby("symbol"):
        av = avsym(sym)  # type: ignore[arg-type]  # groupby symbol key is a string
        ivs = [
            (str(r.start_date_filled), None if r.end_date is None or pd.isna(r.end_date) else str(r.end_date))  # type: ignore[arg-type]  # end_date cells are dates
            for r in g.itertuples()
        ]
        last_end = None if any(i[1] is None for i in ivs) else max(i[1] for i in ivs)  # type: ignore[type-var]  # interval ends are date strings
        a = act[act.symbol == av]
        d = dl[dl.symbol == av]
        flags: list[str] = []
        if last_end is None:
            cls = "CURRENT_MEMBER_ACTIVE" if len(a) else ("CURRENT_MEMBER_NOT_IN_ACTIVE_LISTING")
        else:
            cls = "FORMER_MEMBER"
            if len(a):
                ipo = a.ipoDate.iloc[0]
                if ipo and ipo > last_end:
                    flags.append(
                        f"TICKER_REUSE_SUSPECT: active listing ipoDate {ipo} after membership end {last_end}; AV history likely different issuer"
                    )
                else:
                    flags.append("STILL_LISTED_ACTIVE")
            _dm = d[(d.delistingDate >= last_end[:7]) | (d.delistingDate == "")] if len(d) else d
            if len(d):
                win = [f"{r.ipoDate}..{r.delistingDate}" for r in d.itertuples()]
                ok = [
                    r
                    for r in d.itertuples()
                    if (not r.ipoDate or r.ipoDate <= last_end)  # type: ignore[operator, arg-type]  # ipoDate cells are strings
                    and r.delistingDate
                    and r.delistingDate >= str((pd.Timestamp(last_end) - pd.Timedelta(days=400)).date())  # type: ignore[operator, arg-type]  # delistingDate cells are strings
                ]
                if len(ok) == 1:
                    flags.append(f"DELISTED_MATCH window {ok[0].ipoDate}..{ok[0].delistingDate}")
                elif len(ok) > 1:
                    flags.append("DELISTED_AMBIGUOUS_MULTIPLE " + ";".join(win))
                else:
                    flags.append("DELISTED_RECORD_WINDOW_MISMATCH " + ";".join(win))
            if not len(a) and not len(d):
                flags.append("NO_LISTING_RECORD")
        rows.append(
            dict(
                symbol=sym,
                av_symbol=av,
                kind="EQUITY",
                membership_intervals=ivs,
                membership_last_end=last_end,
                listing_class=cls,
                listing_flags=flags,
                active_rows=a.to_dict("records"),
                delisted_rows=d.to_dict("records"),
            )
        )
    for etf in ETFS:
        a = act[act.symbol == etf]
        rows.append(
            dict(
                symbol=etf,
                av_symbol=etf,
                kind="ETF_HEDGE",
                membership_intervals=[],
                membership_last_end=None,
                listing_class="ETF_ACTIVE" if len(a) else "ETF_NOT_IN_ACTIVE",
                listing_flags=[],
                active_rows=a.to_dict("records"),
                delisted_rows=dl[dl.symbol == etf].to_dict("records"),
            )
        )
    uni_path = WORK / f"UNIVERSE_SOFIA_{TS}.json"
    if not uni_path.exists():
        uni_path.write_text(
            json.dumps(
                dict(
                    sources=sources,
                    rule="sp500_membership intervals overlapping [2015-12-31 LOAD0, 2026-10-28 HOLDOUT1] + backtest_h1_h2.ETFS (11 SECTOR_ETF + SPY AGG BND)",
                    n_equity=len(rows) - len(ETFS),
                    n_etf=len(ETFS),
                    symbols=rows,
                ),
                indent=1,
                default=str,
            )
        )
    log(f"UNIVERSE equity={len(rows) - len(ETFS)} etf={len(ETFS)} total={len(rows)}")
    prog = WORK / f"PROGRESS_SOFIA_{TS}.jsonl"
    done = {}
    if prog.exists():
        for line in prog.read_text().splitlines():
            r = json.loads(line)
            done[r["symbol"]] = r
    for i, r in enumerate(rows):
        sym = r["symbol"]
        if sym in done:
            continue
        rec = dict(
            symbol=sym,
            av_symbol=r["av_symbol"],
            kind=r["kind"],
            listing_class=r["listing_class"],
            listing_flags=r["listing_flags"],
            endpoint="https://www.alphavantage.co/query",
            params=dict(
                function="TIME_SERIES_DAILY_ADJUSTED", symbol=r["av_symbol"], outputsize="full", datatype="csv"
            ),
        )
        final = EQ / f"{sym}.csv"
        hit = existing_for(sym)
        if hit:
            rec.update(status="SKIPPED_EXISTING", existing=hit, checked_utc=utc())
        else:
            kind, body, det = call(rec["params"])
            rec["fetch_utc"] = utc()
            rec["detail"] = det
            if kind == "ERROR_MESSAGE":
                rec["status"] = "NOT_AVAILABLE"
            elif kind == "FAILED":
                rec["status"] = "FAILED"
            else:
                series = cast(bytes, body)
                try:
                    n, f0, f1 = validate_series(series)
                except Exception as ex:
                    rec.update(status="FAILED_VALIDATION", detail=redact(f"{type(ex).__name__}:{ex}")[:200])
                else:
                    if KEY and KEY.encode() in series:
                        rec.update(status="FAILED_KEY_IN_BODY")
                    elif existing_for(sym) or not excl_write(final, series):
                        rec.update(status="SKIPPED_EXISTING_RACE", existing=existing_for(sym))
                    else:
                        rec.update(
                            status="FETCHED",
                            path=str(final),
                            sha256=sha(series),
                            bytes=len(series),
                            rows=n,
                            first_date=f0,
                            last_date=f1,
                        )
                        if (
                            r["membership_intervals"]
                            and f0 > max(i[0] for i in r["membership_intervals"])
                            and r["membership_last_end"]
                            and f0 > r["membership_last_end"]
                        ):
                            rec["listing_flags"] = rec["listing_flags"] + [
                                "SERIES_STARTS_AFTER_MEMBERSHIP_END: different issuer, do not use for member window"
                            ]
        with open(prog, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        log(f"[{i + 1}/{len(rows)}] {sym} {rec['status']} req={L.count}")
    log("FETCH_LOOP_COMPLETE")


if __name__ == "__main__":
    try:
        main()
    except Fatal as ex:
        log(f"FATAL {redact(ex)}")
        sys.exit(2)
    except Exception as ex:
        log(f"ERROR {type(ex).__name__}: {redact(ex)}")
        sys.exit(3)
