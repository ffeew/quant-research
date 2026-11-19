"""Unit checks required by PREREG-v2 §8 before the first v2 run. Checks mechanics only (no performance printed).
Run: .venv/bin/python -m tests.test_v2_engine"""

import sys
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from quant_research.strategies.trend_tsmom import _engine_v1_frozen as E1
from quant_research.strategies.trend_tsmom.tsmom import v2spec as S
from quant_research.strategies.trend_tsmom.tsmom.data import build_panel, load_shortable
from quant_research.strategies.trend_tsmom.tsmom.engine import Config, _rebalance_dates, run

V1_SYMS = [
    "SPY",
    "QQQ",
    "IWM",
    "EFA",
    "EWJ",
    "EWG",
    "EWU",
    "EEM",
    "SHY",
    "IEF",
    "TLT",
    "GLD",
    "SLV",
    "USO",
    "UNG",
    "DBA",
    "DBC",
    "UUP",
    "FXE",
    "FXY",
    "FXB",
    "FXA",
    "FXC",
]
panel = build_panel(sorted(set(V1_SYMS + S.BROAD_EXFX + S.CORE_L12_UUP)))
sh = load_shortable()
res: dict[str, bool] = {}


def check(name, cond):
    res[name] = bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


# 1. v1 defaults reproduce the frozen v1 engine exactly (baseline + implementable)
for cfg in [Config(), Config(gross_cap=2.0, honour_shortable=True)]:
    a = run(panel, V1_SYMS, cfg, sh)["daily"]
    b = E1.run(panel, V1_SYMS, E1.Config(**{k: getattr(cfg, k) for k in E1.Config.__dataclass_fields__}), sh)["daily"]
    check(f"v1-equivalence gross_cap={cfg.gross_cap}", np.allclose(a.values, b.values, atol=1e-14, equal_nan=True))

outs = {vid: run(panel, uni, cfg, sh) for vid, uni, cfg in S.VARIANTS}
for vid, o in outs.items():
    d = o["daily"]
    W = o["weights"]
    check(f"{vid}: gross <= 1.00 at every close", d.gross_lev.max() <= 1.0 + 1e-9)
    nonshort = [s for s in W.columns if not sh.get(s, False)]
    check(f"{vid}: non-shortable {nonshort} never negative", (W[nonshort] >= -1e-12).all().all() if nonshort else True)
    if vid.startswith("V2"):
        check(f"{vid}: long/flat everywhere", (W >= -1e-12).all().all())
    tr = o["trades"]
    check(f"{vid}: trades only on rebalance fills or cap trims", set(tr.reason.unique()) <= {"rebalance", "cap_trim"})

# 2. band = 0 reproduces no-band behaviour; band reduces turnover
v1 = S.V1
a = run(panel, S.CORE_L12, replace(v1, band_rel=0.0, band_abs=0.0), sh)["daily"]
b = run(panel, S.CORE_L12, replace(v1, band_rel=None, band_abs=0.0), sh)["daily"]
check("band=0 == band off", np.allclose(a.values, b.values, atol=1e-12, equal_nan=True))
check("band reduces (or keeps) turnover", outs["V1_PRIMARY"]["daily"].turnover.sum() <= b.turnover.sum() + 1e-12)

# 3. quarterly dates fall in Jan/Apr/Jul/Oct month-ends, first in 2017 window is 2017-01-31
q = _rebalance_dates(panel["px"].index, "Q-JAN")
check("quarterly months subset {1,4,7,10}", set(q.month) <= {1, 4, 7, 10})
check("quarterly includes 2017-01-31", pd.Timestamp("2017-01-31") in q)

# 4. lag: fills occur one session after rebalance dates
m = _rebalance_dates(panel["px"].index, "M")
idx = panel["px"].index
fills = set(idx[[idx.get_loc(t) + 1 for t in m if idx.get_loc(t) + 1 < len(idx)]])
rb = set(outs["V1_PRIMARY"]["trades"].query("reason=='rebalance'").fill_date)
check("rebalance trades only on t+1 sessions", rb <= fills)

ok = all(res.values())
print("ALL UNIT CHECKS PASS" if ok else "UNIT CHECKS FAILED")
sys.exit(0 if ok else 1)
