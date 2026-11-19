"""Data-issue sensitivity: compare verdicts/metrics across results/v1 (base), v1_complete (reused/re-added/gap tickers
removed from the universe), v1_delist_stress (-30% on non-merger delistings, DE terminal_return on mergers).
Writes ../results/v1/data_issues_sensitivity.csv and headline_v1.csv."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pandas as pd

R = Path(__file__).resolve().parents[1] / "results"
modes = {"base": "v1", "complete": "v1_complete", "delist": "v1_delist_stress"}
keep = [
    "holdout_net_sharpe_std",
    "holdout_net_sharpe_std_2x",
    "full_nw_t_net_std",
    "holdout_DSR",
    "info_holdout_gross_sharpe",
    "info_holdout_net_sharpe_tca_base",
    "hard_bars_passed",
    "VERDICT",
]
out = None
for m, d in modes.items():
    p = pd.read_csv(R / d / "validation_passfail.csv").set_index("trial")[keep].add_suffix(f"__{m}")
    out = p if out is None else out.join(p)
out = cast(pd.DataFrame, out)
for m in ("complete", "delist"):
    out[f"verdict_changed_{m}"] = out[f"VERDICT__{m}"] != out["VERDICT__base"]
    out[f"d_holdout_gross_sharpe_{m}"] = out[f"info_holdout_gross_sharpe__{m}"] - out["info_holdout_gross_sharpe__base"]
    out[f"d_holdout_net_sharpe_std_{m}"] = out[f"holdout_net_sharpe_std__{m}"] - out["holdout_net_sharpe_std__base"]
meta = pd.read_csv(R / "v1_delist_stress" / "trial_meta.csv").set_index("trial")
for c in ("straddle_flags", "held_after_last_bar", "share_gross_in_flagged_names", "delisting_pnl_impact"):
    if c in meta:
        out[c] = meta[c]
meta["n_delisting_positions_hit"] = meta.delisting_positions_hit.apply(
    lambda s: len(json.loads(s)) if isinstance(s, str) else 0
)
out["n_delisting_positions_hit"] = meta["n_delisting_positions_hit"]
out.to_csv(R / "v1" / "data_issues_sensitivity.csv")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
print(
    out[
        [
            "holdout_net_sharpe_std__base",
            "holdout_net_sharpe_std__complete",
            "holdout_net_sharpe_std__delist",
            "info_holdout_gross_sharpe__base",
            "info_holdout_gross_sharpe__complete",
            "info_holdout_gross_sharpe__delist",
            "hard_bars_passed__base",
            "hard_bars_passed__complete",
            "hard_bars_passed__delist",
            "verdict_changed_complete",
            "verdict_changed_delist",
            "straddle_flags",
            "held_after_last_bar",
            "n_delisting_positions_hit",
            "delisting_pnl_impact",
            "share_gross_in_flagged_names",
        ]
    ]
    .round(3)
    .to_string()
)
