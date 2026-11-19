"""PREREG-v3 frozen specification (single primary spec + pre-listed ±20% stability diagnostics)."""

from __future__ import annotations

from dataclasses import replace
from typing import TypedDict, cast

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

from .engine_v3 import V3Config

UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "IEF", "TLT", "GLD", "SLV", "USO"]  # pinned (§2)
COST_MODEL_SHA = desk_pin("strategies.trend_tsmom.tsmom.v3spec", "COST_MODEL_SHA")  # TCA owner v1.1 (§2)
PRIMARY = V3Config()  # split_source="table" (data owner CA table), trim_venue="continuous", max_open_fallback=0.5%
LIMITS_FROZEN_SHA_ABBR = "af513e3a…1cf6"  # LIMITS.md as read at drafting; breaker frozen to §5/§9.A/§9.B
# The validator's 5 v1 cost settings: columns 20-24 of his u23 net matrix, same 2017-02-01..2026-10-28 window
U23_PATH = f"{_QR.DESK_DIR}/validation/backtests/trend_sleeve/u23/trial_matrix_net_TxN24.csv"
U23_SHA = desk_pin("strategies.trend_tsmom.tsmom.v3spec", "U23_SHA")
U23_COLS = ["costs_2x", "venue_close(MOC)", "impact_k0.5", "nav_10m", "borrow_50bps"]
PBO_COLUMNS_EXPECTED = 40  # 24 logged + 5 v1 cost settings + v3 primary + 10 stability
PBO_MISSING = "the validator's 17 diagnostics (no daily series; not regenerated before the run)"
SEGMENTS = [  # (label, start, end, status)  (§6, A2, quasi-OOS label)
    ("2005-2007 blind", "2005-01-01", "2007-12-31", "blind"),
    ("2008-2016 partly seen", "2008-01-01", "2016-12-31", "partly seen"),
    ("2017+ seen", "2017-01-01", "2100-01-01", "seen"),
]
QUASI_OOS = ("2005-01-01", "2016-12-31")
PBO_WINDOW = ("2017-02-01", "2026-10-28")


class _Lookback(TypedDict):
    lookback: int
    min_sig_obs: int


def _lb(x: int) -> _Lookback:  # ±20% lookback in sessions; signal history requirement tracks the lookback (A3 for 252)
    return cast(_Lookback, dict(lookback=x, min_sig_obs=x))


STABILITY = [  # §7 item 8 (diagnostics, counted in N=57 per A1)
    ("lookback_9.6m", replace(PRIMARY, name="lookback_9.6m", **_lb(202))),
    ("lookback_14.4m", replace(PRIMARY, name="lookback_14.4m", **_lb(302))),
    ("stop_1.6atr", replace(PRIMARY, name="stop_1.6atr", atr_mult=1.6)),
    ("stop_2.4atr", replace(PRIMARY, name="stop_2.4atr", atr_mult=2.4)),
    ("voltarget_8pct", replace(PRIMARY, name="voltarget_8pct", port_vol_target=0.08)),
    ("voltarget_12pct", replace(PRIMARY, name="voltarget_12pct", port_vol_target=0.12)),
    ("band_20pct", replace(PRIMARY, name="band_20pct", band_rel=0.20)),
    ("band_30pct", replace(PRIMARY, name="band_30pct", band_rel=0.30)),
    (
        "joint_minus20",
        replace(PRIMARY, name="joint_minus20", atr_mult=1.6, port_vol_target=0.08, band_rel=0.20, **_lb(202)),
    ),
    (
        "joint_plus20",
        replace(PRIMARY, name="joint_plus20", atr_mult=2.4, port_vol_target=0.12, band_rel=0.30, **_lb(302)),
    ),
]
SENSITIVITIES = [  # reported, not gated, not trials
    ("costs_2x", replace(PRIMARY, name="costs_2x", cost_mult=2.0)),
    ("borrow_25bps_tomas", replace(PRIMARY, name="borrow_25bps_tomas", borrow_rate=0.0025)),
    ("nav_1m", replace(PRIMARY, name="nav_1m", nav0=1_000_000.0, cost_nav_basis=1_000_000.0)),
]
N_PRIOR = 46
N_REPORT = 47  # 46 + v3 primary
N_DECISION = 57  # A1: + 10 stability runs


# ---- data v2 (option (b), PREREG-v3 §2; validator 02:26 SGT). Frozen constants.
CA_TABLE_START = "2016-01-05"  # corporate-action table is the split source on/after this date
ALPACA_START = "2016-01-04"  # build source switches from Yahoo to Alpaca SIP (data owner sign-off)
NASDAQ_START = "2016-10-28"  # Nasdaq.com official close coverage starts
# Yahoo split events before CA_TABLE_START: source $QR_SCRATCH_DIR/trend_v3_build/work_splitlog.parquet
# (sha256 d749ec2e5bc90ef5ac34e8d3f2d534e5e18ebffb08149189063fd936c9639700), column yahoo_ratio = new shares per old.
PRE2016_SPLITS_SRC_SHA = desk_pin("strategies.trend_tsmom.tsmom.v3spec", "PRE2016_SPLITS_SRC_SHA")
PRE2016_SPLITS = [
    ("IWM", "2005-06-09", 2.0),
    ("EFA", "2005-06-09", 3.0),
    ("EEM", "2005-06-09", 3.0),
    ("EEM", "2008-07-24", 3.0),
    ("SLV", "2008-07-24", 10.0),
]  # (symbol, ex_date, new_per_old)
REF_SOURCE_TABLE_SHA = desk_pin("strategies.trend_tsmom.tsmom.v3spec", "REF_SOURCE_TABLE_SHA")
NASDAQ_SNAPSHOT_SHA = desk_pin("strategies.trend_tsmom.tsmom.v3spec", "NASDAQ_SNAPSHOT_SHA")  # cross-check input only
XCHECK_AGREE_BP, XCHECK_LIST_SUB_BP, XCHECK_LIST_ALL_BP = 1.0, 10.0, 25.0
