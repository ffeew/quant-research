"""Extra diagnostics from run_all.py outputs + core data: SPY correlation, per-position beta, U117 decomposition of R1,
missing-bar breakdown. Writes extra_diagnostics.json and tables_main.md."""

from __future__ import annotations

import json
import sys
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

sys.path.insert(0, ".")
from quant_research.strategies.pead_gap.pit.core import (
    MEMB,
    OOS0,
    SPLIT,
    SPYRET,
    SYMS,
    Ca,
    cal,
    col,
)

S = pd.read_csv("summary.csv")
M = pd.read_csv("daily_pnl_matrix_all_trials.csv", index_col=0, parse_dates=True)
cap = pd.read_csv("costs_capacity.csv").set_index("variant")
T = pd.read_csv("trades_main.csv", parse_dates=["sig"])
out: dict[str, Any] = {}
names = {
    "R1_PIT_all": "R1_PIT_all|gap0.04|vr1.8|atr2.0",
    "R2_PIT_earn": "R2_PIT_earn|gap0.04|vr1.8|atr2.0",
    "R3_PIT_nonearn": "R3_PIT_nonearn|gap0.04|vr1.8|atr2.0",
    "R5_U117": "R5_U117|gap0.04|vr1.8|atr2.0",
}
for r, c in names.items():
    p = M[c]
    for per, sl in (("IS", slice(None, SPLIT)), ("OOS", slice(OOS0, None))):
        x = SPYRET.reindex(p.loc[sl].index)
        out[f"corr_spy|{r}|{per}"] = round(
            float(np.corrcoef(cast(np.ndarray, p.loc[sl].values), cast(np.ndarray, x.fillna(0).values))[0, 1]), 3
        )
    b = S[(S.variant == r) & (S.period == "OOS") & (S.costs == "1x")].beta_spy.iloc[0]
    out[f"beta_per_avg_concurrent_position|{r}|OOS"] = round(float(b / cap.loc[r, "avg_concurrent"]), 3)
# R1 decomposition: trades in the 117 names vs the rest (diagnostic, not a candidate rule)
PRIOR = json.load(open(f"{_QR.DESK_DIR}/validation/backtests/data/bars_sip.json"))["U"]
U117 = {"MRSH" if s == "MMC" else s for s in PRIOR}
r1 = T[T.variant == "R1_PIT_all"]
for lab, sub in (("in_U117", r1[r1.sym.isin(U117)]), ("not_in_U117", r1[~r1.sym.isin(U117)])):
    for per, m in (("IS", sub.sig <= SPLIT), ("OOS", sub.sig >= OOS0)):
        s = sub[m]
        out[f"R1_decomp|{lab}|{per}"] = dict(
            n=len(s), exp_R_1x=round(float(s.R_1x.mean()), 4), hit=round(float((s.R_1x > 0).mean()), 3)
        )
# missing bars while a PIT member: before first bar vs after last bar
mb = MEMB.values
hb = ~np.isnan(Ca)
first = {s: int(np.argmax(hb[:, col[s]])) for s in SYMS}
pre: dict[str, dict[str, int | str]] = {}
post: dict[str, int] = {}
for s in SYMS:
    j = col[s]
    miss = np.where(mb[:, j] & ~hb[:, j])[0]
    if len(miss) == 0:
        continue
    a = int((miss < first[s]).sum())
    b_ = len(miss) - a
    if a:
        pre[s] = dict(days=a, first_bar=str(cal[first[s]].date()))
    if b_:
        post[s] = b_
out["member_days_missing_before_first_bar"] = pre
out["member_days_missing_after_last_bar_total"] = int(sum(post.values()))
out["n_symbols_after_last_bar"] = len(post)
json.dump(out, open("extra_diagnostics.json", "w"), indent=1)
# main markdown table
rows: list[str] = []
labels = {
    "R1_PIT_all": "1 Prior rule, PIT S&P 500",
    "R2_PIT_earn": "2 Earnings-gap only",
    "R3_PIT_nonearn": "3 Non-earnings gap",
    "BENCH_all_eligible_5d_PIT": "4 Benchmark: all >50/200dma, PIT, every 5th day",
    "R5_U117": "5 Old 117-name universe",
}
for v, L_ in labels.items():
    for per in ("IS", "OOS"):
        row_1x = S[(S.variant == v) & (S.period == per) & (S.costs == "1x")].iloc[0]
        row_2x = S[(S.variant == v) & (S.period == per) & (S.costs == "2x")].iloc[0]
        rows.append(
            f"| {L_} | {per} | {row_1x.n} | {row_1x.hit:.3f} | {row_1x.exp_R:+.3f} | {row_1x.sharpe:.2f} | {row_2x.sharpe:.2f} | {row_1x.maxDD_R} | {row_1x.beta_spy} | {row_1x.ff_alpha_t} |"
        )
hdr = "| Run | Period | Trades | Hit | Exp R (1x) | Sharpe 1x | Sharpe 2x | MaxDD R (1x) | Beta (R per 1% SPY) | FF4 alpha t (NW) |\n|---|---|---|---|---|---|---|---|---|---|\n"
open("tables_main.md", "w").write(hdr + "\n".join(rows) + "\n")
print(json.dumps(out, indent=1))
print(hdr + "\n".join(rows))
