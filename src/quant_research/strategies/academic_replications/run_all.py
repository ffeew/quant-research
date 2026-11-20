#!/usr/bin/env python
"""One-command re-run + validation pack for the derivatives researcher's three replications, built to the review's STANDARD.md v1.0.

  $QR_DESK_DIR/research/replication/.venv/bin/python $QR_DESK_DIR/research/replication/run_all.py [--only resmom,bab,imom]
        [--force-stock-imom] [--book 100000] [--skip-grid]

What it does (all read-only on the data owner's / TCA owner's / the review's files; writes only under research/replication/):
  1. Loads the data owner's SIP total returns (ret_total_best, suspect corporate-action days zeroed) + PIT S&P 500 membership.
     Reads the data owner's store only (no fallback; stops if the store is not ready). Live data, if ever needed, via desk_data_client.
  2. For each family runs the base parameters and the +/-20% neighbourhood (one at a time and jointly) for every book,
     next-open fills, TCA owner costs with the review's floors, 1%/yr borrow; plus next-close fills and no-clean data as
     extra trials. Every run is appended to TRIAL_LOG.csv; the T x N daily net-return matrix goes to results/.
  3. Walk-forward OOS (expanding train, 1-year test folds, 21-session embargo, pick = best train Sharpe over the
     parameter grid), DSR (N = full logged trial count), PBO (CSCV, S=16), alpha vs SPY and FF3+UMD, legs, regimes,
     calendar years, capacity, turnover / break-even, delisting exposure, correlations.
  4. Writes <paper folder>/submission/ (SUBMISSION.md + CSVs + equity_curve.png) per family.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.abc
import importlib.util
import json
import math
import pathlib
import sys
import time
from collections.abc import Hashable
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from quant_research.backtest import engine
from quant_research.backtest import trial_log as TL
from quant_research.backtest import validation as V
from quant_research.data import desk_data as dd

OUT = ROOT / "results"
RUN_TS = dt.datetime.now().strftime("%Y-%m-%d %H:%M")


class FamilyCfg(TypedDict):
    folder: str
    title: str
    primary: str
    secondary: list[str]
    int_params: set[str]
    is_sr_proxy: tuple[float | None, str]


FAM: dict[str, FamilyCfg] = {
    "resmom": {
        "folder": "residual_momentum",
        "title": "Residual momentum (Blitz, Huij & Martens 2011)",
        "primary": "resmom_ls",
        "secondary": ["resmom_long", "totmom_ls"],
        "int_params": {"fit_months", "form_months", "skip_days"},
        # in-sample Sharpe proxy for the §6 haircut: public UMD 1965-1989 (post_pub_checks.csv); no public resmom series
        "is_sr_proxy": (
            0.8028,
            "Ken French UMD 1965-01..1989-12 (JT93 in-sample window), proxy; resmom paper Sharpe not used",
        ),
    },
    "bab": {
        "folder": "betting_against_beta",
        "title": "Betting against beta / low volatility (Frazzini & Pedersen 2014)",
        "primary": "bab_fp",
        "secondary": ["lowvol_long", "bab_q"],
        "int_params": {"vol_days"},
        "is_sr_proxy": (0.7034, "AQR BAB USA 1930-12..2012-03 (post_pub_checks.csv), proxy for the paper's US BAB"),
    },
    "imom": {
        "folder": "industry_momentum",
        "title": "Industry momentum (Moskowitz & Grinblatt 1999), sector-ETF version",
        "primary": "imom_etf_ls",
        "secondary": ["imom_etf_long", "imom_etf_ls_1m"],
        "int_params": {"form_months", "topn", "hold_months"},
        "is_sr_proxy": (
            None,
            "set at run time: FF49 VW J6/K6 top5-bot5, 1963-07..1995-07 (MG's sample end), public proxy",
        ),
    },
}


def log(*a: object) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}]", *a, flush=True)


def _load(fam: str) -> ModuleType:
    p = ROOT / FAM[fam]["folder"] / "pipeline.py"
    spec = cast(ModuleSpec, importlib.util.spec_from_file_location(f"pipe_{fam}", p))
    m = importlib.util.module_from_spec(spec)
    cast(importlib.abc.Loader, spec.loader).exec_module(m)
    return m


def grid(base: dict[str, int | float], ints: set[str], skip_grid: bool = False) -> dict[str, dict[str, int | float]]:
    def f(k: str, v: int | float, m: float) -> int | float:
        x = v * m
        return int(round(x)) if k in ints else round(x, 4)

    out: dict[str, dict[str, int | float]] = {"base": dict(base)}
    if skip_grid:
        return out
    for k, v in base.items():
        for m, tag in ((0.8, "m20"), (1.2, "p20")):
            out[f"{k}_{tag}"] = {**base, k: f(k, v, m)}
    out["all_m20"] = {k: f(k, v, 0.8) for k, v in base.items()}
    out["all_p20"] = {k: f(k, v, 1.2) for k, v in base.items()}
    return out


def sr(x: pd.Series) -> float:
    x = x.dropna()
    return x.mean() / x.std() * math.sqrt(252) if len(x) > 20 and x.std() > 0 else np.nan


def data_fingerprint() -> tuple[str, dict[str, str], Any]:
    h = hashlib.sha256()
    for p in [dd.TR_FILE, dd.MEMB_FILE, dd.FF3_DAILY]:
        st = p.stat()
        h.update(f"{p}:{st.st_size}:{int(st.st_mtime)}".encode())
    man = json.load(open(dd.DATA / "manifest.json")) if (dd.DATA / "manifest.json").exists() else {}
    return (
        h.hexdigest()[:16],
        {
            p.name: dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S SGT")
            for p in [dd.TR_FILE, dd.MEMB_FILE, dd.FF3_DAILY]
        },
        man.get("updated_utc") or man.get("updated"),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="resmom,bab,imom")
    ap.add_argument("--force-stock-imom", action="store_true")
    ap.add_argument("--book", type=float, default=engine.BOOK_USD)
    ap.add_argument("--skip-grid", action="store_true")
    a = ap.parse_args()
    fams = a.only.split(",")
    OUT.mkdir(exist_ok=True)
    t0 = time.time()

    st = dd.data_status()
    log("data status:", json.dumps(st, default=str))
    primary = cast(bool, st["primary_ready"])
    if not primary:
        raise SystemExit(
            "the shared data store is not ready (see data/STATUS.md). No fallback by design (data-provenance rule)."
        )
    if primary:
        panel = dd.load_panel(clean=True)
        R = cast(pd.DataFrame, panel["ret"])
        etf_syms = set(dd.universe().query("role=='etf'").symbol) | dd.ETFS
        stocks = [s for s in R.columns if s not in etf_syms]
        mes = [m for m in dd.month_ends(cast(pd.DatetimeIndex, R.index)) if m >= pd.Timestamp("2016-01-31")]
        iv, gaps = dd.validate_intervals(R[[c for c in R.columns if c not in etf_syms]])
        iv.to_csv(OUT / "membership_intervals_coverage.csv", index=False)
        pit_all = dd.pit_mask(mes, stocks, iv)
        has_bar = R.reindex(mes)[stocks].notna()
        elig = pit_all & has_bar
        miss = pit_all & ~has_bar
        cov_year = pd.DataFrame({"member_month_ends": pit_all.sum(axis=1), "without_bar": miss.sum(axis=1)})
        cov_year = cov_year.groupby(cast(pd.DatetimeIndex, cov_year.index).year).sum()
        cov_year["share_missing"] = cov_year.without_bar / cov_year.member_month_ends
        sess_tot = iv[iv.keep].member_sessions.sum()
        sess_have = iv[iv.keep].sessions_with_bars.sum()
        extra_cov = {
            "member_sessions": int(sess_tot),
            "member_sessions_with_bars": int(sess_have),
            "share_member_sessions_missing": 1 - sess_have / sess_tot,
            "intervals_excluded": iv[~iv.keep][["symbol", "start", "end", "note"]].to_dict("records"),
            "partial_intervals": gaps[gaps.keep][["symbol", "start", "end", "coverage", "first_bar", "last_bar"]]
            .astype(str)
            .to_dict("records"),
            "by_year_month_ends": cov_year.reset_index().rename(columns={"index": "year"}).to_dict("records"),
            "missing_symbols_month_ends": sorted(miss.columns[miss.any()].tolist()),
        }
        cov_year.to_csv(OUT / "membership_coverage_by_year.csv")
        json.dump(extra_cov, open(OUT / "membership_coverage.json", "w"), indent=1, default=str)
        dlr = pd.read_parquet(dd.DATA / "universe/delisting_returns.parquet")
        members_at = lambda t: list(elig.columns[elig.loc[t].values])
        ff = dd.ff3_daily()
        fp, mt, _man = data_fingerprint()
        data_label = f"Data owner SIP total_return ret_total_best (clean), fingerprint {fp}"
        suspect_log = cast(pd.DataFrame, panel["suspect_log"])
        log(
            f"PRIMARY: {R.shape[1]} symbols {R.index[0].date()}..{R.index[-1].date()}; PIT eligible per month-end median "
            f"{int(elig.sum(axis=1).median())}; suspect days zeroed {len(suspect_log)}"
        )
        suspect_log.to_csv(OUT / "suspect_returns.csv", index=False)
    rf = ff["RF"]
    ctx = {"month_ends": mes, "members_at": members_at, "ff3": ff}
    cost_label = f"TCA owner v1.1 max validator floor; borrow {engine.BORROW_RATE:.2%}/yr; book ${a.book:,.0f}"
    spy_ex = (R["SPY"] - rf.reindex(R.index).ffill()).rename("SPY_ex") if "SPY" in R.columns else None
    umd_d = (
        pd.read_parquet(dd.DATA / "factors/ken_french/mom_daily.parquet")
        if (dd.DATA / "factors/ken_french/mom_daily.parquet").exists()
        else None
    )
    fac = ff[["Mkt-RF", "SMB", "HML"]].copy()
    if umd_d is not None:
        umd_d["date"] = pd.to_datetime(umd_d["date"].astype(str))
        fac["UMD"] = umd_d.set_index("date").iloc[:, -1].astype(float)
    vix = pd.read_csv(ROOT / "_public_data/VIX_History.csv", parse_dates=["DATE"]).set_index("DATE")["CLOSE"]

    daily_store: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    trial_rows: list[dict[str, Any]] = []
    extra_info: dict[str, Any] = {"coverage": extra_cov}
    TERM: dict[str, dict[Hashable, tuple[float, float]]] = {}
    if dlr is not None:
        lastb = cast(pd.Series, R.apply(cast(Any, pd.Series.last_valid_index)))
        early = [x for x in lastb.index if lastb[x] < R.index[-1] and x not in etf_syms]
        tab = dlr.set_index("symbol")

        def tv(x: object) -> float | None:
            return (
                float(cast(Any, tab.at[x, "terminal_return"]))
                if x in tab.index and pd.notna(cast(Any, tab.at[x, "terminal_return"]))
                else None
            )

        TERM["table"] = {x: ((tv(x) or 0.0), (tv(x) or 0.0)) for x in early}
        TERM["conservative"] = {
            x: cast(tuple[float, float], (tv(x), tv(x)) if tv(x) is not None else (-0.30, -0.30)) for x in early
        }
        TERM["adverse"] = {
            x: cast(tuple[float, float], (tv(x), tv(x)) if tv(x) is not None else (-0.30, 0.30)) for x in early
        }
        extra_info["delist_counts"] = {
            "names_with_bars_ending_early": len(early),
            "matched_deal_terminal_return": int(sum(tv(x) is not None for x in early)),
            "unmatched": int(sum(tv(x) is None for x in early)),
        }
    done_ids = TL.existing_ids()

    def run_book(
        fam: str,
        book: str,
        tag: str,
        params: object,
        targets: dict[pd.Timestamp, pd.Series],
        fill: str = "open",
        pnl: dict[str, pd.DataFrame | str] = panel,
        role: str = "candidate",
        data: str = data_label,
        term: str | None = None,
    ) -> str | None:
        dtag = ("clean" if pnl is panel else "noclean") + (f"+delist_{term}" if term else "")
        tid = f"{fam}|{book}|{tag}|{fill}|{dtag}|{RUN_TS}"
        if len(targets) < 7:
            log(f"  {tid}: {len(targets)} rebalances -> skipped")
            return None
        res = engine.simulate(
            pnl,
            targets,
            rf,
            fill=fill,
            book_usd=a.book,
            etfs=frozenset(etf_syms),
            terminal=cast(dict[str, tuple[float, float]] | None, TERM.get(term) if term else None),
        )
        daily, trades, dl = cast(tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], res)
        daily = daily.iloc[21:] if len(daily) > 260 else daily  # drop the partial first month
        daily_store[tid] = (daily, trades, dl)
        n = daily.net
        trial_rows.append(
            {
                "trial_id": tid,
                "logged_at_sgt": RUN_TS,
                "family": fam,
                "book": book,
                "param_tag": tag,
                "params": params,
                "universe": "PIT S&P 500 (stocks)" if "etf" not in book else "SPDR sector ETFs",
                "data": data,
                "fill": f"next {fill}",
                "costs": cost_label,
                "role": role,
                "has_daily_series": True,
                "sr_net_full": sr(n),
                "sr_net_is_2016_2021": sr(n[n.index < "2022-01-01"]),
                "sr_net_oos_2022plus": sr(n[n.index >= "2022-01-01"]),
                "sr_gross_full": sr(daily.gross),
                "sr_net_2x_full": sr(daily.net2x),
                "start": str(n.index[0].date()),
                "end": str(n.index[-1].date()),
            }
        )
        log(
            f"  {fam}/{book}/{tag}/{fill}/{dtag}: SR gross {sr(daily.gross):.2f} net {sr(n):.2f} "
            f"2x {sr(daily.net2x):.2f}"
        )
        return tid

    imom_public = None
    for fam in fams:
        cfg = FAM[fam]
        mod = _load(fam)
        log(f"=== {fam}: {cfg['title']}")
        if fam == "imom":
            imom_public_rows, _imom_public_series = mod.public_check()
            imom_public = imom_public_rows
            cfg["is_sr_proxy"] = (
                float(imom_public_rows.set_index("window").loc["in_sample_1963-07..1995-07", "sharpe_ann"]),
                cfg["is_sr_proxy"][1],
            )
        G = grid(cast(dict[str, int | float], mod.BASE), cfg["int_params"], a.skip_grid)
        base_targets: dict[str, Any] | None = None
        for tag, p in G.items():
            log(f" params {tag}: {p}")
            if fam == "bab":
                books, info = mod.build_targets(panel, ctx, p)
                if tag == "base":
                    extra_info["bab_info"] = info
            elif fam == "imom":
                books = mod.build_targets_etf(panel, ctx, dd.SECTOR_ETFS, p)
            else:
                books = mod.build_targets(panel, ctx, p)
            if tag == "base":
                base_targets = cast(dict[str, Any], books)
            for book, tg in books.items():
                run_book(fam, book, tag, p, cast(dict[pd.Timestamp, pd.Series], tg))
        # extra trials: next-close fills and un-cleaned data, primary + secondary books, base params
        base_books = cast(dict[str, Any], base_targets)
        for book in [cfg["primary"]] + cfg["secondary"]:
            run_book(
                fam,
                book,
                "base",
                mod.BASE,
                cast(dict[pd.Timestamp, pd.Series], base_books[book]),
                fill="close",
                role="exec_alt",
            )
        if primary:
            raw = dd.load_panel(clean=False)
            for book in [cfg["primary"]] + cfg["secondary"]:
                run_book(
                    fam,
                    book,
                    "base",
                    mod.BASE,
                    cast(dict[pd.Timestamp, pd.Series], base_books[book]),
                    pnl=raw,
                    role="data_alt",
                    data=data_label.replace("(clean)", "(no suspect-day cleaning)"),
                )
            for mode in ("table", "conservative", "adverse"):
                for book in [cfg["primary"]] + cfg["secondary"]:
                    run_book(
                        fam,
                        book,
                        "base",
                        mod.BASE,
                        cast(dict[pd.Timestamp, pd.Series], base_books[book]),
                        role="data_alt",
                        term=mode,
                        data=data_label + f"; delisting returns: {mode}",
                    )
        if fam == "imom":
            cov_f = cast(float, st.get("gics_coverage_former", 0.0))
            if primary and (cov_f >= 0.95 or a.force_stock_imom):
                u = dd.universe()
                g = u[u.role != "etf"].set_index("symbol")["gics_sector"].dropna()
                for book, tg in mod.build_targets_stock(panel, ctx, g).items():
                    run_book(
                        fam,
                        ("" if cov_f >= 0.95 else "DIAG_currentGICS_") + book,
                        "base",
                        mod.BASE,
                        cast(dict[pd.Timestamp, pd.Series], tg),
                        role="candidate" if cov_f >= 0.95 else "diagnostic_survivorship_biased",
                    )
            else:
                extra_info["imom_stock_blocked"] = (
                    f"GICS codes cover {cov_f:.0%} of former S&P 500 members (need >=95%, "
                    "point-in-time). Current-only GICS would re-introduce survivorship bias."
                )
                log("stock-level industry momentum BLOCKED:", extra_info["imom_stock_blocked"])

    # ---------------- trial log + T x N matrix ----------------
    hist = [r for r in TL.historical_rows() if r["trial_id"] not in done_ids]
    if imom_public is not None and f"P|imom|FF49_J6K6|{RUN_TS}" not in done_ids:
        hist.append(
            {
                "trial_id": f"P|imom|FF49_J6K6|{RUN_TS}",
                "logged_at_sgt": RUN_TS,
                "family": "imom",
                "book": "FF49 VW J6/K6 top5-bot5",
                "role": "public_check",
                "has_daily_series": False,
                "data": "Ken French 49 industries",
                "notes": "gross monthly",
            }
        )
    TL.append(hist + trial_rows)
    M = pd.DataFrame({k: v[0].net for k, v in daily_store.items()})
    M.to_parquet(OUT / f"trials_daily_net_{RUN_TS.replace(' ', '_').replace(':', '')}.parquet")
    M.to_csv(OUT / f"trials_daily_net_{RUN_TS.replace(' ', '_').replace(':', '')}.csv.gz")
    tlog = pd.read_csv(TL.LOG)

    # ---------------- per-family validation packs ----------------
    vb: pd.DataFrame | None = None
    vpath = pathlib.Path(f"{_QR.DESK_DIR}/validation/backtests/daily_pnl_R_all_variants.csv")
    if vpath.exists():
        vb = pd.read_csv(vpath, parse_dates=["t"]).set_index("t")
    prim_net: dict[str, pd.Series] = {}
    summary_lines: list[str] = []
    for fam in fams:
        cfg = FAM[fam]
        sub = ROOT / cfg["folder"] / "submission"
        sub.mkdir(exist_ok=True)
        fam_ids = [k for k in daily_store if k.startswith(fam + "|")]
        cand_ids = [k for k in fam_ids if "|open|clean|" in k and "DIAG" not in k]
        # N = distinct specifications ever run (identical re-runs of the same spec are counted once)
        spec = tlog.trial_id.astype(str).map(lambda x: "|".join(x.split("|")[:5]) if len(x.split("|")) == 6 else x)
        N_fam = int(spec[tlog.family == fam].nunique())
        N_all = int(spec.nunique())
        trial_srs = np.array(
            [
                daily_store[k][0].net.mean() / daily_store[k][0].net.std()
                for k in cand_ids
                if daily_store[k][0].net.std() > 0
            ]
        )
        all_srs = np.array([v[0].net.mean() / v[0].net.std() for v in daily_store.values() if v[0].net.std() > 0])
        pbo_all = V.pbo_cscv(pd.DataFrame({k: daily_store[k][0].net for k in cand_ids}))
        packs: dict[str, dict[str, Any]] = {}
        for book in [cfg["primary"]] + cfg["secondary"]:
            bid = f"{fam}|{book}|base|open|clean|{RUN_TS}"
            if bid not in daily_store:
                continue
            daily, trades, dl = daily_store[bid]
            n = daily.net
            pk: dict[str, Any] = {
                "book": book,
                "net": V.basic(n),
                "gross": V.basic(daily.gross),
                "net2x": V.basic(daily.net2x),
                "long_leg_gross": V.basic(daily.gross_long),
                "short_leg_gross": V.basic(daily.gross_short),
            }
            pk["dsr_family"] = V.dsr(n, trial_srs, N_fam)
            pk["dsr_all"] = V.dsr(n, all_srs, N_all)
            book_cands = {k.split("|")[2]: daily_store[k][0].net for k in cand_ids if k.split("|")[1] == book}
            pk["pbo_book_grid"] = V.pbo_cscv(pd.DataFrame(book_cands))
            pk["pbo_family"] = pbo_all
            first_year = max(n.index[0].year + 2, 2019)
            wf, folds = V.walk_forward(book_cands, first_year, cast(pd.Timestamp, n.index[-1]).year)
            wf2x_parts: list[pd.Series] = []
            for f_fold in folds.itertuples():
                k = f"{fam}|{book}|{f_fold.pick}|open|clean|{RUN_TS}"
                x = daily_store[k][0].net2x
                wf2x_parts.append(
                    x[(x.index >= f"{f_fold.test_year}-01-01") & (x.index <= f"{f_fold.test_year}-12-31")].iloc[21:]
                )
            wf2x = pd.concat(wf2x_parts) if wf2x_parts else pd.Series(dtype=float)
            pk["wf"] = {
                **V.basic(wf),
                "folds": len(folds),
                "years": len(wf) / 252,
                "sharpe_2x": sr(wf2x),
                "oos_months": int(wf.groupby(pd.Grouper(freq="ME")).size().gt(0).sum()) if len(wf) else 0,
            }
            pk["wf_folds"] = folds
            pk["ab"] = V.alpha_beta(n, spy_ex, fac) if spy_ex is not None else {}
            pk["ab_gross"] = V.alpha_beta(daily.gross, spy_ex) if spy_ex is not None else {}
            pk["years"] = V.by_year(n)
            pk["regimes"] = V.regimes(n, R["SPY"], vix) if "SPY" in R.columns else pd.DataFrame()
            yrs = len(daily) / 252
            traded = daily.traded.sum() / yrs
            gross_book = (daily.long_mv + daily.short_mv).mean()
            avg_bps = (trades.dw.abs() * trades.bps).sum() / trades.dw.abs().sum() if len(trades) else np.nan
            avg_costs = (trades.dw.abs() * trades.tomas_bps).sum() / trades.dw.abs().sum() if len(trades) else np.nan
            be = pk["gross"]["ann_ret"] / traded * 1e4 if traded > 0 else np.nan
            pk["turn"] = {
                "traded_per_yr_x_nav": traded,
                "avg_gross_exposure": gross_book,
                "oneway_turnover_per_yr_of_gross": traded / 2 / gross_book,
                "avg_holding_months": 12 * gross_book / (traded / 2) if traded > 0 else np.nan,
                "gross_ret_per_unit_traded_bps": be,
                "breakeven_cost_bps_per_side": be,
                "assumed_avg_cost_bps_per_side": avg_bps,
                "tomas_only_avg_cost_bps": avg_costs,
                "breakeven_over_assumed": be / avg_bps if avg_bps else np.nan,
                "cost_drag_ann": daily.cost.sum() / yrs,
                "borrow_drag_ann": daily.borrow.sum() / yrs,
                "avg_long_mv": daily.long_mv.mean(),
                "avg_short_mv": daily.short_mv.mean(),
            }
            part = trades.participation.dropna()
            pk["capacity"] = {
                "book_usd": a.book,
                "max_participation": part.max(),
                "p99_participation": part.quantile(0.99),
                "share_trades_over_1pct_adv": (part > 0.01).mean(),
                "max_participation_at_10x_book": part.max() * 10,
                "share_over_1pct_at_10x": (part * 10 > 0.01).mean(),
            }
            pk["delist"] = dl
            pk["daily"], pk["trades"] = daily, trades
            # correlations
            cors = {}
            if spy_ex is not None:
                cors["SPY"] = n.corr(spy_ex.reindex(n.index))
            for c in fac.columns:
                cors[f"FF_{c}"] = n.corr(fac[c].reindex(n.index))
            if vb is not None:
                for c in ["MOM_monthly_LS", "PEAD_raw_LS", "PEAD_trend_LS", "MOM_bracket_LS"]:
                    if c in vb.columns:
                        cors[f"validation_backtest_{c}"] = n.corr(vb[c].reindex(n.index))
            pk["corr"] = cors
            # neighbourhood
            nb_rows: list[dict[str, float | str]] = []
            for k in cand_ids:
                if k.split("|")[1] != book:
                    continue
                x = daily_store[k][0].net
                nb_rows.append(
                    {
                        "param_tag": k.split("|")[2],
                        "sr_net_full": sr(x),
                        "sr_net_2022plus": sr(x[x.index >= "2022-01-01"]),
                        "sr_net_2x_full": sr(daily_store[k][0].net2x),
                    }
                )
            nb = pd.DataFrame(nb_rows)
            b0 = nb.set_index("param_tag").loc["base"]
            nb["ok_full"] = (
                (nb.sr_net_full > 0) & (nb.sr_net_full >= 0.5 * b0.sr_net_full) if b0.sr_net_full > 0 else False
            )
            nb["ok_2022plus"] = (
                (nb.sr_net_2022plus > 0) & (nb.sr_net_2022plus >= 0.5 * b0.sr_net_2022plus)
                if b0.sr_net_2022plus > 0
                else False
            )
            pk["neigh"] = nb
            alt = {}
            for fill, dat in (
                ("close", "clean"),
                ("open", "noclean"),
                ("open", "clean+delist_table"),
                ("open", "clean+delist_conservative"),
                ("open", "clean+delist_adverse"),
            ):
                k = f"{fam}|{book}|base|{fill}|{dat}|{RUN_TS}"
                if k in daily_store:
                    dsx = daily_store[k]
                    alt[f"{fill}_{dat}"] = sr(dsx[0].net)
                    alt[f"{fill}_{dat}_annret"] = dsx[0].net.mean() * 252
                    alt[f"{fill}_{dat}_events"] = len(dsx[2])
                    alt[f"{fill}_{dat}_long_events"] = int((dsx[2].weight > 0).sum()) if len(dsx[2]) else 0
            pk["alt"] = alt
            packs[book] = pk
            if book == cfg["primary"]:
                prim_net[fam] = n
        write_submission(
            fam,
            cfg,
            packs,
            sub,
            st,
            data_label,
            cost_label,
            fp,
            mt,
            N_fam,
            N_all,
            extra_info,
            a,
            imom_public if fam == "imom" else None,
        )
        prim = packs.get(cfg["primary"])
        if prim:
            summary_lines.append(
                f"{fam}: primary {cfg['primary']} net SR {prim['net'].get('sharpe', np.nan):.2f} (gross "
                f"{prim['gross'].get('sharpe', np.nan):.2f}, 2x {prim['net2x'].get('sharpe', np.nan):.2f}), t_NW "
                f"{prim['net'].get('t_nw', np.nan):.2f}, WF-OOS SR {prim['wf'].get('sharpe', np.nan):.2f}, DSR "
                f"{prim['dsr_family']['DSR']:.2f} (N={N_fam}), PBO {prim['pbo_book_grid'].get('PBO', np.nan):.2f}"
            )
    if len(prim_net) > 1:
        pd.DataFrame(prim_net).corr().to_csv(OUT / "primary_correlations.csv")
    json.dump(
        {
            "data_status": st,
            "primary": primary,
            "args": vars(a),
            "run_ts": RUN_TS,
            "elapsed_s": time.time() - t0,
            "trials_this_run": len(trial_rows),
            "trial_log_rows": int(len(tlog)),
            "summary": summary_lines,
            "extra": {k: v for k, v in extra_info.items() if isinstance(v, str)},
        },
        open(OUT / "run_meta.json", "w"),
        indent=1,
        default=str,
    )
    for l in summary_lines:
        log(l)
    log(f"done in {time.time() - t0:.0f}s")


def _f(x: object, f: str = ".2f") -> str:
    try:
        return format(x, f) if x is not None and np.isfinite(cast(float, x)) else "n/a"
    except Exception:
        return str(x)


def data_caveats(fam: str, cfg: FamilyCfg, packs: dict[str, dict[str, Any]], extra: dict[str, Any]) -> list[str]:
    cov = extra.get("coverage", {}) or {}
    dc = extra.get("delist_counts", {}) or {}
    L = [
        "## Data-affected caveats (read before the numbers)",
        "",
        "**Earnings timing: none of the three strategies (residual momentum, BAB / low vol, industry momentum) uses earnings "
        "dates, earnings surprises or announcement timing.** The known earnings defects in the store (intraday earnings dated "
        "a day late; earnings and predecessor history missing for many former members; see "
        "validation/backtests/pead_long_pit/data_issues.json) therefore do not enter any signal here. The other defects do, as below.",
        "",
    ]
    # 1 delisting
    L += [
        "### 1. Missing delisting returns (material for long books)",
        "",
        f"The data owner's `data/universe/delisting_returns.parquet` has terminal returns only for deals matched in Alpaca's corporate-action feed "
        f"(which starts 2020-04). Of the {dc.get('names_with_bars_ending_early', 'n/a')} stocks whose bars end before the sample end, "
        f"{dc.get('matched_deal_terminal_return', 'n/a')} have a terminal return and {dc.get('unmatched', 'n/a')} do not (they cannot be told apart as "
        "merger vs performance delisting from the data available, so they are treated as performance-related in the stress). "
        "Base runs treat a held position whose bars stop as cash at the last close (0%). Sensitivity (base params, next-open fills, "
        "each logged as a data_alt trial):",
        "- **table**: matched terminal return where known, else 0%;",
        "- **conservative**: matched terminal return where known, else **-30% on both legs** (the validator's suggested assumption; shorts gain);",
        "- **adverse**: matched where known, else -30% on longs and **+30% on shorts** (takeover-premium case; worst for every book).",
        "",
        "| book | delisting events while held (long / short) | net SR base | table | conservative | adverse | net ann base | ann conservative | ann adverse |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for book, pk in packs.items():
        al, dl = pk["alt"], pk["delist"]
        nl = int((dl.weight > 0).sum()) if len(dl) else 0
        L.append(
            f"| {book} | {len(dl)} ({nl} / {len(dl) - nl}) | {_f(pk['net'].get('sharpe'))} | {_f(al.get('open_clean+delist_table'))} | "
            f"{_f(al.get('open_clean+delist_conservative'))} | {_f(al.get('open_clean+delist_adverse'))} | {_f(pk['net'].get('ann_ret'), '.2%')} | "
            f"{_f(al.get('open_clean+delist_conservative_annret'), '.2%')} | {_f(al.get('open_clean+delist_adverse_annret'), '.2%')} |"
        )
    L += [
        "",
        "Per-event detail (symbol, weight held, last bar, return applied in the base run = 0): `delisting_exits_<book>.csv`. "
        "the validator's file lists 120 delisting rows (47 matched, 70 no deal, 3 acquirer price missing); pre-2020 delistings have no terminal "
        "return at all, so the 2016-2019 part of every book is the most exposed.",
        "",
    ]
    # 2 ticker reuse
    L += ["### 2. Ticker reuse (SNDK and others)", ""]
    for r in cov.get("intervals_excluded", []):
        L.append(f"- {r['symbol']} membership interval {r['start']} to {r['end']}: excluded. {r['note']}")
    L += [
        "- Every membership interval is mapped to the symbol's bars (`_common/desk_data.validate_intervals`, output "
        "`results/membership_intervals_coverage.csv`); a name is eligible at a signal date only if it is a PIT member in a kept interval "
        "AND has a bar on that date. The SNDK interval from 2025-11-28 maps to the new Sandisk bars and is kept. The data owner's fixes for "
        "POM, SPLS, NFX, APC, CA, CSRA, DNB, TE (former members cut at the first gap > 10 sessions) are inherited.",
        "",
    ]
    # 3 coverage
    L += [
        "### 3. Former / renamed members missing price history while in the index",
        "",
        f"PIT member-sessions 2016-01..2026-10: {cov.get('member_sessions', 'n/a'):,} ; with bars: {cov.get('member_sessions_with_bars', 'n/a'):,} ; "
        f"missing {_f(cov.get('share_member_sessions_missing', float('nan')), '.2%')}. These member-dates are silently out of the universe "
        "(survivorship-type bias: missing names are mostly predecessors of renamed / merged / spun companies and failed names).",
        "",
        "Member month-ends without a bar, by year:",
        "",
        "| year | member month-ends | without bar | share |",
        "|---|---|---|---|",
    ]
    for r in cov.get("by_year_month_ends", []):
        L.append(
            f"| {r['year']} | {int(r['member_month_ends'])} | {int(r['without_bar'])} | {r['share_missing']:.2%} |"
        )
    pi = cov.get("partial_intervals", [])
    L += [
        "",
        f"Intervals with partial bar coverage ({len(pi)}; full list in `results/membership_intervals_coverage.csv`): "
        + ", ".join(
            f"{r['symbol']} ({float(r['coverage']):.0%}, bars from {r['first_bar']})"
            for r in sorted(pi, key=lambda r: float(r["coverage"]))[:20]
        )
        + (" ..." if len(pi) > 20 else ""),
        f"Symbols that are PIT members at some month-end with no bar ({len(cov.get('missing_symbols_month_ends', []))}): "
        + ", ".join(cov.get("missing_symbols_month_ends", [])[:60])
        + "",
        "",
    ]
    # 4 others
    L += [
        "### 4. Other data items",
        "- PIT shares outstanding: in progress. All books are equal-weighted; the papers' value-weighted variants (and the FP BAB / "
        "Moskowitz-Grinblatt VW industry returns) cannot be run yet.",
        "- Suspect corporate-action days: 12 stock-days with |return| > 40% on split / other-action / TR-mismatch days set to 0 "
        "(`results/suspect_returns.csv`); the no-clean run is logged (SR in the details).",
        "- PIT borrow / ETB history does not exist (snapshots from 2026-10-29): §5 exclusion of unborrowable names is not applied "
        "historically; all shorts pay 1%/yr. Hard-to-borrow failed names on the short side are therefore flattered.",
        "- PIT GICS codes for former members: 0% coverage, so stock-level industry momentum is blocked."
        + (
            " Industry momentum here is the 11 sector-ETF version, so items 1-3 do not affect it (ETFs have full bars and no delistings)."
            if fam == "imom"
            else ""
        ),
        "- The store is still being written (symbol count changed 772 -> 774 during the sprint); results are tied to the file mtimes above.",
        "",
    ]
    return L


def write_submission(
    fam: str,
    cfg: FamilyCfg,
    packs: dict[str, dict[str, Any]],
    sub: pathlib.Path,
    st: dict[str, int | bool | float | str | list[str]],
    data_label: str,
    cost_label: str,
    fp: str,
    mt: dict[str, str],
    N_fam: int,
    N_all: int,
    extra: dict[str, Any],
    a: argparse.Namespace,
    imom_public: pd.DataFrame | None,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    for book, pk in packs.items():
        d = pk["daily"]
        ax.plot((1 + d.net).cumprod(), label=f"{book} net")
        if book == cfg["primary"]:
            ax.plot((1 + d.gross).cumprod(), "--", label=f"{book} gross")
            ax.plot((1 + d.net2x).cumprod(), ":", label=f"{book} net 2x costs")
    ax.set_yscale("log")
    ax.legend(fontsize=8)
    ax.set_title(cfg["title"] + " (excess of rf, per $1 NAV)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(sub / "equity_curve.png", dpi=110)
    plt.close(fig)
    for book, pk in packs.items():
        pk["daily"].to_csv(sub / f"daily_{book}.csv")
        pk["trades"].to_csv(sub / f"trades_{book}.csv.gz", index=False)
        pk["years"].to_csv(sub / f"by_year_{book}.csv")
        pk["regimes"].to_csv(sub / f"regimes_{book}.csv", index=False)
        pk["neigh"].to_csv(sub / f"sensitivity_{book}.csv", index=False)
        pk["wf_folds"].to_csv(sub / f"walk_forward_{book}.csv", index=False)
        pk["delist"].to_csv(sub / f"delisting_exits_{book}.csv", index=False)
    if fam == "bab" and "bab_info" in extra:
        extra["bab_info"].to_csv(sub / "bab_exante_beta_leverage.csv")

    P = packs[cfg["primary"]]
    is_sr, is_note = cfg["is_sr_proxy"]
    L = [
        f"# Validation submission: {cfg['title']}",
        "",
        f"Submitted by the derivatives researcher (Quant Research) to the validator, {RUN_TS} SGT. Built against validation/STANDARD.md v1.0. "
        "Self-assessment only; the verdict is the validator's.",
        "",
        "## Reproduce (one command)",
        "```",
        f"{_QR.DESK_DIR}/research/replication/.venv/bin/python {_QR.DESK_DIR}/research/replication/run_all.py --only "
        + fam,
        "```",
        f"Code: `research/replication/{cfg['folder']}/pipeline.py`, `_common/engine.py` (fills, costs, borrow), "
        "`_common/validation.py` (DSR, PBO, NW, walk-forward), `run_all.py`. Env: `research/replication/.venv` "
        "(`requirements.lock.txt`).",
        f"Data snapshot: {data_label}; file mtimes {json.dumps(mt)}. Trial log: `research/replication/TRIAL_LOG.csv`; "
        f"T x N daily net matrix: `research/replication/results/trials_daily_net_*.parquet`.",
        "",
        "## Codified rules",
        "See the docstring of `pipeline.py` (copied below). No discretion, no overrides.",
        "```",
        (_load(fam).__doc__ or "").strip(),
        "```",
        f"Execution: signal at the close of the last session of each month; market-on-open fill at the next session's open; "
        f"costs {cost_label}; 2x stress doubles costs and borrow. Primary (pre-specified, paper-faithful) book: "
        f"**{cfg['primary']}**; secondary books: {', '.join(cfg['secondary'])}.",
        "",
    ]
    L += [
        "## Headline (base parameters, next-open fills, full desk sample)",
        "",
        "| book | start | net SR | gross SR | net SR 2x | net ann | t (NW) | maxDD | alpha vs SPY (ann, t) | beta SPY | FF3+UMD alpha (ann, t) | WF-OOS SR (yrs) | DSR fam (N) | PBO grid |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for book, pk in packs.items():
        n, g, s2, ab, wf = pk["net"], pk["gross"], pk["net2x"], pk["ab"], pk["wf"]
        L.append(
            f"| {book} | {n.get('start')} | {_f(n.get('sharpe'))} | {_f(g.get('sharpe'))} | {_f(s2.get('sharpe'))} | "
            f"{_f(n.get('ann_ret'), '.1%')} | {_f(n.get('t_nw'))} | {_f(n.get('max_dd'), '.1%')} | "
            f"{_f(ab.get('alpha_ann_vs_spy'), '.1%')} ({_f(ab.get('alpha_t_nw_vs_spy'))}) | {_f(ab.get('beta_spy'))} | "
            f"{_f(ab.get('alpha_ann_ff4'), '.1%')} ({_f(ab.get('alpha_t_nw_ff4'))}) | {_f(wf.get('sharpe'))} ({_f(wf.get('years'), '.1f')}) | "
            f"{_f(pk['dsr_family']['DSR'])} ({N_fam}) | {_f(pk['pbo_book_grid'].get('PBO'))} |"
        )
    L += ["", "![equity curve](equity_curve.png)", ""]
    # checklist for primary
    n, wf, d1, d2 = P["net"], P["wf"], P["dsr_family"], P["dsr_all"]
    ab = P["ab"]
    tr = P["turn"]
    cap = P["capacity"]
    yrs = P["years"]
    maxshare = yrs.share_of_total_pnl.max() if yrs.share_of_total_pnl.notna().any() else np.nan
    worst_reg = P["regimes"].sharpe.min() if len(P["regimes"]) else np.nan
    nb = P["neigh"]
    t_bar = 2.8
    hair = min(wf.get("sharpe", np.nan), 0.40 * is_sr) if is_sr else np.nan
    eval_years = len(P["daily"]) / 252
    checks = [
        (
            "§1 artefacts: rules, one-command code, trial log + TxN matrix, report/equity curve/trade list",
            "MET",
            "files listed above",
        ),
        (
            "§2 PIT universe incl. delisted names",
            "MET (with caveat)",
            f"PIT S&P 500 membership incl. 220 former members; ticker-reuse intervals (SNDK, AA, Q) excluded. Delisting returns only partly available: {len(P['delist'])} held positions hit a delisting; base = cash at last close; conservative-delisting SR {_f(P['alt'].get('open_clean+delist_conservative'))}, adverse {_f(P['alt'].get('open_clean+delist_adverse'))} (see Data-affected caveats)",
        ),
        (
            "§2 SIP volume, adjusted total-return prices",
            "MET",
            "SIP; ret_total_best; 12 suspect corporate-action days zeroed (results/suspect_returns.csv); no-clean SR "
            + _f(P["alt"].get("open_noclean")),
        ),
        (
            "§2 no look-ahead / next-bar open fills",
            "MET",
            f"signal at close t, fill at open t+1. Next-close alt SR {_f(P['alt'].get('close_clean'))}",
        ),
        (
            "§2 history >= 10 years",
            "NOT MET" if eval_years < 10 else "MET",
            f"bars 2016-01..2026-10 (10.8y) but lookbacks leave {eval_years:.1f}y of strategy returns",
        ),
        (
            "§3 OOS: walk-forward >= 5 folds spanning >= 3y, embargo >= 1 rebalance",
            "MET" if wf.get("folds", 0) >= 5 and wf.get("years", 0) >= 3 else "NOT MET",
            f"{wf.get('folds')} annual folds, {_f(wf.get('years'), '.1f')}y OOS, 21-session embargo; selection over the +/-20% grid. Caveat: the period was not untouched (v1 runs at 01:21 SGT and turn-1 runs on 2020+ IEX data are in the trial log)",
        ),
        (
            "§3 >= 30 independent OOS rebalance periods",
            "MET" if wf.get("oos_months", 0) >= 30 else "NOT MET",
            f"{wf.get('oos_months')} OOS months",
        ),
        (
            "§4 OOS Sharpe net > 0.5",
            "MET" if wf.get("sharpe", -9) > 0.5 else "NOT MET",
            f"WF-OOS net SR {_f(wf.get('sharpe'))}; full-sample net SR {_f(n.get('sharpe'))}",
        ),
        (
            "§4/§5 Sharpe > 0 at 2x costs",
            "MET" if P["net2x"].get("sharpe", -9) > 0 and wf.get("sharpe_2x", -9) > 0 else "NOT MET",
            f"full {_f(P['net2x'].get('sharpe'))}, WF-OOS {_f(wf.get('sharpe_2x'))}",
        ),
        (
            "§4 DSR >= 0.95",
            "MET" if d1["DSR"] >= 0.95 and d2["DSR"] >= 0.95 else "NOT MET",
            f"family N={d1['N']}: DSR {d1['DSR']:.3f}, SR0 {d1['SR0_ann']:.2f} ann; all-derivatives-researcher N={d2['N']}: DSR {d2['DSR']:.3f}, SR0 {d2['SR0_ann']:.2f}; T={d1['T']}, skew {d1['skew']:.2f}, kurt {d1['kurt']:.2f}",
        ),
        (
            "§4 t-stat >= 2.8 (replication of published anomaly; NW)",
            "MET" if n.get("t_nw", 0) >= t_bar else "NOT MET",
            f"t_NW {_f(n.get('t_nw'))} (iid {_f(n.get('t_iid'))})",
        ),
        (
            "§4 PBO < 0.20 (<= 0.05 for PASS)",
            "MET" if P["pbo_book_grid"].get("PBO", 1) < 0.2 else "NOT MET",
            f"book grid PBO {_f(P['pbo_book_grid'].get('PBO'))} (N={P['pbo_book_grid'].get('N')}); whole family PBO {_f(P['pbo_family'].get('PBO'))} (N={P['pbo_family'].get('N')}). N~11 per grid -> weakly informative",
        ),
        (
            "§5 costs >= validator minimums; borrow >= 1%/yr; exclude unborrowable",
            "MET (borrow caveat)",
            f"avg {tr['assumed_avg_cost_bps_per_side']:.1f} bps/side (TCA-owner-only {tr['tomas_only_avg_cost_bps']:.1f}); borrow 1%/yr; no PIT borrow history exists, so unborrowable names cannot be excluded at signal time",
        ),
        (
            "§6 post-publication haircut",
            "computed",
            f"expected SR for sizing = min(WF-OOS {_f(wf.get('sharpe'))}, 0.40 x {_f(is_sr)}) = {_f(hair)} ({is_note})",
        ),
        (
            "§7 no year > 40% of PnL",
            "MET" if maxshare <= 0.4 else "NOT MET",
            f"max year share {_f(maxshare, '.0%')} (n/a if total PnL <= 0)",
        ),
        ("§7 no regime Sharpe < -0.5", "MET" if worst_reg >= -0.5 else "NOT MET", f"worst regime SR {_f(worst_reg)}"),
        (
            "§7 +/-20% neighbourhood: SR > 0 and >= 50% of base",
            "MET" if nb.ok_full.all() else "NOT MET",
            f"{int(nb.ok_full.sum())}/{len(nb)} configs pass on full-sample net SR; {int(nb.ok_2022plus.sum())}/{len(nb)} on 2022+ net SR",
        ),
        (
            "§7 legs reported; correlation to book",
            "MET (book history 1 day)",
            f"long leg gross SR {_f(P['long_leg_gross'].get('sharpe'))}, short leg gross SR {_f(P['short_leg_gross'].get('sharpe'))}; desk book has 1 day of history, so correlations are vs SPY/FF factors and the validator's validation backtests",
        ),
        (
            "§8 trade size <= 1% of 20d ADV",
            "MET" if cap["max_participation"] <= 0.01 else "NOT MET",
            f"max {cap['max_participation']:.4%} at ${a.book:,.0f}; at 10x book max {cap['max_participation_at_10x_book']:.3%}",
        ),
        (
            "§8 break-even cost >= 2x assumed",
            "MET" if tr["breakeven_over_assumed"] >= 2 else "NOT MET",
            f"break-even {_f(tr['breakeven_cost_bps_per_side'], '.1f')} bps/side vs assumed {tr['assumed_avg_cost_bps_per_side']:.1f}",
        ),
    ]
    hard_fail = [c for c in checks if c[1].startswith("NOT MET")]
    L += [
        f"## STANDARD.md checklist for the primary book ({cfg['primary']})",
        "",
        "| requirement | status | evidence |",
        "|---|---|---|",
    ]
    L += [f"| {c[0]} | {c[1]} | {c[2]} |" for c in checks]
    L += [
        "",
        f"**Self-assessed verdict: {'FAIL' if hard_fail else 'candidate for CONDITIONAL PASS'}** "
        f"({len(hard_fail)} requirement(s) not met: {'; '.join(c[0] for c in hard_fail) or 'none'}). A FAIL is a verdict on evidence.",
        "",
    ]
    # details
    L += ["## Details per book", ""]
    for book, pk in packs.items():
        L += [
            f"### {book}",
            "",
            f"- Net {json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in pk['net'].items()})}",
            f"- Gross SR {_f(pk['gross'].get('sharpe'))}, 2x-cost SR {_f(pk['net2x'].get('sharpe'))}; long leg gross SR {_f(pk['long_leg_gross'].get('sharpe'))} "
            f"(ann {_f(pk['long_leg_gross'].get('ann_ret'), '.1%')}), short leg gross SR {_f(pk['short_leg_gross'].get('sharpe'))} (ann {_f(pk['short_leg_gross'].get('ann_ret'), '.1%')}).",
            f"- Market: {json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in pk['ab'].items()})}",
            f"- Gross-return beta vs SPY {_f(pk['ab_gross'].get('beta_spy'))}, gross alpha vs SPY {_f(pk['ab_gross'].get('alpha_ann_vs_spy'), '.1%')} (t {_f(pk['ab_gross'].get('alpha_t_nw_vs_spy'))}).",
            f"- Turnover/costs: {json.dumps({k: round(v, 3) for k, v in pk['turn'].items()})}",
            f"- Capacity: {json.dumps({k: round(float(v), 5) for k, v in pk['capacity'].items()})}",
            f"- Walk-forward: SR {_f(pk['wf'].get('sharpe'))}, t_NW {_f(pk['wf'].get('t_nw'))}, folds {pk['wf'].get('folds')}, picks {pk['wf_folds'].pick.tolist() if len(pk['wf_folds']) else []}, 2x SR {_f(pk['wf'].get('sharpe_2x'))}",
            f"- DSR (family N={pk['dsr_family']['N']}): {pk['dsr_family']['DSR']:.3f}; DSR (all derivatives researcher trials N={pk['dsr_all']['N']}): {pk['dsr_all']['DSR']:.3f}",
            f"- PBO grid {_f(pk['pbo_book_grid'].get('PBO'))} (N={pk['pbo_book_grid'].get('N')}), family {_f(pk['pbo_family'].get('PBO'))} (N={pk['pbo_family'].get('N')})",
            f"- Alt trials: next-close fill SR {_f(pk['alt'].get('close_clean'))}; no-clean data SR {_f(pk['alt'].get('open_noclean'))}; delisting returns table/conservative/adverse SR {_f(pk['alt'].get('open_clean+delist_table'))} / {_f(pk['alt'].get('open_clean+delist_conservative'))} / {_f(pk['alt'].get('open_clean+delist_adverse'))}",
            f"- Delisting exits while held: {len(pk['delist'])}"
            + (
                f" ({', '.join(pk['delist'].symbol.astype(str).head(12))}{'...' if len(pk['delist']) > 12 else ''})"
                if len(pk["delist"])
                else ""
            ),
            f"- Correlations: {json.dumps({k: round(float(v), 2) for k, v in pk['corr'].items() if pd.notna(v)})}",
            "",
            "Calendar years:",
            "",
            pk["years"].to_markdown(floatfmt=".3f"),
            "",
            "Regimes (labels lagged 1 day):",
            "",
            pk["regimes"].to_markdown(index=False, floatfmt=".2f"),
            "",
            "+/-20% neighbourhood (net SR):",
            "",
            pk["neigh"].to_markdown(index=False, floatfmt=".2f"),
            "",
        ]
    if fam == "bab" and "bab_info" in extra:
        bi = extra["bab_info"]
        L += [
            "### BAB beta neutrality and leverage (ex-ante, base params, per rebalance)",
            "",
            bi.describe().T[["mean", "min", "max"]].to_markdown(floatfmt=".2f"),
            "",
            "bab_fp is ex-ante beta-neutral by construction (legs levered to beta 1) but needs a long-leg gross of "
            f"{bi.lev_long_leg.mean():.2f}x and total gross {bi.fp_gross.mean():.2f}x NAV on average -> breaches the desk's no-leverage "
            "rule as specified. bab_q is dollar-neutral, NOT beta-neutral (ex-ante beta "
            f"{bi.q_exante_beta.mean():.2f}). Realised betas are in the headline table.",
            "",
        ]
    if imom_public is not None:
        L += [
            "### Public pre/post-2016 check (gross; desk data starts 2016)",
            "",
            imom_public[
                ["series", "window", "start", "end", "n", "mean_ann", "sharpe_ann", "t_stat", "max_dd"]
            ].to_markdown(index=False, floatfmt=".3f"),
            "",
        ]
        if "imom_stock_blocked" in extra:
            L += [
                f"Stock-level version: **BLOCKED**: {extra['imom_stock_blocked']} Code is ready (`build_targets_stock`); it runs automatically when PIT codes land (or `--force-stock-imom` for a labelled diagnostic).",
                "",
            ]
    L += data_caveats(fam, cfg, packs, extra)
    (sub / "SUBMISSION.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
