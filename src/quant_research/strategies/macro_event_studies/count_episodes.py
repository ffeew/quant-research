"""Curve episode gate, Victor follow-up ruling (2026-10-30 ~02:06 SGT).
SIGNAL INPUTS ONLY: DGS2/DGS10 (+ the USO session calendar from the store, used only for its NYSE session dates). No ETF prices or returns.
Merge rule (ruling (1)): an exit to neutral followed by a SAME-direction re-entry within 4 weeks (<= 28 calendar days between the last active
weekly evaluation and the re-entry evaluation) counts as ONE episode. Opposite-direction flips are never merged.
v1.1 = the frozen threshold rule (+/-25bp in, back inside the band out). v1.2 = hysteresis: enter |dS| >= 25bp; exit to flat only when dS <= +10bp
(long-steepener state) / >= -10bp (flattener state); dS past the opposite 25bp reverses directly.
INPUT: current FRED values (NOT ALFRED vintages) unless inputs/alfred_* exist -> PROVISIONAL.
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import pandas as pd, numpy as np, json
A0, A1 = pd.Timestamp("2016-07-01"), pd.Timestamp("2026-10-28")
LB = (pd.Timestamp("2016-06-30") - pd.Timestamp("2005-07-01")).days / 365.25
cal = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_parquet(f"{_QR.DATA_DIR}/bars/daily/adjusted", columns=["symbol","session_date"],
      filters=[("symbol","==","USO")]).session_date)))
g = {s: pd.to_numeric(pd.read_csv(f"inputs/{s.lower()}.csv", parse_dates=["observation_date"]).set_index("observation_date")[s], errors="coerce") for s in ["DGS2","DGS10"]}
yc = (g["DGS10"] - g["DGS2"]).dropna(); yc = yc[yc.index >= "2016-01-01"]
S = yc.reindex(cal).ffill().shift(1); dS = (S - S.shift(63)).dropna()
wk = pd.DatetimeIndex(pd.Series(cal, index=cal).groupby(cal.to_period("W-FRI")).max().values)
dS = dS[dS.index.isin(wk)]; dS = dS[(dS.index >= A0) & (dS.index <= A1)]

def v11(x): return pd.Series(np.where(x >= .25, 1, np.where(x <= -.25, -1, 0)), index=x.index)
def v12(x):
    st, out = 0, []
    for v in x.values:
        if st == 0: st = 1 if v >= .25 else (-1 if v <= -.25 else 0)
        elif st == 1: st = -1 if v <= -.25 else (0 if v <= .10 else 1)
        else: st = 1 if v >= .25 else (0 if v >= -.10 else -1)
        out.append(st)
    return pd.Series(out, index=x.index)

def raw_eps(s):
    eps, cur, start, prev = [], 0, None, None
    for d, v in s.items():
        if v != cur:
            if cur != 0: eps.append([start, prev, cur])
            cur, start = v, d
        prev = d
    if cur != 0: eps.append([start, prev, cur])
    return eps
def merge(eps):
    m = []
    for e in eps:
        if m and m[-1][2] == e[2] and (e[0] - m[-1][1]).days <= 28: m[-1][1] = e[1]
        else: m.append(list(e))
    return m
res = {}
for name, f in [("v1.1", v11), ("v1.2", v12)]:
    s = f(dS); r = raw_eps(s); m = merge(r)
    df = pd.DataFrame(m, columns=["start","last_eval","dir"]); df.to_csv(f"curve_{name}_episodes_merged.csv", index=False)
    dur = ((df.last_eval - df.start).dt.days // 7 + 1)
    by = df.groupby(df.start.dt.year).size().reindex(range(2016, 2027), fill_value=0)
    yrs = (A1 - A0).days / 365.25; rate = len(m) / yrs
    res[name] = dict(raw_episodes=len(r), merged_episodes=len(m), steep=int((df.dir==1).sum()), flat=int((df.dir==-1).sum()),
        one_week_after_merge=int((dur==1).sum()), median_weeks=float(dur.median()), active_weeks=int((s!=0).sum()), weekly_evals=int(len(s)),
        by_start_year={int(k): int(v) for k, v in by.items()}, rate_per_year=round(rate,3), stageA_years=round(yrs,2), stageB_years=round(LB,2),
        projected_stageB=round(rate*LB,1), gate="PASS (>=30)" if rate*LB >= 30 else "DO NOT UNSEAL (<30)",
        input="PROVISIONAL: current FRED DGS2/DGS10 (fredgraph.csv pulled 2026-10-30 ~01:59 SGT), NOT ALFRED vintages")
json.dump(res, open("gate_results_curve_v12.json","w"), indent=1); print(json.dumps(res, indent=1))
