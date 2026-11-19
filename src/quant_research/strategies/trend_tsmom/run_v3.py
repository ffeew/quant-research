"""PREREG-v3 single run. Subcommands:
  preflight            checks everything that does NOT touch the backfill (hashes, pin status, unit tests, outputs_v3 absent)
  pin --sha256 H --ca-sha256 C --diff-sha256 F
                       verify the signed-off v2 build (data_spec_v3.json:path) hashes to H, the data owner's corporate-action
                       table (corporate_actions.path) to C and his v2 substitution diff (substitution_diff.path) to F,
                       then pin all three in PREREG-v3 §2 + §12. Refuses while the §2 reference-source table is TBD.
  run                  the ONE run (refuses on placeholder / hash mismatch / existing outputs_v3/); writes outputs_v3/
Usage once the data owner's hashes arrive:.venv/bin/python run_v3.py pin --sha256 <H> --ca-sha256 <C> --diff-sha256 <F> &&.venv/bin/python run_v3.py run
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from typing import Any, NoReturn, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
from quant_research.strategies.trend_tsmom.tsmom import data_v3 as D
from quant_research.strategies.trend_tsmom.tsmom import v3spec as S
from quant_research.strategies.trend_tsmom.tsmom.engine_v3 import limits_compliance, month_ends, precompute
from quant_research.strategies.trend_tsmom.tsmom.engine_v3 import run as run_engine
from quant_research.strategies.trend_tsmom.tsmom.stats_v3 import dsr, pbo_cscv, perf, sharpe

OUT = "outputs_v3"
SPEC = "data_spec_v3.json"
ANN = 252
COST_MODEL = f"{_QR.COSTS_DIR}/cost_model.py"
CODE_FILES = [
    "run_v3.py",
    "tsmom/engine_v3.py",
    "tsmom/data_v3.py",
    "tsmom/v3spec.py",
    "tsmom/stats_v3.py",
    "tests/test_v3_engine.py",
    "data_spec_v3.json",
]
SGT = dt.timezone(dt.timedelta(hours=8))
now: Callable[[], str] = lambda: dt.datetime.now(SGT).strftime("%Y-%m-%d %H:%M:%S SGT")


def die(msg: str) -> NoReturn:
    print("REFUSED: " + msg)
    sys.exit(2)


def guard_pin(
    pinned: str | None,
    ca_pinned: str | None = None,
    diff_pinned: str | None = None,
    src_pinned: str | None = None,
) -> tuple[str, str, str, str]:
    """A4 + run gate + option (b): no run until the v2 build, corporate-action table, substitution diff and
    reference-source table hashes are ALL pinned in PREREG-v3 §2."""
    if src_pinned is None:
        die("PREREG-v3 §2 reference-source table is still TBD (rule S2, TBD-2); it must be pinned before the v2 build.")
    if pinned is None:
        die(
            "PREREG-v3 §2 data-build hash is still the placeholder (Amendment A4). Pin the data owner's signed-off hash first."
        )
    if ca_pinned is None:
        die("PREREG-v3 §2 corporate-action table hash is still the placeholder (run gate).")
    if diff_pinned is None:
        die("PREREG-v3 §2 v2 substitution-diff hash is still the placeholder (option (b), rule S6).")
    return pinned, ca_pinned, diff_pinned, src_pinned


def read_table(p: str) -> pd.DataFrame:
    return pd.read_parquet(p) if p.endswith(".parquet") else pd.read_csv(p)


def load_spec() -> dict[str, Any]:
    if not os.path.exists(SPEC):
        die(f"{SPEC} missing")
    spec = cast(dict[str, Any], json.load(open(SPEC)))
    if not spec_filled(spec):
        die(f"{SPEC} not filled in (path/layout/column map and corporate_actions from the data owner's sign-off note)")
    return spec


def spec_filled(spec: dict[str, Any]) -> bool:
    ca = spec.get("corporate_actions") or {}
    return bool(
        spec.get("path")
        and spec.get("layout")
        and spec.get("columns", {}).get("tr")
        and all(ca.get(k) for k in ["path", "symbol", "date", "ratio", "ratio_convention"])
        and bool((spec.get("substitution_diff") or {}).get("path"))
        and all((spec.get("nasdaq_xcheck") or {}).get(k) for k in ["path", "sha256"])
    )


def preflight(run_tests: bool = True) -> dict[str, Any]:
    rep: dict[str, Any] = {"time": now()}
    rep["cost_model_sha_ok"] = D.sha_file(COST_MODEL) == S.COST_MODEL_SHA
    rep["pinned_hash"] = D.pinned_hash()
    rep["pinned_ca_hash"] = D.pinned_ca_hash()
    rep["pinned_diff_hash"] = D.pinned_diff_hash()
    rep["pinned_ref_source_hash"] = D.pinned_src_hash()
    rep["outputs_v3_absent"] = not os.path.exists(OUT)
    spec = json.load(open(SPEC)) if os.path.exists(SPEC) else {}
    rep["spec_filled"] = spec_filled(spec)
    rep["u23_matrix_sha_ok"] = os.path.exists(S.U23_PATH) and D.sha_file(S.U23_PATH) == S.U23_SHA
    rep["limits_md_now"] = (
        D.sha_file(f"{_QR.DESK_DIR}/risk/LIMITS.md")[:8] + " (breaker frozen to PREREG; v0.3.x not adopted)"
    )
    if run_tests:
        r = subprocess.run([sys.executable, "-m", "tests.test_v3_engine"], capture_output=True, text=True)
        rep["unit_tests_pass"] = r.returncode == 0
        rep["unit_tests_tail"] = r.stdout.strip().splitlines()[-2:]
        open("tests/unit_checks_v3_output.txt", "w").write(r.stdout + r.stderr)
    for k, v in rep.items():
        print(f"{k}: {v}")
    return rep


def cmd_pin(h: str, ca: str, diff: str) -> None:
    spec = load_spec()
    got = D.sha_path(spec["path"])
    if got != h:
        die(f"sha256({spec['path']}) = {got} != supplied {h}")
    cap = spec["corporate_actions"]["path"]
    got_ca = D.sha_file(cap)
    if got_ca != ca:
        die(f"sha256({cap}) = {got_ca} != supplied {ca}")
    dfp = spec["substitution_diff"]["path"]
    got_df = D.sha_file(dfp)
    if got_df != diff:
        die(f"sha256({dfp}) = {got_df} != supplied substitution-diff hash {diff}")
    if D.pinned_src_hash() is None:
        die(
            "PREREG-v3 §2 reference-source table is still TBD (TBD-2); it must be pinned before the v2 build, so the build cannot be pinned yet"
        )
    txt = open(D.PREREG, encoding="utf-8").read()
    if D.PLACEHOLDER not in txt or D.CA_PLACEHOLDER not in txt or D.DIFF_PLACEHOLDER not in txt:
        die("PREREG-v3 already (partly) pinned; a second pin is a protocol change (log it by hand with the validator)")
    txt = txt.replace(
        f"**`{D.PLACEHOLDER}`**", f"**`{h}`** (data owner sign-off; pinned {now()}; path `{spec['path']}`)"
    )
    txt = txt.replace(f"**`{D.CA_PLACEHOLDER}`**", f"**`{ca}`** (data owner sign-off; pinned {now()}; path `{cap}`)")
    txt = txt.replace(f"**`{D.DIFF_PLACEHOLDER}`**", f"**`{diff}`** (data owner v2 diff; pinned {now()}; path `{dfp}`)")
    txt = (
        txt.rstrip("\n")
        + f"\n- {now()}: data-build hash pinned (A4): `{h}` for `{spec['path']}`; corporate-action table "
        f"hash pinned: `{ca}` for `{cap}`; v2 substitution-diff hash pinned (option (b)): `{diff}` for `{dfp}` (data_spec_v3.json sha256 `{D.sha_file(SPEC)}`). Nothing run yet.\n"
    )
    open(D.PREREG, "w", encoding="utf-8").write(txt)
    print("pinned", h, ca, diff)


# ------------------------------------------------------------------ evaluation helpers
def pbo_add_u23(M: pd.DataFrame) -> pd.DataFrame:
    """Decision 9B-9: append the validator's 5 v1 cost settings (u23 columns 20-24) on the same window."""
    U = pd.read_csv(S.U23_PATH, index_col=0, parse_dates=True)
    cols = list(U.columns)[19:24]
    if cols != S.U23_COLS:
        die(f"u23 columns 20-24 are {cols}, expected {S.U23_COLS}")
    X = U[cols].loc[M.index[0] : M.index[-1]].reindex(M.index)
    if X.isna().any().any():
        die("u23 cost-setting columns do not cover the PBO window")
    X.columns = [f"u23:{c}" for c in cols]
    return pd.concat([M, X], axis=1)


def seg(r: pd.Series, a: str, b: str) -> pd.Series:
    return r.loc[a:b]


def trade_stats(trades: pd.DataFrame, a: str | pd.Timestamp, b: str | pd.Timestamp) -> dict[str, float]:
    t = trades[(trades.date >= a) & (trades.date <= b)]
    return {
        "n_trades": int(t.kind.isin(["entry", "exit", "flip"]).sum()),  # entries, exits, stop-outs (§7.6)
        "n_orders_all": int(len(t)),
        "n_stop_exits": int(t.reason.str.startswith("stop").sum()),
        "turnover_oneway": float(t.dw.sum()),
        "avg_cost_bps": float((t.dw * t.cost_bps_1way).sum() / t.dw.sum()) if t.dw.sum() > 0 else float("nan"),
        "max_pct_adv20": float(t.pct_adv20.max()) if len(t) else float("nan"),
    }


def summarise(o: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    d = o["daily"].loc[a:b]
    if len(d) < 2:
        return {"days": len(d)}
    p = perf(d.net)
    g = perf(d.gross)
    ts = trade_stats(o["trades"], pd.Timestamp(a), pd.Timestamp(b))
    yrs = len(d) / ANN
    out = {
        **{f"net_{k}": v for k, v in p.items()},
        "gross_ann_ret": g["ann_ret"],
        "gross_sharpe": g["sharpe"],
        "max_dd_nav": float(d.dd.max()),
        "max_intraday_dd_nav": float(d.worst_dd_intraday.max()),
        "avg_gross": float(d.gross_lev.mean()),
        "max_gross": float(d.gross_lev.max()),
        "h8_days": int(d.h8.sum()),
        "halt_days": int(d.halted.sum()),
        **ts,
        "turnover_per_year": ts["turnover_oneway"] / yrs if yrs else float("nan"),
    }
    out["breakeven_bps"] = (
        out["gross_ann_ret"] / out["turnover_per_year"] * 1e4 if out["turnover_per_year"] > 0 else float("nan")
    )
    return out


def cmd_run() -> None:
    pinned, ca_pinned, diff_pinned, src_pinned = guard_pin(
        D.pinned_hash(), D.pinned_ca_hash(), D.pinned_diff_hash(), D.pinned_src_hash()
    )
    if os.path.exists(OUT):
        die(f"{OUT}/ already exists: v3 is a single run")
    spec = load_spec()
    if D.sha_file(COST_MODEL) != S.COST_MODEL_SHA:
        die("TCA owner v1.1 cost model hash differs from the PREREG pin")
    pf = preflight(run_tests=True)
    if not pf["unit_tests_pass"]:
        die("unit checks failed; see tests/unit_checks_v3_output.txt")
    t0 = now()
    if D.sha_file(S.U23_PATH) != S.U23_SHA:
        die("the validator's u23 net matrix (PBO columns) differs from the pinned sha256")
    if D.sha_file(spec["substitution_diff"]["path"]) != diff_pinned:
        die("v2 substitution diff differs from the §2 pin (option (b), rule S6)")
    if src_pinned != S.REF_SOURCE_TABLE_SHA:
        die("§2 reference-source table pin differs from the code constant")
    diff_df = read_table(spec["substitution_diff"]["path"])
    try:
        diff_audit = D.check_substitution_diff(diff_df, S.ALPACA_START)
    except RuntimeError as e:
        die(str(e))
    xc = spec["nasdaq_xcheck"]
    if D.sha_file(xc["path"]) != xc["sha256"]:
        die("Nasdaq cross-check input hash differs from data_spec_v3.json (report-only input, X1)")
    panel, info = D.load_pinned_build(spec, S.UNIVERSE, pinned, ca_pinned)  # both hashes verified before reading
    os.makedirs(OUT)
    U = S.UNIVERSE
    prim = run_engine(panel, U, S.PRIMARY)
    stab = {nm: run_engine(panel, U, cfg) for nm, cfg in S.STABILITY}
    sens = {nm: run_engine(panel, U, cfg) for nm, cfg in S.SENSITIVITIES}
    d = prim["daily"]
    qa, qb = S.QUASI_OOS
    rows = [
        {"segment": "full", **summarise(prim, d.index[0], d.index[-1])},
        {"segment": "quasi-OOS 2005-2016", **summarise(prim, qa, qb)},
    ]
    rows += [{"segment": lab, "status": st, **summarise(prim, a, b)} for lab, a, b, st in S.SEGMENTS]
    segs = pd.DataFrame(rows)
    segs.to_csv(f"{OUT}/segments.csv", index=False)
    q = segs.set_index("segment").loc["quasi-OOS 2005-2016"]
    full = segs.set_index("segment").loc["full"]
    blind = segs.set_index("segment").loc["2005-2007 blind"]
    # live-asset count by year (A3)
    pc = precompute(panel, U, S.PRIMARY)
    me = month_ends(pc["tr"].index)
    live = ((pc["n_ret"] >= 252) & pc["vol"].notna() & pc["tr"].notna()).loc[me].sum(1)
    lby = live.groupby(live.index.year).agg(["min", "mean", "max"])
    lby.to_csv(f"{OUT}/live_assets_by_year.csv")
    # DSR (A1: decide N=57, report N=47)
    tl = pd.read_csv("outputs_v2/trial_log_24.csv")
    qnet = d.net.loc[qa:qb]
    dsr_rows = []
    for disp, col in [
        ("gross-dispersion(24 logged; gate)", "gross_sharpe"),
        ("all-net-dispersion(24 logged)", "net_sharpe"),
    ]:
        for N in (S.N_DECISION, S.N_REPORT):
            dsr_rows.append({"version": disp, **dsr(sharpe(qnet), qnet, cast(np.ndarray, tl[col].values), N)})
    dsr_t = pd.DataFrame(dsr_rows)
    dsr_t.to_csv(f"{OUT}/dsr.csv", index=False)
    dsr_gate = dsr_t.query("version.str.startswith('gross') and N==@S.N_DECISION").dsr.iloc[0]
    # PBO (40 of 57 columns with daily series; §9.B(9) as ruled)
    pa, pb = S.PBO_WINDOW
    M = pd.read_csv("outputs_v2/returns_matrix_net_Tx24.csv", index_col=0, parse_dates=True).loc[pa:pb]
    M = pbo_add_u23(M)
    M["V3_PRIMARY"] = d.net.reindex(M.index)
    for nm, o in stab.items():
        M[nm] = o["daily"].net.reindex(M.index)
    M = M.fillna(0.0)
    M.to_csv(f"{OUT}/pbo_matrix_net.csv")
    if M.shape[1] != S.PBO_COLUMNS_EXPECTED:
        die(f"PBO matrix has {M.shape[1]} columns, expected {S.PBO_COLUMNS_EXPECTED}")
    pbo = pbo_cscv(M) | {
        "columns_available": M.shape[1],
        "columns_convention": S.N_DECISION,
        "gap": S.N_DECISION - M.shape[1],
        "missing": S.PBO_MISSING,
    }
    json.dump(pbo, open(f"{OUT}/pbo.json", "w"), indent=2)
    # stability (§7.8)
    srows = []
    for nm, o in stab.items():
        s_ = summarise(o, qa, qb)
        s_["pass"] = bool(s_["net_sharpe"] > 0 and s_["net_sharpe"] >= 0.5 * q.net_sharpe)
        srows.append({"run": nm, **s_})
    stab_t = pd.DataFrame(srows)
    stab_t.to_csv(f"{OUT}/stability.csv", index=False)
    sens_t = pd.DataFrame(
        [
            {"run": nm, "window": w, **summarise(o, a, b)}
            for nm, o in sens.items()
            for w, a, b in [("quasi-OOS", qa, qb), ("full", d.index[0], d.index[-1])]
        ]
    )
    sens_t.to_csv(f"{OUT}/sensitivities.csv", index=False)
    c2x = sens_t.query("run=='costs_2x'").set_index("window")
    # regimes (§7.7)
    yr = d.net.groupby(d.index.year)
    years = pd.DataFrame(
        {"net_sum": yr.sum(), "net_compound": yr.apply(lambda x: (1 + x).prod() - 1), "sharpe": yr.apply(sharpe)}
    )
    years["share_of_total"] = years.net_sum / d.net.sum()
    years.to_csv(f"{OUT}/calendar_years.csv")
    spy = panel["tr"]["SPY"]
    above = (spy > spy.rolling(200).mean()).shift(1).reindex(d.index)
    reg = [
        {"regime": "SPY>200dma", "sharpe": sharpe(d.net[above == True]), "days": int((above == True).sum())},
        {"regime": "SPY<200dma", "sharpe": sharpe(d.net[above == False]), "days": int((above == False).sum())},
    ]
    vix_ok = panel.get("vix") is not None
    if vix_ok:
        vx = panel["vix"].shift(1).reindex(d.index)
        med = vx.median()
        reg += [
            {"regime": "VIX>median", "sharpe": sharpe(d.net[vx > med]), "days": int((vx > med).sum())},
            {"regime": "VIX<=median", "sharpe": sharpe(d.net[vx <= med]), "days": int((vx <= med).sum())},
            {"regime": "VIX>25", "sharpe": sharpe(d.net[vx > 25]), "days": int((vx > 25).sum())},
        ]
    reg_t = pd.DataFrame(reg)
    reg_t.to_csv(f"{OUT}/regimes.csv", index=False)
    # legs, compliance
    navp = d.nav.shift(1)
    legs = {"long": sharpe(d.pnl_long / navp), "short": sharpe(d.pnl_short / navp)}
    dfull = prim["daily"]
    lc = limits_compliance(prim)
    lc["breaches"].to_csv(f"{OUT}/limit_breaches.csv", index=False)
    prim["splits_applied"].to_csv(f"{OUT}/splits_applied.csv", index=False)
    xr = D.nasdaq_yahoo_xcheck(
        read_table(xc["path"]), diff_df, S.XCHECK_AGREE_BP, S.XCHECK_LIST_SUB_BP, S.XCHECK_LIST_ALL_BP
    )
    xr["agreement"].to_csv(f"{OUT}/nasdaq_yahoo_agreement.csv", index=False)
    xr["substituted_gt"].to_csv(f"{OUT}/nasdaq_yahoo_substituted_gt10bp.csv", index=False)
    xr["rows_gt_all"].to_csv(f"{OUT}/nasdaq_yahoo_all_gt25bp.csv", index=False)
    comp = {
        "eod_pos_hard_breach_days": int(dfull.breach_pos_hard.sum()),
        "eod_gross_hard_breach_days": int(dfull.breach_gross_hard.sum()),
        "unstopped_position_days": int(dfull.unstopped_positions.sum()),
        "stop_loosen_violations": int(prim["loosen_violations"]),
        "max_h2_risk_to_stop": float(prim["h2_log"].risk_to_stop_nav.max()) if len(prim["h2_log"]) else 0.0,
        "long_mv_gt_nav_days": int((dfull.long_mv > dfull.nav + 1e-6).sum()),
    }
    comp_orders_ok = (
        comp["unstopped_position_days"] == 0
        and comp["stop_loosen_violations"] == 0
        and comp["max_h2_risk_to_stop"] <= 0.0095 + 1e-9
        and comp["long_mv_gt_nav_days"] == 0
    )
    comp_strict_ok = (
        comp_orders_ok and comp["eod_pos_hard_breach_days"] == 0 and comp["eod_gross_hard_breach_days"] == 0
    )
    crit = [
        ("1 quasi-OOS net SR x0.8 > 0.5", q.net_sharpe * 0.8, q.net_sharpe * 0.8 > 0.5),
        ("2a net SR > 0 at 2x costs (quasi-OOS)", c2x.loc["quasi-OOS"].net_sharpe, c2x.loc["quasi-OOS"].net_sharpe > 0),
        ("2b net SR > 0 at 2x costs (full)", c2x.loc["full"].net_sharpe, c2x.loc["full"].net_sharpe > 0),
        (
            "2c break-even cost >= 2x assumed (quasi-OOS)",
            q.breakeven_bps / q.avg_cost_bps,
            q.breakeven_bps >= 2 * q.avg_cost_bps,
        ),
        ("3 DSR >= 0.95 at N=57 (gross-dispersion)", dsr_gate, dsr_gate >= 0.95),
        ("4 NW t >= 2.8 full history", full.net_nw_t, full.net_nw_t >= 2.8),
        ("5 PBO < 0.20", pbo["pbo"], pbo["pbo"] < 0.20),
        ("6 quasi-OOS trades >= 100", q.n_trades, q.n_trades >= 100),
        ("7a no year > 40% of net PnL", years.share_of_total.max(), years.share_of_total.max() <= 0.40),
        (
            "7b no calendar-year Sharpe < -0.5 (§7.7; confirmed hard by the validator)",
            years.sharpe.min(),
            years.sharpe.min() >= -0.5,
        ),
        (
            "7c no SPY/VIX regime Sharpe < -0.5 (VIX required)",
            reg_t.sharpe.min() if vix_ok else "VIX missing",
            bool(vix_ok and reg_t.sharpe.min() >= -0.5),
        ),
        ("8 stability: all 10 > 0 and >= 50% of primary", int(stab_t["pass"].sum()), bool(stab_t["pass"].all())),
        (
            "9 LIMITS compliance (decision 9B-4: orders ok, breaches cured next open, hard-breach sessions <= 1%)",
            json.dumps({k: v for k, v in lc.items() if k != "breaches"}),
            lc["pass"],
        ),
        ("9s LIMITS compliance strict (no EOD hard breach)", "", comp_strict_ok),
        ("10 blind 2005-2007 net return > 0 (A2)", blind.net_cum_ret, blind.net_cum_ret > 0),
        ("11 every trade <= 1% ADV20", full.max_pct_adv20, full.max_pct_adv20 <= 0.01),
    ]
    ct = pd.DataFrame(crit, columns=["criterion", "value", "pass"])
    ct.to_csv(f"{OUT}/criteria.csv", index=False)
    hard = ct[ct.criterion.str.match(r"^(1|2a|2b|2c|3|4|5|6|7a|7b|7c|8|9|10|11) ")]
    # best attainable verdict is CONDITIONAL PASS (survivorship haircut; partly-seen quasi-OOS) -- PREREG-v3 §7
    verdict = (
        "FAIL (trend shelved for this sprint)"
        if not hard["pass"].all()
        else "CONDITIONAL PASS (for the validator's review)"
    )
    # artefacts
    prim["daily"].to_csv(f"{OUT}/v3_daily.csv")
    prim["trades"].to_csv(f"{OUT}/v3_trades.csv", index=False)
    prim["weights"].loc[d.index].to_csv(f"{OUT}/v3_weights.csv")
    prim["stops"].loc[d.index].to_csv(f"{OUT}/v3_stops.csv")
    prim["events"].to_csv(f"{OUT}/v3_events.csv", index=False)
    prim["contrib_usd"].loc[d.index].to_csv(f"{OUT}/v3_contrib_usd.csv")
    pd.DataFrame(
        [{"trial": 47, "name": "V3_PRIMARY", "date": t0, "data_sha256": pinned, "quasi_oos_net_sr": q.net_sharpe}]
    ).to_csv(f"{OUT}/trial_log_append.csv", index=False)
    meta = {
        "run_started": t0,
        "run_finished": now(),
        "prereg": {"file": "PREREG-v3.md", "sha256": D.sha_file(D.PREREG)},
        "data_build": info,
        "data_v2_substitution": {
            "diff_path": spec["substitution_diff"]["path"],
            "diff_sha256": diff_pinned,
            "reference_source_table_sha256": src_pinned,
            "rule": "PREREG-v3 §2 S1-S8, J1-J3, X1-X3 (option (b), non-trial, N=57)",
            "diff_audit": diff_audit,
            "nasdaq_xcheck": {
                "path": xc["path"],
                "sha256": xc["sha256"],
                "substituted_rows_gt10bp": int(len(xr["substituted_gt"])),
                "all_rows_gt25bp": int(len(xr["rows_gt_all"])),
            },
        },
        "data_spec": {"file": SPEC, "sha256": D.sha_file(SPEC)},
        "rf": {"path": D.RF_PATH, "sha256": D.sha_file(D.RF_PATH), "rf_last_date": panel["rf_last"]},
        "cost_model": {"path": COST_MODEL, "sha256": D.sha_file(COST_MODEL)},
        "limits_md_sha256_now": D.sha_file(f"{_QR.DESK_DIR}/risk/LIMITS.md"),
        "limits_breaker_basis": {
            "frozen_to": f"PREREG-v3 §5/§9.A/§9.B (LIMITS.md {S.LIMITS_FROZEN_SHA_ABBR} at drafting)",
            "disclosure": "LIMITS v0.3.x changes (H9 re-arm at EOD DD<5%, 3%/episode backstop, "
            "chain lock, review validity) NOT adopted; the live breaker may differ.",
        },
        "open_fallback": prim["open_fallback"],
        "splits_applied": int(len(prim["splits_applied"])),
        "u23_matrix": {"path": S.U23_PATH, "sha256": D.sha_file(S.U23_PATH), "columns": S.U23_COLS},
        "standard_md_sha256": D.sha_file(f"{_QR.DESK_DIR}/validation/STANDARD.md"),
        "code": {f: D.sha_file(f) for f in CODE_FILES},
        "config": asdict(S.PRIMARY),
        "universe": U,
        "n_trials": {"decision": S.N_DECISION, "report": S.N_REPORT},
        "legs_sharpe": legs,
        "compliance": comp,
        "pbo": pbo,
        "mechanical_verdict": verdict,
        "blind_note": "2005-2007 is too short to judge on its own (A2); passing it is necessary, not sufficient.",
        "haircut_expectation_sr": min(q.net_sharpe, 0.40 * 1.0),
    }
    json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=2, default=str)
    man = D.dir_manifest(OUT)
    open("outputs_v3.MANIFEST.sha256", "w").write(man)
    hh = hashlib.sha256(man.encode()).hexdigest()
    open("outputs_v3.HASH.txt", "w").write(
        f"outputs_v3 directory hash = sha256(outputs_v3.MANIFEST.sha256) = {hh} ({now()})\n"
    )
    print(ct.to_string(index=False))
    print("VERDICT (mechanical):", verdict)
    print("outputs_v3 hash", hh)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("preflight")
    p = sp.add_parser("pin")
    p.add_argument("--sha256", required=True)
    p.add_argument("--ca-sha256", required=True)
    p.add_argument("--diff-sha256", required=True)
    r = sp.add_parser("run")
    r.add_argument("--spec", default=SPEC)
    a = ap.parse_args()
    if a.cmd == "preflight":
        preflight()
    elif a.cmd == "pin":
        cmd_pin(a.sha256, a.ca_sha256, a.diff_sha256)
    else:
        SPEC = a.spec
        cmd_run()
