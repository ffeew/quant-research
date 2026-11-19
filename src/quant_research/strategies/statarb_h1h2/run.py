"""H1/H2 harness entry point.

    python -m quant_research.strategies.statarb_h1h2.run --syntax-check
    python -m quant_research.strategies.statarb_h1h2.run --config <cfg.toml> --stage dev \\
        --acceptance-hash <sha256 of the pre-registration> [--idea H1|H2|both] [--dry-run-signals]

Refuses (exit 1, or 18 for an identity-list mismatch) unless every DEV input is pinned and
matches, the acceptance hash equals sha256(pre-registration) and its pin, and no row after the
DEV read-time end survives. Holdout is not bound in this harness version and always refuses.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import loaders
from .config import DEV_INPUTS, HarnessConfig, load_config
from .events import earliest_possible_index, make_evidx
from .frames import iloc_int
from .guards import Blocked, require_acceptance_hash
from .pnl import (
    apply_costs_and_returns,
    build_cost_config,
    h1_terminal_bound,
    h2_delisting_receipts,
    h2_delisting_stress,
    sharpe_ann,
)
from .signals import signal_h1, signal_h2
from .splits import H1_TERMINAL_PATHS, HOLDOUT0, MARGIN, check_split_invariants, stage_date_bounds
from .universe import build_elig, build_membership

RUNNER_VERSION = "statarb_h1h2-harness-1"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="statarb_h1h2", description="H1/H2 pre-registered harness (fail closed).")
    p.add_argument("--config", default=None, help="harness TOML (default: $QR_STATARB_H1H2_CONFIG or the example)")
    p.add_argument("--stage", choices=["dev", "holdout"])
    p.add_argument("--acceptance-hash", default=None, help="sha256 of the pre-registration; required for any stage")
    p.add_argument("--idea", choices=["H1", "H2", "both"], default="both")
    p.add_argument("--delisting-stress", action="store_true", help="H2 only: counted -30%% long / 0%% short rerun")
    p.add_argument("--cost-path", default="unknown_borrow_required")
    p.add_argument("--unit", type=float, default=0.005, help="H2 unit (primary 0.5%%; neighbours 0.4/0.6)")
    p.add_argument("--syntax-check", action="store_true", help="check config/imports only; load no data")
    p.add_argument("--dry-run-signals", action="store_true", help="signals only; no P&L")
    p.add_argument("--out", default=None, help="JSON file name, written under the config out_dir (no clobber)")
    return p


def preflight(cfg: HarnessConfig, args: argparse.Namespace) -> str:
    """All gates that need no data parse. Returns the accepted pre-registration sha256."""
    check_split_invariants()
    if args.stage != "dev":
        raise Blocked("REFUSING: this harness binds DEV-only inputs; holdout is not bound.")
    if args.delisting_stress and args.idea != "H2":
        raise Blocked("REFUSING: --delisting-stress is H2 only; pass --idea H2.")
    pending = cfg.pending(DEV_INPUTS)
    if pending:
        raise Blocked(f"REFUSING: inputs PENDING: {pending}")
    pr = cfg.pin("prereg")
    return require_acceptance_hash(args.acceptance_hash, pr.path, pr.sha256, args.stage)


def _write_out(cfg: HarnessConfig, name: str, results: dict[str, Any]) -> Path:
    if os.path.basename(name) != name or not name.endswith(".json"):
        raise Blocked("REFUSING: --out must be a plain *.json file name (written under out_dir).")
    outp = Path(cfg.out_dir) / name
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "x") as f:   # no clobber
        json.dump(results, f, indent=2, default=str)
    return outp


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _main(args)
    except Blocked as b:
        print(str(b), file=sys.stderr)
        return int(b.code) if isinstance(b.code, int) else 1


def _main(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.syntax_check or not args.stage:
        check_split_invariants()
        build_cost_config(args.cost_path)
        print(f"statarb_h1h2 syntax-check OK (config {cfg.source}; pending inputs: {len(cfg.pending())})")
        return 0

    prereg_sha = preflight(cfg, args)
    filter_end, eval_start, eval_end = stage_date_bounds(args.stage)
    if filter_end >= HOLDOUT0:
        raise RuntimeError("DEV filter_end must be before holdout start")
    cost_cfg = build_cost_config(args.cost_path)

    bars = loaders.load_bars_tr(cfg, filter_end)
    if (bars["R"].index >= pd.Timestamp(HOLDOUT0)).any():
        raise RuntimeError("DEV leakage: holdout rows present after filters")
    subind, sector = loaders.load_gics(cfg)
    final_list = loaders.load_identity(cfg)
    lineage = loaders.load_symbol_set(cfg, "lineage_exclusions", "\t")
    if cfg.expected_lineage_exclusions is not None and len(lineage) != cfg.expected_lineage_exclusions:
        raise Blocked(f"REFUSING: expected {cfg.expected_lineage_exclusions} lineage exclusions, got {len(lineage)}.")
    mem, universe_receipt = build_membership(
        loaders.load_parquet_pinned(cfg, "membership"), loaders.load_parquet_pinned(cfg, "listing_status"),
        loaders.load_json_pinned(cfg, "reused_tickers"), loaders.load_json_pinned(cfg, "missing_names"),
        lineage_excl=lineage, dev_universe=loaders.load_symbol_set(cfg, "dev_universe", ","),
        final_list=final_list, listing_overlap_treatment=cfg.listing_overlap_treatment)
    ELIG = build_elig(bars, mem)
    ev_raw = loaders.load_earnings(cfg, filter_end)
    ev = earliest_possible_index(ev_raw, pd.DatetimeIndex(bars["R"].index))
    evidx = make_evidx(ev)
    dates = bars["R"].index
    eval_dates = dates[(dates >= pd.Timestamp(eval_start)) & (dates <= pd.Timestamp(eval_end))]
    if not len(eval_dates):
        raise Blocked("REFUSING: no sessions in the evaluation window.")
    last_exit_i = iloc_int(dates, eval_dates[-1]) - MARGIN

    results: dict[str, Any] = {
        "stage": args.stage, "prereg_sha256": prereg_sha, "runner_version": RUNNER_VERSION,
        "cost_path": cost_cfg.label, "borrow_rate_used": cost_cfg.borrow_rate, "is_pass_bar": cost_cfg.is_pass_bar,
        "k_impact": cost_cfg.k_impact, "filter_end": str(filter_end), "eval": [str(eval_start), str(eval_end)],
        "generated": datetime.now().isoformat(timespec="seconds"), "returns_computed": False,
        "input_pins": {k: v.sha256 for k, v in cfg.inputs.items()}, "universe_receipt": universe_receipt,
        "delisting_stress": bool(args.delisting_stress)}

    for idea in (["H1", "H2"] if args.idea == "both" else [args.idea]):
        stress_overlay = None
        if idea == "H1":
            W, _ = signal_h1(bars, ELIG, subind, evidx, eval_start=eval_start, eval_end=eval_end,
                             last_exit_i=last_exit_i)
        else:
            W, pos = signal_h2(bars, ELIG, subind, sector, ev_raw, evidx, unit=args.unit, eval_start=eval_start,
                               eval_end=eval_end, last_exit_i=last_exit_i)
            results["H2_delisting_receipts"] = h2_delisting_receipts(bars, pos)
            if args.delisting_stress:
                stress_overlay, results["H2_delisting_stress_receipts"] = h2_delisting_stress(bars, W, pos)
        if args.dry_run_signals:
            results[idea] = {"signal_only": True, "n_days_nonzero": int((W.abs().sum(axis=1) > 0).sum()),
                             "avg_gross": float(W.abs().sum(axis=1).mean())}
            continue
        runs: list[tuple[str, pd.DataFrame, pd.Series | None, list[dict[str, Any]] | None]] = [(idea, W, None, None)]
        if idea == "H1":
            roster = loaders.load_json_pinned(cfg, "h1_terminal_roster")
            client = loaders.FileAcquirerCloses(cfg) if "acquirer_closes" in cfg.inputs and \
                not cfg.inputs["acquirer_closes"].pending else None
            runs = []
            for pth in H1_TERMINAL_PATHS:
                W_adj, overlay, receipts = h1_terminal_bound(bars, W, roster, cost_cfg, client=client, path=pth)
                runs.append((f"H1_path{pth}", W_adj, overlay, receipts))
        for key, W_run, ov, recs in runs:
            if idea == "H2" and args.delisting_stress:
                key = "H2_delisting_stress"
            out = apply_costs_and_returns(bars, W_run, cost_cfg, idea=idea)
            daily = out.pop("daily")
            if ov is not None:
                daily["net"] = daily["net"] + ov.reindex(daily.index).fillna(0.0)
                out["terminal_receipts"] = recs
            if stress_overlay is not None:
                daily["net"] = daily["net"] + stress_overlay.reindex(daily.index).fillna(0.0)
            out["net_sharpe_ann"] = sharpe_ann(daily["net"])
            out["gross_sharpe_ann"] = sharpe_ann(daily["gross"])
            if cost_cfg.is_pass_bar:
                sr = out["net_sharpe_ann"]
                out["required_borrow_gate"] = "PASS" if (isinstance(sr, float) and sr > 0) else "FAIL on costs"
            results[key] = out
            results["returns_computed"] = True

    if args.out:
        print(f"wrote {_write_out(cfg, args.out, results)}")
    else:
        print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
