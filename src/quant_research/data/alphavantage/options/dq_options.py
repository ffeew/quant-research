#!/usr/bin/env python3
"""DQ pass. Victor 63d3073d: content stats DEV-only (<2016-06-01).
OOS (>=2016-06-01): existence + row count (from manifest) + sha256 ONLY.
Hashing OOS files (decompress + hash raw payload) is allowed for integrity;
do not inspect quote/IV/expiry/greeks fields on OOS.
Outputs: DQ_REPORT.md, DQ_DEV_per_day.csv
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import json
import os
import statistics
from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = Path(f"{_QR.DATA_DIR}/alphavantage/options")
MANIFEST = ROOT / "MANIFEST.csv"
OUT_MD = ROOT / "DQ_REPORT.md"
OUT_CSV = ROOT / "DQ_DEV_per_day.csv"
OUT_VERIFY = ROOT / "SHA_VERIFY.csv"
SYMBOLS = ["SPY", "QQQ"]
START, END = "2008-01-02", "2026-11-09"
OOS_START = "2016-06-01"
QQQ_RENAME = "2011-03-23"
# Flag: probe showed n=1880 vs ~978 next day (possible overlap)
QQQ_FLAG_DATE = "2011-03-23"


def trading_days() -> list[str]:
    import pandas_market_calendars as mcal

    cal = mcal.get_calendar("NYSE")
    sched = cal.schedule(start_date=START, end_date=END)
    return [d.strftime("%Y-%m-%d") for d in sched.index]


def sha256_file_bytes(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_gz_payload(p: Path) -> tuple[str, bytes]:
    """Hash uncompressed JSON payload (matches fetch MANIFEST sha)."""
    with gzip.open(p, "rb") as f:
        raw = f.read()
    return hashlib.sha256(raw).hexdigest(), raw


def gap_ranges(missing: Collection[str], expected: Sequence[str]) -> list[tuple[str, str, int]]:
    if not missing:
        return []
    eidx = {d: i for i, d in enumerate(expected)}
    miss_sorted = sorted(missing, key=lambda d: eidx[d])
    ranges = []
    rs = re_ = miss_sorted[0]
    prev_i = eidx[rs]
    for d in miss_sorted[1:]:
        i = eidx[d]
        if i == prev_i + 1:
            re_ = d
            prev_i = i
        else:
            ranges.append((rs, re_, eidx[re_] - eidx[rs] + 1))
            rs = re_ = d
            prev_i = i
    ranges.append((rs, re_, eidx[re_] - eidx[rs] + 1))
    return ranges


def path_for(sym: str, d: str) -> Path:
    if d >= OOS_START:
        return ROOT / sym / "oos_holdout" / f"{d}.json.gz"
    return ROOT / sym / f"{d}.json.gz"


def load_manifest_latest() -> dict[tuple[str, str], dict[str, str]]:
    """Last OK/EMPTY/FAIL row per (symbol, date)."""
    latest: dict[tuple[str, str], dict[str, str]] = {}
    if not MANIFEST.exists():
        return latest
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["symbol"], row["date"])
            latest[key] = row
    return latest


def analyze_dev(path: Path, requested_date: str) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "rows": 0,
        "zero_bid": 0,
        "zero_ask": 0,
        "crossed": 0,
        "locked": 0,
        "mark_mid_abs_sum": 0.0,
        "mark_mid_n": 0,
        "mark_mid_gt_0_01": 0,
        "iv_le0": 0,
        "iv_gt3": 0,
        "iv_nan": 0,
        "greeks_missing": 0,
        "n_expiries": 0,
        "nearest_dte": "",
        "farthest_dte": "",
        "has_30_45_dte": 0,
        "n_weekly_like": 0,
        "n_monthly_like": 0,
        "date_mismatch": 0,
        "dup_contractIDs": 0,
        "status": "MISSING",
        "sha256": "",
    }
    if not path.exists():
        return stats
    try:
        sha, raw = sha256_gz_payload(path)
        stats["sha256"] = sha
        data = json.loads(raw)
    except Exception:
        stats["status"] = "CORRUPT"
        return stats
    rows = data.get("data")
    if not isinstance(rows, list):
        stats["status"] = "BAD_PAYLOAD"
        return stats
    if len(rows) == 0:
        stats["status"] = "EMPTY"
        return stats
    stats["status"] = "OK"
    stats["rows"] = len(rows)
    expiries = set()
    dtes = []
    req = datetime.strptime(requested_date, "%Y-%m-%d").date()
    id_counts: Counter[str] = Counter()
    for r in rows:
        cid = r.get("contractID") or ""
        id_counts[cid] += 1
        try:
            bid = float(r.get("bid") or 0)
            ask = float(r.get("ask") or 0)
        except (TypeError, ValueError):
            bid = ask = 0.0
        if bid == 0:
            stats["zero_bid"] += 1
        if ask == 0:
            stats["zero_ask"] += 1
        if bid > ask > 0:
            stats["crossed"] += 1
        if bid == ask and bid > 0:
            stats["locked"] += 1
        # mark vs mid
        try:
            mark = float(r["mark"]) if r.get("mark") not in (None, "") else None
        except (TypeError, ValueError):
            mark = None
        if mark is not None and ask > 0:
            mid = (bid + ask) / 2.0
            diff = abs(mark - mid)
            stats["mark_mid_abs_sum"] += diff
            stats["mark_mid_n"] += 1
            if diff > 0.01:
                stats["mark_mid_gt_0_01"] += 1
        iv_raw = r.get("implied_volatility")
        try:
            iv = float(iv_raw) if iv_raw not in (None, "") else float("nan")
        except (TypeError, ValueError):
            iv = float("nan")
        if iv != iv:
            stats["iv_nan"] += 1
        elif iv <= 0:
            stats["iv_le0"] += 1
        elif iv > 3.0:
            stats["iv_gt3"] += 1
        if any(r.get(k) in (None, "") for k in ("delta", "gamma", "theta", "vega", "rho")):
            stats["greeks_missing"] += 1
        exp = r.get("expiration")
        if exp:
            expiries.add(exp)
            try:
                ed = datetime.strptime(exp, "%Y-%m-%d").date()
                dtes.append((ed - req).days)
            except Exception:
                pass
        if r.get("date") and r.get("date") != requested_date:
            stats["date_mismatch"] += 1
    stats["dup_contractIDs"] = sum(1 for k, v in id_counts.items() if k and v > 1)
    stats["n_expiries"] = len(expiries)
    if dtes:
        stats["nearest_dte"] = min(dtes)
        stats["farthest_dte"] = max(dtes)
        stats["has_30_45_dte"] = int(any(30 <= d <= 45 for d in dtes))
    for exp in expiries:
        try:
            ed = datetime.strptime(exp, "%Y-%m-%d").date()
            if ed.weekday() == 4:
                weeknum = (ed.day - 1) // 7 + 1
                if weeknum == 3:
                    stats["n_monthly_like"] += 1
                else:
                    stats["n_weekly_like"] += 1
        except Exception:
            pass
    return stats


def verify_oos_integrity(path: Path, manifest_row: dict[str, Any] | None) -> dict[str, Any]:
    """existence + sha256 of payload + rows FROM MANIFEST. No field inspection."""
    out = {
        "rows": int(manifest_row["rows"]) if manifest_row and manifest_row.get("rows") not in (None, "") else "",
        "status": "MISSING",
        "sha256": "",
        "sha_match": "",
        "file_exists": 0,
        "manifest_status": (manifest_row or {}).get("status", ""),
    }
    if not path.exists():
        return out
    out["file_exists"] = 1
    try:
        sha, raw = sha256_gz_payload(path)
        out["sha256"] = sha
        # Integrity only: confirm payload is JSON with a list under 'data',
        # without reading quote/IV/greeks/expiry fields.
        data = json.loads(raw)
        if not isinstance(data, dict) or "data" not in data or not isinstance(data["data"], list):
            if any(k in data for k in ("Information", "Note", "Error Message")):
                out["status"] = "BAD_PAYLOAD"
            else:
                out["status"] = "BAD_PAYLOAD"
            return out
        nrows = len(data["data"])
        # Prefer manifest rows; cross-check length only (no field reads)
        if manifest_row and str(manifest_row.get("rows", "")) != "":
            try:
                mrows = int(manifest_row["rows"])
                if mrows != nrows:
                    out["status"] = "ROW_MISMATCH"
                    out["rows"] = mrows  # keep manifest as authoritative for report
                    out["sha_match"] = "1" if (manifest_row.get("sha256") == sha) else "0"
                    return out
            except ValueError:
                pass
        else:
            out["rows"] = nrows
        out["status"] = "EMPTY" if nrows == 0 else "OK"
        if manifest_row and manifest_row.get("sha256"):
            out["sha_match"] = "1" if manifest_row["sha256"] == sha else "0"
        else:
            out["sha_match"] = "NO_MANIFEST"
        return out
    except Exception:
        out["status"] = "CORRUPT"
        return out


def main() -> None:
    expected = trading_days()
    expected_dev = [d for d in expected if d < OOS_START]
    expected_oos = [d for d in expected if d >= OOS_START]
    manifest = load_manifest_latest()

    per_day_fields = [
        "symbol",
        "date",
        "partition",
        "status",
        "rows",
        "zero_bid",
        "zero_ask",
        "crossed",
        "locked",
        "mark_mid_mean_abs",
        "mark_mid_gt_0_01",
        "iv_le0",
        "iv_gt3",
        "iv_nan",
        "greeks_missing",
        "n_expiries",
        "nearest_dte",
        "farthest_dte",
        "has_30_45_dte",
        "n_weekly_like",
        "n_monthly_like",
        "date_mismatch",
        "dup_contractIDs",
        "sha256",
        "sha_match",
    ]
    verify_fields = [
        "symbol",
        "date",
        "partition",
        "path",
        "file_exists",
        "manifest_status",
        "manifest_rows",
        "manifest_sha256",
        "recomputed_sha256",
        "sha_match",
        "status",
    ]
    all_rows_out = []
    verify_rows = []
    lines = []
    sgt = datetime.now(UTC) + timedelta(hours=8)
    lines.append("# Options DQ Report — SPY / QQQ (Victor 63d3073d partitions)")
    lines.append("")
    lines.append(
        f"**Generated:** {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} UTC / "
        f"{sgt.strftime('%Y-%m-%d %H:%M')} Asia/Singapore"
    )
    lines.append(f"**Window:** {START} → {END}. **DEV:** `< {OOS_START}`. **OOS holdout:** `>= {OOS_START}`.")
    lines.append(f"**Expected sessions:** {len(expected)} (DEV {len(expected_dev)}, OOS {len(expected_oos)})")
    lines.append("")
    lines.append(
        "Content checks (spreads/IV/expiry/mark/dups) = **DEV only**. "
        "OOS = existence + rows (manifest) + sha256 integrity only."
    )
    lines.append("")

    summary_json = {}
    sha_mismatch_total = 0
    key_leak_hits = 0  # count only; never print key

    # Key leak scan (count only) over options tree text-ish files + scripts/logs
    # Never print the key value.
    av_key = os.environ.get("ALPHAVANTAGE_API_KEY", "")
    scan_paths = []
    for base in [ROOT, Path(f"{_QR.DATA_DIR}/alphavantage/logs"), Path(f"{_QR.DATA_DIR}/alphavantage/scripts")]:
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file() and p.suffix in (".md", ".csv", ".json", ".log", ".py", ".txt", ".out"):
                    scan_paths.append(p)
    if av_key:
        for p in scan_paths:
            try:
                # skip binary gz
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if av_key in text:
                key_leak_hits += 1

    for sym in SYMBOLS:
        lines.append(f"## {sym}")
        lines.append("")

        # ---- DEV ----
        present = empty = missing = corrupt = 0
        missing_dates = []
        empty_dates = []
        year_rows = defaultdict(list)
        agg: defaultdict[str, int] = defaultdict(int)
        first_ok = last_ok = None
        dte30_days = 0
        n_ok = 0
        weekly_by_year: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"days_with_weekly": 0, "ok": 0})

        for d in expected_dev:
            path = path_for(sym, d)
            mrow = manifest.get((sym, d))
            st = analyze_dev(path, d)
            sha_match = ""
            if mrow and mrow.get("sha256") and st["sha256"]:
                sha_match = "1" if mrow["sha256"] == st["sha256"] else "0"
                if sha_match == "0":
                    sha_mismatch_total += 1
            elif st["sha256"] and not (mrow and mrow.get("sha256")):
                sha_match = "NO_MANIFEST"
            mark_mid_mean = round(st["mark_mid_abs_sum"] / st["mark_mid_n"], 6) if st["mark_mid_n"] else ""
            row = {
                "symbol": sym,
                "date": d,
                "partition": "DEV",
                "status": st["status"],
                "rows": st["rows"],
                "zero_bid": st["zero_bid"],
                "zero_ask": st["zero_ask"],
                "crossed": st["crossed"],
                "locked": st["locked"],
                "mark_mid_mean_abs": mark_mid_mean,
                "mark_mid_gt_0_01": st["mark_mid_gt_0_01"],
                "iv_le0": st["iv_le0"],
                "iv_gt3": st["iv_gt3"],
                "iv_nan": st["iv_nan"],
                "greeks_missing": st["greeks_missing"],
                "n_expiries": st["n_expiries"],
                "nearest_dte": st["nearest_dte"],
                "farthest_dte": st["farthest_dte"],
                "has_30_45_dte": st["has_30_45_dte"],
                "n_weekly_like": st["n_weekly_like"],
                "n_monthly_like": st["n_monthly_like"],
                "date_mismatch": st["date_mismatch"],
                "dup_contractIDs": st["dup_contractIDs"],
                "sha256": st["sha256"],
                "sha_match": sha_match,
            }
            all_rows_out.append(row)
            verify_rows.append(
                {
                    "symbol": sym,
                    "date": d,
                    "partition": "DEV",
                    "path": str(path),
                    "file_exists": int(path.exists()),
                    "manifest_status": (mrow or {}).get("status", ""),
                    "manifest_rows": (mrow or {}).get("rows", ""),
                    "manifest_sha256": (mrow or {}).get("sha256", ""),
                    "recomputed_sha256": st["sha256"],
                    "sha_match": sha_match,
                    "status": st["status"],
                }
            )
            status = st["status"]
            if status == "OK":
                present += 1
                n_ok += 1
                first_ok = first_ok or d
                last_ok = d
                year_rows[d[:4]].append(st["rows"])
                for k in (
                    "rows",
                    "zero_bid",
                    "zero_ask",
                    "crossed",
                    "locked",
                    "iv_le0",
                    "iv_gt3",
                    "iv_nan",
                    "greeks_missing",
                    "date_mismatch",
                    "dup_contractIDs",
                    "mark_mid_gt_0_01",
                ):
                    agg[k] += st[k]
                agg["mark_mid_abs_sum"] += st["mark_mid_abs_sum"]
                agg["mark_mid_n"] += st["mark_mid_n"]
                if st["has_30_45_dte"]:
                    dte30_days += 1
                agg["n_expiries_sum"] += st["n_expiries"]
                y = d[:4]
                weekly_by_year[y]["ok"] += 1
                if st["n_weekly_like"] > 0:
                    weekly_by_year[y]["days_with_weekly"] += 1
            elif status == "EMPTY":
                empty += 1
                empty_dates.append(d)
            elif status == "CORRUPT":
                corrupt += 1
                missing_dates.append(d)
            else:
                missing += 1
                missing_dates.append(d)

        lines.append("### DEV (`< 2016-06-01`) — full content DQ")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Expected | {len(expected_dev)} |")
        lines.append(f"| Present OK | {present} |")
        lines.append(f"| EMPTY | {empty} |")
        lines.append(f"| Missing/corrupt | {missing + corrupt} |")
        lines.append(f"| First OK | {first_ok} |")
        lines.append(f"| Last OK | {last_ok} |")
        lines.append(f"| Days with 30–45 DTE | {dte30_days}/{present} |")
        lines.append("")
        er = gap_ranges(empty_dates, expected_dev)
        mr = gap_ranges(missing_dates, expected_dev)
        if er:
            lines.append("EMPTY ranges:")
            for a, b, n in er[:40]:
                lines.append(f"- {a} → {b} ({n})")
            if len(er) > 40:
                lines.append(f"- … +{len(er) - 40} more ranges")
            lines.append("")
        if mr:
            lines.append("Missing ranges:")
            for a, b, n in mr[:40]:
                lines.append(f"- {a} → {b} ({n})")
            lines.append("")
        lines.append("| Year | OK days | Mean rows | Min | Max | Days w/ weekly-like |")
        lines.append("|---|---|---|---|---|---|")
        for y, v in sorted(year_rows.items()):
            w = weekly_by_year[y]
            lines.append(
                f"| {y} | {len(v)} | {int(statistics.mean(v))} | {min(v)} | {max(v)} | "
                f"{w['days_with_weekly']}/{w['ok']} |"
            )
        lines.append("")
        if present:
            tot = agg["rows"] or 1
            lines.append("| Check | Count | Share of contracts |")
            lines.append("|---|---|---|")
            for label, key in [
                ("Zero bid", "zero_bid"),
                ("Zero ask", "zero_ask"),
                ("Crossed (bid>ask, ask>0)", "crossed"),
                ("Locked (bid=ask>0)", "locked"),
                ("|mark−mid| > 0.01", "mark_mid_gt_0_01"),
                ("IV≤0", "iv_le0"),
                ("IV>3", "iv_gt3"),
                ("IV NaN", "iv_nan"),
                ("Greeks missing", "greeks_missing"),
                ("date≠requested", "date_mismatch"),
                ("Days with duplicate contractIDs", "dup_contractIDs"),
            ]:
                c = agg[key]
                if key == "dup_contractIDs":
                    lines.append(f"| {label} | {c} | (day-level count) |")
                else:
                    lines.append(f"| {label} | {c} | {100 * c / tot:.2f}% |")
            if agg["mark_mid_n"]:
                lines.append(f"| Mean |mark−mid| | {agg['mark_mid_abs_sum'] / agg['mark_mid_n']:.6f} | — |")
            lines.append("")
            lines.append(f"Mean expiries/day: {agg['n_expiries_sum'] / present:.1f}")
            lines.append("")

        # QQQ rename flag
        if sym == "QQQ":
            lines.append("### QQQ rename / 2011-03-23 flag")
            lines.append("")
            lines.append(f"Source mapping: `QQQQ` for dates `< {QQQ_RENAME}`; `QQQ` from `{QQQ_RENAME}`.")
            # Find rows around rename in DEV csv buffer
            around = [r for r in all_rows_out if r["symbol"] == "QQQ" and "2011-03-1" <= r["date"] <= "2011-03-3"]
            # broader window
            around = [r for r in all_rows_out if r["symbol"] == "QQQ" and "2011-03-18" <= r["date"] <= "2011-03-28"]
            lines.append("")
            lines.append("| Date | src expect | status | rows | note |")
            lines.append("|---|---|---|---|---|")
            for r in around:
                note = ""
                if r["date"] == QQQ_FLAG_DATE:
                    note = "FLAG: probe showed elevated rows vs next day (possible QQQQ/QQQ overlap)"
                src = "QQQQ" if r["date"] < QQQ_RENAME else "QQQ"
                lines.append(f"| {r['date']} | {src} | {r['status']} | {r['rows']} | {note} |")
            lines.append("")

        # ---- OOS ----
        oos_ok = oos_empty = oos_miss = oos_bad = 0
        oos_rows_sum = 0
        oos_missing = []
        oos_sha_bad = 0
        for d in expected_oos:
            path = path_for(sym, d)
            mrow = manifest.get((sym, d))
            st = verify_oos_integrity(path, mrow)
            if st.get("sha_match") == "0":
                sha_mismatch_total += 1
                oos_sha_bad += 1
            # DEV-style content fields left blank for OOS in the DEV csv
            # (we still record OOS in verify csv only; DEV per-day csv = DEV only)
            verify_rows.append(
                {
                    "symbol": sym,
                    "date": d,
                    "partition": "OOS",
                    "path": str(path),
                    "file_exists": st["file_exists"],
                    "manifest_status": st["manifest_status"],
                    "manifest_rows": (mrow or {}).get("rows", ""),
                    "manifest_sha256": (mrow or {}).get("sha256", ""),
                    "recomputed_sha256": st["sha256"],
                    "sha_match": st.get("sha_match", ""),
                    "status": st["status"],
                }
            )
            if st["status"] == "OK":
                oos_ok += 1
                with contextlib.suppress(Exception):
                    oos_rows_sum += int(st["rows"] or 0)
            elif st["status"] == "EMPTY":
                oos_empty += 1
            elif st["status"] in ("BAD_PAYLOAD", "CORRUPT", "ROW_MISMATCH"):
                oos_bad += 1
                oos_missing.append(d)
            else:
                oos_miss += 1
                oos_missing.append(d)

        lines.append("### OOS holdout (`>= 2016-06-01`) — existence / rows / sha256 ONLY")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| Expected | {len(expected_oos)} |")
        lines.append(f"| Present OK | {oos_ok} |")
        lines.append(f"| EMPTY | {oos_empty} |")
        lines.append(f"| Missing/bad | {oos_miss + oos_bad} |")
        lines.append(f"| Sha mismatches vs manifest | {oos_sha_bad} |")
        lines.append(f"| Total contract-rows (sum from manifest/len, no content stats) | {oos_rows_sum} |")
        lines.append("")
        if oos_missing:
            lines.append(f"Missing/bad count: {len(oos_missing)}; first={oos_missing[0]} last={oos_missing[-1]}")
            omr = gap_ranges(oos_missing, expected_oos)
            for a, b, n in omr[:20]:
                lines.append(f"- {a} → {b} ({n})")
            lines.append("")

        summary_json[sym] = {
            "dev": {
                "expected": len(expected_dev),
                "ok": present,
                "empty": empty,
                "missing": missing + corrupt,
                "first_ok": first_ok,
                "last_ok": last_ok,
                "total_contracts": agg.get("rows", 0),
                "zero_bid_pct": round(100 * agg.get("zero_bid", 0) / max(agg.get("rows", 1), 1), 2),
                "zero_ask_pct": round(100 * agg.get("zero_ask", 0) / max(agg.get("rows", 1), 1), 2),
                "crossed_pct": round(100 * agg.get("crossed", 0) / max(agg.get("rows", 1), 1), 2),
                "iv_le0_pct": round(100 * agg.get("iv_le0", 0) / max(agg.get("rows", 1), 1), 2),
                "iv_gt3_pct": round(100 * agg.get("iv_gt3", 0) / max(agg.get("rows", 1), 1), 2),
                "dte30_days": dte30_days,
                "dup_contractID_days": agg.get("dup_contractIDs", 0),
            },
            "oos": {
                "expected": len(expected_oos),
                "ok": oos_ok,
                "empty": oos_empty,
                "missing": oos_miss + oos_bad,
                "rows_sum": oos_rows_sum,
                "sha_mismatches": oos_sha_bad,
            },
        }

    # Write DEV-only per-day CSV
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=per_day_fields)
        writer.writeheader()
        for row in all_rows_out:
            writer.writerow(row)

    with open(OUT_VERIFY, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=verify_fields)
        writer.writeheader()
        for row in verify_rows:
            writer.writerow(row)

    man_sha = sha256_file_bytes(MANIFEST) if MANIFEST.exists() else "N/A"
    lines.append("## Integrity / process notes")
    lines.append("")
    lines.append(f"- Sha mismatches (DEV+OOS vs MANIFEST payload sha): **{sha_mismatch_total}**")
    lines.append(
        f"- API key plaintext hits in scanned .md/.csv/.json/.log/.py/.txt/.out under options/logs/scripts: **{key_leak_hits}** (count only)"
    )
    lines.append("- OOS content fields were not used for spreads/IV/greeks/expiry statistics.")
    lines.append("- No backtests, signals, returns, P&L, or realised vol computed.")
    lines.append("")
    lines.append("## File hashes")
    lines.append("")
    lines.append(f"- MANIFEST.csv sha256: `{man_sha}`")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    md_sha = sha256_file_bytes(OUT_MD)
    csv_sha = sha256_file_bytes(OUT_CSV)
    ver_sha = sha256_file_bytes(OUT_VERIFY)
    with open(OUT_MD, "a", encoding="utf-8") as f:
        f.write(f"- DQ_REPORT.md sha256 (pre-append of self-hash; see console JSON for final): `{md_sha}`\n")
        f.write(f"- DQ_DEV_per_day.csv sha256: `{csv_sha}`\n")
        f.write(f"- SHA_VERIFY.csv sha256: `{ver_sha}`\n")
    # Recompute md sha after append
    md_sha_final = sha256_file_bytes(OUT_MD)

    print(
        json.dumps(
            {
                "manifest_sha": man_sha,
                "dq_report_sha": md_sha_final,
                "dq_dev_csv_sha": csv_sha,
                "sha_verify_csv_sha": ver_sha,
                "sha_mismatches": sha_mismatch_total,
                "key_leak_hits": key_leak_hits,
                "summaries": summary_json,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
