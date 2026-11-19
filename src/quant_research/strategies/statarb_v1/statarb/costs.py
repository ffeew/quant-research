"""Vectorised wrapper around Tomas's cost model (src/quant_research/backtest/costs/cost_model.py, v1.1).
Per name-day one-way cost (bps) = fees + venue_hs*half_spread(bucket) + venue_imp*k*sigma_i*sqrt(Q_i/ADV_i)*1e4 + buffer(bucket)
using the module's own BUCKETS / VENUES constants; sigma = measured trailing 20d (lagged), ADV = trailing 20d mean $vol
(lagged), spread = bucket default (no quote history). Fees ~ SEC 0.206 bps on sells (assume half of traded notional
is sells) + CAT (~0.006 bps at $50) -> 0.11 bps/side. validate() checks against cost_model.trade_cost()."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, math
import numpy as np
import pandas as pd
sys.path.append(f"{_QR.COSTS_DIR}")
from quant_research.backtest.costs import cost_model as cm  # noqa: E402

FEES_BPS = 0.5 * cm.SEC_FEE_PER_DOLLAR * 1e4 + 0.01


def bucket_params(adv_usd: pd.DataFrame):
    hs = pd.DataFrame(np.nan, index=adv_usd.index, columns=adv_usd.columns); buf = hs.copy()
    for name, (lo, h, _s, b) in sorted(cm.BUCKETS.items(), key=lambda x: x[1][0]):
        m = adv_usd >= lo
        hs = hs.mask(m, h); buf = buf.mask(m, b)
    return hs.fillna(30.0), buf.fillna(15.0)


def cost_bps(trade_frac, aum_gross, adv_usd, sigma, venue, k):
    """trade_frac: |dw| as fraction of gross book. Returns one-way bps per name-day."""
    hs_m, imp_m = cm.VENUES[venue]
    hs, buf = bucket_params(adv_usd)
    part = (trade_frac * aum_gross) / adv_usd
    imp = imp_m * k * sigma * np.sqrt(part.clip(lower=0)) * 1e4
    return FEES_BPS + hs_m * hs + imp.fillna(0) + buf


def validate():
    out = []
    for adv, px, sh, sig, venue in [(2e9, 50, 200, 0.015, "open"), (5e8, 120, 5000, 0.02, "close"), (1e8, 30, 20000, 0.025, "open")]:
        ref = cm.trade_cost("buy", px, sh, adv / px, sig, None, k=0.75, venue=venue)["total_bps"]
        ref_s = cm.trade_cost("sell", px, sh, adv / px, sig, None, k=0.75, venue=venue)["total_bps"]
        mine = cost_bps(pd.DataFrame([[px * sh / 1e6]]), 1e6, pd.DataFrame([[adv]]), pd.DataFrame([[sig]]), venue, 0.75).iloc[0, 0]
        out.append((adv, venue, round((ref + ref_s) / 2, 3), round(mine, 3)))
    return out
