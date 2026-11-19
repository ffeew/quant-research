"""PREREG-v3 data layer.

Two loaders:
  * build_desk_panel(): the EXISTING 2016+ desk store (TR index + Alpaca raw OHLCV). Used ONLY for unit /
    mechanics checks (no performance is printed by the tests).
  * load_pinned_build(): the signed-off 2005+ backfill. Refuses to read anything unless the sha256 of the build
    equals the hash pinned in PREREG-v3.md §2 (Amendment A4). Nothing in this module opens bars/daily/extended/
    except load_pinned_build(), which is only called by `run_v3.py run`.

Hash convention (same as outputs_v2): a FILE hashes as sha256(file bytes); a DIRECTORY hashes as
sha256 of its manifest = lines "<sha256>  <relative path>\n" for every file, paths sorted (C locale).
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = f"{_QR.DATA_DIR}"
BARS = f"{ROOT}/bars/daily"
RF_PATH = f"{ROOT}/factors/ken_french/ff3_daily.parquet"
PREREG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PREREG-v3.md")
PLACEHOLDER = "<PLACEHOLDER: sha256 of data-owner-signed-off 2005+ v2 build (built under the substitution rule below)>"
DIFF_PLACEHOLDER = "<PLACEHOLDER: sha256 of the data owner's published v2 substitution diff>"
SRC_PLACEHOLDER = "<TBD-2: sha256 of the data owner's per-ticker reference-source table>"
CA_PLACEHOLDER = "<PLACEHOLDER: sha256 of data-owner-signed-off corporate-action table>"
FIELDS = ["tr", "open", "high", "low", "close", "volume"]


def sha_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def dir_manifest(d: str) -> str:
    rows = []
    for base, _, files in os.walk(d):
        for fn in files:
            fp = os.path.join(base, fn)
            rows.append((os.path.relpath(fp, d), sha_file(fp)))
    rows.sort(key=lambda r: r[0].encode())
    return "".join(f"{h}  {rel}\n" for rel, h in rows)


def sha_path(p: str) -> str:
    return sha_file(p) if os.path.isfile(p) else hashlib.sha256(dir_manifest(p).encode()).hexdigest()


def _pinned_row(prefix: str, placeholder: str) -> str | None:
    txt = open(PREREG, encoding="utf-8").read()
    line = next((l for l in txt.splitlines() if l.startswith(prefix)), None)
    if line is None:
        raise RuntimeError(f"PREREG-v3 §2 row '{prefix}' not found")
    if placeholder in line:
        return None
    m = re.search(r"\b([0-9a-f]{64})\b", line)
    return m.group(1) if m else None


def pinned_ca_hash() -> str | None:
    """Corporate-action table hash pinned in PREREG-v3 §2 (None while the placeholder is present). Decision 9B-7 / run gate."""
    return _pinned_row("| **Corporate-action table**", CA_PLACEHOLDER)


def pinned_diff_hash() -> str | None:
    """v2 substitution-diff hash pinned in PREREG-v3 §2 (option (b), rule S6). None while the placeholder is present."""
    return _pinned_row("| **Substitution diff (v2)**", DIFF_PLACEHOLDER)


def pinned_src_hash() -> str | None:
    """Per-ticker reference-source table hash (rule S2, TBD-2). Must be pinned BEFORE the v2 build. None while TBD."""
    return _pinned_row("| **Reference-source table**", SRC_PLACEHOLDER)


def load_corporate_actions(ca: dict[str, Any], expected_sha: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """the data owner's corporate-action table -> DataFrame(symbol, date, price_factor). Hash verified FIRST.
    ca = {"path":..., "symbol":..., "date":..., "ratio":..., "ratio_convention": "price_factor"|"new_per_old"|"old_per_new",
          "type_column": optional, "split_types": optional list of values in type_column that are splits}"""
    got = sha_file(ca["path"])
    if got != expected_sha:
        raise RuntimeError(
            f"corporate-action table hash mismatch: {ca['path']} sha256 {got} != pinned {expected_sha}. Refusing to run."
        )
    t = pd.read_parquet(ca["path"]) if ca["path"].endswith(".parquet") else pd.read_csv(ca["path"])
    if ca.get("type_column"):
        t = t[t[ca["type_column"]].isin(ca["split_types"])]
    r = t[ca["ratio"]].astype(float)
    conv = ca["ratio_convention"]
    f = {"price_factor": r, "new_per_old": 1.0 / r, "old_per_new": r}[conv]
    out = pd.DataFrame(
        {
            "symbol": t[ca["symbol"]].astype(str).values,
            "date": pd.to_datetime(t[ca["date"]]).values,
            "price_factor": f.values,
        }
    )
    return out, {"path": ca["path"], "sha256": got, "n_rows_splits": int(len(out)), "ratio_convention": conv}


def pre2016_split_table() -> pd.DataFrame:
    """Frozen Yahoo split events before the corporate-action table starts (PREREG-v3 §2, amended C7)."""
    from quant_research.strategies.trend_tsmom.tsmom import v3spec as S

    return pd.DataFrame(
        [
            {"symbol": s, "date": pd.Timestamp(d), "price_factor": 1.0 / r, "source": "yahoo_pre2016"}
            for s, d, r in S.PRE2016_SPLITS
        ]
    )


def merge_split_sources(ca: pd.DataFrame, pre: pd.DataFrame, start: str) -> pd.DataFrame:
    """Amended C7: the corporate-action table from `start` on, Yahoo split events before it. A CA row before `start` or a
    Yahoo row on/after it means the sources overlap: abort."""
    st = pd.Timestamp(start)
    ca = ca.copy()
    ca["date"] = pd.to_datetime(ca["date"])
    pre = pre.copy()
    pre["date"] = pd.to_datetime(pre["date"])
    if (ca["date"] < st).any():
        raise RuntimeError(f"corporate-action table has split rows before {start}; split sources overlap (C7). Abort.")
    if (pre["date"] >= st).any():
        raise RuntimeError(f"pre-2016 Yahoo split list has rows on/after {start} (C7). Abort.")
    ca["source"] = "corporate_action_table"
    return (
        pd.concat([pre, ca], ignore_index=True)[["symbol", "date", "price_factor", "source"]]
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )


OHLC = ["open", "high", "low", "close"]


def check_substitution_diff(diff: pd.DataFrame, alpaca_start: str) -> dict[str, Any]:
    """§2 S4/S5 audit of the data owner's published v2 diff (columns symbol, date, old_<f>, new_<f> for f in OHLC).
    Aborts (RuntimeError) if any substituted row lacks a positive new value for any of the four fields, breaks
    low <= min(open, close) and max(open, close) <= high, or is dated before the Alpaca start (S3: pre-2016 rows never trigger)."""
    need = ["symbol", "date"] + [f"{p}_{f}" for p in ("old", "new") for f in OHLC]
    miss = [c for c in need if c not in diff.columns]
    if miss:
        raise RuntimeError(f"substitution diff lacks columns {miss} (S6)")
    d = diff.copy()
    d["date"] = pd.to_datetime(d["date"])
    new = d[[f"new_{f}" for f in OHLC]].astype(float)
    bad_ref = ~(new > 0).all(axis=1)
    if bad_ref.any():
        raise RuntimeError(
            f"S5: {int(bad_ref.sum())} substituted rows lack a reference value for some OHLC field. Abort."
        )
    o, h, l, c = (new[f"new_{f}"] for f in OHLC)
    bad = ~((l <= np.minimum(o, c)) & (np.maximum(o, c) <= h))
    if bad.any():
        raise RuntimeError(
            f"S5: {int(bad.sum())} substituted rows are OHLC-inconsistent after substitution (no repair). Abort."
        )
    pre = d["date"] < pd.Timestamp(alpaca_start)
    if pre.any():
        raise RuntimeError(
            f"S3: {int(pre.sum())} substituted rows before {alpaca_start}; pre-2016 Yahoo rows cannot trigger. Abort."
        )
    if d.duplicated(["symbol", "date"]).any():
        raise RuntimeError("substitution diff has duplicate (symbol, date) rows")
    return {"rows": int(len(d)), "by_symbol": {k: int(v) for k, v in d.symbol.value_counts().sort_index().items()}}


def nasdaq_yahoo_xcheck(
    x: pd.DataFrame, diff: pd.DataFrame, agree_bp: float = 1.0, list_sub_bp: float = 10.0, list_all_bp: float = 25.0
) -> dict[str, Any]:
    """§2 X1-X3 report-only cross-check (no substitution effect). x: symbol, date, nasdaq_close_raw, yahoo_close_raw.
    Returns per-ticker share of days within `agree_bp`, all rows > list_all_bp, substituted rows > list_sub_bp.
    Every listed substituted row must be in the diff (abort otherwise)."""
    x = x.copy()
    x["date"] = pd.to_datetime(x["date"])
    x = x.dropna(subset=["nasdaq_close_raw", "yahoo_close_raw"])
    x["dev_bp"] = (x.nasdaq_close_raw / x.yahoo_close_raw - 1) * 1e4
    share = (
        x.assign(ok=x.dev_bp.abs() <= agree_bp).groupby("symbol").agg(days=("ok", "size"), share_within=("ok", "mean"))
    )
    keys = set(zip(diff["symbol"], pd.to_datetime(diff["date"])))
    x["substituted"] = [(s, d) in keys for s, d in zip(x.symbol, x.date)]
    all_rows = x[x.dev_bp.abs() > list_all_bp][
        ["symbol", "date", "nasdaq_close_raw", "yahoo_close_raw", "dev_bp", "substituted"]
    ]
    sub_rows = x[x.substituted & (x.dev_bp.abs() > list_sub_bp)][
        ["symbol", "date", "nasdaq_close_raw", "yahoo_close_raw", "dev_bp"]
    ]
    if not all((s, d) in keys for s, d in zip(sub_rows.symbol, sub_rows.date)):
        raise RuntimeError("X2: a listed substituted row is missing from the data owner's diff")
    return {
        "agreement": share.reset_index(),
        "rows_gt_all": all_rows.reset_index(drop=True),
        "substituted_gt": sub_rows.reset_index(drop=True),
    }


def pinned_hash() -> str | None:
    """Data-build hash pinned in PREREG-v3 §2 (None while the placeholder is present)."""
    txt = open(PREREG, encoding="utf-8").read()
    line = next((l for l in txt.splitlines() if l.startswith("| **Data build (backfill)**")), None)
    if line is None:
        raise RuntimeError("PREREG-v3 §2 data-build row not found")
    if PLACEHOLDER in line:
        return None
    m = re.search(r"\b([0-9a-f]{64})\b", line)
    return m.group(1) if m else None


def load_rf(index: pd.DatetimeIndex) -> tuple[pd.Series, str]:
    d = pd.read_parquet(RF_PATH)
    if not isinstance(d.index, pd.DatetimeIndex):
        dc = [c for c in d.columns if "date" in c.lower()]
        d = d.set_index(pd.to_datetime(d[dc[0]]))
    rf = d["RF"].astype(float)
    if rf.abs().max() > 0.01:
        rf = rf / 100.0
    rf = rf.sort_index()
    return rf.reindex(index).ffill(), str(rf.index.max().date())


def _wide(frames: dict[str, pd.Series], idx: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(frames).reindex(idx)


def build_desk_panel(symbols: list[str]) -> dict[str, Any]:
    """2016+ desk store only (unit checks)."""
    tr = pd.read_parquet(
        f"{BARS}/total_return/daily_total_return.parquet", columns=["symbol", "session_date", "tr_index_best"]
    )
    tr["session_date"] = pd.to_datetime(tr["session_date"])
    out: dict[str, dict[str, pd.Series]] = {f: {} for f in FIELDS}
    for s in symbols:
        raw = pd.read_parquet(
            f"{BARS}/raw/{s}.parquet", columns=["session_date", "open", "high", "low", "close", "volume"]
        )
        raw["session_date"] = pd.to_datetime(raw["session_date"])
        raw = raw.set_index("session_date").sort_index()
        t = tr[tr.symbol == s].set_index("session_date")["tr_index_best"].sort_index()
        out["tr"][s] = t
        for f in ["open", "high", "low", "close", "volume"]:
            out[f][s] = raw[f]
    idx = pd.DatetimeIndex(sorted(set().union(*[v.index for v in out["tr"].values()])))
    panel: dict[str, Any] = {f: _wide(out[f], idx) for f in FIELDS}
    panel["rf"], panel["rf_last"] = load_rf(idx)
    panel["source"] = "desk 2016+ (TR tr_index_best + Alpaca raw OHLCV)"
    return panel


def load_pinned_build(
    spec: dict[str, Any], symbols: list[str], expected_sha: str, expected_ca_sha: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the signed-off backfill described by `spec` (data_spec_v3.json). Verifies the hash FIRST.

    spec = {"path": <file or directory>, "layout": "long" | "per_symbol",
            "pattern": "{symbol}.parquet" (per_symbol only),
            "columns": {"symbol": ..., "date": ..., "tr": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...},
            "vix": optional {"path":..., "date":..., "value":...}}
    """
    path = spec["path"]
    got = sha_path(path)
    if got != expected_sha:
        raise RuntimeError(f"data hash mismatch: {path} sha256 {got} != pinned {expected_sha}. Refusing to run (A4).")
    if not expected_ca_sha or not spec.get("corporate_actions", {}).get("path"):
        raise RuntimeError("corporate-action table not pinned / not in the data spec (run gate)")
    ca_splits, ca_info = load_corporate_actions(spec["corporate_actions"], expected_ca_sha)
    from quant_research.strategies.trend_tsmom.tsmom import v3spec as S

    splits = merge_split_sources(ca_splits, pre2016_split_table(), S.CA_TABLE_START)
    ca_info["pre2016_yahoo_splits"] = [f"{s} {d} {r:g}:1" for s, d, r in S.PRE2016_SPLITS]
    cols = spec["columns"]
    need = ["date", "tr", "close"]
    for k in need:
        if not cols.get(k):
            raise RuntimeError(f"data spec missing required column mapping '{k}'")
    frames: dict[str, dict[str, pd.Series]] = {f: {} for f in FIELDS}
    if spec["layout"] == "long":
        files = (
            [path]
            if os.path.isfile(path)
            else sorted(os.path.join(b, f) for b, _, fs in os.walk(path) for f in fs if f.endswith(".parquet"))
        )
        d = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        d[cols["date"]] = pd.to_datetime(d[cols["date"]])
        for s in symbols:
            x = d[d[cols["symbol"]] == s].set_index(cols["date"]).sort_index()
            if x.index.duplicated().any():
                raise RuntimeError(f"duplicate sessions for {s} in build")
            for f in FIELDS:
                frames[f][s] = (
                    x[cols[f]].astype(float) if cols.get(f) and cols[f] in x else pd.Series(np.nan, index=x.index)
                )
    elif spec["layout"] == "per_symbol":
        for s in symbols:
            fp = os.path.join(path, spec["pattern"].format(symbol=s))
            x = pd.read_parquet(fp)
            x[cols["date"]] = pd.to_datetime(x[cols["date"]])
            x = x.set_index(cols["date"]).sort_index()
            for f in FIELDS:
                frames[f][s] = (
                    x[cols[f]].astype(float) if cols.get(f) and cols[f] in x else pd.Series(np.nan, index=x.index)
                )
    else:
        raise RuntimeError(f"unknown layout {spec['layout']}")
    missing = [s for s in symbols if len(frames["tr"].get(s, [])) == 0 or frames["tr"][s].notna().sum() == 0]
    if missing:
        raise RuntimeError(f"pinned universe symbols missing from build: {missing}")
    idx = pd.DatetimeIndex(sorted(set().union(*[v.dropna().index for v in frames["tr"].values()])))
    panel: dict[str, Any] = {f: _wide(frames[f], idx) for f in FIELDS}
    panel["rf"], panel["rf_last"] = load_rf(idx)
    panel["source"] = f"pinned build {path} sha256 {got}"
    info: dict[str, Any] = {
        "path": path,
        "sha256": got,
        "first_date": str(idx.min().date()),
        "last_date": str(idx.max().date()),
        "coverage": {
            s: {
                "first_tr": str(cast(pd.Timestamp, panel["tr"][s].first_valid_index()).date()),
                "hl_fraction": float(panel["high"][s].notna().mean()),
                "open_fraction": float(panel["open"][s].notna().mean()),
            }
            for s in symbols
        },
    }
    vix = None
    if spec.get("vix"):
        v = pd.read_parquet(spec["vix"]["path"])
        v[spec["vix"]["date"]] = pd.to_datetime(v[spec["vix"]["date"]])
        vix = v.set_index(spec["vix"]["date"])[spec["vix"]["value"]].astype(float).reindex(idx)
        info["vix_sha256"] = sha_file(spec["vix"]["path"])
    panel["vix"] = vix
    panel["splits"] = splits
    info["corporate_actions"] = ca_info
    return panel, info
