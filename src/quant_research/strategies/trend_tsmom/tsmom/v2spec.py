"""PREREG-v2 frozen specification (§2-§3 + amendments). Single source of truth for run_v2.py and tests."""
from dataclasses import replace
from .engine import Config

EVAL_START = "2017-02-01"
EVAL_END = "2026-10-28"
CORE_L12 = "SPY QQQ IWM EFA EEM EWJ IEF TLT GLD SLV USO".split()
CORE_L12_UUP = CORE_L12 + ["UUP"]
BROAD_EXFX = CORE_L12 + "EWG EWU UNG DBA DBC".split()

V2_COMMON = Config(name="v2_common", lookbacks=(12,), rebalance="M", vol_com=60.0, sizing="pvt",
                   port_vol_target=0.10, cov_window=252, gross_cap=1.0, gross_cap_hard=1.0,
                   honour_shortable=True, lag=1, nav_usd=1_000_000.0, venue="continuous", impact_k=1.0,
                   borrow_rate=0.0025, band_rel=0.25, band_abs=0.005)

VARIANTS = [  # (id, universe, cfg)  -- exactly PREREG-v2 §3
    ("V1_PRIMARY", CORE_L12, replace(V2_COMMON, name="V1_PRIMARY")),
    ("V2_longflat", CORE_L12, replace(V2_COMMON, name="V2_longflat", long_flat_all=True)),
    ("V3_core+UUP", CORE_L12_UUP, replace(V2_COMMON, name="V3_core+UUP")),
    ("V4_quarterly", CORE_L12, replace(V2_COMMON, name="V4_quarterly", rebalance="Q-JAN")),
    ("V5_broad_exFX", BROAD_EXFX, replace(V2_COMMON, name="V5_broad_exFX")),
]
V1 = VARIANTS[0][2]
SENSITIVITIES = [  # non-trial, V1 only (§3 + A2)
    ("costs_2x", replace(V1, cost_mult=2.0)),
    ("venue_close(MOC)", replace(V1, venue="close")),
    ("nav_10m", replace(V1, nav_usd=10_000_000.0)),
    ("borrow_50bps", replace(V1, borrow_rate=0.005)),
    ("borrow_100bps(STANDARD floor)", replace(V1, borrow_rate=0.01)),
    ("band_off", replace(V1, band_rel=None, band_abs=0.0)),
]
STABILITY = [  # Victor A1.3, V1 only, not trials
    ("lookback_9m", replace(V1, lookbacks=(9,))),
    ("lookback_15m", replace(V1, lookbacks=(15,))),
    ("voltarget_8pct", replace(V1, port_vol_target=0.08)),
    ("voltarget_12pct", replace(V1, port_vol_target=0.12)),
]
