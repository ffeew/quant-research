"""Per-class shares outstanding from filing XBRL instances (dimensioned dei:EntityCommonStockSharesOutstanding),
for issuers whose cover-page share count is reported only per class (SEC companyfacts drops dimensional facts),
plus a flagged fallback, and a rebuilt company market cap.

Targets: universe non-ETF symbols with no undimensioned dei:EntityCommonStockSharesOutstanding filed in the last 15 months,
plus known multi-class issuers. Filings: earnings/edgar_10q10k.parquet (10-Q/10-K, per CIK period).
For each filing: https://www.sec.gov/Archives/edgar/data/<cik>/<accn>/index.json -> XBRL instance (*_htm.xml or <x>-<date>.xml)
-> every dei:EntityCommonStockSharesOutstanding fact with its StatementClassOfStockAxis member and instant date.

Outputs (data/fundamentals/):
  shares_by_class.parquet  symbol, cik, accession, form, filed, available_session, as_of_date, class_member, shares, dimensioned
  shares_company.parquet   symbol, available_session, shares_company (economic, as-converted where documented), method, n_classes
  market_cap_daily_v2.parquet  as market_cap_daily + shares_method; per symbol best of:
        dei_undimensioned (cover page)  > dei_class_sum (this script) > fallback_us_gaap_CommonStockSharesOutstanding
        > fallback_us_gaap_WeightedAverageBasic   (fallbacks flagged; they lag and are period-average / balance-sheet dates)
Economic conversion: BRK class A = 1,500 class B (Berkshire 2010 split terms); ACN Class X carries no economic rights -> excluded;
V class B/C convert at changing rates -> class A only, flagged 'class_A_only_conversion_varies'.
market cap = shares_company x close of the symbol's own class (approximation when class prices differ, e.g. GOOGL vs GOOG).
Usage: python shares_classes.py   (SEC fair access: <= ~5 req/s from this script)
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import pandas as pd
import requests

from quant_research.data.pipelines.common import DATA, START, calendar, log, update_manifest, write_parquet
from quant_research.data.pipelines.earnings import SEC_UA, sec_get

OUT = DATA / "fundamentals"
RAW = OUT / "raw" / "xbrl_instances"
MULTI = {
    "GOOGL",
    "GOOG",
    "BRK.B",
    "FOX",
    "FOXA",
    "NWS",
    "NWSA",
    "UA",
    "UAA",
    "DISCA",
    "DISCK",
    "LEN",
    "HEI",
    "META",
    "V",
    "MA",
    "CMCSA",
    "F",
    "UPS",
}


def get_text(url: str) -> str | None:
    for k in range(6):
        try:
            r = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "gzip"}, timeout=60)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(2**k)
    return None


CTX = re.compile(r"<(?:xbrli:)?context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</(?:xbrli:)?context>", re.S)
FACT = re.compile(
    r"<dei:EntityCommonStockSharesOutstanding\b([^>]*)>([^<]*)</dei:EntityCommonStockSharesOutstanding>", re.S
)


def parse(xml: str) -> list[dict[str, Any]]:
    ctx: dict[str, tuple[str | None, list[tuple[str, str]]]] = {}
    for cid, body in CTX.findall(xml):
        instant = re.search(r"<(?:xbrli:)?instant>([^<]+)<", body)
        mem = re.findall(r"<xbrldi:explicitMember[^>]*dimension=\"([^\"]+)\"[^>]*>([^<]+)<", body)
        ctx[cid] = (instant.group(1).strip() if instant else None, mem)
    out: list[dict[str, Any]] = []
    for attrs, val in FACT.findall(xml):
        c = re.search(r"contextRef=\"([^\"]+)\"", attrs)
        if not c or c.group(1) not in ctx:
            continue
        inst, mem = ctx[c.group(1)]
        cls = [m for d, m in mem if "ClassOfStock" in d or "StatementClass" in d]
        try:
            v = float(val.strip().replace(",", ""))
        except ValueError:
            continue
        out.append(
            dict(
                as_of_date=inst,
                class_member=cls[0].strip() if cls else None,
                other_dims=";".join(f"{d}={m}" for d, m in mem if m not in cls) or None,
                shares=v,
                dimensioned=bool(mem),
            )
        )
    return out


def instance_url(cik: int | str, accn: str) -> str | None:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}"
    j = sec_get(base + "/index.json")
    time.sleep(0.2)
    if not j:
        return None
    names = [i["name"] for i in j["directory"]["item"]]
    c = [n for n in names if n.endswith("_htm.xml")] or [
        n
        for n in names
        if n.endswith(".xml")
        and not re.search(r"(_cal|_def|_lab|_pre|FilingSummary|MetaLinks)", n, re.I)
        and re.search(r"\d{8}\.xml$", n)
    ]
    return f"{base}/{c[0]}" if c else None


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--mcap-only", action="store_true")
    _args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    u = pd.read_parquet(DATA / "universe/universe.parquet")
    syms = set(u.loc[u.role != "etf", "symbol"])
    so = pd.read_parquet(OUT / "shares_outstanding.parquet")
    recent = so[
        (so.tag == "EntityCommonStockSharesOutstanding")
        & (pd.to_datetime(so.filed) >= pd.Timestamp.today() - pd.Timedelta(days=455))
    ]
    cur = pd.read_parquet(DATA / "universe/sp500_current.parquet")
    targets = sorted(((set(cur.symbol) - set(recent.symbol)) | (MULTI & syms)) & syms)
    q = pd.read_parquet(DATA / "earnings/edgar_10q10k.parquet")
    q = q[
        q.symbol.isin(targets) & q.form.isin(["10-Q", "10-K"]) & (q.filing_date.astype(str) >= "2015-06-01")
    ].drop_duplicates(["symbol", "accession"])
    log.info("targets=%d filings=%d", len(targets), len(q))
    rows: list[dict[str, Any]] = []
    fails: list[str] = []
    for n, r in enumerate(q.itertuples()):
        cache = RAW / f"{r.accession}.json"
        if cache.exists():
            facts = json.loads(cache.read_text())
        else:
            url = instance_url(r.cik, r.accession)  # type: ignore[arg-type]  # filing cik and accession cells are strings
            xml = get_text(url) if url else None
            time.sleep(0.2)
            if xml is None:
                fails.append(f"{r.symbol}:{r.accession}")
                continue
            facts = parse(xml)
            cache.write_text(json.dumps(facts))
        for f in facts:
            rows.append(
                dict(
                    symbol=r.symbol,
                    cik=int(r.cik),  # type: ignore[arg-type]  # filing cik cells are ints
                    accession=r.accession,
                    form=r.form,
                    filed=pd.Timestamp(r.filing_date).date(),  # type: ignore[arg-type]  # filing dates are dates
                    **f,
                )
            )
        if n % 200 == 0:
            log.info("instances %d/%d rows=%d fails=%d", n, len(q), len(rows), len(fails))
    sc = pd.DataFrame(rows)
    sess = pd.Index(sorted(calendar(START)["date"]))
    sc["available_session"] = [sess[min(sess.searchsorted(d, side="right"), len(sess) - 1)] for d in sc.filed]
    sc["as_of_date"] = pd.to_datetime(sc.as_of_date, errors="coerce").dt.date
    write_parquet(sc, OUT / "shares_by_class.parquet")

    # company-level economic shares per filing
    comp_rows: list[dict[str, Any]] = []
    for (s, accn), g in sc.groupby(["symbol", "accession"]):
        g = g[g.other_dims.isna()] if g.other_dims.notna().any() and g.other_dims.isna().any() else g
        g = g[g.as_of_date == g.as_of_date.max()] if g.as_of_date.notna().any() else g
        und = g[~g.dimensioned]
        dim = g[g.dimensioned & g.class_member.notna()].drop_duplicates("class_member")
        method = None
        if s.startswith("BRK"):  # type: ignore[attr-defined]  # groupby symbol key is a string
            a = dim[dim.class_member.str.contains("ClassA", case=False)].shares.sum()
            b = dim[dim.class_member.str.contains("ClassB", case=False)].shares.sum()
            tot = a * 1500 + b if (a or b) else None
            method = "dei_class_sum_brk_A_x1500_plus_B"
        elif s == "V":
            a = dim[dim.class_member.str.contains("ClassA|CommonClassA", case=False)].shares.sum()
            tot = a or None
            method = "dei_class_A_only_conversion_varies"
        elif len(dim):
            d2 = dim[~dim.class_member.str.contains("ClassX|Class X", case=False)] if s == "ACN" else dim
            tot = d2.shares.sum()
            method = "dei_class_sum" + ("_excl_class_X" if s == "ACN" else "")
        elif len(und):
            tot = und.shares.iloc[0]
            method = "dei_undimensioned_instance"
        else:
            continue
        comp_rows.append(
            dict(
                symbol=s,
                accession=accn,
                available_session=g.available_session.iloc[0],
                as_of_date=g.as_of_date.max(),
                shares_company=tot,
                n_classes=len(dim),
                classes=";".join(dim.class_member.astype(str)),
                method=method,
            )
        )
    comp = pd.DataFrame(comp_rows).dropna(subset=["shares_company"])
    write_parquet(comp, OUT / "shares_company.parquet")

    # market cap v2
    # one value per filing: the latest cover-page instant in that accession; if one accession carries several undimensioned values
    # for the same instant (rare), take the max (never sum: summing across filings/instants caused the 2016 >3x outliers, e.g. A).
    d0 = so[so.tag == "EntityCommonStockSharesOutstanding"].dropna(subset=["value"])
    d0 = d0[d0.period_end == d0.groupby(["symbol", "accn"]).period_end.transform("max")]
    d0 = d0.groupby(["symbol", "accn", "available_session"]).value.max().reset_index().sort_values("available_session")
    dei = (
        d0.groupby(["symbol", "available_session"]).value.last().reset_index().assign(shares_method="dei_undimensioned")
    )
    cs = comp[["symbol", "available_session", "shares_company", "method"]].rename(
        columns={"shares_company": "value", "method": "shares_method"}
    )
    fb1 = (
        so[so.tag == "CommonStockSharesOutstanding"]
        .sort_values("period_end")
        .groupby(["symbol", "available_session"])
        .value.last()
        .reset_index()
        .assign(shares_method="fallback_us_gaap_CommonStockSharesOutstanding")
    )
    fx = pd.read_parquet(
        OUT / "xbrl_facts.parquet",
        columns=["symbol", "tag", "value", "period_start", "period_end", "available_session"],
    )
    fx = fx[fx.tag == "WeightedAverageNumberOfSharesOutstandingBasic"].dropna(subset=["period_start"])
    fx = fx[(pd.to_datetime(fx.period_end) - pd.to_datetime(fx.period_start)).dt.days.between(80, 100)]
    fb2 = (
        fx.sort_values("period_end")
        .groupby(["symbol", "available_session"])
        .value.last()
        .reset_index()
        .assign(shares_method="fallback_us_gaap_WeightedAverageBasic_quarter")
    )
    _pri = {"dei_undimensioned": 0}
    allsh = []
    for k, src in enumerate([dei, cs, fb1, fb2]):
        src = src.assign(p=k)
        allsh.append(src)
    A = pd.concat(allsh, ignore_index=True)
    best = A.groupby("symbol").p.min()  # per symbol best available source family (stable method, no source flipping)
    # but a symbol whose best source has gone stale (> 15 months) falls to the next family that is fresh
    last = A.groupby(["symbol", "p"]).available_session.max().reset_index()
    fresh = (
        last[pd.to_datetime(last.available_session) >= pd.Timestamp.today() - pd.Timedelta(days=455)]
        .groupby("symbol")
        .p.min()
    )
    choose = best.copy()
    choose.update(fresh)
    A = A[A.p == A.symbol.map(choose)]
    A = A.rename(columns={"available_session": "session_date", "value": "shares"}).dropna(subset=["shares"])
    bars = pd.read_parquet(DATA / "bars/daily/raw", columns=["symbol", "session_date", "close"])
    bars["session_date"] = pd.to_datetime(bars.session_date)
    A["session_date"] = pd.to_datetime(A.session_date)
    mc = pd.merge_asof(
        bars.sort_values("session_date"),
        A[["symbol", "session_date", "shares", "shares_method"]].sort_values("session_date"),
        on="session_date",
        by="symbol",
        direction="backward",
    )
    mc = mc.rename(columns={"close": "close_raw"})
    mc["market_cap"] = mc.shares * mc.close_raw
    mc["session_date"] = mc.session_date.dt.date
    mc["multi_class"] = mc.symbol.isin(MULTI)
    # share-count jump QA: shares change > 2x (either way) between consecutive filings without a split/reverse split in
    # corporate_actions within (previous filing, this filing] -> flag (kept, not altered)
    ca = pd.read_parquet(DATA / "corporate_actions/all_actions.parquet")
    spl = ca[ca.type.isin(["forward_splits", "reverse_splits", "unit_splits", "stock_dividends"])][
        ["symbol", "ex_date"]
    ].dropna()
    spl["ex_date"] = pd.to_datetime(spl.ex_date)
    A2 = A.sort_values(["symbol", "session_date"]).copy()
    A2["prev_shares"] = A2.groupby("symbol").shares.shift()
    A2["prev_date"] = A2.groupby("symbol").session_date.shift()
    A2["jump"] = A2.shares / A2.prev_shares
    J = A2[(A2.jump > 2) | (A2.jump < 0.5)].copy()
    J["split_between"] = [
        bool(((spl.symbol == s_) & (spl.ex_date > p_) & (spl.ex_date <= d_)).any())
        for s_, p_, d_ in zip(J.symbol, J.prev_date, J.session_date)
    ]
    J = J[~J.split_between]
    write_parquet(J.drop(columns=["p"], errors="ignore"), OUT / "qa_shares_jumps.parquet")
    flag = set(zip(J.symbol, J.session_date))
    mc["shares_jump_flag"] = False
    if flag:
        k = pd.Series(list(zip(mc.symbol, pd.to_datetime(mc.session_date))))  # type: ignore[assignment]  # k was the source-family index
        # flag every day served by a flagged filing value (until the next filing)
        A2["flag"] = [(s_, d_) in flag for s_, d_ in zip(A2.symbol, A2.session_date)]
        f2 = pd.merge_asof(
            mc.assign(sd=pd.to_datetime(mc.session_date)).sort_values("sd")[["symbol", "sd"]],
            A2[["symbol", "session_date", "flag"]].rename(columns={"session_date": "sd"}).sort_values("sd"),
            on="sd",
            by="symbol",
            direction="backward",
        )
        mc = mc.assign(sd=pd.to_datetime(mc.session_date)).merge(f2, on=["symbol", "sd"], how="left").drop(columns="sd")
        mc["shares_jump_flag"] = mc.flag.fillna(False).astype(bool)
        mc = mc.drop(columns="flag")
    # own-median outlier QA (the stat-arb researcher): market cap > 3x or < 1/3 of the symbol's own median in the quarter
    _medq = mc.groupby([mc.symbol, pd.to_datetime(mc.session_date).dt.to_period("Q")]).shares.transform("median")
    medall = mc.groupby("symbol").shares.transform("median")
    mc["shares_vs_own_median"] = mc.shares / medall
    mc["shares_outlier_3x"] = (mc.shares_vs_own_median > 3) | (mc.shares_vs_own_median < 1 / 3)
    write_parquet(
        mc.sort_values(["symbol", "session_date"]).reset_index(drop=True), OUT / "market_cap_daily_v2.parquet"
    )
    last_d = mc.session_date.max()
    L = mc[mc.session_date == last_d]
    old = pd.read_parquet(OUT / "market_cap_daily.parquet", columns=["symbol", "session_date", "market_cap"])
    Lo = old[old.session_date == old.session_date.max()]
    info = {
        "targets": len(targets),
        "filings": len(q),
        "instance_fails": len(fails),
        "class_rows": len(sc),
        "company_rows": len(comp),
        "current_members_with_mcap_before": int(Lo[Lo.symbol.isin(cur.symbol)].market_cap.notna().sum()),
        "current_members_with_mcap_after": int(L[L.symbol.isin(cur.symbol)].market_cap.notna().sum()),
        "current_members": len(cur),
        "still_missing": sorted(set(cur.symbol) - set(L[L.market_cap.notna()].symbol)),
        "method_counts_last_day": L[L.symbol.isin(cur.symbol)].shares_method.value_counts().to_dict(),
        "mcap_coverage_all_rows_before": float(old.market_cap.notna().mean()),
        "mcap_coverage_all_rows_after": float(mc.market_cap.notna().mean()),
        "shares_jump_events_no_split": int(len(J)),
        "rows_shares_outlier_3x_after": int(mc.shares_outlier_3x.sum()),
    }
    update_manifest("shares_classes", info)
    log.info("%s", info)


if __name__ == "__main__":
    main()
