"""v1.3 delisting returns for exits that Alpaca's merger corporate actions do not cover (Alpaca CA history starts 2020-04).
Run AFTER delisting.py. Fills rows of universe/delisting_returns.parquet whose terminal_return is null.

Every deal term below was read from the target's (or for renames the issuer's) SEC 8-K at `url`; the script re-downloads each
document (cached in universe/raw/delisting_terms/) and VERIFIES that every string in `verify` appears in the text, otherwise the
row stays null with reason terms_not_verified. Nothing is typed in without a matching filing.

terminal_value = cash + sum(ratio * acquirer RAW close on the first session >= effective date)   (Alpaca SIP raw, asof-mapped)
terminal_return = terminal_value / last_close_raw - 1
Flags: approximate (always), cvr_excluded (CVR / contingent rights given zero value), election (holder election / proration: the
listed option is used), renamed (not a delisting: ticker change, the security continues -> terminal_return 0 by construction and
the panel continues under the new ticker), distress (bankruptcy / bank failure: no deal; uses the last OTC print from Alpaca if any).
Usage: python delisting_terms.py
"""

from __future__ import annotations

import datetime as dt
import html
import re
import time
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import DATA, DATA_URL, get, log, update_manifest, write_parquet
from quant_research.data.pipelines.delisting import acq_close
from quant_research.data.pipelines.earnings import sec_get

RAW = DATA / "universe/raw/delisting_terms"
A = "https://www.sec.gov/Archives/edgar/data/"
# symbol: (cash, [(acquirer_symbol_at_time, ratio)], url, [verify strings], flags)
TERMS = {
    "ABMD": (380.00, [], A + "815094/000119312522311074/d353287d8k.htm", ["$380.00", "$35.00"], ["cvr_excluded"]),
    "AET": (145.00, [("CVS", 0.8378)], None, ["0.8378", "$145.00"], []),
    "ANDV": (
        0.13 * 152.27,
        [("MPC", 0.87 * 1.87)],
        A + "50104/000005010418000239/",
        ["1.87", "$152.27", "87%"],
        ["election"],
    ),
    "APC": (59.00, [("OXY", 0.2934)], None, ["$59.00", "0.2934"], []),
    "ARG": (143.00, [], None, ["$143.00"], []),
    "BCR": (222.93, [("BDX", 0.5077)], None, ["$222.93", "0.5077"], []),
    "BHI": (
        17.50,
        [("BHGE", 1.0)],
        A + "808362/000119312517220863/",
        ["one share of BHGE", "$17.50"],
        ["special_dividend_paid_by_acquirer"],
    ),
    "BMS": (0.0, [("AMCR", 5.1)], None, ["5.1 ordinary shares"], []),
    "BRCM": (54.50, [], None, ["$54.50", "0.4378"], ["election"]),
    "BXLT": (18.00, [("SHPG", 0.1482)], None, ["$18.00", "0.1482"], []),
    "CA": (44.50, [], A + "356028/000119312518317918/d631849d8k.htm", ["$44.50"], []),
    "ADT": (42.00, [], A + "1546640/000119312516582209/d177489d8k.htm", ["$42.00"], []),
    "EVHC": (46.00, [], A + "1678531/000119312518297466/d637722d8k.htm", ["$46.00"], []),
    "CELG": (
        50.00,
        [("BMY", 1.0)],
        A + "816284/000110465919065939/",
        ["$50.00", "one share of Bristol-Myers Squibb"],
        ["cvr_excluded"],
    ),
    "COL": (93.33, [("UTX", 0.37525)], None, ["$93.33", "0.37525"], []),
    "CPGX": (25.50, [], None, ["$25.50"], []),
    "CSRA": (41.25, [], None, ["$41.25"], []),
    "CVC": (34.90, [], None, ["$34.90"], []),
    "DNB": (145.00, [], None, ["$145.00"], []),
    "EMC": (24.05, [("DVMT", 0.11146)], None, ["0.11146", "$24.05"], ["tracking_stock"]),
    "ESRX": (48.75, [("CI", 0.2434)], None, ["0.2434", "$48.75"], []),
    "GAS": (66.00, [], None, ["$66.00"], []),
    "GMCR": (92.00, [], None, ["$92.00"], []),
    "HAR": (112.00, [], None, ["$112.00"], []),
    "HOLX": (76.00, [], None, ["$76.00", "CVR"], ["cvr_excluded"]),
    "HOT": (21.00, [("MAR", 0.800)], None, ["$21.00", "0.800"], []),
    "LLL": (0.0, [("LHX", 1.30)], None, ["1.30"], []),
    "LLTC": (46.00, [("ADI", 0.2321)], None, ["$46.00", "0.2321"], []),
    "LVLT": (26.50, [("CTL", 1.4286)], None, ["$26.50", "1.4286"], []),
    "MJN": (90.00, [], None, ["$90.00"], []),
    "MON": (128.00, [], None, ["$128.00"], []),
    "NFX": (0.0, [("ECA", 2.6719)], None, ["2.6719"], []),
    "PCL": (0.0, [("WY", 1.60)], None, ["1.60 Weyerhaeuser"], []),
    "PCP": (235.00, [], None, ["$235.00"], []),
    "POM": (27.25, [], None, ["$27.25"], []),
    "RAI": (29.44, [("BTI", 0.5260)], None, ["0.5260", "29.44"], ["adr"]),
    "RHT": (190.00, [], None, ["$190.00"], []),
    "RTN": (0.0, [("RTX", 2.3348)], None, ["2.3348"], []),
    "SCG": (0.0, [("D", 0.6690)], None, ["0.6690"], []),
    "SE": (0.0, [("ENB", 0.984)], A + "1373835/000119312517057856/d338638d8k.htm", ["0.984"], []),
    "SNI": (65.82, [("DISCK", 1.0584)], None, ["$65.82", "1.0584"], []),
    "SPLS": (10.25, [], None, ["$10.25"], []),
    "STI": (0.0, [("BBT", 1.295)], None, ["1.295"], []),
    "STJ": (46.75, [("ABT", 0.8708)], None, ["0.8708", "$46.75"], []),
    "SWN": (0.0, [("CHK", 0.0867)], None, ["0.0867"], []),
    "TE": (27.55, [], None, ["$27.55"], []),
    "TSS": (0.0, [("GPN", 0.8101)], None, ["0.8101"], []),
    "TWC": (100.00, [("CHTR", 0.5409)], None, ["$100.00", "0.5409", "$115.00"], ["election"]),
    "TWX": (53.75, [("T", 1.437)], None, ["1.437", "$53.75"], []),
    "VIAB": (0.0, [("VIAC", 0.59625)], A + "1339947/000119312519306335/d833313d8k.htm", ["0.59625"], []),
    "WBA": (11.45, [], None, ["$11.45"], ["cvr_excluded"]),
    "WCG": (120.00, [("CNC", 3.38)], None, ["3.38", "$120.00"], []),
    "WFM": (42.00, [], None, ["$42.00"], []),
    "XL": (57.60, [], None, ["$57.60"], []),
    "GGP": (None, [], None, [], ["complex_election_unpriced"]),
}
RENAMED = {"ACE": "CB", "CDAY": "DAY", "FBHS": "FBIN", "DISCA": "WBD", "DISCK": "WBD", "TYC": "JCI", "ESV": "VAL"}
DISTRESS_OTC = {
    "CHK": "CHKAQ",
    "DO": "DOFSQ",
    "ENDP": "ENDPQ",
    "FTR": "FTRCQ",
    "MNK": "MNKKQ",
    "SIVB": "SIVBQ",
    "BBBY": "BBBYQ",
    "FRC": "FRCB",
    "SBNY": "SBNY",
    "ESV": "VALPQ",
}


def doc_text(url: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "_", url)[-120:]
    f = RAW / f"{key}.txt"
    if f.exists():
        return f.read_text()
    if url.endswith("/"):  # filing folder -> primary 8-K document via index.json
        j = sec_get(url + "index.json")
        time.sleep(0.12)
        items = [
            i["name"]
            for i in j["directory"]["item"]
            if i["name"].lower().endswith((".htm", ".html")) and "index" not in i["name"].lower()
        ]
        url = url + items[0]
    from quant_research.data.pipelines.shares_classes import get_text

    t = get_text(url) or ""
    time.sleep(0.12)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    f.write_text(t)
    return t


def otc_last(sym: str, after: dt.date | str) -> Any:
    try:
        j = get(
            DATA_URL + "/v2/stocks/bars",
            {
                "symbols": sym,
                "timeframe": "1Day",
                "start": str(after),
                "end": str(pd.Timestamp(after) + pd.Timedelta(days=60))[:10],
                "feed": "sip",
                "adjustment": "raw",
                "asof": str(after),
            },
        )
    except RuntimeError:
        return None
    return (j.get("bars") or {}).get(sym, [])


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    d = pd.read_parquet(DATA / "universe/delisting_returns.parquet")
    ext = pd.read_json(DATA / "universe/raw/delisting_8k/extract_20261030.json").set_index("symbol")
    for c in ("terms_source_url", "terms_verified", "flags", "otc_symbol"):
        if c not in d:
            d[c] = None
    cache: dict[str, pd.DataFrame] = {}
    for i, r in d[d.terminal_return.isna()].iterrows():
        s = r.symbol
        if s in RENAMED and s not in DISTRESS_OTC:
            d.loc[i, ["reason", "flags"]] = [f"renamed_to_{RENAMED[s]}", "renamed"]
            continue
        if s in TERMS:
            cash, legs, url, ver, fl = TERMS[s]
            url = url or (ext.loc[s, "url"] if s in ext.index and isinstance(ext.loc[s, "url"], str) else None)
            if cash is None or not url:
                d.loc[i, ["reason", "flags"]] = ["terms_not_priced", ",".join(fl)]
                continue
            t = doc_text(url)
            ok = all(v in t for v in ver)
            d.loc[i, ["terms_source_url", "terms_verified"]] = [url, ok]
            if not ok:
                d.loc[i, ["reason", "flags"]] = [
                    "terms_not_verified:" + ",".join(v for v in ver if v not in t),
                    ",".join(fl),
                ]
                continue
            eff = (pd.Timestamp(r.last_session) + pd.Timedelta(days=1)).date()
            val, miss, acq = cash, [], []
            for sym, ratio in legs:
                px, pd_ = acq_close(sym, eff, cache)
                if px is None:
                    miss.append(sym)
                    continue
                val += ratio * px
                acq.append(f"{sym}:{ratio}@{px}({pd_})")
            if miss:
                d.loc[i, ["reason", "flags"]] = ["acquirer_price_missing:" + ",".join(miss), ",".join(fl)]
                continue
            d.loc[
                i,
                [
                    "terminal_value",
                    "terminal_return",
                    "cash_per_share",
                    "acquirer",
                    "reason",
                    "flags",
                    "deal_type",
                    "effective_date",
                ],
            ] = [
                val,
                val / r.last_close_raw - 1,
                cash,
                ";".join(acq) or None,
                "sec_8k_terms",
                ",".join(fl) or None,
                "cash" if not legs else ("stock" if cash == 0 else "stock_and_cash"),
                eff,
            ]
            d.loc[i, "suspect"] = abs(val / r.last_close_raw - 1) > 0.15
            continue
        if s in DISTRESS_OTC:
            o = DISTRESS_OTC[s]
            b = otc_last(o, pd.Timestamp(r.last_session) + pd.Timedelta(days=1))
            if b:
                last = b[-1]
                v = float(last["c"])
                d.loc[i, ["terminal_value", "terminal_return", "reason", "flags", "otc_symbol", "effective_date"]] = [
                    v,
                    v / r.last_close_raw - 1,
                    "distress_last_otc_print_within_60d",
                    "distress",
                    o,
                    pd.Timestamp(last["t"]).date(),
                ]
            else:
                d.loc[i, ["reason", "flags", "otc_symbol"]] = ["distress_no_otc_bars_in_alpaca", "distress", o]
            continue
    d["approximate"] = True
    write_parquet(d, DATA / "universe/delisting_returns.parquet")
    info = {
        "rows": len(d),
        "with_terminal_return": int(d.terminal_return.notna().sum()),
        "reason": d.reason.value_counts().to_dict(),
    }
    update_manifest("delisting_terms", info)
    log.info("%s", info)


if __name__ == "__main__":
    main()
