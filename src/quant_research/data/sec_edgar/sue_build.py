"""Build desk-wide PIT SUE control (COMMON C9 / derived/SPEC.md), v0.6 draft (2026-11-06 SGT).

Computes EPS panel, SUE (primary + drift variant), the announcement-return CONTROL input, and signal-only
coverage ONLY. No strategy/factor returns, no backtests, no joins to CVA/TSC/MXD signal outcomes.
All inputs are read from the immutable v1.3 release pin (common.STORE == releases/v1.3).

Availability (binding):
  * 8-K EX-99 GAAP diluted EPS: known at its 8-K acceptance tau (acceptance_datetime_et).
  * XBRL 3-month GAAP diluted EPS: known only at its own 10-Q/10-K acceptance (else Dmitri available_session
    09:29 ET, flagged). Never back-dated to the 8-K. No Q4 = FY - 9M anywhere.
  * Every lag in UE / sigma is the value AS KNOWN at tau_q (knowledge <= tau_q); avail_et = max knowledge of the
    numerator and all lags used (asserted == knowledge of the numerator).
  * Fiscal-period labels are point-in-time (pit_period.py).
  * Announcement-return control: usable only from the open of the session after reaction_session+1.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from quant_research.data.sec_edgar import common, pit_period

OUT = common.OUT
STORE = common.STORE
SPEC_VERSION = "sue_v0.6_draft"
SIGMA_FLOOR = 0.01
MIN_LAGS = 4  # of 8; COMMON C9
DDOF = 1
QTR_DAYS = 91.3125
LAG_TOL_DAYS = 20
GAAP_BASES = ["GAAP", "GAAP_stmt", "GAAP_implicit"]
EXCL_EVENT_TYPES = ["preannouncement_or_interim", "other_202_no_periodic"]


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_splits() -> dict[str, pd.DataFrame]:
    s = pd.read_parquet(STORE / "corporate_actions/splits.parquet").copy()
    s["ex_date"] = pd.to_datetime(s.ex_date)
    s["known_as_of_date"] = pd.to_datetime(s.known_as_of_date)
    s["split_ratio"] = s.split_ratio.astype(float)
    s = s[["symbol", "ex_date", "known_as_of_date", "split_ratio"]].dropna(subset=["ex_date", "split_ratio"])
    return {cast(str, k): g for k, g in s.groupby("symbol")}


def split_factor(
    splits: Mapping[str, pd.DataFrame],
    symbol: str,
    start_excl: pd.Timestamp,
    end_incl: pd.Timestamp,
    known_asof: pd.Timestamp,
) -> float:
    g = splits.get(symbol)
    if g is None:
        return 1.0
    m = (g.ex_date > start_excl) & (g.ex_date <= end_incl)
    m &= g.known_as_of_date.isna() | (g.known_as_of_date <= known_asof)
    r = g.loc[m, "split_ratio"]
    return float(cast(float, r.prod())) if len(r) else 1.0


def eligible_ex99(eps8k: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    e = eps8k.copy()
    e["acceptance_et"] = pd.to_datetime(e.acceptance_et)
    e["fiscal_period"] = pd.to_datetime(e.fiscal_period)
    steps = {"events": int(len(e))}
    m_gaap = e.eps_basis.isin(GAAP_BASES) & e.eps_diluted_reported.notna()
    steps["gaap_diluted_parsed"] = int(m_gaap.sum())
    m_pre = (e.is_preannouncement == True) | e.event_type.fillna("").isin(EXCL_EVENT_TYPES)
    steps["excluded_preannouncement_or_nonperiodic"] = int((m_gaap & m_pre).sum())
    m = m_gaap & ~m_pre
    lagd = (e.acceptance_et.dt.normalize() - e.fiscal_period).dt.days
    m_win = e.fiscal_period.notna() & (lagd > 0) & (lagd <= 100)
    steps["excluded_no_pit_period_or_outside_100d"] = int((m & ~m_win).sum())
    e1 = e[m & m_win].sort_values(["cik", "fiscal_period", "acceptance_et"])
    n0 = len(e1)
    e1 = e1.drop_duplicates(["cik", "fiscal_period"], keep="first")  # FIRST 8-K for period p
    steps["dropped_later_8k_same_period"] = int(n0 - len(e1))
    steps["eligible_ex99_rows"] = int(len(e1))
    out = pd.DataFrame(
        {
            "cik": e1.cik.astype(int),
            "ticker": e1.ticker,
            "period_end": e1.fiscal_period,
            "eps": e1.eps_diluted_reported.astype(float),
            "eps_source": "ex99",
            "knowledge_et": e1.acceptance_et,
            "knowledge_src": "8k_acceptance",
            "accession": e1.accession,
            "reaction_session": pd.to_datetime(e1.reaction_session),
            "fiscal_period_src": e1.get("fiscal_period_src"),
        }
    )
    return out, steps


def xbrl_rows(xq: pd.DataFrame) -> pd.DataFrame:
    x = xq.copy()
    assert (x.derivation == "reported_3m").all(), "FY-9M or derived row present"
    return pd.DataFrame(
        {
            "cik": x.cik.astype(int),
            "ticker": x.ticker,
            "period_end": pd.to_datetime(x.period_end),
            "eps": x.eps_diluted_xbrl.astype(float),
            "eps_source": "xbrl",
            "knowledge_et": pd.to_datetime(x.knowledge_et_eff),
            "knowledge_src": x.knowledge_src,
            "accession": x.accession_10q10k,
            "reaction_session": pd.NaT,
            "fiscal_period_src": "xbrl",
        }
    )


def build_panels(ex: pd.DataFrame, xb: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    hist = pd.concat([ex, xb], ignore_index=True)
    hist["_pref"] = (hist.eps_source != "ex99").astype(int)
    hist = hist.sort_values(["cik", "period_end", "_pref", "knowledge_et"])
    # numerator per (cik, period): 8-K value if one exists, else XBRL (at its own acceptance)
    preferred = hist.drop_duplicates(["cik", "period_end"], keep="first").drop(columns="_pref").reset_index(drop=True)
    return preferred, hist.drop(columns="_pref").reset_index(drop=True)


def build_sue(preferred: pd.DataFrame, history: pd.DataFrame, splits: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    H: dict[Any, tuple[Any, Any, Any, Any, Any]] = {}
    for c, g in history.groupby("cik"):
        H[c] = (
            g.period_end.values.astype("datetime64[ns]"),
            g.knowledge_et.values.astype("datetime64[ns]"),
            g.eps.values.astype(float),
            (g.eps_source == "ex99").values,
            g.eps_source.values,
        )
    tol = np.timedelta64(LAG_TOL_DAYS, "D")
    rows = []
    for raw in preferred.itertuples(index=False):
        r = cast(Any, raw)  # itertuples cells are vendor scalars
        PE, KN, EPS, ISX, SRC = H[r.cik]
        pe, asof = pd.Timestamp(r.period_end), pd.Timestamp(r.knowledge_et)
        known = np.datetime64(asof) >= KN  # AS-OF tau_q: only values public at the numerator's time
        pes = np.unique(PE[known])
        base = {
            **r._asdict(),
            "sue": np.nan,
            "ue": np.nan,
            "sigma": np.nan,
            "n_lags": 0,
            "sue_drift": np.nan,
            "floored_sigma": False,
            "mixed_source": False,
            "lag_max_knowledge_et": pd.NaT,
            "eps_lag4": np.nan,
            "eps_lag4_source": None,
        }

        def val(k: int) -> tuple[float, str, pd.Timestamp, np.datetime64] | None:
            if not len(pes):
                return None
            tgt = np.datetime64(pe - pd.Timedelta(days=QTR_DAYS * k))
            d = np.abs(pes - tgt)
            j = int(np.argmin(d))
            if d[j] > tol:
                return None
            p = pes[j]
            m = known & (p == PE)
            if (m & ISX).any():
                m = m & ISX
            idx = np.where(m)[0]
            idx = idx[np.argmin(KN[idx])]  # earliest filing among those known
            fac = split_factor(splits, r.ticker, pd.Timestamp(p), pe, asof)
            return cast(
                tuple[float, str, pd.Timestamp, np.datetime64],
                (float(EPS[idx]) * fac, SRC[idx], pd.Timestamp(KN[idx]), p),
            )

        l4 = val(4)
        if l4 is None:
            rows.append({**base, "reason": "missing_eps_lag4_asof"})
            continue
        used = [l4]
        ue = float(cast(float, r.eps)) - l4[0]
        ues = []
        for j in range(1, 9):
            a, b = val(j), val(j + 4)
            if a is None or b is None:
                continue
            ues.append(a[0] - b[0])
            used += [a, b]
        srcs = {r.eps_source} | {u[1] for u in used}
        lagmax = max(u[2] for u in used)
        assert lagmax <= asof, (r.cik, pe)
        base.update(
            ue=ue,
            n_lags=len(ues),
            mixed_source=len(srcs) > 1,
            lag_max_knowledge_et=lagmax,
            eps_lag4=l4[0],
            eps_lag4_source=l4[1],
        )
        if len(ues) < MIN_LAGS:
            rows.append({**base, "reason": "insufficient_sigma_lags"})
            continue
        sigma = float(np.std(ues, ddof=DDOF))
        floored = sigma < SIGMA_FLOOR
        sigma = max(sigma, SIGMA_FLOOR)
        base.update(
            sigma=sigma,
            floored_sigma=floored,
            sue=ue / sigma,
            sue_drift=(ue - float(np.mean(ues))) / sigma,
            reason="ok",
        )
        rows.append(base)
    df = pd.DataFrame(rows)
    df["avail_et"] = df[["knowledge_et", "lag_max_knowledge_et"]].max(axis=1)
    return df


def announcement_control(spine: pd.DataFrame) -> pd.DataFrame:
    """Control (a) input: stock TR - SPY TR, close(session before reaction_session) -> close(reaction_session+1).
    One row per eligible quarterly 8-K event (independent of EPS parse). usable_session = next session open."""
    tr = pd.read_parquet(
        STORE / "bars/daily/total_return/daily_total_return.parquet",
        columns=["symbol", "session_date", "ret_total_best"],
    )
    tr["session_date"] = pd.to_datetime(tr.session_date)
    lr = {s: g.set_index("session_date").ret_total_best for s, g in tr.groupby("symbol")}
    sess = common.sessions()
    sv = sess.values
    out = []
    for raw in spine.itertuples(index=False):
        r = cast(Any, raw)  # itertuples cells are vendor scalars
        rs = pd.Timestamp(r.reaction_session) if pd.notna(r.reaction_session) else None
        rec = dict(
            accession=r.accession,
            cik=r.cik,
            ticker=r.ticker,
            acceptance_et=r.acceptance_et,
            reaction_session=rs,
            ann_ret=np.nan,
        )
        if rs is None:
            out.append({**rec, "ann_ret_reason": "missing_reaction_session"})
            continue
        p = np.searchsorted(sv, np.datetime64(rs), side="left")
        p2 = np.searchsorted(sv, np.datetime64(rs), side="right")
        if p == 0 or p2 + 1 >= len(sv):
            out.append({**rec, "ann_ret_reason": "window_outside_calendar"})
            continue
        start, end, usable = pd.Timestamp(sv[p - 1]), pd.Timestamp(sv[p2]), pd.Timestamp(sv[p2 + 1])
        rec.update(ann_window_start_excl=start, ann_window_end=end, usable_session=usable)
        s, mkt = lr.get(r.ticker), cast(pd.Series, lr.get("SPY"))
        if s is None:
            out.append({**rec, "ann_ret_reason": "no_bars_for_symbol"})
            continue
        ws = s[(s.index > start) & (s.index <= end)]
        wm = mkt[(mkt.index > start) & (mkt.index <= end)]
        if len(ws) != len(wm) or len(ws) == 0 or ws.isna().any():
            out.append({**rec, "ann_ret_reason": "missing_bars"})
            continue
        rec["ann_ret"] = float(cast(float, (1 + ws).prod()) - cast(float, (1 + wm).prod()))
        out.append({**rec, "ann_ret_reason": "ok"})
    return pd.DataFrame(out)


def coverage_report(sue: pd.DataFrame, ann: pd.DataFrame) -> pd.DataFrame:
    mem = pd.read_parquet(STORE / "universe/sp500_membership.parquet")
    mem["start"] = pd.to_datetime(mem.start_date_filled.fillna(mem.start_date))
    mem["end"] = pd.to_datetime(mem.end_date)
    sess = common.sessions()
    sv = sess.values
    ok = sue[sue.reason == "ok"].copy()
    ok["avail_session"] = common.knowledge_session(ok.avail_et, sess).values  # for the 130-session age rule
    a = ann[ann.ann_ret_reason == "ok"].copy()
    rows = []
    for me in pd.date_range("2017-01-31", "2026-10-31", freq="ME"):
        pos = cast(int, np.searchsorted(sv, np.datetime64(me), side="right") - 1)
        form = pd.Timestamp(sv[pos])
        cutoff = form + pd.Timedelta(hours=16)
        members = set(mem[(mem.start <= form) & (mem.end.isna() | (mem.end > form))].symbol)
        lb = pd.Timestamp(sv[max(0, pos - 130)])
        av = ok[(ok.avail_et < cutoff) & (ok.avail_session >= lb)]
        av = av.sort_values("avail_et").drop_duplicates("cik", keep="last")
        av = av[av.ticker.isin(members)]
        lb63 = pd.Timestamp(sv[max(0, pos - 63)])
        aa = a[(a.usable_session <= form) & (a.reaction_session >= lb63)]
        aa = aa.sort_values("usable_session").drop_duplicates("cik", keep="last")
        aa = aa[aa.ticker.isin(members)]
        n = len(av)
        rows.append(
            dict(
                formation_date=form.date(),
                year=form.year,
                month=form.month,
                n_members=len(members),
                n_sue=n,
                pass_300=n >= 300,
                dropped=n < 300,
                n_annret=len(aa),
                share_ex99=(av.eps_source == "ex99").mean() if n else np.nan,
                share_xbrl_fallback=(av.eps_source == "xbrl").mean() if n else np.nan,
                share_mixed=av.mixed_source.mean() if n else np.nan,
                share_floored_sigma=av.floored_sigma.mean() if n else np.nan,
                stage=(
                    "A"
                    if form <= pd.Timestamp("2021-11-30")
                    else ("embargo" if form <= pd.Timestamp("2022-11-30") else "B")
                ),
            )
        )
    return pd.DataFrame(rows)


def gap_classes(
    eps8k: pd.DataFrame,
    steps: Mapping[str, int],
    sue: pd.DataFrame,
    ann: pd.DataFrame,
    cov: pd.DataFrame,
) -> dict[str, Any]:
    mem = pd.read_parquet(STORE / "universe/sp500_membership.parquet")
    e = eps8k
    aa_evhc = {}
    for cik, sym in [(1675149, "AA"), (1578318, "EVHC")]:
        ev = e[e.cik.astype(int) == cik]
        mm = mem[mem.symbol == sym]
        inside = 0
        for t in pd.to_datetime(ev.acceptance_et):
            st = pd.to_datetime(mm.start_date_filled.fillna(mm.start_date))
            en = pd.to_datetime(mm.end_date)
            inside += int(((st <= t) & (en.isna() | (en > t))).any())
        aa_evhc[sym] = dict(cik=cik, v13_8k_events=int(len(ev)), inside_pit_membership_by_symbol=inside)
    ok = sue.reason == "ok"
    return {
        "funnel": steps,
        "eps_basis_all_events": e.eps_basis.value_counts(dropna=False).to_dict(),
        "no_ex99_events_8k_body_used": int((e.ex99_rule == "primary_doc_url fallback").sum()),
        "no_ex99_events_gaap_parsed": int(
            ((e.ex99_rule == "primary_doc_url fallback") & e.eps_basis.isin(GAAP_BASES)).sum()
        ),
        "event_type_unjoined_nan": int(e.event_type.isna().sum()),
        "unlabeled_per_share_rejected": int((e.eps_basis == "unlabeled-per-share").sum()),
        "adjusted_only_rejected": int((e.eps_basis == "adjusted").sum()),
        "no_eps_parsed": int((e.eps_basis == "none").sum()),
        "fiscal_period_src_all_events": e.fiscal_period_src.value_counts(dropna=False).to_dict(),
        "fiscal_period_pit_vs_expost_agree_share": float(
            (e.fiscal_period == e.fiscal_period_expost)[e.fiscal_period.notna() & e.fiscal_period_expost.notna()].mean()
        ),
        "fiscal_period_pit_missing_expost_present": int(
            (e.fiscal_period.isna() & e.fiscal_period_expost.notna()).sum()
        ),
        "sue_reason_counts": sue.reason.value_counts().to_dict(),
        "xbrl_available_session_fallback_share_of_ok_numerators": float(
            (sue.loc[ok, "knowledge_src"] == "available_session_fallback").mean()
        ),
        "annret_reason_counts": ann.ann_ret_reason.value_counts().to_dict(),
        "aa_evhc_reconciliation": aa_evhc,
        "ethan_v1_v2_used_for_values": False,
        "ex99_rule_ethan_v1_additive_rows": int((e.ex99_rule == "ethan_v1_additive").sum()),
    }


def main() -> None:
    eps8k = pd.read_parquet(OUT / "eps8k_full_with_validation.parquet")
    xq = pd.read_parquet(OUT / "xbrl_eps_quarterly.parquet")
    splits = load_splits()
    eps8k["fiscal_period_expost"] = pd.to_datetime(eps8k.fiscal_period)
    eps8k = pit_period.assign_fiscal_period_pit(eps8k, xq)
    eps8k.to_parquet(OUT / "eps8k_full_pit.parquet", index=False)
    ex, steps = eligible_ex99(eps8k)
    xb = xbrl_rows(xq)
    preferred, history = build_panels(ex, xb)
    preferred.to_parquet(OUT / "eps_preferred_panel.parquet", index=False)
    history.to_parquet(OUT / "eps_history_panel.parquet", index=False)
    sue = build_sue(preferred, history, splits)
    sue["avail_session"] = common.knowledge_session(sue.avail_et, common.sessions()).values
    sue.to_parquet(OUT / "sue_events.parquet", index=False)
    ok = sue.reason == "ok"
    sue.loc[
        ok,
        [
            "cik",
            "ticker",
            "period_end",
            "knowledge_et",
            "avail_et",
            "avail_session",
            "sue",
            "sue_drift",
            "eps_source",
            "mixed_source",
            "floored_sigma",
        ],
    ].to_parquet(OUT / "sue_drift_variant.parquet", index=False)
    # announcement control spine: eligible quarterly 8-K events (not preannouncement), independent of EPS parse
    sp = eps8k.copy()
    sp["acceptance_et"] = pd.to_datetime(sp.acceptance_et)
    sp = sp[~((sp.is_preannouncement == True) | sp.event_type.fillna("").isin(EXCL_EVENT_TYPES))]
    sp["reaction_session"] = pd.to_datetime(sp.reaction_session)
    sp["cik"] = sp.cik.astype(int)
    ann = announcement_control(sp)
    ann.to_parquet(OUT / "sue_annret_control.parquet", index=False)
    cov = coverage_report(sue, ann)
    cov.to_parquet(OUT / "sue_monthly_coverage.parquet", index=False)
    cov.to_csv(OUT / "sue_monthly_coverage.csv", index=False)
    fb = sue[ok & (sue.eps_source == "xbrl")]
    gaps = gap_classes(eps8k, steps, sue, ann, cov)

    def yr(c: pd.DataFrame, lo: int, hi: int) -> dict[str, int | float]:
        c = c[(c.year >= lo) & (c.year <= hi)]
        return dict(
            months=int(len(c)),
            pass_300=int(c.pass_300.sum()),
            dropped=int(c.dropped.sum()),
            mean_n_sue=round(float(c.n_sue.mean()), 1),
            min_n_sue=int(c.n_sue.min()),
            max_n_sue=int(c.n_sue.max()),
            mean_n_members=round(float(c.n_members.mean()), 1),
            mean_share_xbrl_fallback=round(float(c.share_xbrl_fallback.mean()), 4),
        )

    stB = cov[cov.stage == "B"]
    log = {
        "spec_version": SPEC_VERSION,
        "data_release_id": common.DATA_RELEASE_ID,
        "data_release_top_hash": common.RELEASE_TOP_HASH,
        "coverage_complete": False,
        "coverage_complete_reason": "real gaps persist (see gap_classes + coverage mean_n_members - mean_n_sue): 8-K events "
        "without a usable GAAP diluted EPS (none/unlabeled/adjusted-only), events without a PIT "
        "fiscal period, PIT members with no SUE in the 130-session window, ticker-grain membership "
        "join. AA/EVHC are NOT a gap (outside/before PIT membership; Victor v2 review 2.3). "
        "Not Victor-reviewed / not Dmitri-promoted.",
        "not_a_frozen_complete_sue_input": True,
        "event_spine": "v1.3 edgar_8k_202 (form 8-K) + earnings_events; Ethan v1/v2 NOT used for values",
        "input_hashes": {
            "eps8k_full_with_validation": _sha(OUT / "eps8k_full_with_validation.parquet"),
            "xbrl_eps_quarterly": _sha(OUT / "xbrl_eps_quarterly.parquet"),
            "edgar_8k_202": _sha(common.earnings_path("edgar_8k_202.parquet")),
            "edgar_10q10k": _sha(common.earnings_path("edgar_10q10k.parquet")),
            "earnings_events": _sha(common.earnings_path("earnings_events.parquet")),
            "xbrl_facts_v13": _sha(STORE / "fundamentals/xbrl_facts.parquet"),
            "splits_v13": _sha(STORE / "corporate_actions/splits.parquet"),
            "sp500_membership_v13": _sha(STORE / "universe/sp500_membership.parquet"),
            "daily_total_return_v13": _sha(STORE / "bars/daily/total_return/daily_total_return.parquet"),
            "spy_raw_v13_calendar": _sha(STORE / "bars/daily/raw/SPY.parquet"),
        },
        "n_eps8k_rows": int(len(eps8k)),
        "n_preferred": int(len(preferred)),
        "preferred_source": preferred.eps_source.value_counts().to_dict(),
        "n_sue_ok": int(ok.sum()),
        "n_sue_total": int(len(sue)),
        "fallback_share_among_ok": float((sue.loc[ok, "eps_source"] == "xbrl").mean()),
        "fallback_share_among_ok_by_year": sue[ok]
        .groupby(pd.to_datetime(sue[ok].avail_et).dt.year)
        .eps_source.apply(lambda s: round(float((s == "xbrl").mean()), 4))
        .to_dict(),
        "fallback_median_lag_days_vs_8k_tau": None,
        "mixed_share_among_ok": float(sue.loc[ok, "mixed_source"].mean()),
        "floored_sigma_share_among_ok": float(sue.loc[ok, "floored_sigma"].mean()),
        "availability_assert_lags_le_numerator": bool(
            (sue.loc[ok, "lag_max_knowledge_et"] <= sue.loc[ok, "knowledge_et"]).all()
        ),
        "extractor_match_rate_vs_xbrl_all": float(
            eps8k.loc[eps8k.xbrl_match.notna(), "xbrl_match"].astype(bool).mean()
        ),
        "extractor_match_rate_vs_xbrl_gaap": float(
            eps8k.loc[eps8k.xbrl_match.notna() & eps8k.eps_basis.isin(GAAP_BASES), "xbrl_match"].astype(bool).mean()
        ),
        "n_extractor_xbrl_comparable": int(eps8k.xbrl_match.notna().sum()),
        "coverage_2017_2026": yr(cov, 2017, 2026),
        "coverage_2017_2018": yr(cov, 2017, 2018),
        "coverage_by_year": {int(y): yr(cov, y, y) for y in sorted(cov.year.unique())},
        "stage_B_months": int(len(stB)),
        "stage_B_dropped": int(stB.dropped.sum()),
        "stage_B_dropped_share": float(stB.dropped.mean()),
        "dropped_months": cov[cov.dropped][["formation_date", "n_sue", "stage"]].astype(str).to_dict("records"),
        "gap_classes": gaps,
        "strategy_returns_computed": False,
    }
    # fallback lag vs the same period's 8-K tau (only where an 8-K event exists but EPS was not usable)
    sp8 = eps8k[eps8k.fiscal_period.notna()][["cik", "fiscal_period", "acceptance_et"]].copy()
    sp8["cik"] = sp8.cik.astype(int)
    sp8["acceptance_et"] = pd.to_datetime(sp8.acceptance_et)
    sp8 = sp8.sort_values("acceptance_et").drop_duplicates(["cik", "fiscal_period"])
    j = fb.merge(sp8, left_on=["cik", "period_end"], right_on=["cik", "fiscal_period"], how="inner")
    if len(j):
        log["fallback_median_lag_days_vs_8k_tau"] = float(
            ((j.knowledge_et - j.acceptance_et).dt.total_seconds() / 86400).median()
        )
        log["fallback_rows_with_8k_event"] = int(len(j))
    json.dump(log, open(OUT / "sue_build.log.json", "w"), indent=1, default=str)
    print(
        json.dumps(
            {
                k: log[k]
                for k in [
                    "n_sue_ok",
                    "fallback_share_among_ok",
                    "coverage_2017_2026",
                    "coverage_2017_2018",
                    "stage_B_dropped",
                ]
            },
            indent=1,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
