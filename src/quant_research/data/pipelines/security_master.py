"""Security master + predecessor histories + point-in-time member-day return panel (data v1.2).

security_id = "S<CIK 10 digits>-<listing start YYYYMMDD>" (listing start = first session in our data, >= 2016-01-04),
              "ETF-<TICKER>" for ETFs, "T-<TICKER>-<YYYYMMDD>" if no CIK. Same company renamed (LB->BBWI, DLPH->APTV,
              UA(class A)->UAA, Q->IQV) keeps one security_id; a different issuer reusing a ticker gets a new one.
Outputs
  reference/security_master.parquet      one row per security: security_id, cik, entity_name, first/last session, tickers used
  reference/security_segments.parquet    security_id -> bars source (main|predecessor file), ticker_at_time, asof, seg_from, seg_to, evidence
  reference/security_joins.parquet       join-day / distribution returns computed from public deal terms (with evidence URL)
  bars/daily/predecessors/{raw,adjusted}/<TICKER>_asof<YYYYMMDD>.parquet   Alpaca SIP bars of predecessor tickers (asof mapping)
  universe/sp500_member_days.parquet     one row per (session, index ticker) S&P 500 member-day 2016+: security_id, segment,
                                         close_raw, open_adj/close_adj (segment-level), ret_total (security total return), ret_source,
                                         no_bar (True for the 1-5 days between last trade and index removal; untradable)
Usage: python security_master.py [--refetch]
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any

import numpy as np
import pandas as pd

from quant_research.data.pipelines.common import DATA, calendar, log, update_manifest, write_parquet
from quant_research.data.pipelines.daily_bars import ADJ, fetch, to_df

PRED_DIR = DATA / "bars/daily/predecessors"
# Curated predecessor segments. Every row verified 2026-10-30: Alpaca asof query returns bars; CIK name checked on
# data.sec.gov/submissions; exchange terms from the cited filing / press release / Alpaca corporate action.
PRED: list[dict[str, Any]] = [
    dict(
        index_ticker="SKYD",
        pred="PARA",
        asof="2025-08-06",
        seg_from="2016-01-04",
        seg_to="2025-08-06",
        cik=813828,
        name="Paramount Global (fka ViacomCBS, CBS Corp)",
        join_date="2025-08-07",
        ratio=1.0,
        cash=0.0,
        spin=None,
        same_security=False,
        confidence="medium",
        evidence="Alpaca corporate action stock_mergers PARA->PSKY rate 1.0 eff 2025-08-07 (class B holders could alternatively elect $15 cash, prorated; 1:1 stock used); PSKY renamed SKYD 2026-10-06 (Alpaca name_changes)",
    ),
    dict(
        index_ticker="BBWI",
        pred="LB",
        asof="2021-08-02",
        seg_from="2016-01-04",
        seg_to="2021-08-02",
        cik=701985,
        name="L Brands, Inc. (now Bath & Body Works)",
        join_date="2021-08-03",
        ratio=1.0,
        cash=0.0,
        spin=("VSCO", "2021-08-04", 1 / 3),
        same_security=True,
        confidence="high",
        evidence="https://investors.bbwinc.com/news-releases/news-release-details/bath-body-works-inc-completes-separation-victorias-secret (1 VSCO per 3 shares, after close 2021-08-02; renamed BBWI)",
    ),
    dict(
        index_ticker="VTRS",
        pred="MYL",
        asof="2020-11-13",
        seg_from="2016-01-04",
        seg_to="2020-11-13",
        cik=1623613,
        name="Mylan N.V.",
        join_date="2020-11-16",
        ratio=1.0,
        cash=0.0,
        spin=None,
        same_security=False,
        confidence="high",
        evidence="Alpaca corporate action stock_mergers MYL->VTRSV rate 1.0 eff 2020-11-16 (Mylan holders received 1 Viatris share)",
    ),
    dict(
        index_ticker="LIN",
        pred="PX",
        asof="2018-10-30",
        seg_from="2016-01-04",
        seg_to="2018-10-30",
        cik=884905,
        name="Praxair, Inc.",
        join_date="2018-10-31",
        ratio=1.0,
        cash=0.0,
        spin=None,
        same_security=False,
        confidence="high",
        evidence="https://www.sec.gov/Archives/edgar/data/1707925/000119312518313073/d643979d8k.htm (each Praxair share -> 1 Linde plc share)",
    ),
    dict(
        index_ticker="APTV",
        pred="DLPH",
        asof="2017-11-16",
        seg_from="2016-01-04",
        seg_to="2017-11-16",
        cik=1521332,
        name="Delphi Automotive PLC (now Aptiv)",
        join_date="2017-11-17",
        ratio=1.0,
        cash=0.0,
        spin=None,
        same_security=True,
        confidence="high",
        evidence="same issuer (CIK 1521332 formerNames Delphi Automotive PLC); Alpaca switches the symbol to APTV on 2017-11-17 with continuous prices",
    ),
    dict(
        index_ticker="FTI",
        pred="FTI",
        asof="2017-01-13",
        seg_from="2016-01-04",
        seg_to="2017-01-13",
        cik=1135152,
        name="FMC Technologies, Inc.",
        join_date="2017-01-17",
        ratio=1.0,
        cash=0.0,
        spin=None,
        same_security=False,
        confidence="high",
        evidence="https://www.sec.gov/Archives/edgar/data/1135152/000119312517010427/d326621d8k.htm (each FMCTI share -> 1 TechnipFMC share)",
    ),
    dict(
        index_ticker="AA",
        pred="AA",
        asof="2016-10-05",
        seg_from="2016-01-04",
        seg_to="2016-10-05",
        cik=4281,
        name="Alcoa Inc. (later Arconic Inc., now Howmet)",
        join_date="2016-10-06",
        ratio=1 / 3,
        cash=0.0,
        spin=None,
        same_security=True,
        confidence="high",
        evidence="Alpaca corporate action reverse_splits AA ex 2016-10-06 old 3 new 1; Alcoa Inc. pre-separation (Alcoa Corp spun 2016-11-01)",
    ),
    dict(
        index_ticker="SNDK",
        pred="SNDK",
        asof="2016-05-12",
        seg_from="2016-01-04",
        seg_to="2016-05-12",
        cik=1000180,
        name="SanDisk Corp (acquired by WDC 2016-05-12)",
        join_date=None,
        ratio=None,
        cash=None,
        spin=None,
        same_security=False,
        confidence="high",
        evidence="old SanDisk; the main SNDK file is the 2025 spin from WDC (CIK 2023554), a different issuer",
    ),
    dict(
        index_ticker="DD",
        pred="DD",
        asof="2017-08-30",
        seg_from="2016-01-04",
        seg_to="2017-08-31",
        cik=30554,
        name="E. I. du Pont de Nemours and Company (EIDP)",
        join_date=None,
        ratio=None,
        cash=None,
        spin=None,
        same_security=False,
        confidence="high",
        evidence="Alpaca's main DD file before 2017-09-01 carries Dow Chemical prices (identical to DOW, e.g. 66.65 on 2017-08-31); DD asof 2017-08-30 returns EIDP (83.93 on 2017-08-31). DD left the index 2017-08-31 (DWDP added) so no join day.",
    ),
    dict(
        index_ticker="UAA",
        pred="UA",
        asof="2016-04-07",
        seg_from="2016-01-04",
        seg_to="2016-04-07",
        cik=1336917,
        name="Under Armour Class A (traded as UA until 2016-04-07)",
        join_date="2016-04-08",
        ratio=1.0,
        cash=0.0,
        spin=("UA", None, 1.0),
        same_security=True,
        confidence="high",
        evidence="https://www.sec.gov/Archives/edgar/data/1336917/000119312516613432/d197397ds3asr.htm (1 Class C share per Class A share, ex 2016-04-08; Class A became UAA)",
    ),
]
# membership intervals served by another main file (same issuer, renamed): Q (QuintilesIMS 2017-08-29..2017-11-14) -> IQV
ALIAS: list[dict[str, Any]] = [
    dict(
        index_ticker="Q",
        main_file="IQV",
        seg_from="2017-08-29",
        seg_to="2017-11-14",
        cik=1478242,
        evidence="Wikipedia change 2017-11-15: QuintilesIMS changed ticker Q->IQV; CIK 1478242 formerNames Quintiles IMS Holdings",
    )
]
# within-security distributions Alpaca's adjusted series gets wrong (verified individually)
# legs: (symbol, asof, shares per old share) valued at the leg's raw close on the fix date; factor = shares of the same line per old share
# (e.g. 1/3 for a 1:3 reverse split); cash per old share; prev_file = file holding the previous close if not the same file.
FIX: list[dict[str, Any]] = [
    dict(
        symbol="APTV",
        date="2017-12-05",
        legs=[("DLPH", "2017-12-06", 1 / 3)],
        evidence="Aptiv 8-K https://www.sec.gov/Archives/edgar/data/1521332/000119312517363912/d453817d8k.htm: 1 Delphi Technologies share per 3 Delphi Automotive shares; Alpaca adj return -71.6% is wrong",
        confidence="high",
    ),
    dict(
        symbol="RTX",
        date="2020-04-03",
        legs=[("CARR", None, 1.0), ("OTIS", None, 0.5)],
        evidence="UTC press release https://www.sec.gov/Archives/edgar/data/101829/000114036120005675/nc10009877x1_ex99-1.htm: 1 CARR + 0.5 OTIS per UTX share, 2020-04-03. Alpaca encodes it as a 1:2 reverse split (adj -71%)",
        confidence="high",
    ),
    dict(
        symbol="SW",
        date="2016-05-16",
        legs=[("NGVT", None, 1 / 6)],
        evidence="WestRock spin of Ingevity, 1 NGVT per 6 WRK; Alpaca carries it as reverse_splits WRK 2016-05-16 new_rate 0.1666 (adj -84.5% is wrong)",
        confidence="medium",
    ),
    dict(
        symbol="SW",
        date="2024-07-08",
        legs=[],
        cash=5.0,
        evidence="WestRock 8-K https://www.sec.gov/Archives/edgar/data/1732845/000095014224001867/eh240504483_8k.htm: each WRK share -> 1 Smurfit Westrock share + $5.00 cash (closed 2024-07-05)",
        confidence="high",
    ),
    dict(
        symbol="TGNA",
        date="2017-06-01",
        legs=[("CARS", None, 1 / 3)],
        evidence="TEGNA spin of Cars.com, 1 CARS per 3 TGNA; Alpaca carries it as reverse_splits TGNA 2017-06-01 new_rate 0.33333 (adj -78% is wrong)",
        confidence="medium",
    ),
    dict(
        symbol="DD",
        date="2019-06-03",
        legs=[("CTVA", None, 1 / 3)],
        factor=1 / 3,
        evidence="DuPont 8-K https://www.sec.gov/Archives/edgar/data/1666700/000119312519163322/d715311d8k.htm: 1 CTVA per 3 DWDP, then 1:3 reverse split (Alpaca adj +17.8% is wrong)",
        confidence="high",
    ),
    dict(
        symbol="TT",
        date="2020-03-02",
        legs=[("IR", None, 0.8824)],
        evidence="Ingersoll-Rand plc Reverse Morris Trust with Gardner Denver: 0.8824 Gardner Denver (renamed IR) shares per IR plc share; Alpaca carries it as reverse_splits IR 2020-03-02 new_rate 0.8824 (TT adj -11.4% is wrong)",
        confidence="medium",
    ),
    dict(
        symbol="IR",
        date="2020-03-02",
        legs=[],
        evidence="Gardner Denver -> Ingersoll Rand Inc.: no distribution to GDI holders; Alpaca's IR reverse_splits 0.8824 record (the RMT ratio for TT holders) is wrongly applied to the IR line (adj -11.7%); raw close/prev used",
        confidence="medium",
    ),
    dict(
        symbol="HWM",
        date="2020-04-01",
        prev_file="ARNC",
        legs=[("ARNC", None, 0.25)],
        evidence="Arconic Inc. -> Howmet: 1 Arconic Corp (new ARNC) share per 4 Arconic Inc. shares, 2020-04-01; Alpaca ARNC reverse_splits 0.25 record; HWM file starts 2020-04-01 so the join day was NaN",
        confidence="medium",
    ),
    dict(
        skip=True,
        symbol="HON",
        date="2026-06-29",
        legs=[("HONA", None, 0.5)],
        evidence="Alpaca spin_offs HON->HONA new_rate 0.5 ex 2026-06-29 (also mis-recorded as reverse_splits 0.5)",
        confidence="medium",
    ),
    dict(
        symbol="CTVA",
        date="2026-10-01",
        legs=[("VYLR", None, 1.0)],
        evidence="Alpaca spin_offs CTVA->VYLR new_rate 1.0 ex 2026-10-01 (adj -83.8% does not credit the spin)",
        confidence="medium",
    ),
    dict(
        symbol="UAA",
        date="2016-04-08",
        legs=[("UA", None, 1.0)],
        evidence="Class C dividend 1 UA per UAA, ex 2016-04-08 (already in joins); listed here only for completeness",
        confidence="high",
        skip=True,
    ),
]
# CIK by date for tickers whose issuer changed while the price series continued (verified names on data.sec.gov/submissions
# 2026-10-30). Cut dates are the public completion dates of the reorganisation/merger (confidence medium: not filing-verified to the day).
CIK_PERIODS: dict[str, Any] = {
    "DD": [
        (None, "2017-08-31", 30554, "E. I. du Pont de Nemours (EIDP)"),
        ("2017-09-01", None, 1666700, "DowDuPont / DuPont de Nemours"),
    ],
    "DOW": [(None, "2017-08-31", 29915, "Dow Chemical Co"), ("2019-03-20", None, 1751788, "Dow Inc.")],
    "FOXA": [(None, "2019-03-19", 1308161, "Twenty-First Century Fox"), ("2019-03-20", None, 1754301, "Fox Corp")],
    # v1.2b holding-company reorganisations / redomiciles (new CIK took over the ticker; names verified on data.sec.gov/submissions)
    "FOX": [
        (None, "2019-03-19", 1308161, "Twenty-First Century Fox (class B)"),
        ("2019-03-20", None, 1754301, "Fox Corp (class B)"),
    ],
    "DIS": [
        (None, "2019-03-19", 1001039, "Walt Disney Co (now TWDC Enterprises 18)"),
        ("2019-03-20", None, 1744489, "Walt Disney Co (new holdco)"),
    ],
    "CI": [
        (None, "2018-12-20", 701221, "Cigna Corp (now Cigna Holding Co)"),
        ("2018-12-21", None, 1739940, "Cigna Corp / Cigna Group"),
    ],
    "AVGO": [
        (None, "2016-01-31", 1441634, "Avago Technologies"),
        ("2016-02-01", "2018-04-04", 1649338, "Broadcom Ltd"),
        ("2018-04-05", None, 1730168, "Broadcom Inc."),
    ],
    "BLK": [
        (None, "2024-09-30", 1364742, "BlackRock Inc (now BlackRock Finance)"),
        ("2024-10-01", None, 2012383, "BlackRock, Inc. (new holdco)"),
    ],
    "XOM": [(None, "2026-06-30", 34088, "Exxon Mobil Corp"), ("2026-07-01", None, 2115436, "ExxonMobil Holdings Corp")],
    "APA": [
        (None, "2021-02-26", 6769, "Apache Corp"),
        ("2021-03-01", None, 1841666, "APA Corp (holding-company reorg 1:1)"),
    ],
    "XRX": [
        (None, "2019-07-31", 108772, "Xerox Corp"),
        ("2019-08-01", None, 1770450, "Xerox Holdings (holding-company reorg 1:1)"),
    ],
    "TYC": [(None, "2016-09-02", 833444, "Tyco International plc (became Johnson Controls International plc)")],
    "EVHC": [
        (None, "2016-11-30", 1578318, "Envision Healthcare Holdings"),
        ("2016-12-01", None, 1678531, "Envision Healthcare Corp (AmSurg merger)"),
    ],
    "SW": [
        (None, "2024-07-05", 1636023, "WestRock Co (Alpaca carries WRK history under SW)"),
        ("2024-07-08", None, 2005951, "Smurfit Westrock plc"),
    ],
}
# former members whose ticker->CIK map pointed at the ticker's CURRENT owner (ticker reuse in SEC company_tickers / EFTS):
CIK_FIX: dict[str, tuple[int, str]] = {
    "APC": (773910, "Anadarko Petroleum Corp"),
    "POM": (1135971, "Pepco Holdings"),
    "SE": (1373835, "Spectra Energy Corp"),
    "STI": (750556, "SunTrust Banks"),
    "TE": (350563, "TECO Energy"),
    "XL": (875159, "XL Group"),
    "BHI": (808362, "Baker Hughes Inc"),
    "ARNC": (4281, "Arconic Inc. (ex-Alcoa Inc., now Howmet)"),
    # v1.2 (sentiment researcher gap list): EFTS name search had matched subsidiaries/unrelated filers; verified on data.sec.gov/submissions 2026-10-30
    "CDAY": (1725057, "Ceridian HCM Holding (now Dayforce)"),
    "AGN": (1578845, "Allergan plc (fka Actavis plc)"),
    "BCR": (9892, "C. R. Bard"),
    "CCE": (1491675, "Coca-Cola Enterprises, Inc."),
    "ESV": (314808, "Ensco plc (now Valaris)"),
    "ETFC": (1015780, "E*TRADE Financial"),
    "GGP": (1496048, "GGP Inc. (General Growth Properties)"),
    "HAR": (800459, "Harman International Industries"),
    "LVLT": (794323, "Level 3 Communications Inc"),
    "MJN": (1452575, "Mead Johnson Nutrition"),
    "MNK": (1567892, "Mallinckrodt plc"),
    "NLSN": (1492633, "Nielsen Holdings plc"),
    "SCG": (754737, "SCANA Corp"),
    "SEE": (1012100, "Sealed Air Corp"),
    "TWC": (1377013, "Time Warner Cable Inc."),
    "TWX": (1105705, "Time Warner Inc."),
    "WCG": (1279363, "WellCare Health Plans"),
    "YHOO": (1011006, "Yahoo! Inc. (later Altaba)"),
    "DISCA": (1437107, "Discovery, Inc."),
    "DISCK": (1437107, "Discovery, Inc."),
    # v1.2b: ticker map pointed at a later/unrelated owner of the ticker (found by the CIK-age vs membership audit)
    "ADT": (1546640, "ADT Corp (2012-2016; not ADT Inc. 1703056)"),
    "CA": (356028, "CA, Inc. (not Cavitation Technologies)"),
    "CTRA": (858470, "Coterra Energy (ex-Cabot Oil & Gas; not Contura/Alpha Metallurgical)"),
    "HFC": (48039, "HollyFrontier Corp"),
}
# main files that mix issuers (cut dates): rows < cut belong to the first issuer
MIXED: dict[str, dict[str, Any]] = {
    "AA": dict(
        cut="2016-11-01",
        before_cik=4281,
        after_cik=1675149,
        note="Alcoa Inc. until 2016-10-31; Alcoa Corp from 2016-11-01",
    ),
    "SW": dict(
        cut="2024-07-08",
        before_cik=1636023,
        after_cik=2005951,
        note="WestRock (WRK) history until 2024-07-05; Smurfit Westrock from 2024-07-08 (1 SW + $5 cash per WRK)",
    ),
    "UA": dict(
        cut="2016-04-08",
        before_cik=1336917,
        after_cik=1336917,
        note="pre-2016-04-08 rows are the Class A (UAA) history; Class C from 2016-04-08",
    ),
}


def close_on(sym: str, day: str, asof: str) -> float | None:
    r = fetch([sym], day, f"{day}T23:59:00Z", "raw", "sip", asof).get(sym, [])
    return r[0]["c"] if r else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    a = ap.parse_args()
    cal = calendar("2016-01-01")
    sess = pd.Index(sorted(cal["date"]))
    fetched = dt.datetime.now(dt.UTC)
    # 1) predecessor bars
    for p in PRED:
        for adj in ("raw", "adjusted"):
            f = PRED_DIR / adj / f"{p['pred']}_asof{p['asof'].replace('-', '')}.parquet"
            if f.exists() and not a.refetch:
                continue
            bars = fetch([p["pred"]], p["seg_from"], f"{p['seg_to']}T23:59:00Z", ADJ[adj], "sip", p["asof"]).get(
                p["pred"], []
            )
            df = to_df(p["pred"], bars, adj, "sip", p["asof"], pd.Timestamp(fetched))
            df = df[
                (df.session_date >= pd.Timestamp(p["seg_from"]).date())
                & (df.session_date <= pd.Timestamp(p["seg_to"]).date())
            ]
            df["zero_volume"] = df.volume == 0
            df["index_ticker"] = p["index_ticker"]
            write_parquet(df, f)
            log.info("pred %s %s rows=%d", p["pred"], adj, len(df))
    # 2) CIK per main symbol (same priority as earnings.py)
    u = pd.read_parquet(DATA / "universe/universe.parquet")
    m = pd.read_parquet(DATA / "reference/ticker_cik_map.parquet").dropna(subset=["cik"])
    pr = {
        "wikipedia_sp500_cik": 0,
        "sec_company_tickers": 1,
        "edgar_submissions": 2,
        "alpaca_name_change": 3,
        "manual_verified_edgar": -1,
        "efts_name_search": 4,
    }
    m = m.assign(p=m.source.map(pr)).sort_values("p").drop_duplicates("ticker")
    cik = dict(zip(m.ticker, m.cik.astype(int)))
    ename = dict(zip(m.ticker, m.entity_name))
    for t_, (c_, n_) in CIK_FIX.items():  # v1.2b: verified issuer CIKs also drive security_id for these tickers
        cik[t_] = c_
        ename[t_] = n_
    raw = pd.read_parquet(DATA / "bars/daily/raw", columns=["symbol", "session_date"])
    rng = raw.groupby("symbol").session_date.agg(["min", "max"])

    def sid(c: Any, d: Any, t: Any) -> str:
        return f"S{int(c):010d}-{pd.Timestamp(d):%Y%m%d}" if c is not None else f"T-{t}-{pd.Timestamp(d):%Y%m%d}"

    seg_rows: list[dict[str, Any]] = []
    etf = set(u.loc[u.role == "etf", "symbol"])
    predmap = {p["index_ticker"]: p for p in PRED}
    for s in u.symbol:
        lo, hi = rng.loc[s, "min"], rng.loc[s, "max"]
        if s in etf:
            seg_rows.append(
                dict(
                    security_id=f"ETF-{s}",
                    cik=cik.get(s),
                    entity_name=ename.get(s),
                    bars_source="main",
                    bars_file=s,
                    ticker_at_time=s,
                    asof=None,
                    seg_from=lo,
                    seg_to=hi,
                    evidence="etf",
                )
            )
            continue
        if s in MIXED:
            x = MIXED[s]
            cut = pd.Timestamp(x["cut"]).date()
            first_id = None
            if s == "AA":
                first_id = sid(4281, "2016-01-04", s)  # Alcoa Inc. security also owns the predecessor segment
            if s == "UA":
                first_id = sid(1336917, "2016-01-04", "UAA")  # = UAA's security (class A)
            first_id = first_id or sid(x["before_cik"], lo, s)
            seg_rows.append(
                dict(
                    security_id=first_id,
                    cik=x["before_cik"],
                    entity_name=None,
                    bars_source="main",
                    bars_file=s,
                    ticker_at_time=s,
                    asof=None,
                    seg_from=lo,
                    seg_to=sess[sess.searchsorted(cut) - 1],
                    evidence=x["note"],
                )
            )
            seg_rows.append(
                dict(
                    security_id=sid(x["after_cik"], cut, s),
                    cik=x["after_cik"],
                    entity_name=ename.get(s),
                    bars_source="main",
                    bars_file=s,
                    ticker_at_time=s,
                    asof=None,
                    seg_from=cut,
                    seg_to=hi,
                    evidence=x["note"],
                )
            )
            continue
        pred = predmap.get(s)
        i = sid(pred["cik"], pred["seg_from"], s) if pred and pred["same_security"] else sid(cik.get(s), lo, s)
        seg_rows.append(
            dict(
                security_id=i,
                cik=cik.get(s),
                entity_name=ename.get(s),
                bars_source="main",
                bars_file=s,
                ticker_at_time=s,
                asof=None,
                seg_from=lo,
                seg_to=hi,
                evidence="main bars file",
            )
        )
    for p in PRED:
        i = sid(p["cik"], p["seg_from"], p["pred"])
        if p["index_ticker"] == "UAA":
            i = sid(1336917, "2016-01-04", "UAA")
        seg_rows.append(
            dict(
                security_id=i,
                cik=p["cik"],
                entity_name=p["name"],
                bars_source="predecessor",
                bars_file=f"{p['pred']}_asof{p['asof'].replace('-', '')}",
                ticker_at_time=p["pred"],
                asof=p["asof"],
                seg_from=pd.Timestamp(p["seg_from"]).date(),
                seg_to=pd.Timestamp(p["seg_to"]).date(),
                evidence=p["evidence"],
            )
        )
    seg = pd.DataFrame(seg_rows)
    # UAA main file segment must carry the class-A security id
    seg.loc[(seg.bars_file == "UAA"), "security_id"] = sid(1336917, "2016-01-04", "UAA")
    seg.loc[(seg.bars_file == "AA") & (seg.seg_from == rng.loc["AA", "min"]), "security_id"] = sid(
        4281, "2016-01-04", "AA"
    )
    write_parquet(seg, DATA / "reference/security_segments.parquet")
    sm = (
        seg.groupby("security_id")
        .agg(
            cik=("cik", "first"),
            entity_name=("entity_name", lambda x: next((v for v in x if isinstance(v, str)), None)),
            first_session=("seg_from", "min"),
            last_session=("seg_to", "max"),
            tickers=("ticker_at_time", lambda x: ",".join(dict.fromkeys(x))),
            n_segments=("bars_file", "size"),
        )
        .reset_index()
    )
    write_parquet(sm, DATA / "reference/security_master.parquet")
    cp_rows: list[dict[str, Any]] = []
    lo_all = "2016-01-04"
    for t in u.symbol:
        if t in etf:
            continue
        if t in CIK_PERIODS:
            for f_, t_, c, nm in CIK_PERIODS[t]:
                cp_rows.append(
                    dict(
                        index_ticker=t,
                        cik=c,
                        entity_name=nm,
                        valid_from=f_ or lo_all,
                        valid_to=t_,
                        method="cik_period_override",
                        confidence="medium",
                    )
                )
            continue
        base = CIK_FIX.get(t, (cik.get(t), ename.get(t)))
        pred = predmap.get(t)
        al = [x for x in ALIAS if x["index_ticker"] == t]
        if t == "AA":
            cp_rows += [
                dict(
                    index_ticker=t,
                    cik=4281,
                    entity_name="Alcoa Inc.",
                    valid_from=lo_all,
                    valid_to="2016-10-31",
                    method="mixed_file_cut",
                    confidence="high",
                ),
                dict(
                    index_ticker=t,
                    cik=1675149,
                    entity_name="Alcoa Corp",
                    valid_from="2016-11-01",
                    valid_to=None,
                    method="mixed_file_cut",
                    confidence="high",
                ),
            ]
            continue
        if pred:
            cp_rows.append(
                dict(
                    index_ticker=t,
                    cik=pred["cik"],
                    entity_name=pred["name"],
                    valid_from=pred["seg_from"],
                    valid_to=pred["seg_to"],
                    method="predecessor_segment",
                    confidence=pred["confidence"],
                )
            )
            if t == "SNDK":
                cp_rows.append(
                    dict(
                        index_ticker=t,
                        cik=base[0],
                        entity_name=base[1],
                        valid_from="2025-02-13",
                        valid_to=None,
                        method="ticker_map",
                        confidence="high",
                    )
                )
            elif not pred["same_security"]:
                cp_rows.append(
                    dict(
                        index_ticker=t,
                        cik=base[0],
                        entity_name=base[1],
                        valid_from=pred["join_date"],
                        valid_to=None,
                        method="ticker_map",
                        confidence="high",
                    )
                )
            else:
                cp_rows[-1]["valid_to"] = None
            continue
        if al:
            a0 = al[0]
            cp_rows += [
                dict(
                    index_ticker=t,
                    cik=a0["cik"],
                    entity_name="QuintilesIMS / IQVIA",
                    valid_from=a0["seg_from"],
                    valid_to=a0["seg_to"],
                    method="alias_main_file",
                    confidence="high",
                ),
                dict(
                    index_ticker=t,
                    cik=base[0],
                    entity_name=base[1],
                    valid_from="2025-10-01",
                    valid_to=None,
                    method="ticker_map",
                    confidence="high",
                ),
            ]
            continue
        cp_rows.append(
            dict(
                index_ticker=t,
                cik=base[0],
                entity_name=base[1],
                valid_from=lo_all,
                valid_to=None,
                method="cik_fix_former_member" if t in CIK_FIX else "ticker_map",
                confidence="high" if t in CIK_FIX else None,
            )
        )
    cp = pd.DataFrame(cp_rows)
    cp["cik"] = pd.to_numeric(cp.cik, errors="coerce").astype("Int64")
    write_parquet(cp, DATA / "reference/cik_periods.parquet")

    # 3) join returns from deal terms
    def last_close(file: str, src: str) -> pd.DataFrame:
        return pd.read_parquet(
            (PRED_DIR / "raw" / f"{file}.parquet")
            if src == "predecessor"
            else (DATA / "bars/daily/raw" / f"{file}.parquet")
        )

    join_rows: list[dict[str, Any]] = []
    for p in PRED:
        if not p["join_date"]:
            continue
        pr_ = pd.read_parquet(PRED_DIR / "raw" / f"{p['pred']}_asof{p['asof'].replace('-', '')}.parquet")
        prev_bar = pr_[pr_.volume > 0].sort_values("session_date").iloc[-1]
        jd = pd.Timestamp(p["join_date"]).date()
        if p["index_ticker"] == "AA":  # within the same AA ticker: post-reverse-split rows in the main AA file
            succ = pd.read_parquet(DATA / "bars/daily/raw/AA.parquet")
        else:
            succ = pd.read_parquet(DATA / f"bars/daily/raw/{p['index_ticker']}.parquet")
        sc = succ.loc[succ.session_date == jd, "close"]
        if sc.empty:
            log.warning("no successor close %s %s", p["index_ticker"], jd)
            continue
        val = float(sc.iloc[0]) * p["ratio"] + p["cash"]
        spin_note = ""
        if p["spin"]:
            sym, asof, r = p["spin"]
            c = close_on(sym, p["join_date"], asof)
            if c is None:
                log.warning("no spin close %s", sym)
                continue
            val += r * c
            spin_note = f" + {r:.4f} x {sym} close {c}"
        join_rows.append(
            dict(
                index_ticker=p["index_ticker"],
                session_date=jd,
                pred_last_close=float(prev_bar.close),
                pred_last_date=prev_bar.session_date,
                successor_close=float(sc.iloc[0]),
                ratio=p["ratio"],
                value_per_pred_share=val,
                ret_total=val / float(prev_bar.close) - 1,
                formula=f"({float(sc.iloc[0])} x {p['ratio']:.4f}{spin_note}) / {float(prev_bar.close)} - 1",
                kind="predecessor_join",
                confidence=p["confidence"],
                evidence=p["evidence"],
            )
        )
    tr = pd.read_parquet(
        DATA / "bars/daily/total_return/daily_total_return.parquet",
        columns=[
            "symbol",
            "session_date",
            "close_raw",
            "open_adj",
            "close_adj",
            "ret_total_best",
            "ret_total",
            "alpaca_adj_ret",
            "tr_mismatch_gt50bps",
        ],
    )
    for fx in FIX:
        if fx.get("skip"):
            continue
        d = pd.Timestamp(fx["date"]).date()
        t = tr[tr.symbol == fx["symbol"]].sort_values("session_date")
        cur_px = float(t.loc[t.session_date == d, "close_raw"].iloc[0])
        pf = tr[tr.symbol == fx.get("prev_file", fx["symbol"])]
        prev_row = pf[pf.session_date < d].sort_values("session_date").iloc[-1]
        prev_px = float(prev_row.close_raw)
        fac = fx.get("factor", 1.0)
        cash = fx.get("cash", 0.0)
        val = cur_px * fac + cash
        parts = [f"{cur_px} x {fac:.4f}"] + ([f"{cash} cash"] if cash else [])
        ok = True
        for sym, asof, r in fx["legs"]:
            c = close_on(sym, fx["date"], asof)
            if c is None:
                log.warning("no leg close %s %s", sym, fx["date"])
                ok = False
                break
            val += r * c
            parts.append(f"{r:.4f} x {sym} {c}")
        if not ok:
            continue
        join_rows.append(
            dict(
                index_ticker=fx["symbol"],
                session_date=d,
                pred_last_close=prev_px,
                pred_last_date=prev_row.session_date,
                successor_close=cur_px,
                ratio=fac,
                value_per_pred_share=val,
                ret_total=val / prev_px - 1,
                formula=f"({' + '.join(parts)}) / {prev_px} - 1",
                kind="distribution_fix",
                confidence=fx["confidence"],
                evidence=fx["evidence"],
            )
        )
    joins = pd.DataFrame(join_rows)
    write_parquet(joins, DATA / "reference/security_joins.parquet")

    # 4) member-day panel
    mem = pd.read_parquet(DATA / "universe/sp500_membership.parquet")
    last = min(sess[sess <= dt.date.today()][-1], raw.session_date.max())
    S = sess[(sess >= dt.date(2016, 1, 4)) & (sess <= last)]
    md_rows: list[tuple[Any, Any]] = []
    for r in mem.itertuples():
        e = r.end_date or dt.date(2100, 1, 1)
        for d in S[(r.start_date_filled <= S) & (e > S)]:
            md_rows.append((d, r.symbol))
    md = pd.DataFrame(md_rows, columns=["session_date", "index_ticker"]).drop_duplicates()
    # resolve the segment for each member-day
    pred_rows: list[pd.DataFrame] = []
    for p in PRED:
        f = PRED_DIR / "adjusted" / f"{p['pred']}_asof{p['asof'].replace('-', '')}.parquet"
        ad = pd.read_parquet(f).sort_values("session_date")
        rw = pd.read_parquet(PRED_DIR / "raw" / f.name).sort_values("session_date")
        frame = (
            ad[["session_date", "open", "close"]]
            .rename(columns={"open": "open_adj", "close": "close_adj"})
            .merge(rw[["session_date", "close", "volume"]].rename(columns={"close": "close_raw"}), on="session_date")
        )
        frame["ret_total"] = frame.close_adj.pct_change()
        frame["ret_source"] = "predecessor_alpaca_adj_all"
        frame.loc[frame.volume == 0, ["ret_total"]] = np.nan
        frame.loc[frame.volume == 0, "ret_source"] = "placeholder_zero_volume"
        frame["index_ticker"] = p["index_ticker"]
        frame["bars_file"] = f"predecessors/{f.stem}"
        frame["security_id"] = seg.loc[
            (seg.bars_source == "predecessor") & (seg.bars_file == f.stem), "security_id"
        ].iloc[0]
        pred_rows.append(frame.drop(columns="volume"))
    for alias in ALIAS:
        t = tr[
            (tr.symbol == alias["main_file"])
            & (tr.session_date >= pd.Timestamp(alias["seg_from"]).date())
            & (tr.session_date <= pd.Timestamp(alias["seg_to"]).date())
        ]
        frame = t[["session_date", "open_adj", "close_adj", "close_raw", "ret_total_best"]].rename(
            columns={"ret_total_best": "ret_total"}
        )
        frame["ret_source"] = f"main_tr_best:{alias['main_file']}"
        frame["index_ticker"] = alias["index_ticker"]
        frame["bars_file"] = alias["main_file"]
        frame["security_id"] = seg.loc[seg.bars_file == alias["main_file"], "security_id"].iloc[0]
        pred_rows.append(frame)
    P = pd.concat(pred_rows, ignore_index=True)
    main = tr.rename(columns={"symbol": "index_ticker"})
    main = main.assign(
        ret_total_own=main.ret_total,
        ret_total=main.ret_total_best,
        ret_source="main_tr_best",
        bars_file=main.index_ticker,
    )
    # security id on main rows via segments
    sg = seg[seg.bars_source == "main"][["bars_file", "security_id", "seg_from", "seg_to"]]
    main = main.merge(sg, on="bars_file", how="left")
    main = main[(main.session_date >= main.seg_from) & (main.session_date <= main.seg_to)].drop(
        columns=["seg_from", "seg_to"]
    )
    # predecessor/alias rows take precedence over main rows on the same (day, index_ticker)
    out = md.merge(P, on=["session_date", "index_ticker"], how="left")
    have = out.security_id.notna()
    m2 = md.merge(
        main[
            [
                "session_date",
                "index_ticker",
                "security_id",
                "bars_file",
                "close_raw",
                "open_adj",
                "close_adj",
                "ret_total",
                "ret_total_own",
                "ret_source",
                "alpaca_adj_ret",
                "tr_mismatch_gt50bps",
            ]
        ],
        on=["session_date", "index_ticker"],
        how="left",
    )
    out = pd.concat(
        [
            out[have],
            m2[
                ~m2.set_index(["session_date", "index_ticker"]).index.isin(
                    out[have].set_index(["session_date", "index_ticker"]).index
                )
            ],
        ],
        ignore_index=True,
    )
    # SNDK old interval must never be served by the new SNDK file (main SNDK rows start 2025-02-13 anyway)
    # join-day + distribution fixes
    J = joins.set_index(["index_ticker", "session_date"])
    k = out.set_index(["index_ticker", "session_date"]).index
    hit = k.isin(J.index)
    out.loc[hit, "ret_total"] = [J.loc[x, "ret_total"] for x in k[hit]]
    out.loc[hit, "ret_source"] = [f"deal_terms:{J.loc[x, 'kind']}" for x in k[hit]]
    # UA class C first day: the previous row is class A history -> no valid one-day return for the UA line
    out.loc[(out.index_ticker == "UA") & (out.session_date == dt.date(2016, 4, 8)), ["ret_total", "ret_source"]] = [  # type: ignore[index, assignment]  # loc assigns a two-cell row
        np.nan,
        "nan_first_day_new_class",
    ]
    out["no_bar"] = out.security_id.isna() | out.close_raw.isna()
    # suspect flag: |ret| > 40% not explained by a deal-terms fix, or Alpaca adj vs own TR > 10% apart
    ca = pd.read_parquet(DATA / "corporate_actions/all_actions.parquet")
    spin_days = set(
        zip(
            ca.loc[ca.type == "spin_offs", "source_symbol"],
            pd.to_datetime(ca.loc[ca.type == "spin_offs", "ex_date"]).dt.date,
        )
    )
    is_fix = out.ret_source.astype(str).str.startswith("deal_terms")
    spin = pd.Series([(t, d) in spin_days for t, d in zip(out.index_ticker, out.session_date)], index=out.index)
    big = (out.ret_total.abs() > 0.40) & ~is_fix
    disagree = ((out.alpaca_adj_ret - out.ret_total_own).abs() > 0.10) & ~is_fix & ~spin
    manual = (out.index_ticker == "HON") & (out.session_date == dt.date(2026, 6, 29))
    out["ret_suspect"] = big | disagree | manual
    out["ret_suspect_reason"] = np.select(
        [manual, big & disagree, big, disagree],
        [
            "HON/HONA 2026-06-29: Alpaca spin 0.5 HONA, but HON raw fell only 1.9% while HONA traded ~221 -> distribution terms unverified",
            "abs_ret_gt_40pct_and_alpaca_vs_own_tr_gt_10pct",
            "abs_ret_gt_40pct_unverified (often a real move)",
            "alpaca_adj_vs_own_tr_gt_10pct_no_spin_record",
        ],
        default="",
    )
    out = out.sort_values(["session_date", "index_ticker"]).reset_index(drop=True)
    write_parquet(out, DATA / "universe/sp500_member_days.parquet")
    by = out.groupby(pd.to_datetime(out.session_date).dt.year).no_bar.sum().to_dict()
    info = {
        "securities": int(len(sm)),
        "segments": int(len(seg)),
        "predecessor_segments": len(PRED),
        "joins": int(len(joins)),
        "member_days": int(len(out)),
        "member_days_without_bar": int(out.no_bar.sum()),
        "no_bar_by_year": {str(k): int(v) for k, v in by.items()},
        "updated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    update_manifest("security_master", info)
    log.info("%s", info)


if __name__ == "__main__":
    main()
