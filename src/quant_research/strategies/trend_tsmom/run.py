"""Run the trend-sleeve replication: baseline + pre-listed robustness grid. Writes outputs/*.csv|json|md.
Usage: .venv/bin/python run.py
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from quant_research.strategies.trend_tsmom.tsmom.data import (
    ASSET_CLASS,
    CARD_UNIVERSE,
    EXT_EXTRA,
    build_panel,
    load_shortable,
)
from quant_research.strategies.trend_tsmom.tsmom.engine import Config, run
from quant_research.strategies.trend_tsmom.tsmom.stats import corr_to, deflated_sharpe, monthly, perf, sharpe_se

OUT = "outputs"
ALL = CARD_UNIVERSE + EXT_EXTRA
panel = build_panel(ALL)
shortable = load_shortable()
avail = [s for s in CARD_UNIVERSE if s in panel["px"].columns]
ext = [s for s in ALL if s in panel["px"].columns]
spy_x = panel["px"]["SPY"].pct_change(fill_method=None) - panel["rf"]

BASE = Config()
# ---- pre-listed variants (written before looking at results; every one is reported) ----
trials = []
for lb in [(1,), (3,), (6,), (12,), (1, 3, 12)]:
    for rb in ["M", "W"]:
        trials.append((f"lb{'-'.join(map(str, lb))}_{rb}", avail, replace(BASE, lookbacks=lb, rebalance=rb)))
trials += [
    ("mop_40pct_unscaled", avail, replace(BASE, sizing="mop")),
    ("class_balanced", avail, replace(BASE, class_balanced=True)),
    ("gross_cap_2x", avail, replace(BASE, gross_cap=2.0)),
    ("honour_shortable", avail, replace(BASE, honour_shortable=True)),
    ("implementable(cap2x+shortable)", avail, replace(BASE, gross_cap=2.0, honour_shortable=True)),
    ("implementable_blend_M", avail, replace(BASE, gross_cap=2.0, honour_shortable=True, lookbacks=(1, 3, 12))),
    ("vol_com20", avail, replace(BASE, vol_com=20)),
    ("lag0(same-close fill)", avail, replace(BASE, lag=0)),
    ("extended_universe", ext, BASE),
]
cost_variants = [
    ("costs_2x", replace(BASE, cost_mult=2.0)),
    ("venue_close(MOC)", replace(BASE, venue="close")),
    ("impact_k0.5", replace(BASE, impact_k=0.5)),
    ("nav_10m", replace(BASE, nav_usd=10_000_000)),
    ("borrow_50bps", replace(BASE, borrow_rate=0.005)),
]


EVAL_START = "2017-02-01"  # common evaluation start for all ETF-book variants (12m lookback + vol warm-up)


def summarise(name: str, o: dict[str, Any], start: str = EVAL_START) -> dict[str, Any]:
    d = o["daily"].loc[start:]
    y = len(d) / 252
    g, n = perf(d.gross), perf(d.net)
    c = corr_to(d.net, spy_x)
    gross_ann = g["ann_ret"]
    cost_ann = (d.cost.sum() + d.borrow.sum()) / y
    turn = d.turnover.sum() / y
    be = gross_ann / turn * 1e4 if turn > 0 else np.nan
    avg_bps = d.cost.sum() / d.turnover.sum() * 1e4 if d.turnover.sum() > 0 else np.nan
    net2 = gross_ann - 2 * cost_ann
    flag = "FAIL" if n["ann_ret"] <= 0 else "WARN" if (net2 <= 0 or cost_ann > 0.5 * gross_ann) else "PASS"
    return {
        "variant": name,
        "start": n["start"],
        "years": round(y, 2),
        "gross_ret": gross_ann,
        "gross_vol": g["ann_vol"],
        "gross_sharpe": g["sharpe"],
        "net_ret": n["ann_ret"],
        "net_vol": n["ann_vol"],
        "net_sharpe": n["sharpe"],
        "net_t": n["t_stat"],
        "net_maxdd": n["max_dd"],
        "net_cagr": n["cagr"],
        "cost_drag": cost_ann,
        "turnover_x": turn,
        "avg_cost_bps_1way": avg_bps,
        "breakeven_bps_1way": be,
        "avg_gross_lev": d.gross_lev.mean(),
        "max_gross_lev": d.gross_lev.max(),
        "corr_spy_d": c["corr_daily"],
        "corr_spy_m": c["corr_monthly"],
        "skew_m": n["skew_m"],
        "costs_flag": flag,
    }


def fmt(df: pd.DataFrame, pct: Sequence[str] = (), f2: Sequence[str] = (), f1: Sequence[str] = ()) -> str:
    df = df.copy()
    for c in df.columns:
        if c in pct:
            df[c] = df[c].map(lambda v: f"{v * 100:.1f}%" if pd.notna(v) else "")
        elif c in f2:
            df[c] = df[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "")
        elif c in f1:
            df[c] = df[c].map(lambda v: f"{v:.1f}" if pd.notna(v) else "")
    return df.to_markdown(index=False)


PCT = (
    "gross_ret",
    "gross_vol",
    "net_ret",
    "net_vol",
    "net_maxdd",
    "net_cagr",
    "cost_drag",
    "ann_ret",
    "ann_vol",
    "max_dd",
)
F2 = (
    "gross_sharpe",
    "net_sharpe",
    "net_t",
    "corr_spy_d",
    "corr_spy_m",
    "skew_m",
    "avg_gross_lev",
    "max_gross_lev",
    "sharpe",
    "t_stat",
    "years",
)
F1 = ("turnover_x", "avg_cost_bps_1way", "breakeven_bps_1way")

res = {}
rows = []
for name, uni, cfg in trials:
    o = run(panel, uni, cfg, shortable)
    if name == "lb12_M":
        name = "BASELINE = lb12_M (pvt10, card universe)"
        base_o = o
    res[name] = o
    for k in ("daily", "weights", "contrib", "cost_by_asset", "turn_by_asset"):
        o[k] = o[k].loc[EVAL_START:]
    rows.append(summarise(name, o))
grid = pd.DataFrame(rows)
bi = int(grid.index[grid.variant.str.startswith("BASELINE")][0])
grid = pd.concat([grid.loc[[bi]], grid.drop(index=bi)]).reset_index(drop=True)
crows = [summarise("BASELINE", base_o)]
for name, cfg in cost_variants:
    o = run(panel, avail, cfg, shortable)
    o["daily"] = o["daily"].loc[EVAL_START:]
    res[name] = o
    crows.append(summarise(name, o))
cgrid = pd.DataFrame(crows)
# benchmarks (not trials)
bench = []
lo = run(panel, avail, replace(BASE, long_only_benchmark=True), shortable)
lo["daily"] = lo["daily"].loc[EVAL_START:]
res["long_only_volscaled"] = lo
bench.append(summarise("long-only vol-scaled (same sizing, signal=+1)", lo))
sp = perf(spy_x.loc[base_o["daily"].index])
bench.append(
    {
        "variant": "SPY excess TR (buy&hold)",
        "start": sp["start"],
        "years": round(sp["years"], 2),
        "net_ret": sp["ann_ret"],
        "net_vol": sp["ann_vol"],
        "net_sharpe": sp["sharpe"],
        "net_maxdd": sp["max_dd"],
    }
)
bgrid = pd.DataFrame(bench)

# ---- multiple testing: DSR of baseline against all signal/sizing trials ----
sr_trials = list(grid["net_sharpe"].values)
dsr = deflated_sharpe(grid.iloc[0]["net_sharpe"], base_o["daily"].net, sr_trials)
dsr_g = deflated_sharpe(grid.iloc[0]["gross_sharpe"], base_o["daily"].gross, list(grid["gross_sharpe"].values))
se = sharpe_se(grid.iloc[0]["net_sharpe"], base_o["daily"].net)

# ---- per-asset contributions (baseline) ----
y = len(base_o["daily"]) / 252
pa = pd.DataFrame(
    {
        "class": pd.Series({s: ASSET_CLASS[s] for s in base_o["symbols"]}),
        "liq_bucket(cost model)": pd.Series(base_o["buckets"]),
        "avg_abs_weight": base_o["weights"].abs().mean(),
        "gross_contrib": base_o["contrib"].sum() / y,
        "cost_contrib": base_o["cost_by_asset"].sum() / y,
        "turnover_x": base_o["turn_by_asset"].sum() / y,
        "net_sharpe_standalone_proxy": (base_o["contrib"].sum() / y - base_o["cost_by_asset"].sum() / y)
        / (base_o["contrib"].std() * np.sqrt(252)),
        "shortable_ETB_today": pd.Series({s: shortable.get(s, False) for s in base_o["symbols"]}),
    }
)
pa["net_contrib_ex_borrow"] = pa.gross_contrib - pa.cost_contrib
pa = pa.sort_values("gross_contrib", ascending=False).reset_index().rename(columns={"index": "asset"})
by_cls = (
    pa.groupby("class")[["gross_contrib", "cost_contrib", "net_contrib_ex_borrow", "turnover_x"]].sum().reset_index()
)


# ---- subperiods ----
def sub(o: dict[str, Any], label: str) -> list[dict[str, Any]]:
    d = o["daily"]
    out = []
    for a, b_ in [("2017-01-01", "2019-12-31"), ("2020-01-01", "2022-12-31"), ("2023-01-01", "2026-12-31")]:
        x = d.loc[a:b_]
        g, n = perf(x.gross), perf(x.net)
        out.append(
            {
                "variant": label,
                "period": f"{a[:4]}-{b_[:4] if b_[:4] != '2026' else '2026YTD'}",
                "gross_ret": g["ann_ret"],
                "gross_sharpe": g["sharpe"],
                "net_ret": n["ann_ret"],
                "net_sharpe": n["sharpe"],
                "net_maxdd": n["max_dd"],
                "corr_spy_d": corr_to(x.net, spy_x)["corr_daily"],
            }
        )
    return out


subp = pd.DataFrame(
    sub(base_o, "BASELINE")
    + sub(res["implementable(cap2x+shortable)"], "implementable")
    + sub(res["lb1-3-12_M"], "blend 1/3/12 M")
    + sub(res["venue_close(MOC)"], "baseline, MOC venue")
)
cal = base_o["daily"][["gross", "net"]].groupby(base_o["daily"].index.year).apply(lambda x: (1 + x).prod() - 1)
spy_cal = spy_x.loc[base_o["daily"].index].groupby(base_o["daily"].index.year).apply(lambda x: (1 + x).prod() - 1)
cal["SPY_excess"] = spy_cal
cal = cal.reset_index().rename(columns={"index": "year"})
cal.columns = ["year", "gross", "net", "SPY_excess"]

# crisis behaviour: sleeve in SPY's worst decile months
m = pd.concat([monthly(base_o["daily"].net), monthly(spy_x.loc[base_o["daily"].index])], axis=1).dropna()
m.columns = ["sleeve", "spy"]
worst = m[m.spy <= m.spy.quantile(0.1)]
crisis = {
    "n_months": int(len(worst)),
    "spy_avg": worst.spy.mean(),
    "sleeve_avg_net": worst.sleeve.mean(),
    "sleeve_hit": float((worst.sleeve > 0).mean()),
}

# positions now
last = base_o["weights"].iloc[-1]
cur = pd.DataFrame({"asset": last.index, "weight": last.values}).sort_values("weight")

# ---- write ----
grid.to_csv(f"{OUT}/grid.csv", index=False)
cgrid.to_csv(f"{OUT}/cost_variants.csv", index=False)
bgrid.to_csv(f"{OUT}/benchmarks.csv", index=False)
pa.to_csv(f"{OUT}/per_asset_baseline.csv", index=False)
subp.to_csv(f"{OUT}/subperiods.csv", index=False)
cal.to_csv(f"{OUT}/calendar_years_baseline.csv", index=False)
base_o["daily"].to_csv(f"{OUT}/baseline_daily.csv")
base_o["weights"].to_csv(f"{OUT}/baseline_weights.csv")
res["implementable(cap2x+shortable)"]["daily"].to_csv(f"{OUT}/implementable_daily.csv")
meta = {
    "run_at_sgt": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "sources": panel["sources"],
    "rf_source": "Ken French ff3_daily RF",
    "rf_last_date": panel["rf_last"],
    "symbols_used_card": avail,
    "missing_from_card": [s for s in CARD_UNIVERSE if s not in avail],
    "data_first": str(panel["px"].index[0].date()),
    "data_last": str(panel["px"].index[-1].date()),
    "dsr_net": dsr,
    "dsr_gross": dsr_g,
    "sharpe_se_net": se,
    "crisis": crisis,
    "crypto": "excluded by desk decision 2026-10-30",
    "baseline_cfg": base_o["cfg"],
    "n_trials": len(grid),
}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=2, default=float)
with open(f"{OUT}/tables.md", "w") as fh:
    fh.write("## Grid (net = after TCA owner cost model + 25bps borrow; ETFs only, crypto excluded)\n\n")
    fh.write(fmt(grid, PCT, F2, F1) + "\n\n## Cost variants on baseline\n\n" + fmt(cgrid, PCT, F2, F1))
    fh.write("\n\n## Benchmarks\n\n" + fmt(bgrid, PCT, F2, F1))
    fh.write(
        "\n\n## Per-asset (baseline, annualised)\n\n"
        + fmt(pa, ("gross_contrib", "cost_contrib", "net_contrib_ex_borrow"), ("avg_abs_weight",), ("turnover_x",))
    )
    fh.write(
        "\n\n## By asset class\n\n"
        + fmt(by_cls, ("gross_contrib", "cost_contrib", "net_contrib_ex_borrow"), (), ("turnover_x",))
    )
    fh.write(
        "\n\n## Subperiods\n\n"
        + fmt(subp, ("gross_ret", "net_ret", "net_maxdd"), ("gross_sharpe", "net_sharpe", "corr_spy_d"))
    )
    fh.write("\n\n## Calendar years (baseline)\n\n" + fmt(cal, ("gross", "net", "SPY_excess")))
    fh.write("\n\n## Current baseline weights (last session)\n\n" + fmt(cur, (), ("weight",)))
    fh.write(
        "\n\n## Meta\n\n```json\n"
        + json.dumps(
            {k: meta[k] for k in ["dsr_net", "dsr_gross", "sharpe_se_net", "crisis", "n_trials", "rf_last_date"]},
            indent=2,
            default=float,
        )
        + "\n```\n"
    )
print(open(f"{OUT}/tables.md").read())
