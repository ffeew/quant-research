"""PREREG-v2 run: exactly V1-V5 + pre-listed non-trial sensitivities/stability/benchmarks. Writes outputs_v2/ only.
Usage: .venv/bin/python run_v2.py      (v1 outputs/ untouched)"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import itertools
import json
import math
import operator
import os
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from quant_research.strategies.trend_tsmom.tsmom import v2spec as S
from quant_research.strategies.trend_tsmom.tsmom.data import ASSET_CLASS, EXT_EXTRA, build_panel, load_shortable
from quant_research.strategies.trend_tsmom.tsmom.engine import Config, run
from quant_research.strategies.trend_tsmom.tsmom.stats import corr_to, monthly, perf, sharpe_se
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import require_pins

# recorded in meta.json only, so refuse up front on a PENDING / missing pin (before any work)
PINS = require_pins(
    "strategies.trend_tsmom.run_v2", "meta.data_build.prereg_tr_sha256", "meta.cost_model.prereg_sha256"
)

OUT = "outputs_v2"
os.makedirs(OUT, exist_ok=True)
ANN = 252


def sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


# ---------- data ----------
V1_CARD = json.load(open("outputs/meta.json"))["symbols_used_card"]  # v1's 23 ETFs (fixed list)
V1_SRC = json.load(open("outputs/meta.json"))["sources"]
V1_EXT = [s for s in V1_CARD + EXT_EXTRA if V1_SRC.get(s, "MISSING") != "MISSING"]
ALL = sorted(set(V1_EXT + S.BROAD_EXFX + S.CORE_L12_UUP))
panel = build_panel(ALL)
shortable = load_shortable()
P = panel["px"]
spy_x = P["SPY"].pct_change(fill_method=None) - panel["rf"]
E0, E1_ = S.EVAL_START, S.EVAL_END
cut: Callable[[pd.DataFrame | pd.Series], Any] = lambda d: d.loc[E0:E1_]

# ---------- v1 trials re-run on current build (for DSR/PBO matrix) ----------
B = Config()
v1_trials = []
for lb in [(1,), (3,), (6,), (12,), (1, 3, 12)]:
    for rb in ["M", "W"]:
        v1_trials.append((f"v1:lb{'-'.join(map(str, lb))}_{rb}", V1_CARD, replace(B, lookbacks=lb, rebalance=rb)))
v1_trials += [
    ("v1:mop_40pct_unscaled", V1_CARD, replace(B, sizing="mop")),
    ("v1:class_balanced", V1_CARD, replace(B, class_balanced=True)),
    ("v1:gross_cap_2x", V1_CARD, replace(B, gross_cap=2.0)),
    ("v1:honour_shortable", V1_CARD, replace(B, honour_shortable=True)),
    ("v1:implementable(cap2x+shortable)", V1_CARD, replace(B, gross_cap=2.0, honour_shortable=True)),
    ("v1:implementable_blend_M", V1_CARD, replace(B, gross_cap=2.0, honour_shortable=True, lookbacks=(1, 3, 12))),
    ("v1:vol_com20", V1_CARD, replace(B, vol_com=20)),
    ("v1:lag0(same-close fill)", V1_CARD, replace(B, lag=0)),
    ("v1:extended_universe", V1_EXT, B),
]
assert len(v1_trials) == 19


def summarise(name: str, o: dict[str, Any]) -> dict[str, Any]:
    d = cut(o["daily"])
    y = len(d) / ANN
    g, n = perf(d.gross), perf(d.net)
    c = corr_to(d.net, spy_x)
    gross_ann = g["ann_ret"]
    cost_ann = (d.cost.sum() + d.borrow.sum()) / y
    turn = d.turnover.sum() / y
    be = gross_ann / turn * 1e4 if turn > 0 else np.nan
    avg_bps = d.cost.sum() / d.turnover.sum() * 1e4 if d.turnover.sum() > 0 else np.nan
    net2 = gross_ann - 2 * cost_ann
    flag = "FAIL" if n["ann_ret"] <= 0 else "WARN" if (net2 <= 0 or cost_ann > 0.5 * gross_ann) else "PASS"
    hold_m = 2 * d.gross_lev.mean() / turn * 12 if turn > 0 else np.nan
    return {
        "variant": name,
        "start": n["start"],
        "end": n["end"],
        "years": y,
        "gross_ret": gross_ann,
        "gross_vol": g["ann_vol"],
        "gross_sharpe": g["sharpe"],
        "net_ret": n["ann_ret"],
        "net_vol": n["ann_vol"],
        "net_sharpe": n["sharpe"],
        "net_t": n["t_stat"],
        "net_sharpe_se": sharpe_se(n["sharpe"], d.net),
        "net_cagr": n["cagr"],
        "net_maxdd": n["max_dd"],
        "skew_m": n["skew_m"],
        "cost_drag": cost_ann,
        "trading_cost": d.cost.sum() / y,
        "borrow": d.borrow.sum() / y,
        "net_at_2x_cost": net2,
        "turnover_x": turn,
        "avg_cost_bps_1way": avg_bps,
        "breakeven_bps_1way": be,
        "avg_hold_months": hold_m,
        "avg_gross_lev": d.gross_lev.mean(),
        "max_gross_lev": d.gross_lev.max(),
        "avg_net_lev": d.net_lev.mean(),
        "corr_spy_d": c["corr_daily"],
        "corr_spy_m": c["corr_monthly"],
        "n_cap_trims": o.get("n_cap_trims", 0),
        "n_band_holds": o.get("n_band_holds", 0),
        "costs_flag": flag,
    }


R = {}
rows_trials = []
for name, uni, cfg in v1_trials:
    o = run(panel, uni, cfg, shortable)
    R[name] = o
    rows_trials.append(summarise(name, o) | {"family": "v1", "cfg": json.dumps(asdict(cfg)), "universe": " ".join(uni)})
for vid, uni, cfg in S.VARIANTS:
    o = run(panel, uni, cfg, shortable)
    R[vid] = o
    rows_trials.append(summarise(vid, o) | {"family": "v2", "cfg": json.dumps(asdict(cfg)), "universe": " ".join(uni)})
trials = pd.DataFrame(rows_trials)
assert len(trials) == 24
v1o = R["V1_PRIMARY"]
v1d = cut(v1o["daily"])

# ---------- T x N return matrices ----------
idx = cut(P).index
RN = pd.DataFrame({k: cut(R[k]["daily"]).net.reindex(idx) for k in trials.variant}).fillna(0.0)
RG = pd.DataFrame({k: cut(R[k]["daily"]).gross.reindex(idx) for k in trials.variant}).fillna(0.0)


# ---------- DSR ----------
def dsr(sr_ann: float, r: pd.Series, sr_trials: list[float], N: int) -> dict[str, Any]:
    r = r.dropna()
    n = len(r)
    v = np.var(np.array(sr_trials) / math.sqrt(ANN), ddof=1)
    em = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - em) * norm.ppf(1 - 1 / N) + em * norm.ppf(1 - 1 / (N * math.e)))
    s = sr_ann / math.sqrt(ANN)
    g3 = skew(r)
    g4 = kurtosis(r, fisher=False)
    den = math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s)
    return {
        "N": N,
        "sr0_ann": sr0 * math.sqrt(ANN),
        "dsr": norm.cdf((s - sr0) * math.sqrt(n - 1) / den),
        "T": n,
        "skew_d": g3,
        "kurt_d": g4,
        "psr_vs0": norm.cdf(s * math.sqrt(n - 1) / den),
    }


v1row = trials.set_index("variant").loc["V1_PRIMARY"]
dsr_rows = []
for disp, col in [("gross-dispersion", "gross_sharpe"), ("all-net-dispersion", "net_sharpe")]:
    for N in (24, 30, 50):
        dsr_rows.append(
            {"version": disp, "sd_trial_sr_ann": trials[col].std(ddof=1)}
            | dsr(cast(float, v1row.net_sharpe), v1d.net, cast(list[float], list(trials[col])), N)
        )
dsr_t = pd.DataFrame(dsr_rows)
gate_dsr = dsr_t.query("version=='gross-dispersion' and N==24").dsr.iloc[0]


# ---------- PBO via CSCV (S=16) ----------
def pbo_cscv(M: pd.DataFrame, S_: int = 16) -> dict[str, Any]:
    T = len(M) - len(M) % S_
    X = cast(np.ndarray, M.iloc[:T].values)
    blocks = np.array_split(np.arange(T), S_)

    def sr(a: np.ndarray) -> np.ndarray:
        sd = a.std(0, ddof=1)
        return np.where(sd > 0, a.mean(0) / sd, -np.inf)

    logits: list[float] = []
    n = X.shape[1]
    for comb in itertools.combinations(range(S_), S_ // 2):
        isx = np.concatenate([blocks[i] for i in comb])
        oos = np.concatenate([blocks[i] for i in range(S_) if i not in comb])
        best = int(np.argmax(sr(X[isx])))
        so = sr(X[oos])
        rank = (so < so[best]).sum() + 0.5 * ((so == so[best]).sum() - 1) + 1  # 1..n
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
    lam = np.array(logits)
    return {
        "S": S_,
        "n_combinations": len(lam),
        "n_trials": n,
        "T": T,
        "pbo": float((lam <= 0).mean()),
        "median_logit": float(np.median(lam)),
    }


pbo_net = pbo_cscv(RN)
pbo_gross = pbo_cscv(RG)

# ---------- sensitivities, stability, benchmarks ----------
sens_rows: list[dict[str, Any]] = [summarise("V1_PRIMARY (base)", v1o)]
for nm, cfg in S.SENSITIVITIES:
    o = run(panel, S.CORE_L12, cfg, shortable)
    sens_rows.append(summarise(nm, o))
sens = pd.DataFrame(sens_rows)
stab_rows: list[dict[str, Any]] = []
for nm, cfg in S.STABILITY:
    o = run(panel, S.CORE_L12, cfg, shortable)
    s_ = summarise(nm, o)
    s_["pass(>0 and >=50% of V1)"] = bool(s_["net_sharpe"] > 0 and s_["net_sharpe"] >= 0.5 * v1row.net_sharpe)
    stab_rows.append(s_)
stab = pd.DataFrame(stab_rows)
lo = run(panel, S.CORE_L12, replace(S.V1, name="longonly_bench", long_only_benchmark=True), shortable)
bench_rows: list[dict[str, Any]] = [summarise("long-only CORE-L12 (same sizing/cap/band, signal=+1)", lo)]
sp = perf(spy_x.loc[v1d.index])
bench_rows.append(
    {
        "variant": "SPY excess TR",
        "net_ret": sp["ann_ret"],
        "net_vol": sp["ann_vol"],
        "net_sharpe": sp["sharpe"],
        "net_maxdd": sp["max_dd"],
        "start": sp["start"],
    }
)
bench = pd.DataFrame(bench_rows)


# ---------- V1 diagnostics ----------
def subp(name: str, d: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for a, b_, lab in [
        ("2017-01-01", "2019-12-31", "2017-19"),
        ("2020-01-01", "2022-12-31", "2020-22"),
        ("2023-01-01", "2026-12-31", "2023-26YTD"),
    ]:
        x = d.loc[a:b_]
        g, n = perf(x.gross), perf(x.net)
        out.append(
            {
                "variant": name,
                "period": lab,
                "gross_ret": g["ann_ret"],
                "net_ret": n["ann_ret"],
                "net_sharpe": n["sharpe"],
                "net_maxdd": n["max_dd"],
                "net_cum": cast(float, (1 + x.net).prod()) - 1,
            }
        )
    return out


sub = pd.DataFrame(functools.reduce(operator.iadd, [subp(k, cut(R[k]["daily"])) for k, _, _ in S.VARIANTS], []))
ex22 = v1d.net[v1d.index.year != 2022]
ex22_sr = ex22.mean() / ex22.std() * math.sqrt(ANN)
cal = v1d[["gross", "net"]].groupby(v1d.index.year).agg(["sum", lambda x: (1 + x).prod() - 1])
cal.columns = ["gross_sum", "gross_compound", "net_sum", "net_compound"]
cal["SPY_excess"] = spy_x.loc[v1d.index].groupby(v1d.index.year).apply(lambda x: (1 + x).prod() - 1)
cal["share_of_total_net_pnl"] = cal.net_sum / v1d.net.sum()
largest_year_share = cal.share_of_total_net_pnl.max()
# SPY 200dma regime (known at t-1)
spy_px = P["SPY"]
above = (spy_px > spy_px.rolling(200).mean()).shift(1).reindex(v1d.index)
reg_rows: list[dict[str, Any]] = []
for lab, mask in [("SPY above 200dma", above == True), ("SPY below 200dma", above == False)]:
    x = v1d[mask.values]
    n = perf(x.net)
    g = perf(x.gross)
    reg_rows.append(
        {
            "regime": lab,
            "days": len(x),
            "frac": len(x) / len(v1d),
            "gross_ret": g["ann_ret"],
            "net_ret": n["ann_ret"],
            "net_vol": n["ann_vol"],
            "net_sharpe": n["sharpe"],
            "spy_excess_ret": spy_x.loc[x.index].mean() * ANN,
        }
    )
reg = pd.DataFrame(reg_rows)
# long vs short legs (weight held over the day = previous close weight)
Wp = v1o["weights"].shift(1)
C_ = v1o["contrib"]
legs = pd.DataFrame({"long": cut(C_.where(Wp > 0, 0.0).sum(1)), "short": cut(C_.where(Wp < 0, 0.0).sum(1))})
legs_t = pd.DataFrame(
    [
        {
            "leg": k,
            "gross_ann_contrib": legs[k].mean() * ANN,
            "vol": legs[k].std() * math.sqrt(ANN),
            "sharpe": legs[k].mean() / legs[k].std() * math.sqrt(ANN) if legs[k].std() > 0 else np.nan,
            "avg_exposure": (
                cut(v1o["weights"]).clip(lower=0).sum(1) if k == "long" else -cut(v1o["weights"]).clip(upper=0).sum(1)
            ).mean(),
        }
        for k in legs
    ]
)
legs_t.loc[legs_t.leg == "short", "borrow_ann"] = v1d.borrow.mean() * ANN
# per asset
y = len(v1d) / ANN
pa = pd.DataFrame(
    {
        "class": pd.Series({s: ASSET_CLASS[s] for s in v1o["symbols"]}),
        "bucket": pd.Series(v1o["buckets"]),
        "shortable_ETB_today": pd.Series({s: shortable.get(s, False) for s in v1o["symbols"]}),
        "avg_abs_w": cut(v1o["weights"]).abs().mean(),
        "avg_w": cut(v1o["weights"]).mean(),
        "gross_contrib": cut(v1o["contrib"]).sum() / y,
        "cost_contrib": cut(v1o["cost_by_asset"]).sum() / y,
        "turnover_x": cut(v1o["turn_by_asset"]).sum() / y,
    }
)
pa["net_ex_borrow"] = pa.gross_contrib - pa.cost_contrib
pa = pa.sort_values("net_ex_borrow", ascending=False)
# capacity: trade notional / 20d ADV$ (lagged)
adv_usd = (panel["close_raw"] * panel["volume_raw"]).rolling(20, min_periods=10).mean().shift(1)
trd = v1o["trades"].copy()
trd = trd[(trd.fill_date >= E0) & (trd.fill_date <= E1_)]
trd["pct_adv20"] = [n_ / adv_usd.at[d_, s_] * 100 for d_, s_, n_ in zip(trd.fill_date, trd.symbol, trd.notional_usd)]
crisis_m = pd.concat([monthly(v1d.net), monthly(spy_x.loc[v1d.index])], axis=1).dropna()
crisis_m.columns = ["v1", "spy"]
worst = crisis_m[crisis_m.spy <= crisis_m.spy.quantile(0.1)]


# ---------- Stage A ----------
def subpos(d: pd.DataFrame) -> int:
    return sum(
        cast(float, (1 + d.loc[a:b].net).prod()) - 1 > 0
        for a, b in [("2017", "2019"), ("2020", "2022"), ("2023", "2026")]
    )


nonshort = [s for s in v1o["symbols"] if not shortable.get(s, False)]
mech = bool(cut(v1o["daily"]).gross_lev.max() <= 1.0 + 1e-9 and (v1o["weights"][nonshort] >= -1e-12).all().all())
crit = [
    ("1 net Sharpe >= 0.40", f"{v1row.net_sharpe:.3f}", v1row.net_sharpe >= 0.40),
    (
        "2 TCA owner flag = PASS (net>0 at 2x costs AND cost <= 50% gross)",
        f"{v1row.costs_flag} (net@2x {v1row.net_at_2x_cost * 100:.2f}%, cost/gross {v1row.cost_drag / v1row.gross_ret * 100 if v1row.gross_ret > 0 else float('nan'):.0f}%)",
        v1row.costs_flag == "PASS",
    ),
    ("3 net max DD >= -15%", f"{v1row.net_maxdd * 100:.1f}%", v1row.net_maxdd >= -0.15),
    ("4a net Sharpe ex-2022 > 0", f"{ex22_sr:.3f}", ex22_sr > 0),
    ("4b net return > 0 in >= 2 of 3 subperiods", f"{subpos(v1d)}/3", subpos(v1d) >= 2),
    ("5 DSR (gross-dispersion, N=24) >= 0.50", f"{gate_dsr:.3f}", gate_dsr >= 0.50),
    ("6 mechanical: gross<=1.00 always, no short in non-shortable", str(mech), mech),
]
stage = pd.DataFrame(crit, columns=["criterion", "value", "met"])
verdict = (
    "ELIGIBLE FOR STAGE B VALIDATION (screen cleared; NOT a pass; nothing trades)"
    if stage.met.all()
    else "FAIL (Stage A screen not cleared; v2 sleeve fails per PREREG-v2 §5; no rescue by secondary variants)"
)

# ---------- write ----------
trials.to_csv(f"{OUT}/trial_log_24.csv", index=False)
RN.to_csv(f"{OUT}/returns_matrix_net_Tx24.csv")
RG.to_csv(f"{OUT}/returns_matrix_gross_Tx24.csv")
v2t = trials[trials.family == "v2"].drop(columns=["cfg"])
v2t.to_csv(f"{OUT}/variants_v2.csv", index=False)
sens.to_csv(f"{OUT}/sensitivities_v1.csv", index=False)
stab.to_csv(f"{OUT}/stability_v1.csv", index=False)
bench.to_csv(f"{OUT}/benchmarks.csv", index=False)
dsr_t.to_csv(f"{OUT}/dsr_table.csv", index=False)
sub.to_csv(f"{OUT}/subperiods_v2.csv", index=False)
cal.to_csv(f"{OUT}/calendar_years_v1.csv")
reg.to_csv(f"{OUT}/regime_spy200_v1.csv", index=False)
legs_t.to_csv(f"{OUT}/legs_v1.csv", index=False)
pa.to_csv(f"{OUT}/per_asset_v1.csv")
trd.to_csv(f"{OUT}/trades_v1.csv", index=False)
v1d.to_csv(f"{OUT}/v1_daily.csv")
cut(v1o["weights"]).to_csv(f"{OUT}/v1_weights.csv")
pd.DataFrame({"equity_net": (1 + v1d.net).cumprod(), "equity_gross": (1 + v1d.gross).cumprod()}).to_csv(
    f"{OUT}/v1_equity_curve.csv"
)
stage.to_csv(f"{OUT}/stage_a_v1.csv", index=False)
json.dump({"net": pbo_net, "gross": pbo_gross}, open(f"{OUT}/pbo_cscv.json", "w"), indent=2)
code_files = [
    "run_v2.py",
    "tsmom/engine.py",
    "tsmom/data.py",
    "tsmom/stats.py",
    "tsmom/v2spec.py",
    "tests/test_v2_engine.py",
]
meta = {
    "run_at_sgt": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "prereg": {"file": "PREREG-v2.md", "sha256": sha("PREREG-v2.md")},
    "data_build": {
        "total_return": {
            "path": f"{_QR.DATA_DIR}/bars/daily/total_return/daily_total_return.parquet",
            "sha256": sha(f"{_QR.DATA_DIR}/bars/daily/total_return/daily_total_return.parquet"),
        },
        "assets_snapshot": {
            "path": f"{_QR.DATA_DIR}/assets/snapshots/assets_2026-10-29.parquet",
            "sha256": sha(f"{_QR.DATA_DIR}/assets/snapshots/assets_2026-10-29.parquet"),
        },
        "rf": {
            "path": f"{_QR.DATA_DIR}/factors/ken_french/ff3_daily.parquet",
            "sha256": sha(f"{_QR.DATA_DIR}/factors/ken_french/ff3_daily.parquet"),
            "rf_last_date": panel["rf_last"],
        },
        "prereg_tr_sha256": PINS["meta.data_build.prereg_tr_sha256"],
    },
    "cost_model": {
        "name": "TCA owner v1.1",
        "path": f"{_QR.COSTS_DIR}/cost_model.py",
        "sha256": sha(f"{_QR.COSTS_DIR}/cost_model.py"),
        "prereg_sha256": PINS["meta.cost_model.prereg_sha256"],
    },
    "code_version": {
        "vcs": "none (not a git repo); per-file sha256",
        "files": {f: sha(f) for f in code_files},
        "combined_sha256": hashlib.sha256("".join(sha(f) for f in code_files).encode()).hexdigest(),
    },
    "eval_window": [str(v1d.index[0].date()), str(v1d.index[-1].date())],
    "sources": {s: panel["sources"][s] for s in ALL},
    "n_trials_total": 24,
    "v1_trials_rerun_on_current_build": True,
    "stage_b_extended_file_read": False,
    "shortability": "today's flags (2026-10-29) applied to full history: LOOK-AHEAD limitation",
    "stage_a_verdict": verdict,
    "dsr_gate": gate_dsr,
    "pbo": {"net": pbo_net, "gross": pbo_gross},
    "v1_capacity_max_pct_adv20": float(trd.pct_adv20.max()),
    "largest_year_share_of_net_pnl": float(largest_year_share),
    "net_sharpe_ex2022": ex22_sr,
    "crisis_worst_decile_spy_months": {"n": int(len(worst)), "spy_avg": worst.spy.mean(), "v1_avg": worst.v1.mean()},
    "unit_checks": "tests/unit_checks_output.txt",
}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=2, default=float)
print("Stage A:", verdict)
print(stage.to_string(index=False))
