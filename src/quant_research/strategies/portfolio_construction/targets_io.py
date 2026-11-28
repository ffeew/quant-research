"""
Append-only, never-overwrite output layer for construct.py (portfolio-owned). Places no orders.

Layout (under --outdir, default $QR_DESK_DIR/portfolio):
  targets/targets_<YYYYMMDD>T<HHMMSS>SGT[_gp].json   tradable book, one file per run, NEVER overwritten
  shadow/targets_<YYYYMMDD>T<HHMMSS>SGT[_gp].json    shadow book,   one file per run, NEVER overwritten
  targets_log.jsonl                                  append-only run log, one JSON line per book per run, plus
                                                     correction records (type "correction"); earlier lines are NEVER edited
  targets/latest.json, shadow/latest.json            convenience symlinks to the newest file (NON-AUTHORITATIVE)
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from typing import Any

from quant_research.strategies.portfolio_construction import fail_closed as fc

SGT = dt.timezone(dt.timedelta(hours=8))
LOG_SCHEMA_VERSION = 3  # v3 (2026-10-30 ~02:20, FRAMEWORK v0.7): + type ("run"|"correction"), method_version, limits_version, data_source
# v2 (02:08, v0.6): + panic_provisional/panic_applied, backstop_equity, halt_armed, earnings, data_defects


def run_stamp(now: dt.datetime | None = None) -> tuple[dt.datetime, str]:
    now = (now or dt.datetime.now(SGT)).astimezone(SGT)
    return now, now.strftime("%Y%m%dT%H%M%S") + "SGT"


def write_exclusive(path: str, doc: dict[str, Any]) -> str:
    """Atomically create `path` with JSON `doc`; raise FileExistsError if it already exists (never overwrite).
    Write to a temp file in the same dir, fsync, then hard-link into place (link() fails if the target exists)."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    if os.path.lexists(path):
        raise FileExistsError(f"refusing to overwrite existing targets file: {path}")
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=d)
    try:
        os.fchmod(fd, 0o644)  # readable by the desk (mkstemp defaults to 0600)
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=1, default=float)
            f.flush()
            os.fsync(f.fileno())
        os.link(tmp, path)  # atomic, fails with FileExistsError if path exists (race-safe)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    return sha256(path)


def write_checked(docs: Sequence[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any], str]]:
    """Fail-closed publish: every doc's compliance must pass BEFORE any file is created.

    If any check of any doc is not PASS/INFO (including a FAIL in a shadow book), nothing is
    written for any doc (no file, no temp file, no directory) and a coded stop (non-zero exit)
    lists every failed check: a shadow-book FAIL also blocks the tradable file. Every path is
    checked with ``os.path.lexists`` before the first write, so a clash on a later doc means
    nothing is written for an earlier one either. Otherwise each doc is written with
    :func:`write_exclusive`. Returns ``[(path, doc, sha256), ...]``.
    """
    fc.require_compliance_pass(docs)
    taken = [p for p, _ in docs if os.path.lexists(p)]
    if taken:
        raise FileExistsError("refusing to overwrite existing targets file: " + ", ".join(taken))
    return [(p, doc, write_exclusive(p, doc)) for p, doc in docs]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def append_log(log_path: str, record: dict[str, Any]) -> None:
    """Append one JSON line under an exclusive flock with O_APPEND, then fsync. Never rewrites earlier lines."""
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    line = json.dumps(record, default=float, separators=(",", ":"), ensure_ascii=False)
    if "\n" in line:
        raise ValueError("log record must serialise to a single line")
    fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, (line + "\n").encode())
        os.fsync(fd)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def update_latest(path: str) -> str:
    """Point <dir>/latest.json at `path` (relative symlink, swapped atomically). Convenience only, NOT authoritative."""
    d = os.path.dirname(path)
    link = os.path.join(d, "latest.json")
    tmp = os.path.join(d, ".latest.tmp")
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(os.path.basename(path), tmp)
    os.replace(tmp, link)
    return link


def mtime_sgt(path: str) -> str | None:
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path), SGT).isoformat(timespec="seconds")
    except OSError:
        return None


def log_record(
    doc: dict[str, Any],
    path: str,
    digest: str,
    run_id: str,
    generated: str,
    positions_path: str | None,
    backfill_note: str | None = None,
) -> dict[str, Any]:
    ro = doc.get("risk_overlays", {})
    pan = ro.get("panic", {})
    brk = ro.get("breaker", {})
    comp = doc.get("compliance", [])
    hard_fail = [c["limit"] for c in comp if c["status"] == "FAIL"]
    prov = doc.get("data_provenance") or {}
    rec = dict(
        schema_version=LOG_SCHEMA_VERSION,
        type="run",
        method_version=doc.get("method_version"),
        limits_version=doc.get("limits_version"),
        earnings_gate=doc.get("earnings_gate"),
        t8_status=doc.get("t8_status"),
        run_id=run_id,
        generated_sgt=generated,
        book=doc.get("book_type"),
        sleeve_id=doc.get("sleeve_id"),
        book_name=doc.get("book_name"),
        tradable=doc.get("tradable"),
        target_date=doc.get("asof"),
        file=path,
        file_sha256=digest,
        equity=doc.get("equity"),
        equity_source=doc.get("equity_source"),
        positions_source=positions_path,
        positions_mtime_sgt=mtime_sgt(positions_path) if positions_path else None,
        state=dict(
            panic=pan.get("panic"),
            panic_multiplier=pan.get("multiplier_momentum_trend"),
            panic_fail_safe=pan.get("fail_safe"),
            panic_as_of_sgt=pan.get("as_of_sgt"),
            breaker_state=brk.get("state"),
            gross_cap_pct=brk.get("gross_cap_pct"),
            new_trades_allowed=brk.get("new_trades_allowed"),
            breaker_fail_safe=brk.get("fail_safe"),
            breaker_as_of_sgt=brk.get("as_of_sgt"),
            halted_derisk_only=ro.get("halted_derisk_only"),
            sleeve_m={k: v.get("m") for k, v in (ro.get("sleeve_multipliers") or {}).items()},
            panic_factor={k: v.get("panic_factor") for k, v in (ro.get("sleeve_multipliers") or {}).items()},
            risk_inflation=ro.get("risk_inflation"),
            shrinkage_delta=ro.get("shrinkage_delta"),
            panic_provisional=ro.get("panic_provisional", pan.get("panic_provisional")),
            panic_applied=ro.get("panic_applied", pan.get("applied")),
            panic_final=pan.get("final"),
            t8_status=pan.get("t8_status"),
            panic_responses={
                k: pan.get(k)
                for k in (
                    "multiplier_momentum_trend",
                    "momentum_short_notional_multiplier",
                    "new_loser_shorts_allowed",
                    "net_beta_floor",
                )
            },
            panic_response_source=pan.get("response_source"),
            breaker_state_in_file=brk.get("state_in_file"),
            backstop_equity=brk.get("backstop_equity"),
            halt_armed=brk.get("halt_armed"),
            sigma_target={k: v.get("sigma_target") for k, v in (ro.get("vol_scaling") or {}).items()} or None,
        ),
        earnings=(
            dict(
                policy=ro["earnings"].get("policy"),
                next_earnings_file=((ro["earnings"]["calendar"] or {}).get("next_earnings") or {}).get("path"),
                next_earnings_sha256=((ro["earnings"]["calendar"] or {}).get("next_earnings") or {}).get("sha256"),
                next_earnings_reason=((ro["earnings"]["calendar"] or {}).get("next_earnings") or {}).get("reason"),
                n_by_kind={k: len(v) for k, v in (ro["earnings"].get("by_kind") or {}).items()},
                calendar_fresh=(ro["earnings"]["calendar"] or {}).get("fresh"),
                calendar_fetched_at_utc=(ro["earnings"]["calendar"] or {}).get("fetched_at_utc"),
                horizon_end_session=(ro["earnings"]["calendar"] or {}).get("horizon_end_session"),
                n_in_window=ro["earnings"].get("n_in_window"),
                n_unknown_next_date=len(ro["earnings"].get("unknown_next_date") or []),
                unknown_date_shorts_flagged=[
                    r["symbol"]
                    for r in doc.get("targets", [])
                    if r.get("earnings_status", "").startswith("unknown") and (r.get("target_shares") or 0) < 0
                ],
            )
            if ro.get("earnings")
            else None
        ),
        data_source=(
            dict(
                book_history=(prov.get("book_history") or {}).get("source"),
                live_row=(prov.get("live_row") or {}).get("source"),
                sleeve_proxy=(prov.get("sleeve_proxy") or {}).get("proxy_src"),
                sleeve_proxy_status=(prov.get("sleeve_proxy") or {}).get("status"),
            )
            if prov.get("book_history")
            else None
        ),
        data_defects=(
            dict(
                book_affected=(doc.get("data_provenance") or {}).get("book_affected_by_data_defects"),
                provisional_results_referenced=list(
                    ((doc.get("data_provenance") or {}).get("provisional_results_referenced") or {}).keys()
                ),
                label=next(
                    iter(((doc.get("data_provenance") or {}).get("provisional_results_referenced") or {}).values()),
                    None,
                ),
            )
            if doc.get("data_provenance")
            else None
        ),
        portfolio=(doc.get("portfolio") or {}).get("target"),
        compliance=dict(
            n_pass=sum(c["status"] == "PASS" for c in comp),
            n_info=sum(c["status"] == "INFO" for c in comp),
            n_fail=len(hard_fail),
            failed=hard_fail,
        ),
        targets=[
            dict(
                symbol=r["symbol"],
                side=r.get("side"),
                target_shares=r.get("target_shares"),
                target_weight=r.get("target_weight"),
                stop=r.get("stop_price"),
            )
            for r in doc.get("targets", [])
        ],
    )
    if backfill_note:
        rec["backfill"] = True
        rec["note"] = backfill_note
    return rec


# ---------------------------------------------------------------------------------------------------------------
# Correction records (append-only). A correction never edits an earlier line; it names the lines it corrects
# (line number + run_id + book + generated_sgt, all must match) and the corrected / annotated fields.
# ---------------------------------------------------------------------------------------------------------------
def correction_record(
    corrects: list[dict[str, Any]],
    fields: dict[str, Any],
    note: str,
    author: str = "the portfolio-construction lead (Portfolio Construction)",
    requested_by: str | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = (now or dt.datetime.now(SGT)).astimezone(SGT)
    return dict(
        schema_version=LOG_SCHEMA_VERSION,
        type="correction",
        generated_sgt=now.isoformat(timespec="seconds"),
        correction_id="corr_" + now.strftime("%Y%m%dT%H%M%S") + "SGT",
        corrects=corrects,
        fields=fields,
        note=note,
        author=author,
        requested_by=requested_by,
    )


def read_log(log_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Reader for targets_log.jsonl. Returns (runs, corrections, issues).
    runs: book/run records only (type 'run' or no type), each a dict with '_line' and an '_effective' view:
          the record's own fields, overlaid with the fields of every correction that targets it (in log order),
          and method_version filled in: the record's own value; else the correction's; else inferred
          ('v1' for schema 1-2 non-backfill lines; None for backfills without a correction), with
          '_effective.method_version_source' = 'record' | 'correction' | 'inferred'.
    corrections: type 'correction' records (never treated as books).
    issues: correction targets that do not match any line exactly (ignored, reported)."""
    runs: list[dict[str, Any]] = []
    corr: list[dict[str, Any]] = []
    issues: list[str] = []
    with open(log_path) as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            d = json.loads(line)
            d["_line"] = n
            (corr if d.get("type") == "correction" else runs).append(d)
    by_line = {d["_line"]: d for d in runs}
    applied: dict[int, list[dict[str, Any]]] = {}
    for c in corr:
        for t in c.get("corrects") or []:
            d = by_line.get(t.get("line"))
            if d is None or any(
                t.get(k) is not None and d.get(k) != t.get(k) for k in ("run_id", "book", "generated_sgt")
            ):
                issues.append(f"{c.get('correction_id')}: target {t} does not match any log line; ignored")
                continue
            applied.setdefault(d["_line"], []).append(c)
    for d in runs:
        eff = {k: v for k, v in d.items() if not k.startswith("_")}
        src = "record" if d.get("method_version") else None
        for c in applied.get(d["_line"], []):
            eff.update(c.get("fields") or {})
            if (c.get("fields") or {}).get("method_version") and not src:
                src = "correction"
        if not eff.get("method_version") and not d.get("backfill") and (d.get("schema_version") or 0) <= 2:
            eff["method_version"] = "v1"
            src = "inferred"
        eff["method_version_source"] = src
        eff["corrections"] = [c.get("correction_id") for c in applied.get(d["_line"], [])]
        d["_effective"] = eff
    return runs, corr, issues
