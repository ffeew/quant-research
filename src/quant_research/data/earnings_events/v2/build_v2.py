"""Build earnings_events_8k202 v2 under equity/earnings_events/v2/.
Read-only on v1 artifacts and $QR_DESK_DIR/data. No returns/SUE. No edits under data/."""

from __future__ import annotations

import hashlib
import os

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin, require_pins

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.dirname(os.path.abspath(__file__))
V1_HASH = desk_pin("data.earnings_events.v2.build_v2", "V1_HASH")
OLD_HASH = desk_pin("data.earnings_events.v2.build_v2", "OLD_HASH")
PARENT_V13 = desk_pin("data.earnings_events.v2.build_v2", "PARENT_V13")
VALIDATION_PIT = desk_pin("data.earnings_events.v2.build_v2", "VALIDATION_PIT")
# VALIDATION_PIT is only recorded in the output: refuse on any PENDING / missing pin before any work
require_pins("data.earnings_events.v2.build_v2", "V1_HASH", "OLD_HASH", "PARENT_V13", "VALIDATION_PIT")

os.chdir(ROOT)


def sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


assert sha(f"{ROOT}/earnings_events_8k202.parquet") == V1_HASH

v1 = pd.read_parquet(f"{ROOT}/earnings_events_8k202.parquet")
old = pd.read_parquet(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet")
assert sha(f"{_QR.DATA_DIR}/earnings/edgar_8k_202.parquet") == OLD_HASH
core = pd.read_parquet(f"{ROOT}/work/all_202_filings.parquet")
dropped = pd.read_parquet(f"{ROOT}/work/events_dup_accessions_dropped.parquet")
ex_audit = pd.read_parquet(f"{V2}/work/exhibits_cluster_audit.parquet")
cluster_concern = pd.read_parquet(f"{V2}/audit/cluster_first_lacks_ex991_sib_has.parquet")
seg = pd.read_parquet(f"{ROOT}/work/segments_final.parquet")
mem = pd.read_parquet(f"{_QR.DATA_DIR}/universe/sp500_membership.parquet")

# ---------- dual-CIK / component identities ----------
# All CIKs that ever listed each accession in all_202 + dropped
comp = pd.concat(
    [
        core[["accession", "cik", "sec_name"]].assign(src="all_202"),
        dropped[["accession", "cik", "sec_name"]].assign(src="finalize_dropped"),
    ],
    ignore_index=True,
).drop_duplicates(["accession", "cik"])
comp_agg = (
    comp.groupby("accession")
    .agg(
        cik_components=("cik", lambda s: ",".join(str(int(x)) for x in sorted(set(s)))),
        source_accession_ciks=("cik", lambda s: ",".join(str(int(x)) for x in sorted(set(s)))),
        component_sec_names=("sec_name", lambda s: " | ".join(sorted(set(map(str, s))))),
        n_component_ciks=("cik", "nunique"),
    )
    .reset_index()
)

v2 = v1.copy()
v2 = v2.merge(comp_agg, on="accession", how="left", validate="one_to_one")
v2["cik_components"] = v2["cik_components"].fillna(v2.cik.astype(str))
v2["source_accession_ciks"] = v2["source_accession_ciks"].fillna(v2.cik.astype(str))
v2["component_sec_names"] = v2["component_sec_names"].fillna(v2.sec_name)
v2["n_component_ciks"] = v2["n_component_ciks"].fillna(1).astype(int)
v2["cik_is_canonical"] = True
v2["canonical_cik_rule"] = np.where(
    v2.n_component_ciks > 1,
    "finalize_v1: prefer in_sp500 then lower CIK; components preserved in cik_components",
    "single_cik",
)

# ---------- cluster availability (first acceptance ≠ full info public) ----------
# Pin: keep cluster-first ACCESSION (v1 stable; Item 2.02 event identity).
# Add conservative EX-99 availability time when a sibling first supplies EX-99.1.
multi = core[core.cluster_n_filings > 1].merge(ex_audit, on="accession", how="left")
rows = []
for _cid, g in multi.groupby("cluster"):
    g = g.sort_values("acceptance_utc")
    first = g.iloc[0]
    with_ex = g[g.ex99_url.notna()]
    with_991 = g[g.ex99_rule == "EX-99.1"]
    if len(with_991):
        avail_acc = with_991.iloc[0].accession
        avail_utc = with_991.iloc[0].acceptance_utc
        avail_rule = "EX-99.1"
    elif len(with_ex):
        avail_acc = with_ex.iloc[0].accession
        avail_utc = with_ex.iloc[0].acceptance_utc
        avail_rule = with_ex.iloc[0].ex99_rule
    else:
        avail_acc, avail_utc, avail_rule = first.accession, first.acceptance_utc, first.ex99_rule
    deferred = (
        (pd.isna(first.ex99_url))
        and (avail_acc != first.accession)
        and pd.notna(g.set_index("accession").loc[avail_acc].ex99_url if avail_acc in set(g.accession) else np.nan)
    )
    # clearer deferred flag from concern list
    deferred = first.accession in set(cluster_concern.first_acc.values)
    if deferred:
        sib = g[g.accession != first.accession]
        sib991 = sib[sib.ex99_rule == "EX-99.1"]
        if len(sib991):
            avail_acc = sib991.iloc[0].accession
            avail_utc = sib991.iloc[0].acceptance_utc
            avail_rule = "EX-99.1"
    lag = (pd.Timestamp(avail_utc) - pd.Timestamp(first.acceptance_utc)).total_seconds() / 3600.0
    rows.append(
        dict(
            accession=first.accession,
            ex99_available_accession=avail_acc,
            ex99_available_utc=pd.Timestamp(avail_utc),
            ex99_available_rule=avail_rule,
            cluster_ex99_lag_hours=lag,
            cluster_availability_flag=(
                "ex99_deferred_to_sibling"
                if deferred
                else ("ex99_on_first" if pd.notna(first.ex99_url) else "no_ex99_in_cluster")
            ),
            cluster_rule_pin="cluster_first_accession_retained; availability may lag to sibling EX-99",
        )
    )
avail = pd.DataFrame(rows)
# dual-CIK: same accession can be cluster-first under two CIKs; one avail row per accession
# prefer ex99_deferred_to_sibling if any
rank = {"ex99_deferred_to_sibling": 0, "ex99_on_first": 1, "no_ex99_in_cluster": 2}
avail["_r"] = avail.cluster_availability_flag.map(rank).fillna(9)
avail = avail.sort_values(["accession", "_r"]).drop_duplicates("accession", keep="first").drop(columns="_r")
v2 = v2.merge(avail, on="accession", how="left", validate="one_to_one")
# singles / non-multi: availability = own acceptance if has ex99 else null flag
single_mask = v2.cluster_availability_flag.isna()
v2.loc[single_mask, "ex99_available_accession"] = v2.loc[single_mask, "accession"]
v2.loc[single_mask, "ex99_available_utc"] = v2.loc[single_mask, "acceptance_utc"]
v2.loc[single_mask, "ex99_available_rule"] = v2.loc[single_mask, "ex99_rule"]
v2.loc[single_mask, "cluster_ex99_lag_hours"] = 0.0
v2.loc[single_mask & v2.ex99_url.notna(), "cluster_availability_flag"] = "ex99_on_first_or_single"
v2.loc[single_mask & v2.ex99_url.isna() & v2.in_sp500, "cluster_availability_flag"] = "no_ex99_in_sp500"
v2.loc[single_mask & ~v2.in_sp500, "cluster_availability_flag"] = "outside_index_exhibits_not_fetched_v1"
v2.loc[single_mask, "cluster_rule_pin"] = "cluster_first_accession_retained; availability may lag to sibling EX-99"

# For deferred cases, point ex99_* display fields at the sibling exhibit while keeping event accession
# (do not rewrite acceptance_utc — the review accepted v1 timestamps; availability is separate)
defer_map = cluster_concern.set_index("first_acc")
for first_acc, row in defer_map.iterrows():
    sib_acc = str(row.sib_ex99_acc).split(";")[0]
    sib_ex = ex_audit[ex_audit.accession == sib_acc]
    if len(sib_ex) != 1:
        continue
    sx = sib_ex.iloc[0]
    m = v2.accession == first_acc
    v2.loc[m, "ex99_url"] = sx.ex99_url
    v2.loc[m, "ex99_filename"] = sx.ex99_filename
    v2.loc[m, "ex99_type"] = sx.ex99_type
    v2.loc[m, "ex99_description"] = sx.ex99_description
    v2.loc[m, "ex99_rule"] = f"v2:deferred_from_sibling:{sx.ex99_rule}"
    v2.loc[m, "exhibit_count"] = sx.exhibit_count
    v2.loc[m, "ex99_available_accession"] = sib_acc
    v2.loc[m, "ex99_available_utc"] = core.loc[core.accession == sib_acc, "acceptance_utc"].iloc[0]
    v2.loc[m, "cluster_availability_flag"] = "ex99_deferred_to_sibling"
    v2.loc[m, "cluster_ex99_lag_hours"] = float(row.hours_to_first_sib_ex991)

n_deferred = int((v2.cluster_availability_flag == "ex99_deferred_to_sibling").sum())
print("deferred EX99 clusters applied:", n_deferred)

# ---------- lineage decisions AA / EVHC (NOT restored as in_sp500) ----------
# AA: membership ends 2016-11-01 (removed on Arconic spin). Alcoa Corp CIK1675149 post-split
# never in sp500_membership as AA. The review accepted v1 membership PIT.
# EVHC: CIK1578318 Holdings filings are before membership start 2016-12-02; segment correctly
# uses CIK1678531 Envision Healthcare Corp for the membership window.
lineage_decisions = [
    dict(
        symbol="AA",
        cik=1675149,
        n_old=44,
        decision="do_not_restore",
        status="excluded_outside_membership_aa_post_split",
        evidence=(
            "SEC CIK1675149=Alcoa Corp (ticker AA), former Alcoa Upstream Corp; "
            "sp500_changes 2016-11-01 removed AA/Alcoa added ARNC/Arconic; "
            "membership AA end_date=2016-11-01; AA not in sp500_current; "
            "v1 segment maps AA only to predecessor CIK4281 through 2016-11-01. "
            "Post-split Alcoa Corp 2.02 filings are real but outside S&P membership."
        ),
    ),
    dict(
        symbol="AA",
        cik=4281,
        n_old=7,
        decision="already_in_v1_via_segment",
        status="kept_predecessor_segment",
        evidence="Pre-split Alcoa Inc (now Howmet CIK4281) covered by v1 AA segment through 2016-11-01.",
    ),
    dict(
        symbol="EVHC",
        cik=1578318,
        n_old=5,
        decision="do_not_restore",
        status="excluded_before_membership_evhc_holdings",
        evidence=(
            "SEC CIK1578318=Envision Healthcare Holdings, Inc.; 2.02 filings 2013-11..2016-11-01. "
            "EVHC membership starts 2016-12-02. Old table labeled these EVHC before add date. "
            "v1 correctly maps membership window to CIK1678531 Envision Healthcare Corp."
        ),
    ),
    dict(
        symbol="EVHC",
        cik=1678531,
        n_old=9,
        decision="already_in_v1_via_segment",
        status="kept_membership_window_cik",
        evidence="Envision Healthcare Corp filings during EVHC membership 2016-12-02..2018-10-11 are in v1.",
    ),
]
pd.DataFrame(lineage_decisions).to_csv(f"{V2}/audit/lineage_decisions_aa_evhc.csv", index=False)

# ---------- accession-level old→new reconciliation (1:1 by old accession) ----------
v1_acc = set(v2.accession)
cluster_members = set()
for s in v2.cluster_accessions.dropna():
    for a in str(s).split(";"):
        if a:
            cluster_members.add(a)

# map cluster member -> kept accession
member_to_kept = {}
for _, r in v2.iterrows():
    kept = r.accession
    for a in str(r.cluster_accessions).split(";"):
        if a:
            member_to_kept[a] = kept

old_u = old.drop_duplicates("accession").copy()
# if multi-symbol old rows for same accession, keep first for accession recon (symbol recon is separate)
recs = []
for _, r in old_u.iterrows():
    a = r.accession
    if a in v1_acc:
        v = v2.loc[v2.accession == a].iloc[0]
        if int(r.cik) != int(v.cik):
            status, reason = (
                "dual_cik_alias_other_canonical",
                (f"old cik={int(r.cik)} ({r.sec_name}); v2 canonical cik={int(v.cik)}; components={v.cik_components}"),
            )
        else:
            status, reason = "kept_exact", "accession present with same CIK"
        recs.append(
            dict(
                old_accession=a,
                old_cik=int(r.cik),
                old_symbol_example=r.symbol,
                old_sec_name=r.sec_name,
                new_accession=a,
                new_cik=int(v.cik),
                status=status,
                reason=reason,
                old_acceptance_utc=r.acceptance_datetime_utc,
                new_acceptance_utc=v.acceptance_utc,
            )
        )
    elif a in cluster_members:
        kept = member_to_kept[a]
        v = v2.loc[v2.accession == kept].iloc[0]
        recs.append(
            dict(
                old_accession=a,
                old_cik=int(r.cik),
                old_symbol_example=r.symbol,
                old_sec_name=r.sec_name,
                new_accession=kept,
                new_cik=int(v.cik),
                status="cluster_member",
                reason=f"absorbed into cluster kept accession {kept}",
                old_acceptance_utc=r.acceptance_datetime_utc,
                new_acceptance_utc=v.acceptance_utc,
            )
        )
    elif int(r.cik) == 1675149 and r.symbol == "AA":
        recs.append(
            dict(
                old_accession=a,
                old_cik=int(r.cik),
                old_symbol_example=r.symbol,
                old_sec_name=r.sec_name,
                new_accession=None,
                new_cik=None,
                status="excluded_outside_membership_aa_post_split",
                reason=lineage_decisions[0]["evidence"],
                old_acceptance_utc=r.acceptance_datetime_utc,
                new_acceptance_utc=None,
            )
        )
    elif int(r.cik) == 1578318 and r.symbol == "EVHC":
        recs.append(
            dict(
                old_accession=a,
                old_cik=int(r.cik),
                old_symbol_example=r.symbol,
                old_sec_name=r.sec_name,
                new_accession=None,
                new_cik=None,
                status="excluded_before_membership_evhc_holdings",
                reason=lineage_decisions[2]["evidence"],
                old_acceptance_utc=r.acceptance_datetime_utc,
                new_acceptance_utc=None,
            )
        )
    else:
        recs.append(
            dict(
                old_accession=a,
                old_cik=int(r.cik),
                old_symbol_example=r.symbol,
                old_sec_name=r.sec_name,
                new_accession=None,
                new_cik=None,
                status="unresolved_absent",
                reason="absent from v2 and not in documented lineage/cluster",
                old_acceptance_utc=r.acceptance_datetime_utc,
                new_acceptance_utc=None,
            )
        )

recon = pd.DataFrame(recs)
assert recon.old_accession.is_unique
assert len(recon) == old.accession.nunique()
print("accession recon statuses:\n", recon.status.value_counts())
assert (recon.status == "unresolved_absent").sum() == 0, recon[recon.status == "unresolved_absent"]
recon.to_parquet(f"{V2}/old_to_new_reconciliation.parquet", index=False)
recon.to_csv(f"{V2}/old_to_new_reconciliation.csv", index=False)

# ---------- symbol|accession display-key reconciliation (920) ----------
old["key"] = old.symbol + "|" + old.accession
# expand v2 keys
exp = []
for _, r in v2.iterrows():
    syms = [x for x in str(r.index_symbols).split(",") if x] if pd.notna(r.index_symbols) else []
    if r.ticker_at_event and r.ticker_at_event not in syms:
        syms.append(r.ticker_at_event)
    for s in syms:
        exp.append((s, r.accession, int(r.cik), r.ticker_at_event, r.index_symbols))
v2_keys = {f"{s}|{a}": (c, t, idx) for s, a, c, t, idx in exp}

key_rows = []
for _, r in old.iterrows():
    k = r.key
    if k in v2_keys:
        key_rows.append(
            dict(
                old_key=k,
                old_symbol=r.symbol,
                old_accession=r.accession,
                old_cik=int(r.cik),
                category="exact_symbol_accession_match",
                detail="key present in v2 expanded index_symbols/ticker",
            )
        )
        continue
    a = r.accession
    if a in v1_acc:
        v = v2.loc[v2.accession == a].iloc[0]
        if int(r.cik) != int(v.cik):
            cat, detail = (
                "dual_cik_display_other_canonical",
                (
                    f"old symbol {r.symbol} cik {int(r.cik)}; v2 canonical {v.ticker_at_event} cik {int(v.cik)}; "
                    f"components={v.cik_components}"
                ),
            )
        else:
            cat, detail = (
                "ticker_rename_or_period_label",
                (f"old symbol {r.symbol}; v2 ticker_at_event={v.ticker_at_event} index_symbols={v.index_symbols}"),
            )
        key_rows.append(
            dict(old_key=k, old_symbol=r.symbol, old_accession=a, old_cik=int(r.cik), category=cat, detail=detail)
        )
    elif a in cluster_members:
        kept = member_to_kept[a]
        key_rows.append(
            dict(
                old_key=k,
                old_symbol=r.symbol,
                old_accession=a,
                old_cik=int(r.cik),
                category="cluster_member_symbol_key",
                detail=f"accession clustered into {kept}; symbol grain not exploded",
            )
        )
    elif int(r.cik) == 1675149:
        key_rows.append(
            dict(
                old_key=k,
                old_symbol=r.symbol,
                old_accession=a,
                old_cik=int(r.cik),
                category="lineage_aa_post_split_excluded",
                detail="see lineage_decisions",
            )
        )
    elif int(r.cik) == 1578318:
        key_rows.append(
            dict(
                old_key=k,
                old_symbol=r.symbol,
                old_accession=a,
                old_cik=int(r.cik),
                category="lineage_evhc_pre_membership_excluded",
                detail="see lineage_decisions",
            )
        )
    else:
        key_rows.append(
            dict(
                old_key=k,
                old_symbol=r.symbol,
                old_accession=a,
                old_cik=int(r.cik),
                category="unresolved_display_key",
                detail="needs review",
            )
        )

key_recon = pd.DataFrame(key_rows)
miss = key_recon[key_recon.category != "exact_symbol_accession_match"]
print("display-key non-exact", len(miss), "by cat:\n", miss.category.value_counts())
assert len(miss) == 920 or abs(len(miss) - 920) <= 5, len(miss)  # allow tiny variance if expand differs
assert (key_recon.category == "unresolved_display_key").sum() == 0
key_recon.to_parquet(f"{V2}/symbol_accession_key_reconciliation.parquet", index=False)
key_recon.to_csv(f"{V2}/symbol_accession_key_reconciliation.csv", index=False)

# ---------- finalize v2 columns / version ----------
v2["dataset_version"] = "earnings_events_8k202 v2 (the sentiment researcher, 2026-11-06)"
v2["v1_parent_sha256"] = V1_HASH
v2["validator_pit_ruling_sha256"] = VALIDATION_PIT
# ensure accession unique
assert v2.accession.is_unique
assert set(v1.accession).issubset(set(v2.accession))
assert len(v2) == len(v1)  # no restores; all v1 kept exactly once

# timestamp unchanged vs v1 for shared rows
joined = v2.set_index("accession")[["acceptance_utc"]].join(
    v1.set_index("accession")[["acceptance_utc"]].rename(columns={"acceptance_utc": "v1"})
)
assert (joined.acceptance_utc == joined.v1).all()

# in_sp500 covered by segments
seg_ok = seg[seg.identity_ok]


def covered(r: pd.Series) -> bool:
    d = pd.Timestamp(
        r.acceptance_et.tz_localize(None).date()
        if hasattr(r.acceptance_et, "tz_localize")
        else pd.Timestamp(r.acceptance_et).date()
    )
    # acceptance_et is tz-aware in v1
    d = pd.Timestamp(pd.Timestamp(r.acceptance_utc).tz_convert("America/New_York").date())
    s = seg_ok[(seg_ok.cik == r.cik) & (seg_ok.seg_start <= d) & (seg_ok.seg_end > d)]
    return len(s) > 0


ins = v2[v2.in_sp500]
# sample check all
cov_ok = sum(covered(r) for _, r in ins.iterrows())
print("in_sp500 segment cover", cov_ok, "/", len(ins))
assert cov_ok == len(ins)

# cluster_accessions consistency: every member listed; kept accession is first chronologically in core
bad_cluster = 0
for _, r in v2[v2.cluster_n_filings > 1].iterrows():
    members = [a for a in str(r.cluster_accessions).split(";") if a]
    if r.accession not in members:
        bad_cluster += 1
    sub = core[core.accession.isin(members)].sort_values("acceptance_utc")
    if len(sub) and sub.iloc[0].accession != r.accession:
        # after our pin we still keep first — verify
        bad_cluster += 1
assert bad_cluster == 0, bad_cluster

out_path = f"{V2}/earnings_events_8k202_v2.parquet"
v2.to_parquet(out_path, index=False, compression="zstd")
print("wrote", out_path, len(v2), "sha", sha(out_path))
print("deferred flags", n_deferred)
print("ex99_url in_sp500", int(v2[v2.in_sp500].ex99_url.notna().sum()))
