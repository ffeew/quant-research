"""Price-level data QA only: AV vs existing Alpaca SIP bars. No returns/performance/signals."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

TS = sys.argv[1]
W = Path(f"{_QR.DESK_DIR}/statarb/av_rebuild_20261110")
A = Path(f"{_QR.DATA_DIR}/bars/daily")
prog = list(
    {
        r["symbol"]: r for r in (json.loads(l) for l in (W / f"PROGRESS_SOFIA_{TS}.jsonl").read_text().splitlines())
    }.values()
)


def stats(a: pd.Series, b: pd.Series) -> dict[str, Any]:
    d = (a / b - 1).abs() * 100
    d = d.replace([np.inf, -np.inf], np.nan).dropna()
    if not len(d):
        return dict(n=0)
    return dict(
        n=int(len(d)),
        max_pct=round(float(d.max()), 4),
        median_pct=round(float(d.median()), 5),
        days_gt_0_5pct=int((d > 0.5).sum()),
        days_gt_2pct=int((d > 2).sum()),
        worst_date=str(d.idxmax()),
    )


def events(f: pd.Series) -> tuple[set[Any], set[Any]]:
    r = (f / f.shift(1)).dropna()
    thr = max(4e-4, 10 * float((r - 1).abs().median()))  # Alpaca adjusted closes are rounded; noise floor ~2e-4
    split = set(r[(r > 1.25) | (r < 0.8)].index)
    div = set(r[((r - 1).abs() > thr) & (r <= 1.25) & (r >= 0.8)].index)
    return split, div


out = []
for p in prog:
    sym = p["symbol"]
    if p["status"] != "FETCHED":
        continue
    rf, af = A / "raw" / f"{sym}.parquet", A / "adjusted" / f"{sym}.parquet"
    rec = dict(symbol=sym, kind=p["kind"], listing_flags=p["listing_flags"])
    if not rf.exists() or not af.exists():
        rec["alpaca"] = "ABSENT"
        out.append(rec)
        continue
    av = pd.read_csv(p["path"], parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    raw = pd.read_parquet(rf, columns=["session_date", "close", "volume"])
    raw.index = pd.to_datetime(raw.session_date)
    raw = raw.sort_index()
    adj = pd.read_parquet(af, columns=["session_date", "close"])
    adj.index = pd.to_datetime(adj.session_date)
    adj = adj.sort_index()
    lo, hi = max(av.index.min(), raw.index.min()), min(av.index.max(), raw.index.max())
    avw, rw = av.loc[lo:hi], raw.loc[lo:hi]
    common = avw.index.intersection(rw.index)
    rec.update(
        av_first=str(av.index.min().date()),
        av_last=str(av.index.max().date()),
        alp_first=str(raw.index.min().date()),
        alp_last=str(raw.index.max().date()),
        overlap_window=[str(lo.date()), str(hi.date())] if lo <= hi else None,
        overlap_days=int(len(common)),
        alp_dates_missing_in_av=int(len(rw.index.difference(avw.index))),
        av_dates_missing_in_alp=int(len(avw.index.difference(rw.index))),
        missing_in_av_sample=[str(x.date()) for x in rw.index.difference(avw.index)[:5]],
        extra_in_av_sample=[str(x.date()) for x in avw.index.difference(rw.index)[:5]],
    )
    if len(common):
        rec["raw_close"] = stats(avw.close.loc[common], rw.close.loc[common])
        ca = common.intersection(adj.index)
        rec["adjusted_close"] = stats(avw.adjusted_close.loc[ca], adj.close.loc[ca])
        v = rw.volume.loc[common].astype(float)
        va = avw.volume.loc[common].astype(float)
        vd = ((va / v - 1).abs() * 100).replace([np.inf, -np.inf], np.nan).dropna()
        rec["volume"] = dict(
            median_pct=round(float(vd.median()), 3) if len(vd) else None,
            days_gt_5pct=int((vd > 5).sum()),
            days_gt_25pct=int((vd > 25).sum()),
        )
        f = (adj.close / raw.close).loc[lo:hi].dropna()
        s_alp, d_alp = events(f)
        s_av = set(avw.index[avw.split_coefficient != 1.0])
        d_av = set(avw.index[avw.dividend_amount > 0])

        # Alpaca factor change appears on ex-date; tolerate 1-session offset
        def match(x: set[Any], y: set[Any]) -> int:
            yi = sorted(y)
            m = 0
            for t in x:
                if any(abs((t - u).days) <= 3 for u in yi):
                    m += 1
            return m

        rec["splits"] = dict(
            av=len(s_av),
            alpaca_implied=len(s_alp),
            matched=match(s_av, s_alp),
            av_dates=[str(x.date()) for x in sorted(s_av)],
            alpaca_dates=[str(x.date()) for x in sorted(s_alp)],
        )
        rec["dividends"] = dict(
            av=len(d_av),
            alpaca_implied=len(d_alp),
            av_matched_in_alpaca=match(d_av, d_alp),
            alpaca_matched_in_av=match(d_alp, d_av),
        )
        # likely cause heuristics
        dd = (avw.close.loc[common] / rw.close.loc[common] - 1).abs() * 100
        big = dd[dd > 2]
        cause = []
        if any("REUSE" in f or "STARTS_AFTER" in f for f in p["listing_flags"]):
            cause.append("ticker reuse / different issuer")
        if len(big):
            ratios = avw.close.loc[big.index] / rw.close.loc[big.index]
            if len(big) > 5 and ratios.std() / ratios.mean() < 0.02:
                cause.append(
                    f"constant price ratio {ratios.mean():.4f} over {len(big)} days (unapplied split/share-class/issuer mismatch)"
                )
            elif len(big) <= 5:
                cause.append("isolated day(s): likely bad print / stale close")
            else:
                cause.append("varying multi-day divergence")
        ad = rec["adjusted_close"]
        if ad.get("days_gt_0_5pct", 0) > 20 and rec["raw_close"].get("days_gt_0_5pct", 0) <= 5:
            cause.append("raw agrees, adjusted diverges: adjustment methodology (dividend/split factor) difference")
        if rec["splits"]["av"] != rec["splits"]["matched"] or (
            rec["splits"]["alpaca_implied"] != len(s_alp & s_av)
            and rec["splits"]["alpaca_implied"] > rec["splits"]["matched"]
        ):
            cause.append("split event set mismatch")
        rec["likely_causes"] = cause
    out.append(rec)
res = W / f"CROSSCHECK_SOFIA_{TS}.json"
assert not res.exists()
cmp_ = [r for r in out if r.get("raw_close", {}).get("n")]


def agg(key: str, fld: str) -> list[Any]:
    return [r[key][fld] for r in cmp_]


summary = dict(
    symbols_compared=len(cmp_),
    alpaca_absent=sum(r.get("alpaca") == "ABSENT" for r in out),
    raw_close=dict(
        median_of_median_pct=float(np.median(agg("raw_close", "median_pct"))),
        symbols_any_day_gt_2pct=sum(x > 0 for x in agg("raw_close", "days_gt_2pct")),
        symbols_any_day_gt_0_5pct=sum(x > 0 for x in agg("raw_close", "days_gt_0_5pct")),
        total_days_gt_0_5=int(sum(agg("raw_close", "days_gt_0_5pct"))),
        total_days_gt_2=int(sum(agg("raw_close", "days_gt_2pct"))),
        total_overlap_days=int(sum(r["overlap_days"] for r in cmp_)),
    ),
    adjusted_close=dict(
        median_of_median_pct=float(np.median(agg("adjusted_close", "median_pct"))),
        symbols_any_day_gt_2pct=sum(x > 0 for x in agg("adjusted_close", "days_gt_2pct")),
        symbols_any_day_gt_0_5pct=sum(x > 0 for x in agg("adjusted_close", "days_gt_0_5pct")),
        total_days_gt_0_5=int(sum(agg("adjusted_close", "days_gt_0_5pct"))),
        total_days_gt_2=int(sum(agg("adjusted_close", "days_gt_2pct"))),
    ),
    volume_median_of_median_pct=float(
        np.median([r["volume"]["median_pct"] for r in cmp_ if r["volume"]["median_pct"] is not None])
    ),
    date_mismatch=dict(
        symbols_with_alp_dates_missing_in_av=sum(r["alp_dates_missing_in_av"] > 0 for r in cmp_),
        total_alp_dates_missing_in_av=sum(r["alp_dates_missing_in_av"] for r in cmp_),
        symbols_with_av_dates_missing_in_alp=sum(r["av_dates_missing_in_alp"] > 0 for r in cmp_),
        total_av_dates_missing_in_alp=sum(r["av_dates_missing_in_alp"] for r in cmp_),
    ),
    splits=dict(
        av=sum(r["splits"]["av"] for r in cmp_),
        alpaca_implied=sum(r["splits"]["alpaca_implied"] for r in cmp_),
        av_matched=sum(r["splits"]["matched"] for r in cmp_),
    ),
    dividends=dict(
        av=sum(r["dividends"]["av"] for r in cmp_),
        alpaca_implied=sum(r["dividends"]["alpaca_implied"] for r in cmp_),
        av_matched=sum(r["dividends"]["av_matched_in_alpaca"] for r in cmp_),
    ),
)
worst_raw = sorted(cmp_, key=lambda r: (-r["raw_close"]["days_gt_2pct"], -r["raw_close"]["max_pct"]))[:15]
worst_adj = sorted(cmp_, key=lambda r: (-r["adjusted_close"]["days_gt_2pct"], -r["adjusted_close"]["max_pct"]))[:15]
pick = lambda r: dict(
    symbol=r["symbol"],
    raw=r["raw_close"],
    adj=r["adjusted_close"],
    dates=dict(miss_av=r["alp_dates_missing_in_av"], extra_av=r["av_dates_missing_in_alp"]),
    splits=r["splits"],
    causes=r["likely_causes"],
    flags=r["listing_flags"],
)
res.write_text(
    json.dumps(
        dict(
            scope="PRICE-LEVEL DATA QA ONLY; no returns/performance",
            summary=summary,
            worst_raw=[pick(r) for r in worst_raw],  # type: ignore[no-untyped-call]  # lambda has no annotation syntax
            worst_adjusted=[pick(r) for r in worst_adj],  # type: ignore[no-untyped-call]  # lambda has no annotation syntax
            per_symbol=out,
        ),
        indent=1,
        default=str,
    )
)
pd.DataFrame(
    [
        dict(
            symbol=r["symbol"],
            overlap=r["overlap_days"],
            raw_max=r["raw_close"]["max_pct"],
            raw_med=r["raw_close"]["median_pct"],
            raw_gt05=r["raw_close"]["days_gt_0_5pct"],
            raw_gt2=r["raw_close"]["days_gt_2pct"],
            adj_max=r["adjusted_close"].get("max_pct"),
            adj_med=r["adjusted_close"].get("median_pct"),
            adj_gt05=r["adjusted_close"].get("days_gt_0_5pct"),
            adj_gt2=r["adjusted_close"].get("days_gt_2pct"),
            vol_med=r["volume"]["median_pct"],
            miss_av=r["alp_dates_missing_in_av"],
            extra_av=r["av_dates_missing_in_alp"],
            splits_av=r["splits"]["av"],
            splits_alp=r["splits"]["alpaca_implied"],
            splits_matched=r["splits"]["matched"],
            causes="; ".join(r["likely_causes"]),
        )
        for r in cmp_
    ]
).to_csv(W / f"CROSSCHECK_SOFIA_{TS}.csv", index=False)
print(json.dumps(summary, indent=1))
