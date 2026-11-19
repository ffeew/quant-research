"""Append-only trial log (validation STANDARD §1.3). One row per variant ever run by the derivatives researcher. The derivatives researcher, 2026-10-30."""

from __future__ import annotations

import csv
import fcntl
import json
import pathlib
from typing import Any, cast

import pandas as pd

from quant_research.utils import env as _env
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = pathlib.Path(f"{_QR.DESK_DIR}/research/replication")
LOG = pathlib.Path(_env.getenv("RESEARCH_TRIAL_LOG", ROOT / "TRIAL_LOG.csv"))  # override only for code smoke tests
COLS = [
    "trial_id",
    "logged_at_sgt",
    "family",
    "book",
    "param_tag",
    "params",
    "universe",
    "data",
    "fill",
    "costs",
    "role",
    "has_daily_series",
    "sr_net_full",
    "sr_net_is_2016_2021",
    "sr_net_oos_2022plus",
    "sr_gross_full",
    "sr_net_2x_full",
    "start",
    "end",
    "notes",
]


def existing_ids() -> set[str]:
    if not LOG.exists():
        return set()
    return cast(set[str], set(pd.read_csv(LOG, usecols=["trial_id"]).trial_id))


def append(rows: list[dict[str, Any]]) -> None:
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            r = {
                **r,
                "params": json.dumps(r.get("params", {}), sort_keys=True)
                if isinstance(r.get("params"), dict)
                else r.get("params", ""),
            }
            w.writerow(r)
        fcntl.flock(f, fcntl.LOCK_UN)


def historical_rows() -> list[dict[str, Any]]:
    """Trials run before the v2 pipeline (no daily series kept). Numbers copied from the saved summary files."""
    rows: list[dict[str, Any]] = []

    def add(
        fam: str,
        book: Any,
        tag: str,
        sr: Any,
        start: Any,
        end: Any,
        notes: str,
        data: str,
    ) -> None:
        rows.append(
            {
                "trial_id": f"H|{fam}|{book}|{tag}",
                "logged_at_sgt": "2026-10-30 (retro-logged 01:40)",
                "family": fam,
                "book": book,
                "param_tag": tag,
                "params": "",
                "universe": "",
                "data": data,
                "fill": "",
                "costs": "",
                "role": "historical",
                "has_daily_series": False,
                "sr_net_full": sr,
                "start": start,
                "end": end,
                "notes": notes,
            }
        )

    for tag in ("paper36", "noint12"):
        s = pd.read_csv(ROOT / f"blitz-huij-martens-2011-residual-momentum/summary_{tag}.csv")
        for r in s.itertuples():
            if r.series == "ew_universe":
                continue
            add(
                "resmom",
                r.series,
                f"turn1_{tag}",
                r.sharpe_ann,
                r.start,
                r.end,
                "gross, monthly, statarb IEX survivor universe",
                "statarb/data/daily_bars.json (IEX)",
            )
    add(
        "resmom",
        "resmom_ls",
        "turn1_buggy_intercept_on_scoring_window",
        "",
        "",
        "",
        "bug: residuals summed to zero; discarded",
        "statarb IEX",
    )
    s = pd.read_csv(ROOT / "frazzini-pedersen-2014-betting-against-beta/summary.csv")
    for r in s.itertuples():
        if r.series in ("ew_universe", "spy"):
            continue
        add(
            "bab",
            r.series,
            "turn1",
            r.sharpe_ann,
            r.start,
            r.end,
            "gross, monthly, statarb IEX survivor universe",
            "statarb IEX",
        )
    h = ROOT / "results/history/run_0121-0123_SGT_nextclose_tomas_only.csv"
    if h.exists():
        s = pd.read_csv(h)
        s = s[s.window == "full"]
        for r in s.itertuples():
            fam = {"resmom": "resmom", "bab": "bab", "imom": "imom"}[cast(str, r.strategy)]
            add(
                fam,
                r.variant,
                "v1_0121_nextclose_tomas",
                r.sharpe_net,
                r.start,
                r.end,
                "v1 engine: next-close MOC, TCA owner costs only, borrow 25bp, book $1M",
                "data owner SIP total return (clean)",
            )
    for fam, name in [
        ("resmom", "UMD public proxy"),
        ("bab", "AQR BAB public"),
        ("imom", "FF49 J6/K1 top5-bot5 public proxy"),
        ("other", "ST_Rev public proxy"),
        ("other", "RMW public proxy"),
    ]:
        add(
            fam,
            name,
            "turn1_public_post_pub_check",
            "",
            "",
            "",
            "public factor check (post_pub_checks.csv), not a desk variant",
            "Ken French / AQR",
        )
    # v2 run started 01:36 SGT, killed at ~01:43 to add the ticker-reuse / delisting handling (same specs otherwise)
    import re

    lp = ROOT / "results/history/run_all_0136_killed_for_data_fixes.log"
    if lp.exists():
        for line in lp.read_text().splitlines():
            m = re.search(
                r"\[(\d\d:\d\d:\d\d)\]\s+(\w+)/(\S+?)/(\S+?)/(open|close)(/noclean)?: SR gross (\S+) net (\S+) 2x (\S+)",
                line,
            )
            if not m:
                continue
            ts, fam, book, tag, fill, nc, g, n, n2 = m.groups()
            rows.append(
                {
                    "trial_id": f"{fam}|{book}|{tag}|{fill}|{'noclean' if nc else 'clean'}|0136killed",
                    "logged_at_sgt": f"2026-10-30 {ts}",
                    "family": fam,
                    "book": book,
                    "param_tag": tag,
                    "params": "",
                    "universe": "PIT S&P 500 (before SNDK/AA/Q interval exclusion)",
                    "data": "data owner store, v2 run killed mid-way",
                    "fill": fill,
                    "costs": "max(the TCA owner, validator floor) + 1% borrow",
                    "role": "superseded_rerun",
                    "has_daily_series": False,
                    "sr_net_full": float(n),
                    "sr_gross_full": float(g),
                    "sr_net_2x_full": float(n2),
                    "notes": "v2 run 01:36 SGT killed for data fixes; same spec as the later run",
                }
            )
    return rows
