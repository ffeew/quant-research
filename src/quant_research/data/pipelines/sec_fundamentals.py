"""Point-in-time fundamentals and shares outstanding from SEC EDGAR XBRL companyfacts
(data.sec.gov/api/xbrl/companyfacts/CIK##########.json), for every universe ticker with a CIK.
Outputs (data/fundamentals/):
  xbrl_facts.parquet  long table: symbol, cik, taxonomy, tag, unit, value, period_start, period_end, fy, fp, form,
                      filed, accn, frame, knowledge_date (= filed), available_session (first NYSE session AFTER filed)
  shares_outstanding.parquet  dei:EntityCommonStockSharesOutstanding (cover page, 'as of' a date near filing) and
                      us-gaap:CommonStockSharesOutstanding (balance sheet), PIT by filed date
  market_cap_daily.parquet    symbol, session_date, shares (latest dei value with available_session <= date),
                      close_raw, market_cap  (approximate: see caveats)
Caveats: companyfacts excludes dimensional facts. For multi-class issuers (GOOGL/GOOG, BRK.A/B, FOX/FOXA, NWS/NWSA)
the cover-page value can be one class or missing -> flagged multi_class. Restatements appear as later `filed` rows
(we keep ALL rows so as-of joins on knowledge_date are PIT). The filed DATE is known but not the time of day
-> available_session = next session after filed (conservative).
Usage: python sec_fundamentals.py   (full refresh ~10 min; SEC fair-access 10 req/s respected)"""
import time
import pandas as pd
import gzip, json, os
from quant_research.data.pipelines.common import DATA, START, calendar, write_parquet, update_manifest, log
from quant_research.data.pipelines.earnings import sec_get

OUT = DATA / "fundamentals"
TAGS = {
 "us-gaap": ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueNet","CostOfRevenue","CostOfGoodsAndServicesSold",
             "GrossProfit","OperatingIncomeLoss","NetIncomeLoss","NetCashProvidedByUsedInOperatingActivities","Assets","AssetsCurrent",
             "LiabilitiesCurrent","Liabilities","CashAndCashEquivalentsAtCarryingValue","ShortTermBorrowings","DebtCurrent","LongTermDebtCurrent",
             "LongTermDebt","LongTermDebtNoncurrent","DepreciationDepletionAndAmortization","DepreciationAndAmortization",
             "StockholdersEquity","StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest","PreferredStockValue",
             "PaymentsOfDividends","PaymentsOfDividendsCommonStock","PaymentsForRepurchaseOfCommonStock","EarningsPerShareBasic",
             "EarningsPerShareDiluted","WeightedAverageNumberOfDilutedSharesOutstanding","WeightedAverageNumberOfSharesOutstandingBasic",
             "CommonStockSharesOutstanding","ResearchAndDevelopmentExpense","SellingGeneralAndAdministrativeExpense","IncomeTaxExpenseBenefit",
             "InterestExpense","InventoryNet","AccountsReceivableNetCurrent","PropertyPlantAndEquipmentNet"],
 "dei": ["EntityCommonStockSharesOutstanding","EntityPublicFloat"]}
MULTI = {"GOOGL","GOOG","BRK.B","BRK.A","FOX","FOXA","NWS","NWSA","UA","UAA","DISCA","DISCK","LEN","HEI"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    u = pd.read_parquet(DATA / "universe/universe.parquet")
    ref = DATA / "reference/ticker_cik_map.parquet"
    if ref.exists():
        m = pd.read_parquet(ref).dropna(subset=["cik"])
        m = m[m.ticker.isin(set(u.symbol))]
        pr = {"wikipedia_sp500_cik": 0, "sec_company_tickers": 1, "edgar_submissions": 2, "alpaca_name_change": 3, "manual_verified_edgar": 3, "efts_name_search": 4}
        m["p"] = m.source.map(pr)
        cik = m.sort_values("p").drop_duplicates("ticker").set_index("ticker").cik.astype(int).to_dict()
    else:
        cur = pd.read_parquet(DATA / "universe/sp500_current.parquet"); cik = dict(zip(cur.symbol, cur.cik.astype(int)))
    # v1.2: period-aware CIKs (reference/cik_periods.parquet): a ticker can map to several issuers over time; facts are kept
    # only when filed inside that CIK's validity window for the ticker. Tickers absent from cik_periods use the map above.
    pairs = []
    cpf = DATA / "reference/cik_periods.parquet"
    if cpf.exists():
        cp = pd.read_parquet(cpf).dropna(subset=["cik"]); cp = cp[cp.index_ticker.isin(set(u.symbol))]
        for r in cp.itertuples():
            pairs.append((r.index_ticker, int(r.cik), str(r.valid_from) if pd.notna(r.valid_from) else "0000", str(r.valid_to) if pd.notna(r.valid_to) else "9999"))
    have = {p[0] for p in pairs}
    pairs += [(s, c, "0000", "9999") for s, c in cik.items() if s not in have]
    rows, missing = [], []
    for i, (s, c, lo, hi) in enumerate(sorted(pairs)):
        cf = OUT / "raw" / "companyfacts" / f"CIK{c:010d}.json.gz"   # raw cache (reused if < 20h old)
        if cf.exists() and time.time() - cf.stat().st_mtime < 20 * 3600:
            j = json.loads(gzip.decompress(cf.read_bytes()))
        else:
            try:
                j = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json")
            except Exception as e:
                missing.append(f"{s}:{type(e).__name__}"); continue
            time.sleep(0.11)
            if j:
                cf.parent.mkdir(parents=True, exist_ok=True); tmp = cf.with_suffix(".tmp")
                tmp.write_bytes(gzip.compress(json.dumps(j).encode())); os.replace(tmp, cf)
        if not j: missing.append(f"{s}:404"); continue
        for tax, tags in TAGS.items():
            facts = j.get("facts", {}).get(tax, {})
            for t in tags:
                for unit, vals in facts.get(t, {}).get("units", {}).items():
                    for v in vals:
                        if v.get("filed", "") < "2014-01-01": continue
                        if lo != "0000" and not (max(lo, "2014-01-01") <= v.get("filed", "") <= hi) and not (lo <= "2016-01-04" and v.get("filed", "") < lo): continue
                        rows.append((s, c, tax, t, unit, v.get("val"), v.get("start"), v.get("end"), v.get("fy"), v.get("fp"),
                                     v.get("form"), v.get("filed"), v.get("accn"), v.get("frame")))
        if i % 100 == 0: log.info("companyfacts %d/%d rows=%d", i, len(pairs), len(rows))
    df = pd.DataFrame(rows, columns=["symbol","cik","taxonomy","tag","unit","value","period_start","period_end","fy","fp","form","filed","accn","frame"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce").astype("float64")  # some filers report >int64 values
    for c in ("period_start","period_end","filed"): df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    df["fy"] = pd.to_numeric(df["fy"], errors="coerce").astype("Int64")
    df["knowledge_date"] = df["filed"]
    sess = pd.Index(sorted(calendar(START)["date"]))
    idx = sess.searchsorted(pd.Index(df["filed"]), side="right")
    df["available_session"] = [sess[k] if k < len(sess) else None for k in idx]
    write_parquet(df, OUT / "xbrl_facts.parquet")
    so = df[df.tag.isin(["EntityCommonStockSharesOutstanding","CommonStockSharesOutstanding"])].copy()
    so["multi_class"] = so.symbol.isin(MULTI)
    so = so.sort_values(["symbol","available_session","tag"])
    write_parquet(so, OUT / "shares_outstanding.parquet")
    # daily market cap via as-of join on available_session (cover-page shares preferred)
    dei = so[so.tag == "EntityCommonStockSharesOutstanding"].groupby(["symbol","available_session"]).value.sum().reset_index()
    dei = dei.rename(columns={"available_session": "session_date", "value": "shares"}).dropna()
    bars = pd.read_parquet(DATA / "bars/daily/raw", columns=["symbol","session_date","close"])
    bars["session_date"] = pd.to_datetime(bars.session_date); dei["session_date"] = pd.to_datetime(dei.session_date)
    mc = pd.merge_asof(bars.sort_values("session_date"), dei.sort_values("session_date"), on="session_date", by="symbol", direction="backward")
    mc = mc.rename(columns={"close": "close_raw"}); mc["market_cap"] = mc.shares * mc.close_raw
    mc["session_date"] = mc.session_date.dt.date; mc["multi_class"] = mc.symbol.isin(MULTI)
    write_parquet(mc.sort_values(["symbol","session_date"]).reset_index(drop=True), OUT / "market_cap_daily.parquet")
    info = {"facts_rows": len(df), "symbols": int(df.symbol.nunique()), "filed_range": [df.filed.min(), df.filed.max()],
            "shares_rows": len(so), "mcap_rows": len(mc), "mcap_coverage": float(mc.market_cap.notna().mean()), "missing": missing}
    update_manifest("sec_fundamentals", info); log.info("%s", {k: v for k, v in info.items() if k != "missing"} | {"missing": len(missing)})


if __name__ == "__main__":
    main()
