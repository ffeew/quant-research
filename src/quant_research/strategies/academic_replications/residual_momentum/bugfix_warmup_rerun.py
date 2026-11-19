"""Bug-fix rerun (2026-10-30, after Victor's check): residual momentum warm-up bug.
Reruns ONLY the primary L/S (resmom_ls) and long-only (resmom_long) books at BASE params with the fixed pipeline
(nominal 24-of-36-month minimum enforced, no clipped windows). Same config as the logged base trials, so it is logged
in TRIAL_LOG.csv with role 'bugfix_rerun' and a trial_id whose spec key equals the base spec (counted once in N).
Restates results from 2019-02 (first month whose signal has a full 36-month fit window). Same engine, costs, data.
Run: $QR_DESK_DIR/research/replication/.venv/bin/python <this file>
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import json
import pathlib
import sys
import time
from importlib.machinery import ModuleSpec
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant_research.backtest import engine
from quant_research.backtest import trial_log as TL
from quant_research.backtest import validation as V
from quant_research.data import desk_data as dd

TS = time.strftime("%Y-%m-%d_%H%M")
HERE = pathlib.Path(__file__).resolve().parent
SUB = HERE / "submission"
spec = cast(ModuleSpec, importlib.util.spec_from_file_location("pipe", HERE / "pipeline.py"))
mod = importlib.util.module_from_spec(spec)
cast(importlib.abc.Loader, spec.loader).exec_module(mod)

panel = dd.load_panel(clean=True)
R = cast(pd.DataFrame, panel["ret"])
etf_syms = set(dd.universe().query("role=='etf'").symbol) | dd.ETFS
stocks = [s for s in R.columns if s not in etf_syms]
mes = [m for m in dd.month_ends(cast(pd.DatetimeIndex, R.index)) if m >= pd.Timestamp("2016-01-31")]
iv, _ = dd.validate_intervals(R[stocks])
elig = dd.pit_mask(mes, stocks, iv) & R.reindex(mes)[stocks].notna()
ff = dd.ff3_daily()
rf = ff["RF"]
ctx = {"month_ends": mes, "members_at": lambda t: list(elig.columns[elig.loc[t].values]), "ff3": ff}
fac = ff[["Mkt-RF", "SMB", "HML"]].copy()
u = pd.read_parquet(dd.DATA / "factors/ken_french/mom_daily.parquet")
u["date"] = pd.to_datetime(u["date"].astype(str))
fac["UMD"] = u.set_index("date").iloc[:, -1].astype(float)
spy_ex = R["SPY"] - rf.reindex(R.index).ffill()

books = mod.build_targets(panel, ctx, mod.BASE)
first_sig = min(books["resmom_ls"])
print("first signal with scores:", first_sig.date(), "n rebalances", len(books["resmom_ls"]))
# trial SR distribution for DSR (same as the submission: family candidate columns of the 01:47 T x N matrix)
M = pd.read_parquet(sorted((ROOT / "results").glob("trials_daily_net_*.parquet"))[-1])
cand = [c for c in M.columns if c.startswith("resmom|") and "|open|clean|" in c and "DIAG" not in c]
srs_full = np.array([M[c].mean() / M[c].std() for c in cand])
Mt = M.loc[M.index >= "2019-02-01", cand]
srs_t = np.array([Mt[c].mean() / Mt[c].std() for c in cand])
N = 75
out: dict[str, Any] = {}
rows: list[dict[str, Any]] = []
for book in ("resmom_ls", "resmom_long"):
    daily, trades, dl = cast(
        tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
        engine.simulate(panel, books[book], rf, fill="open", book_usd=100000, etfs=frozenset(etf_syms)),
    )
    daily.to_csv(SUB / f"daily_{book}_bugfix.csv")
    trades.to_csv(SUB / f"trades_{book}_bugfix.csv.gz", index=False)
    old = pd.read_csv(SUB / f"daily_{book}.csv", index_col=0, parse_dates=True)
    res: dict[str, Any] = {}
    for lab, st in (("corrected_from_first_trade", None), ("corrected_2019-02+", "2019-02-01")):
        d = daily if st is None else daily[daily.index >= st]
        if st is None:
            d = d.iloc[21:]  # drop partial first month, as in run_all
        n = d.net
        res[lab] = {
            "start": str(n.index[0].date()),
            "end": str(n.index[-1].date()),
            "net": V.basic(n),
            "gross": V.basic(d.gross),
            "net2x": V.basic(d.net2x),
            "dsr_fullperiod_trial_var": V.dsr(n, srs_full, N),
            "dsr_trimmed_trial_var": V.dsr(n, srs_t, N),
            "ab": V.alpha_beta(n, spy_ex, fac),
            "by_year": V.by_year(n).reset_index().to_dict("records"),
            "turnover_x_nav_per_yr": d.traded.sum() / (len(d) / 252),
            "delist_events": int(len(dl)),
        }
    o = old[old.index >= "2019-02-01"]
    res["old_series_trimmed_2019-02+"] = {
        "net": V.basic(o.net),
        "gross": V.basic(o.gross),
        "net2x": V.basic(o.net2x),
        "dsr_fullperiod_trial_var": V.dsr(o.net, srs_full, N),
    }
    j = daily.index.intersection(o.index)
    res["max_abs_diff_vs_old_2019-02+"] = float((daily.net.loc[j] - o.net.loc[j]).abs().max())
    out[book] = res
    c = res["corrected_from_first_trade"]
    rows.append(
        {
            "trial_id": f"resmom|{book}|base|open|clean|{TS}_bugfix_warmup",
            "logged_at_sgt": TS,
            "family": "resmom",
            "book": book,
            "param_tag": "base",
            "params": str(mod.BASE),
            "universe": "PIT S&P 500 (stocks)",
            "data": "Dmitri SIP total_return (clean), same snapshot",
            "fill": "next open",
            "costs": "Tomas v1.1 max Victor floor; borrow 1%/yr; book $100,000",
            "role": "bugfix_rerun",
            "has_daily_series": True,
            "sr_net_full": c["net"]["sharpe"],
            "sr_gross_full": c["gross"]["sharpe"],
            "sr_net_2x_full": c["net2x"]["sharpe"],
            "start": c["start"],
            "end": c["end"],
            "notes": f"BUG-FIX RERUN of resmom|{book}|base|open|clean|2026-10-30_0147 (same config; warm-up min-obs bug fixed). "
            f"Not a new trial: spec key identical, N unchanged. 2019-02+ net SR {res['corrected_2019-02+']['net']['sharpe']:.3f}",
        }
    )
TL.append(rows)
json.dump(out, open(SUB / "bugfix_warmup_rerun.json", "w"), indent=1, default=str)
for b, r in out.items():
    for k in ("corrected_from_first_trade", "corrected_2019-02+", "old_series_trimmed_2019-02+"):
        x = r[k]
        print(
            b,
            k,
            x.get("start", ""),
            "net %.3f gross %.3f 2x %.3f t %.2f DSR %.3f"
            % (
                x["net"]["sharpe"],
                x["gross"]["sharpe"],
                x["net2x"]["sharpe"],
                x["net"]["t_nw"],
                x["dsr_fullperiod_trial_var"]["DSR"],
            ),
            ("DSRtrim %.3f" % x["dsr_trimmed_trial_var"]["DSR"]) if "dsr_trimmed_trial_var" in x else "",
            (
                "alpha %.3f t %.2f beta %.2f ff4a %.3f"
                % (
                    x["ab"]["alpha_ann_vs_spy"],
                    x["ab"]["alpha_t_nw_vs_spy"],
                    x["ab"]["beta_spy"],
                    x["ab"]["alpha_ann_ff4"],
                )
            )
            if "ab" in x
            else "",
            "maxDD %.3f annret %.4f" % (x["net"].get("max_dd", np.nan), x["net"]["ann_ret"]),
        )
    print(b, "max abs diff vs old 2019-02+:", r["max_abs_diff_vs_old_2019-02+"])
