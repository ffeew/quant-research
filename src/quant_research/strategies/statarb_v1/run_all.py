"""First-pass stat-arb tests (PRELIMINARY). Everything is driven by config.py.
Usage: python run_all.py [--price-set adjusted|total_return|raw] [--source cio_data] [--only name1,name2] [--tag x]
Outputs -> ../results/<source>_<price_set>[_tag]/ : summary.csv, daily_<strategy>__<exec>.csv, pairs trade logs, run_info.json"""
import sys, json, time, argparse, importlib
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from quant_research.strategies.statarb_v1 import config as CFG
from quant_research.strategies.statarb_v1.statarb.data import load_panel
from quant_research.strategies.statarb_v1.statarb import backtest as bt
from quant_research.strategies.statarb_v1.statarb import costs

ap = argparse.ArgumentParser()
ap.add_argument("--price-set", default=CFG.PRICE_SET); ap.add_argument("--source", default=CFG.SOURCE)
ap.add_argument("--only", default=None); ap.add_argument("--tag", default="")
ap.add_argument("--no-jump-filter", action="store_true")
a = ap.parse_args()
HOLD = pd.Timestamp(CFG.HOLDOUT_START)
OUT = Path(__file__).resolve().parents[1] / "results" / f"{a.source}_{a.price_set}{('_' + a.tag) if a.tag else ''}"
OUT.mkdir(parents=True, exist_ok=True)
t0 = time.time()
P = load_panel(a.source, price_set=a.price_set, jump_filter=CFG.JUMP_FILTER and not a.no_jump_filter,
               jump_abs_ret=CFG.JUMP_ABS_RET, split_ratios=CFG.SPLIT_RATIOS, split_tol=CFG.SPLIT_TOL)
print("loaded", P.close.shape, P.close.index[0].date(), P.close.index[-1].date(), f"{time.time()-t0:.0f}s", P.notes, flush=True)
O = pd.concat([P.open, P.etf_open], axis=1); Cl = pd.concat([P.close, P.etf_close], axis=1)
BAD = pd.concat([P.bad, pd.DataFrame(False, index=P.etf_close.index, columns=P.etf_close.columns)], axis=1)
ADV = P.dollar_vol.rolling(20, min_periods=10).mean()          # known at close t (cost inputs lagged: used for trades at t+1)
SIG = P.ret_cc.rolling(20, min_periods=10).std()
info = {"label": CFG.LABEL, "source": a.source, "price_set": a.price_set, "notes": P.notes,
        "first": str(P.close.index[0].date()), "last": str(P.close.index[-1].date()), "holdout_start": str(HOLD.date()),
        "n_symbols": int(P.close.shape[1]), "avg_pit_members": float(P.member.sum(axis=1).mean()),
        "cost_model_check(ref_vs_vectorised_bps)": costs.validate(), "strategies": {}}
SCEN = [("base_k0.75_borrow25", CFG.AUM_GROSS[0], CFG.K_BASE, CFG.BORROW_BASE),
        ("stress_k1.0_borrow50", CFG.AUM_GROSS[0], CFG.K_STRESS, CFG.BORROW_STRESS)] + \
       [(f"base_at_${aum/1e6:.0f}M", aum, CFG.K_BASE, CFG.BORROW_BASE) for aum in CFG.AUM_GROSS[1:]]
rows = []

def periods(res):
    act = res.index[res["gross_exposure"] > 0]
    s = act[0] if len(act) else res.index[0]
    return {"dev_2017-2021(walk-fwd)": res.loc[s:HOLD - pd.Timedelta(days=1)], "holdout_2022+(OOS)": res.loc[HOLD:], "full": res.loc[s:]}

names = a.only.split(",") if a.only else list(CFG.STRATEGIES)
for name in names:
    fn, kw = CFG.STRATEGIES[name]
    mod, f = fn.rsplit(".", 1)
    t1 = time.time()
    W = getattr(importlib.import_module(f"statarb.{mod}"), f)(P, **kw)
    print(name, "weights built", f"{time.time()-t1:.0f}s", flush=True)
    si = {"params": kw, "build_sec": round(time.time() - t1)}
    if "trades" in W.attrs:
        tr, fl = W.attrs["trades"], W.attrs["formation_log"]
        fl.to_csv(OUT / f"{name}_formation_log.csv", index=False)
        si["formation_summary"] = fl.drop(columns="formation_end").sum().to_dict()
    for ex in CFG.EXECS:
        fwd = bt.fwd_returns(O, Cl, BAD, ex)[W.columns]
        for sc, aum, k, br in SCEN:
            res, trades = bt.run(W, fwd, ADV.reindex(columns=W.columns), SIG.reindex(columns=W.columns), ex, aum, k, br)
            res = res.iloc[:-2]
            if sc == SCEN[0][0]:
                res.to_csv(OUT / f"daily_{name}__{ex}.csv")
                cap = bt.capacity(res.attrs.get("w", W).iloc[:-2], trades.iloc[:-2], ADV.reindex(columns=W.columns))
                si[f"capacity_{ex}"] = {"1pctADV_$gross": cap[0.01], "5pctADV_$gross": cap[0.05]}
            for per, r in periods(res).items():
                for row in bt.summarise(r, name, per, {"exec": ex, "scenario": sc, "aum_gross": aum}):
                    if row["pnl"] == "gross" and sc != SCEN[0][0]:
                        continue
                    if row["pnl"] == "gross":
                        row["scenario"] = "gross(no costs)"
                    row["cap_1pctADV_$"] = si.get(f"capacity_{ex}", {}).get("1pctADV_$gross")
                    row["cap_5pctADV_$"] = si.get(f"capacity_{ex}", {}).get("5pctADV_$gross")
                    rows.append(row)
            if "trades" in W.attrs and sc == SCEN[0][0]:
                tr = W.attrs["trades"].copy()
                if len(tr):
                    pr = []
                    for _, t in tr.iterrows():
                        rng = fwd.loc[t.entry:t.exit].iloc[:-1]
                        gy, gx = 1 / (1 + t.beta), t.beta / (1 + t.beta)
                        pr.append((t.side * gy * rng[t.y].fillna(0) - t.side * gx * rng[t.x].fillna(0)).sum())
                    tr["gross_ret_per_pair_notional"] = pr
                    tr.to_csv(OUT / f"{name}_trades_{ex}.csv", index=False)
                    for per, sl in [("dev", tr[tr.entry < HOLD]), ("holdout", tr[tr.entry >= HOLD])]:
                        si[f"round_trips_{ex}_{per}"] = {"n": int(len(sl)), "hit_rate": float((sl.gross_ret_per_pair_notional > 0).mean()) if len(sl) else None,
                            "mean_gross_bps_per_trade(on pair gross notional)": float(sl.gross_ret_per_pair_notional.mean() * 1e4) if len(sl) else None,
                            "exit_reasons": sl.reason.value_counts().to_dict()}
    info["strategies"][name] = si
    pd.DataFrame(rows).to_csv(OUT / "summary.csv", index=False)
    json.dump(info, open(OUT / "run_info.json", "w"), indent=1, default=str)
    print(name, "done", f"{time.time()-t0:.0f}s", flush=True)
df = pd.DataFrame(rows); df.insert(0, "label", CFG.LABEL); df.insert(1, "price_set", a.price_set)
df.to_csv(OUT / "summary.csv", index=False)
json.dump(info, open(OUT / "run_info.json", "w"), indent=1, default=str)
print("ALL DONE", f"{time.time()-t0:.0f}s")
