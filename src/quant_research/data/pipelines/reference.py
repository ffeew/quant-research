"""Reference data: ticker<->CIK map with ticker history, CIK former-name history, S&P 400/600 current lists.
Outputs (data/reference/):
  ticker_cik_map.parquet   ticker, cik, entity_name, valid_from, valid_to, source, match_method, confidence
  cik_former_names.parquet cik, name, name_from, name_to   (EDGAR submissions formerNames)
  sp400_current.parquet / sp600_current.parquet  (Wikipedia snapshot; NO historical changes -> not PIT)
Sources & precedence:
  1 sec_company_tickers  (www.sec.gov/files/company_tickers.json; current tickers only)  confidence=high
  2 wikipedia_sp500_cik  (CIK column of current S&P 500 table)                            confidence=high
  3 alpaca_name_change   (Alpaca corporate actions name_changes old_symbol->new_symbol, process_date = switch date)
                         old ticker inherits CIK of new ticker; valid_to = process_date                confidence=high
  4 edgar_submissions    (tickers listed in data.sec.gov/submissions/CIK*.json)                 confidence=high
  5 efts_name_search     (former S&P members not otherwise resolved: EDGAR entity search on the Wikipedia
                         security name, top hit) valid range = first..last Alpaca bar (lower/upper bounds) confidence=medium
valid_from/valid_to are best-effort: null = unknown/open. Requires SEC_USER_AGENT env (org + contact email)."""
import io, re, time, datetime as dt
import pandas as pd, requests
from quant_research.data.pipelines.common import DATA, UA, write_parquet, update_manifest, log
from quant_research.data.pipelines.earnings import sec_get, SEC_UA

OUT = DATA / "reference"


def efts(name):
    r = requests.get("https://efts.sec.gov/LATEST/search-index", params={"keysTyped": name}, headers={"User-Agent": SEC_UA}, timeout=30)
    time.sleep(0.15)
    if r.status_code != 200: return None
    hits = r.json().get("hits", {}).get("hits", [])
    return (int(hits[0]["_id"]), hits[0]["_source"]["entity"], hits[0]["_score"]) if hits else None


def wiki_list(url):
    r = requests.get(url, headers=UA, timeout=60); r.raise_for_status()
    t = pd.read_html(io.StringIO(r.text))[0]
    t.columns = [str(c).lower().replace(" ", "_") for c in t.columns]
    t["snapshot_date"] = dt.date.today()
    return t


# Former S&P members the automated search could not resolve. Each CIK below was checked by hand on 2026-10-30 against
# data.sec.gov/submissions (entity name / formerNames shown). These are verified EDGAR facts, not guesses.
MANUAL = {  # ticker: (cik, evidence)
    "BMS": (11199, "Amcor Flexibles North America, Inc.; formerNames BEMIS CO INC"),
    "BRCM": (1054374, "BROADCOM CORP"),
    "DISH": (1001082, "DISH Network CORP; formerNames ECHOSTAR COMMUNICATIONS CORP"),
    "DPS": (1418135, "Keurig Dr Pepper Inc.; formerNames Dr Pepper Snapple Group, Inc."),
    "EMC": (790070, "EMC CORP"),
    "ESRX": (1532063, "Express Scripts Holding Co."),
    "FLIR": (354908, "Teledyne FLIR, LLC; formerNames FLIR SYSTEMS INC"),
    "GAS": (1004155, "SOUTHERN CO GAS; formerNames AGL RESOURCES INC"),
    "HES": (4447, "HESS CORP; formerNames AMERADA HESS CORP"),
    "HOT": (316206, "STARWOOD HOTELS & RESORTS WORLDWIDE, LLC; formerNames STARWOOD HOTEL & RESORTS WORLDWIDE, INC"),
    "PBCT": (1378946, "People's United Financial, Inc."),
    "PCP": (79958, "PRECISION CASTPARTS CORP"),
    "RTN": (1047122, "RAYTHEON CO/"),
    "TSS": (721683, "TOTAL SYSTEM SERVICES INC"),
    "WYN": (1361658, "Travel & Leisure Co.; formerNames WYNDHAM WORLDWIDE CORP"),
    # override: EFTS name search matched ARNC to Arconic Corp (CIK 1790982, the 2020 spin). The S&P member ARNC
    # (2016-11-01..2020-04-01) was Arconic Inc. = ex-Alcoa Inc., now Howmet (CIK 4281; formerNames Arconic Inc., ALCOA INC.)
    "ARNC": (4281, "Howmet Aerospace Inc.; formerNames Arconic Inc., ALCOA INC. (verified 2026-10-30)"),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    u = pd.read_parquet(DATA / "universe/universe.parquet")
    cur = pd.read_parquet(DATA / "universe/sp500_current.parquet")
    ch = pd.read_parquet(DATA / "universe/sp500_changes.parquet")
    ca = pd.read_parquet(DATA / "corporate_actions/all_actions.parquet")
    rows = []
    tick = sec_get("https://www.sec.gov/files/company_tickers.json")
    for v in tick.values():
        rows.append(dict(ticker=v["ticker"].upper().replace("-", "."), cik=int(v["cik_str"]), entity_name=v["title"], valid_from=None, valid_to=None,
                         source="sec_company_tickers", match_method="exact", confidence="high"))
    for s, c, n in zip(cur.symbol, cur.cik, cur.security):
        rows.append(dict(ticker=s, cik=int(c), entity_name=n, valid_from=None, valid_to=None, source="wikipedia_sp500_cik", match_method="exact", confidence="high"))
    m = pd.DataFrame(rows)
    cikof = m.drop_duplicates("ticker").set_index("ticker").cik.to_dict()
    # Alpaca name changes give dated ticker switches
    nc = ca[ca.type == "name_changes"]
    for r in nc.itertuples():
        new, old, d = getattr(r, "new_symbol", None), getattr(r, "old_symbol", None), r.process_date
        if not isinstance(old, str) or not isinstance(new, str): continue
        c = cikof.get(new.upper())
        rows.append(dict(ticker=old.upper(), cik=c, entity_name=None, valid_from=None, valid_to=d, source="alpaca_name_change", match_method=f"renamed_to:{new}", confidence="high" if c else "low"))
        rows.append(dict(ticker=new.upper(), cik=c, entity_name=None, valid_from=d, valid_to=None, source="alpaca_name_change", match_method=f"renamed_from:{old}", confidence="high" if c else "low"))
        if c is not None: cikof.setdefault(old.upper(), c)
    # EDGAR submissions for universe CIKs: tickers + former names
    former = []
    ciks = sorted({cikof[s] for s in u.symbol if s in cikof and cikof[s] is not None})
    for i, c in enumerate(ciks):
        j = sec_get(f"https://data.sec.gov/submissions/CIK{int(c):010d}.json"); time.sleep(0.11)
        if not j: continue
        for t in j.get("tickers", []):
            rows.append(dict(ticker=t.upper().replace("-", "."), cik=int(c), entity_name=j.get("name"), valid_from=None, valid_to=None, source="edgar_submissions", match_method="exact", confidence="high"))
        for f in j.get("formerNames", []):
            former.append(dict(cik=int(c), name=f["name"], name_from=f.get("from", "")[:10] or None, name_to=f.get("to", "")[:10] or None, current_name=j.get("name")))
        if i % 150 == 0: log.info("submissions %d/%d", i, len(ciks))
    # unresolved former S&P members -> EDGAR entity name search
    names = {}
    for r in ch.itertuples():
        if isinstance(r.removed_ticker, str) and isinstance(r.removed_security, str): names[r.removed_ticker] = r.removed_security
    bars = DATA / "bars/daily/raw"
    unresolved = []
    for s in u.symbol:
        if s in cikof and cikof[s] is not None: continue
        nm = names.get(s)
        hit = None if s in MANUAL else (efts(re.sub(r"\s*\(.*?\)", "", nm)) if nm else None)
        if not hit and s in MANUAL:
            hit = (MANUAL[s][0], MANUAL[s][1], 0.0); src, conf = "manual_verified_edgar", "high"
        elif hit: src, conf = "efts_name_search", "medium"
        if not hit: unresolved.append(s); continue
        f = bars / f"{s}.parquet"; vf = vt = None
        if f.exists():
            b = pd.read_parquet(f, columns=["session_date"]); vf, vt = b.session_date.min(), b.session_date.max()
        rows.append(dict(ticker=s, cik=hit[0], entity_name=hit[1], valid_from=vf, valid_to=vt, source=src,
                         match_method=f"name:{nm}|score:{hit[2]:.1f}", confidence=conf))
        cikof[s] = hit[0]
    m = pd.DataFrame(rows)
    for c in ("valid_from", "valid_to"): m[c] = pd.to_datetime(m[c], errors="coerce").dt.date
    m["cik"] = m["cik"].astype("Int64")
    m = m.drop_duplicates(["ticker", "cik", "source", "valid_from", "valid_to"]).sort_values(["ticker", "source"]).reset_index(drop=True)
    m["in_universe"] = m.ticker.isin(set(u.symbol))
    write_parquet(m, OUT / "ticker_cik_map.parquet")
    fn = pd.DataFrame(former)
    write_parquet(fn, OUT / "cik_former_names.parquet")
    info = {"rows": len(m), "tickers": int(m.ticker.nunique()), "universe_resolved": int(u.symbol.isin(set(m.dropna(subset=['cik']).ticker)).sum()),
            "universe_unresolved": unresolved, "former_names_rows": len(fn)}
    for k, url in (("sp400", "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"), ("sp600", "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies")):
        try:
            t = wiki_list(url); write_parquet(t.astype(str), OUT / f"{k}_current.parquet"); info[f"{k}_current"] = len(t)
        except Exception as e:
            info[f"{k}_current"] = f"failed: {type(e).__name__}"
    update_manifest("reference", info); log.info("%s", info)


if __name__ == "__main__":
    main()
