"""Single place to switch datasets / costs / execution. To rerun everything on new adjusted or total-return
bars just change PRICE_SET (or pass --price-set on the run_all.py command line)."""

from __future__ import annotations

from typing import Any

PRICE_SET = "adjusted"  # "adjusted" (data/bars/daily/adjusted, adjustment=all) | "total_return" | "raw"
SOURCE = "cio_data"  # "cio_data" (DE dataset, preferred) | "statarb_iex" | "data_json" (fallbacks)
LABEL = "v1, research only"  # DE confirmed final build 2026-10-30 01:28 SGT
JUMP_FILTER = True  # drop split-sized / implausible jumps from signals and P&L
JUMP_ABS_RET = 0.40  # |1d return| above this is flagged
SPLIT_RATIOS = (2, 3, 4, 5, 8, 10, 20)  # 2:1+ only; 3:2 / 5:4 ratios would flag ordinary +-20-33% earnings moves
SPLIT_TOL = 0.02
HOLDOUT_START = "2022-01-01"  # dev = walk-forward 2017-2021; holdout (OOS) = 2022-01-01 .. last bar
EXECS = (
    "open_t1",
    "close_t1",
)  # signal at close t; trade at open(t+1) [MOO] or close(t+1) [MOC]; MOC after 15:50 ET is rejected so no same-close
AUM_GROSS = (10e6, 100e6, 1e9)  # gross book sizes for size-dependent impact (baseline = first)
K_BASE, K_STRESS = 0.75, 1.0  # sqrt-impact coefficient (Tomas cost_model v1.1)
BORROW_BASE, BORROW_STRESS = 0.0025, 0.0050
MIN_ADV = 2e7  # $ ADV floor for eligibility
STRATEGIES: dict[str, tuple[str, dict[str, Any]]] = {
    # name: (module.function, kwargs)  -- all decided at close t with data <= t
    "a_pairs_EG_BH": ("pairs.run_pairs_weights", dict(z_in=2.0, z_out=0.5, z_stop=4.0, top_k=20, q=0.05)),
    "a_pairs_EG_noMTcorr": ("pairs.run_pairs_weights", dict(z_in=2.0, z_out=0.5, z_stop=4.0, top_k=20, q=1.0)),
    "b_sectorETF_resid_rev5": ("reversal.sector_etf_reversal", dict(lookback=5, beta_win=60)),
    "c_PCA5_resid_rev5": ("reversal.pca_reversal", dict(k=5, lookback=5)),
    # paper-replication hooks (simplified first-pass versions; full replications to follow)
    "AL_sscore_PCA15": ("papers.avellaneda_lee", dict(factors="pca", k=15)),
    "AL_sscore_ETF": ("papers.avellaneda_lee", dict(factors="etf")),
    "Blitz_FF3_monthly": ("papers.blitz_ff3", dict(est_months=36, decile=0.1)),
}

# ---------------- v1 variant grid (PRE-REGISTERED 2026-10-30 ~01:40 SGT, before any v1 result was seen) ----------------
# Priority (Tomas): cut turnover -> wider AL bands and a no-trade buffer. Selection rule, fixed in advance: within each
# family pick the variant with the best DEV (2017-2021) net Sharpe under the desk-standard cost floor, exec=open_t1;
# the holdout is then read once for that pick. All variants are logged as trials (DSR N, PBO matrix).
AL_BANDS = {
    "B0_1.25/0.50/0.75(AL)": (1.25, 0.50, 0.75),
    "B1_1.50/0.25/0.25": (1.50, 0.25, 0.25),
    "B2_1.75/0.00/0.00": (1.75, 0.0, 0.0),
    "B3_2.00/0.50/0.50": (2.00, 0.50, 0.50),
    "B4_2.00/0.00/0.00": (2.00, 0.0, 0.0),
}
BUFFERS = (0.0, 0.5)  # relative no-trade band on |target - held| / |target|
V1_VARIANTS: list[dict[str, Any]] = []
for bn, (so, cl, cs) in AL_BANDS.items():
    for bf in BUFFERS:
        V1_VARIANTS.append(
            dict(
                family="AL_ETF",
                name=f"AL_ETF_{bn}_buf{bf}",
                kind="al",
                factors="etf",
                bands=(so, cl, cs),
                buffer=bf,
                replication=True,
            )
        )
for bn in ["B0_1.25/0.50/0.75(AL)", "B2_1.75/0.00/0.00"]:
    for bf in BUFFERS if bn.startswith("B0") else (0.5,):
        V1_VARIANTS.append(
            dict(
                family="AL_PCA15",
                name=f"AL_PCA15_{bn}_buf{bf}",
                kind="al",
                factors="pca",
                bands=AL_BANDS[bn],
                buffer=bf,
                replication=True,
            )
        )
for lb in (5, 10, 21):
    for bf in BUFFERS:
        V1_VARIANTS.append(
            dict(
                family="b_sectorETF_rev",
                name=f"b_sectorETF_rev{lb}_buf{bf}",
                kind="fn",
                fn="reversal.sector_etf_reversal",
                kw=dict(lookback=lb, beta_win=60),
                buffer=bf,
                replication=False,
            )
        )
for bf in BUFFERS:
    V1_VARIANTS.append(
        dict(
            family="c_PCA5_rev",
            name=f"c_PCA5_rev5_buf{bf}",
            kind="fn",
            fn="reversal.pca_reversal",
            kw=dict(k=5, lookback=5),
            buffer=bf,
            replication=False,
        )
    )
V1_VARIANTS.append(
    dict(
        family="Blitz_FF3",
        name="Blitz_FF3_monthly_d10",
        kind="fn",
        fn="papers.blitz_ff3",
        kw=dict(est_months=36, decile=0.1),
        buffer=0.0,
        replication=True,
    )
)
for nm, q in [("a_pairs_EG_BH", 0.05), ("a_pairs_EG_noMTcorr", 1.0)]:
    V1_VARIANTS.append(
        dict(
            family="a_pairs_EG",
            name=nm,
            kind="fn",
            fn="pairs.run_pairs_weights",
            kw=dict(z_in=2.0, z_out=0.5, z_stop=4.0, top_k=20, q=q),
            buffer=0.0,
            replication=False,
        )
    )
# Trials run BEFORE v1 that are not identical to a v1 config (count toward DSR N; see results/v1/trial_log.csv):
PRIOR_TRIALS = [
    ("IEX smoke: pairs v0 (no per-stock cap) x2 exec", 2),
    ("IEX smoke: b rev5 x2 exec (same-close & next-open)", 2),
    ("IEX smoke: c PCA5 x2 exec", 2),
    ("IEX smoke: pairs BH/noMT v1 (re-entry churn bug) x2 exec", 4),
    ("IEX smoke: pairs BH/noMT v2 x2 exec", 4),
    ("cio_data v0: b,c,Blitz with 1.25/1.5 split-ratio jump filter x2 exec", 6),
    ("cio_data v0: raw bars + jump filter (b,c) x2 exec", 4),
    ("cio_data v0: raw bars, no jump filter (b,c) x2 exec", 4),
    (
        "cio_data v0: AL_PCA15 / AL_ETF default via old code x2 exec (same config as v1 B0 buf0; counted once more for safety)",
        4,
    ),
]
# Cost scenarios. 'std' = desk STANDARD.md section 5 floors: per side max(TCA, floor + half-spread), floor 5 bps
# large (L1/L2), 10 mid (L3), 20 small (L4), 2 bps ETFs; borrow 1%/yr. Verdicts use std / std_2x.
SCENARIOS = {
    "tca_base": dict(k=0.75, borrow=0.0025, mult=1.0, floor=False),
    "tca_stress": dict(k=1.0, borrow=0.0050, mult=1.0, floor=False),
    "tca_2x": dict(k=0.75, borrow=0.0025, mult=2.0, floor=False),
    "std": dict(k=0.75, borrow=0.01, mult=1.0, floor=True),
    "std_2x": dict(k=0.75, borrow=0.01, mult=2.0, floor=True),
}
