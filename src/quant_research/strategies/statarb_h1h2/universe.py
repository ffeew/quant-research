"""Point-in-time universe and eligibility (pre-registered rules)."""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from .guards import Blocked
from .splits import ETFS

Interval = tuple[pd.Timestamp, Any]  # end may be NaT (open)


def subtract_intervals(iv: Interval, cuts: list[Interval]) -> list[Interval]:
    """[s, e) minus a list of [cs, ce) intervals (Timestamps; e may be NaT = open)."""
    out = [iv]
    for cs, ce in cuts:
        nxt: list[Interval] = []
        for s, e in out:
            e_ = e if pd.notna(e) else pd.Timestamp.max
            ce_ = ce if pd.notna(ce) else pd.Timestamp.max
            if ce_ <= s or cs >= e_:
                nxt.append((s, e))
                continue
            if cs > s:
                nxt.append((s, cs))
            if ce_ < e_:
                nxt.append((ce, e))
        out = nxt
    return out


def build_membership(pm: pd.DataFrame, listing: pd.DataFrame, reused_tickers: dict, missing_names: dict, *,
                     lineage_excl: Iterable[str] = (), dev_universe: Iterable[str] | None = None,
                     final_list: dict | None = None,
                     listing_overlap_treatment: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """PIT membership clipped to listing windows, minus reused-ticker original-member periods,
    minus missing names, minus ETFs, minus identity exclusions. Returns (mem, receipt).

    pm:      symbol, start_date_filled, end_date (NaT = open; end exclusive) [, after_boundary]
    listing: symbol, ipoDate, delistingDate ('null' / NaN = still listed), listing_source (active|delisted)
    """
    treatment = dict(listing_overlap_treatment or {})
    r18_cuts = {t["ticker"]: [(pd.Timestamp(a), pd.Timestamp(b) if b else pd.NaT)
                              for a, b in t["original_member_periods"]] for t in reused_tickers["tickers"]}
    m14_set = {t["ticker"] for t in missing_names["tickers"]}
    ls = listing.copy()
    lineage = set(lineage_excl)
    both = (set(ls.loc[ls["listing_source"] == "active", "symbol"])
            & set(ls.loc[ls["listing_source"] == "delisted", "symbol"]))
    in_uni = both & set(pm["symbol"]) & (set(dev_universe) if dev_universe is not None else set(pm["symbol"]))
    fl = final_list or {}
    fl_excl: dict[str, str] = dict(fl.get("excluded", {}))
    fl_kept: set[str] = set(fl.get("kept", ()))
    in_uni -= set(r18_cuts) | m14_set | lineage | set(ETFS) | set(fl_excl)
    uncovered = sorted(in_uni - set(treatment) - fl_kept)
    if uncovered:
        raise Blocked(f"REFUSING: {len(uncovered)} in-universe symbols in both listing sources with no "
                      f"treatment: {uncovered}")
    ls["ipo"] = pd.to_datetime(ls["ipoDate"].replace({"null": None}), errors="coerce")
    ls["dl"] = pd.to_datetime(ls["delistingDate"].replace({"null": None}), errors="coerce")
    windows = {s: [(r.ipo, (r.dl + pd.Timedelta(days=1)) if pd.notna(r.dl) else pd.NaT)
                   for r in g.itertuples()] for s, g in ls.groupby("symbol")}
    rows: list[dict] = []
    rec: dict[str, Any] = {
        "reused_removed": [], "missing_gap": [], "no_listing_record": [], "etf_rows_dropped": [],
        "listing_clipped": [], "lineage_excl_dropped": [], "final_list_sha256": fl.get("sha256"),
        "final_list_excluded": [], "final_list_kept": sorted(fl_kept),
        "final_list_kept_covered_overlap": sorted(in_uni & fl_kept),
        "after_boundary_member_rows": (sorted(pm.loc[pm["after_boundary"].astype(bool), "symbol"])
                                       if "after_boundary" in pm.columns else []),
    }
    for r in pm.itertuples():
        s = r.symbol
        if s in lineage:
            rec["lineage_excl_dropped"].append(s)
            continue
        if s in fl_excl:
            rec["final_list_excluded"].append({"symbol": s, "reason": fl_excl[s]})
            continue
        iv = (pd.Timestamp(r.start_date_filled), pd.Timestamp(r.end_date) if pd.notna(r.end_date) else pd.NaT)
        if s in ETFS:
            rec["etf_rows_dropped"].append(s)
            continue
        if s in m14_set:
            rec["missing_gap"].append({"symbol": s, "start": str(iv[0].date()),
                                       "end": None if pd.isna(iv[1]) else str(iv[1].date())})
            continue
        parts = [iv]
        if s in r18_cuts:
            parts = subtract_intervals(iv, r18_cuts[s])
            if parts != [iv]:
                rec["reused_removed"].append(s)
        w = windows.get(s)
        if not w:
            if parts:
                rec["no_listing_record"].append(s)
            continue
        clipped = []
        for ps, pe in parts:
            for ws, we in w:
                s0 = max(ps, ws) if pd.notna(ws) else ps
                e_candidates = [x for x in (pe, we) if pd.notna(x)]
                e0 = min(e_candidates) if e_candidates else pd.NaT
                if pd.isna(e0) or s0 < e0:
                    clipped.append((s0, e0))
        if clipped != parts:
            rec["listing_clipped"].append(s)
        for cs, ce in clipped:
            rows.append({"symbol": s, "start_date_filled": cs, "end_date": ce if pd.notna(ce) else None})
    mem = pd.DataFrame(rows, columns=["symbol", "start_date_filled", "end_date"])
    rec["n_member_rows"] = int(len(mem))
    return mem, rec


def build_elig(bars: dict[str, pd.DataFrame], mem: pd.DataFrame) -> pd.DataFrame:
    """Member & price >= $5 & ADV20 >= $20M & no zero volume & no |r| > 40% in 20d & 252-session history."""
    R, PX, VOL = bars["R"], bars["PX"], bars["VOL"]
    dates = R.index
    DV = PX * VOL
    ADV20 = DV.rolling(20, min_periods=10).mean()
    JUMP20 = (R.abs() > 0.40).astype(float).rolling(20, min_periods=1).max().astype(bool)
    ZV = VOL == 0
    M = pd.DataFrame(False, index=dates, columns=R.columns)
    for _, r in mem.iterrows():
        if r.symbol not in M.columns:
            continue
        s = pd.Timestamp(r.start_date_filled)
        e = pd.Timestamp(r.end_date) if pd.notna(r.end_date) else dates[-1] + pd.Timedelta(days=1)
        M.loc[(dates >= s) & (dates < e), r.symbol] = True
    ELIG = M & (PX >= 5) & (ADV20 >= 2e7) & ~ZV & ~JUMP20 & R.notna()
    ELIG = ELIG & (R.rolling(252, min_periods=252).count() >= 252)
    return ELIG
