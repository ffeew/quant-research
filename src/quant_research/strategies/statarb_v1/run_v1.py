"""v1 trial runner (label: 'v1, research only'). One command regenerates every v1 number from the DE dataset:
    ../.venv/bin/python run_v1.py && ../.venv/bin/python validate_v1.py
Builds target weights for every pre-registered variant in config.V1_VARIANTS (AL s-scores cached once per factor
model), backtests both lagged executions (open_t1 primary - STANDARD 'next-bar open'; close_t1 secondary), and
writes per-trial daily gross/net under every cost scenario in config.SCENARIOS to ../results/v1/daily/."""

from __future__ import annotations

import importlib
import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

sys.path.insert(0, str(Path(__file__).parent))
import argparse

from quant_research.strategies.statarb_v1 import config as CFG
from quant_research.strategies.statarb_v1.statarb import backtest as bt
from quant_research.strategies.statarb_v1.statarb import costs as C
from quant_research.strategies.statarb_v1.statarb import papers
from quant_research.strategies.statarb_v1.statarb.data import CIO, ETFS, load_panel

ap = argparse.ArgumentParser()
ap.add_argument("only", nargs="?", default=None)
ap.add_argument(
    "--mode",
    default="base",
    choices=["base", "complete", "delist_stress"],
    help="complete: drop reused/re-added/gap tickers (data_issues); delist_stress: -30%% on non-merger delistings",
)
A = ap.parse_args()
OUT = Path(__file__).resolve().parents[1] / "results" / ("v1" if A.mode == "base" else f"v1_{A.mode}")
(OUT / "daily").mkdir(parents=True, exist_ok=True)
(OUT / "cache").mkdir(exist_ok=True)
(OUT / "trades").mkdir(exist_ok=True)
(OUT / "cache").mkdir(exist_ok=True)
only = A.only.split(",") if A.only else None
t0 = time.time()
P = load_panel(
    "cio_data",
    price_set=CFG.PRICE_SET,
    jump_filter=CFG.JUMP_FILTER,
    jump_abs_ret=CFG.JUMP_ABS_RET,
    split_ratios=CFG.SPLIT_RATIOS,
    split_tol=CFG.SPLIT_TOL,
)
from quant_research.strategies.statarb_v1.statarb import data_issues as DI
from quant_research.strategies.statarb_v1.statarb.data import _membership

FLAG = DI.flagged_symbols(P.close, _membership(P.close.index, P.close.columns))
EVENTS = DI.delisting_events(-0.30)
if A.mode == "complete":
    drop = [s for s in FLAG["all"] if s in P.member.columns]
    P.member.loc[:, drop] = False
    print("complete-history mode: excluded", len(drop), "symbols", flush=True)
CACHE = (
    (Path(__file__).resolve().parents[1] / "results" / "v1" / "cache") if A.mode == "delist_stress" else OUT / "cache"
)
print(
    "loaded", P.close.shape, P.close.index[0].date(), P.close.index[-1].date(), f"{time.time() - t0:.0f}s", flush=True
)
O = pd.concat([P.open, P.etf_open], axis=1)
Cl = pd.concat([P.close, P.etf_close], axis=1)
BAD = pd.concat([P.bad, pd.DataFrame(False, index=P.etf_close.index, columns=P.etf_close.columns)], axis=1)
# ETF $ADV from raw bars (real consolidated volume, not a placeholder)
edv = {}
for e in P.etf_close.columns:
    d = pd.read_parquet(CIO / "bars/daily/raw" / f"{e}.parquet", columns=["session_date", "close", "volume"])
    edv[e] = pd.Series((d.close * d.volume).values, index=pd.to_datetime(d.session_date))
DV = pd.concat([P.dollar_vol, pd.DataFrame(edv).reindex(P.close.index)], axis=1)
ADV = DV.rolling(20, min_periods=10).mean()
SIG = pd.concat([P.ret_cc, P.etf_close.pct_change(fill_method=None)], axis=1).rolling(20, min_periods=10).std()
# STANDARD.md s5 per-side minimum before half-spread. S&P 500 constituents are large-cap by index definition -> 5 bps,
# except thin names (Tomas bucket L4, 20d ADV < $50M) -> small-cap/thin row 20 bps; liquid ETFs 2 bps.
FLOOR = {"L1": 5.0, "L2": 5.0, "L3": 5.0, "L4": 20.0}


def floor_bps(adv: pd.DataFrame, cols: pd.Index) -> pd.DataFrame:
    hs, _ = C.bucket_params(adv)
    f = pd.DataFrame(20.0, index=adv.index, columns=adv.columns)
    for name, (lo, *_r) in sorted(C.cm.BUCKETS.items(), key=lambda x: x[1][0]):
        f = f.mask(adv >= lo, FLOOR[name[:2]])
    etf = [c for c in cols if c in ETFS]
    f[etf] = 2.0  # liquid ETFs (SPY / sector SPDRs) row
    return f + hs  # + full half-spread (market order)


def get_weights(v: dict[str, Any]) -> pd.DataFrame:
    f = CACHE / f"W_{v['name'].replace('/', '-')}.pkl"
    if f.exists():
        return cast(pd.DataFrame, pickle.load(open(f, "rb")))
    if v["kind"] == "al":
        sf = CACHE / f"ALscores_{v['factors']}.pkl"
        if sf.exists():
            S, B = pickle.load(open(sf, "rb"))
        else:
            t1 = time.time()
            S, B = papers.al_scores(P, v["factors"], k=15)
            pickle.dump((S, B), open(sf, "wb"))
            print("  AL scores", v["factors"], f"{time.time() - t1:.0f}s", flush=True)
        so, cl, cs = v["bands"]
        W = papers.al_weights(P, S, B, v["factors"], so, cl, cs)
    else:
        mod, fn = v["fn"].rsplit(".", 1)
        W = getattr(importlib.import_module(f"statarb.{mod}"), fn)(P, **v["kw"])
    pickle.dump(W, open(f, "wb"))
    return W


log = []
for v in CFG.V1_VARIANTS:
    if only and v["name"] not in only and v["family"] not in only:
        continue
    t1 = time.time()
    W = get_weights(v)
    cols = W.columns
    adv, sig = ADV.reindex(columns=cols).fillna(5e9), SIG.reindex(columns=cols).fillna(0.01)
    fl = floor_bps(adv, cols)
    for ex in CFG.EXECS:
        fwd = bt.fwd_returns(O, Cl, BAD, ex)[cols]
        if A.mode == "delist_stress":
            fwd, hits = DI.apply_delisting(fwd, ex, EVENTS)
        res, trades = bt.run(W, fwd, adv, sig, ex, CFG.AUM_GROSS[0], CFG.K_BASE, CFG.BORROW_BASE, buffer=v["buffer"])
        w = res.attrs["w"]
        res, trades, w = res.iloc[:-2], trades.iloc[:-2], w.iloc[:-2]
        caldays = pd.Series(w.index, index=w.index).diff().dt.days.shift(-1).fillna(1.0)
        short = w.clip(upper=0).abs().sum(axis=1)
        out = res[["gross", "turnover", "gross_exposure", "net_exposure", "n_names", "n_name_trades"]].copy()
        for sc, p in CFG.SCENARIOS.items():
            cb = C.cost_bps(
                trades, CFG.AUM_GROSS[0], adv.loc[trades.index], sig.loc[trades.index], bt.VENUE[ex], p["k"]
            )
            if p["floor"]:
                cb = cast(pd.DataFrame, np.maximum(cb, fl.loc[trades.index]))
            tc = (trades * cb).sum(axis=1) / 1e4 * p["mult"]
            bc = short * p["borrow"] * caldays / 360 * p["mult"]
            out[f"tcost_{sc}"], out[f"bcost_{sc}"], out[f"net_{sc}"] = tc, bc, out["gross"] - tc - bc
        stk = [c for c in cols if c not in ETFS]
        ws = w[stk]
        out["opens"] = ((ws.abs() > 1e-9) & (ws.shift(1).abs().fillna(0) <= 1e-9)).sum(axis=1)  # new name positions
        out["long_gross"] = (w.clip(lower=0) * fwd.reindex_like(w).fillna(0)).sum(axis=1)
        out["short_gross"] = (w.clip(upper=0) * fwd.reindex_like(w).fillna(0)).sum(axis=1)
        out.attrs = {}
        out.to_parquet(OUT / "daily" / f"{v['name'].replace('/', '-')}__{ex}.parquet")
        cap = bt.capacity(w, trades, ADV.reindex(columns=cols))
        rec = {
            "trial": f"{v['name']}__{ex}",
            "family": v["family"],
            "variant": v["name"],
            "exec": ex,
            "buffer": v["buffer"],
            "params": json.dumps(
                v.get("kw", {"bands(open,close_long,close_short)": v.get("bands"), "factors": v.get("factors")})
            ),
            "replication": v["replication"],
            "cap_1pctADV_$": cap[0.01],
            "cap_5pctADV_$": cap[0.05],
        }
        if "trades" in W.attrs and len(W.attrs["trades"]):
            tr = W.attrs["trades"].copy()
            pr = []
            for _, t in tr.iterrows():
                rng = fwd.loc[t.entry : t.exit].iloc[:-1]
                gy, gx = 1 / (1 + t.beta), t.beta / (1 + t.beta)
                pr.append((t.side * gy * rng[t.y].fillna(0) - t.side * gx * rng[t.x].fillna(0)).sum())
            tr["gross_ret_per_pair_notional"] = pr
            tr.to_csv(OUT / "trades" / f"{v['name']}__{ex}.csv", index=False)
            rec["pair_round_trips_total"] = len(tr)
            rec["pair_round_trips_holdout"] = int((tr.entry >= pd.Timestamp(CFG.HOLDOUT_START)).sum())
        Wt = W.attrs.get("trades") if "trades" in W.attrs else None
        aud = DI.straddle_audit(w, Cl[[c for c in cols if c in Cl]], FLAG["all"], Wt)
        rec["straddle_flags"] = len(aud)
        rec["straddle_detail"] = json.dumps(aud[:20])
        zomb = DI.end_of_data_holdings(w, Cl[[c for c in cols if c in Cl]])
        rec["held_after_last_bar"] = len(zomb)
        rec["held_after_last_bar_detail"] = json.dumps(zomb[:20])
        flg = [c for c in cols if c in FLAG["all"]]
        rec["share_gross_in_flagged_names"] = (
            float(w[flg].abs().sum(axis=1).mean() / w.abs().sum(axis=1).replace(0, np.nan).mean()) if flg else 0.0
        )
        if A.mode == "delist_stress":
            held = [
                (s_, str(d_.date()), r_, float(w.loc[d_, s_]))
                for s_, d_, r_ in hits
                if d_ in w.index and abs(w.loc[d_, s_]) > 1e-9
            ]
            rec["delisting_positions_hit"] = json.dumps(held)
            rec["delisting_pnl_impact"] = float(sum(r_ * wt for *_x, r_, wt in held))
        log.append(rec)
    print(v["name"], f"{time.time() - t1:.0f}s (total {time.time() - t0:.0f}s)", flush=True)
    prev = pd.read_csv(OUT / "trial_meta.csv") if (OUT / "trial_meta.csv").exists() else pd.DataFrame()
    allm = pd.concat([prev[~prev.trial.isin([r["trial"] for r in log])] if len(prev) else prev, pd.DataFrame(log)])
    allm.to_csv(OUT / "trial_meta.csv", index=False)
json.dump(
    {
        "label": CFG.LABEL,
        "dataset": f"{_QR.DATA_DIR} (DE final build; manifest.json)",
        "price_set": CFG.PRICE_SET,
        "notes": P.notes,
        "first": str(P.close.index[0].date()),
        "last": str(P.close.index[-1].date()),
        "n_symbols": int(P.close.shape[1]),
        "avg_pit_members": float(P.member.sum(axis=1).mean()),
        "cost_model_check": C.validate(),
        "mode": A.mode,
        "flagged_symbols": {k: sorted(v) for k, v in FLAG.items()},
        "scenarios": CFG.SCENARIOS,
        "floor_bps": FLOOR,
    },
    open(OUT / "run_info.json", "w"),
    indent=1,
    default=str,
)
print("ALL DONE", f"{time.time() - t0:.0f}s")
