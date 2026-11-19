#!/usr/bin/env python3
"""Build issuer-document distribution/split ledger for 9 ETFs + v1.3 reconciliation. Reads only files under
./sources (raw issuer docs) and v1.3 corporate_actions (read-only). Writes only to --out (must not exist)."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import openpyxl
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "sources")
V13 = f"{_QR.DATA_DIR}/releases/v1.3/corporate_actions"
SPDR = ["XLP", "XLV", "XLU", "XLY", "XLI", "XLK"]
ISH = ["IEF", "SHY", "TLT"]
ALL11 = ["XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"]
START = dt.date(2016, 1, 1)
LOG = [json.loads(l) for l in open(os.path.join(ROOT, "fetch_log.jsonl"))]
byfile = {r["file"]: r for r in LOG if r.get("file")}


def sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def src(rel: str) -> tuple[str, str, str]:
    r = byfile["sources/" + rel]
    assert sha(os.path.join(SRC, rel)) == r["sha256"], rel
    return r["url"], r["sha256"], "sources/" + rel


def d_us(s: str) -> dt.date:
    s = s.strip()
    f = "%m/%d/%Y" if len(s.split("/")[-1]) == 4 else "%m/%d/%y"
    return dt.datetime.strptime(s, f).date()


def dec(s: str | None) -> Decimal | None:
    s = (s or "").strip().replace("$", "")
    return None if s in ("", "-") else Decimal(s)


D9 = pa.decimal128(18, 9)
SCHEMA = pa.schema(
    [
        ("row_id", pa.string()),
        ("ticker", pa.string()),
        ("issuer", pa.string()),
        ("event_type", pa.string()),
        ("ex_date", pa.date32()),
        ("record_date", pa.date32()),
        ("payable_date", pa.date32()),
        ("declaration_date", pa.date32()),
        ("amount_str", pa.string()),
        ("amount_decimal", D9),
        ("income_str", pa.string()),
        ("st_cap_gain_str", pa.string()),
        ("lt_cap_gain_str", pa.string()),
        ("roc_str", pa.string()),
        ("split_ratio_str", pa.string()),
        ("split_new_per_old", D9),
        ("frequency", pa.string()),
        ("cusip", pa.string()),
        ("source_kind", pa.string()),
        ("source_url", pa.string()),
        ("source_file", pa.string()),
        ("doc_sha256", pa.string()),
        ("date_field_provenance", pa.string()),
        ("notes", pa.string()),
    ]
)
rows: list[dict[str, Any]] = []


def add(**k: Any) -> None:
    base = {f.name: None for f in SCHEMA}
    base.update(k)
    rows.append(base)


# ---- SSGA XLSX (as-paid amounts; no declaration date column)
u, h, f = src("ssga/spdr-etf-historical-distributions.xlsx")
ws = openpyxl.load_workbook(os.path.join(ROOT, f), read_only=True).worksheets[0]
hdr = None
for xlsx in ws.iter_rows(values_only=True):
    if hdr is None:
        hdr = xlsx
        assert hdr[:10] == (
            "FUND NAME",
            "TICKER",
            "CUSIP",
            "EX-DATE",
            "RECORD DATE",
            "PAYABLE DATE",
            "DIVIDEND ($)",
            "SHORT TERM CAPITAL GAIN ($)",
            "LONG TERM CAPITAL GAIN ($)",
            "FREQUENCY",
        ), hdr
        continue
    if xlsx[1] not in SPDR:
        continue
    ex = d_us(cast(str, xlsx[3]))
    if ex < START:
        continue
    prov = json.dumps(
        {"ex_date": f, "record_date": f, "payable_date": f, "declaration_date": "NOT_PUBLISHED_IN_SOURCE", "amount": f}
    )
    common = dict(
        ticker=xlsx[1],
        issuer="SSGA/Select Sector SPDR Trust",
        ex_date=ex,
        record_date=d_us(cast(str, xlsx[4])),
        payable_date=d_us(cast(str, xlsx[5])),
        frequency=xlsx[9],
        cusip=xlsx[2],
        source_kind="ISSUER_XLSX_HISTORICAL_DISTRIBUTIONS",
        source_url=u,
        source_file=f,
        doc_sha256=h,
        date_field_provenance=prov,
        income_str=xlsx[6],
        st_cap_gain_str=xlsx[7],
        lt_cap_gain_str=xlsx[8],
    )
    add(
        row_id=f"{xlsx[1]}|{ex}|CASH_DIST",
        event_type="CASH_DIST",
        amount_str=xlsx[6],
        amount_decimal=dec(cast(str, xlsx[6])),
        notes="dividend column; as-paid (not split-adjusted)",
        **common,
    )
    for col, lab in ((7, "ST"), (8, "LT")):
        gain = dec(cast(str | None, xlsx[col]))
        if gain is not None and gain != 0:
            add(
                row_id=f"{xlsx[1]}|{ex}|CAP_GAIN_{lab}",
                event_type="CAP_GAIN",
                amount_str=xlsx[col],
                amount_decimal=gain,
                notes=f"{lab} capital gain column",
                **common,
            )
# ---- iShares annual distribution summaries (tax docs)
DOCS = {
    2017: (
        "ishares/wayback_20181009163310_2017-ishares-distribution-summary-final-364627.pdf",
        {"ltcg": 6, "stcg": 2, "income": 1, "roc": 7},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF_VIA_WAYBACK",
    ),
    2018: (
        "ishares/wayback_20190422064338_2018-ishares-distribution-summary-icrmh0219u-716296.pdf",
        {"ltcg": 6, "stcg": 2, "income": 1, "roc": 7},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF_VIA_WAYBACK",
    ),
    2019: (
        "ishares/wayback_20220124040012_2019-ishares-distribution-summary-icrmh0220u-1067863.pdf",
        {"ltcg": 6, "stcg": 2, "income": 1, "roc": 7},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF_VIA_WAYBACK",
    ),
    2020: (
        "ishares/2020-ishares-distribution-summary.pdf",
        {"ltcg": 3, "roc": 4},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF",
    ),
    2021: (
        "ishares/2021-ishares-distribution-summary.pdf",
        {"ltcg": 3, "roc": 4},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF",
    ),
    2022: (
        "ishares/2022-ishares-distribution-summary-stamped.pdf",
        {"ltcg": 3, "roc": 4},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF",
    ),
    2023: (
        "ishares/2023-ishares-distribution-summary-stamped.pdf",
        {"ltcg": 3, "roc": 4},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF",
    ),
    2024: (
        "ishares/2024-ishares-etf-distribution-summary-stamped-extended.pdf",
        {"ltcg": 3, "roc": 4},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF",
    ),
    2025: (
        "ishares/2025-ishares-distribution-summary-stamped.pdf",
        {"ltcg": 4, "roc": 5},
        "ISSUER_ANNUAL_DISTRIBUTION_SUMMARY_PDF",
    ),
}
DRE = re.compile(r"^\d{2}/\d{2}/\d{2}(\d{2})?$")
for yr, (rel, cols, kind) in DOCS.items():
    u, h, f = src(rel)
    txt = subprocess.run(
        ["pdftotext", "-layout", os.path.join(ROOT, f), "-"], capture_output=True, text=True, check=True
    ).stdout
    for line in txt.split("\n"):
        m = re.match(r"^\s*(IEF|SHY|TLT)\s", line)
        if not m:
            continue
        toks = line.split()
        di = [i for i, x in enumerate(toks) if DRE.match(x)]
        assert len(di) >= 3 and di[1] == di[0] + 1 and di[2] == di[0] + 2, line
        record_dt, ex, pay = (d_us(toks[i]) for i in di[:3])
        cells = toks[di[2] + 1 :]
        get = cast(
            Callable[[str], str | None],
            lambda k: cells[cols[k]] if k in cols and cols[k] < len(cells) else None,
        )
        total = cells[0]
        ltcg = get("ltcg")
        stcg = get("stcg")
        inc = get("income")
        roc = get("roc")
        lt = dec(ltcg) or Decimal(0)
        st_amt = dec(stcg) or Decimal(0)
        et = "CAP_GAIN" if dec(total) == lt + st_amt and (lt + st_amt) > 0 else "CASH_DIST"
        prov = json.dumps(
            {
                "ex_date": f,
                "record_date": f,
                "payable_date": f,
                "declaration_date": "NOT_PUBLISHED_IN_SOURCE",
                "amount": f + " (TOTAL DISTRIB PER SHARE)",
            }
        )
        add(
            row_id=f"{m.group(1)}|{ex}|{et}|{yr}",
            ticker=m.group(1),
            issuer="iShares/BlackRock",
            event_type=et,
            ex_date=ex,
            record_date=record_dt,
            payable_date=pay,
            amount_str=total,
            amount_decimal=dec(total),
            income_str=inc,
            st_cap_gain_str=stcg,
            lt_cap_gain_str=ltcg,
            roc_str=roc,
            frequency="Monthly",
            source_kind=kind,
            source_url=u,
            source_file=f,
            doc_sha256=h,
            date_field_provenance=prov,
            notes=(f"tax-year {yr} summary; total includes LTCG {ltcg}" if lt > 0 else f"tax-year {yr} summary")
            + ("; STCG not separately published (folded in ordinary dividends)" if "stcg" not in cols else ""),
        )
# ---- 2026 YTD iShares: prior sealed product-page projection (distribution table only)
pj = "prior_sealed/product_page_distributions_projection.json"
pjp = os.path.join(SRC, pj)
pjsha = sha(pjp)
P = json.load(open(pjp))
URLS = {
    "IEF": "https://www.ishares.com/us/products/239456/ishares-710-year-treasury-bond-etf",
    "SHY": "https://www.ishares.com/us/products/239452/ishares-13-year-treasury-bond-etf",
    "TLT": "https://www.ishares.com/us/products/239454/ishares-20-year-treasury-bond-etf",
}
pd_ = cast(Callable[[str], dt.date], lambda s: dt.datetime.strptime(s, "%b %d, %Y").date())
for s in ISH:
    for x in P[s]["distributions"]:
        ex = pd_(x["ex_date"])
        if ex.year < 2026:
            continue
        tot = x["total"].replace("$", "")
        lt = dec(x["lt_cap_gains"]) or Decimal(0)
        st_amt = dec(x["st_cap_gains"]) or Decimal(0)
        et = "CAP_GAIN" if dec(tot) == lt + st_amt and lt + st_amt > 0 else "CASH_DIST"
        prov = json.dumps(
            {
                "ex_date": "sources/" + pj,
                "record_date": "sources/" + pj,
                "payable_date": "sources/" + pj,
                "declaration_date": "NOT_PUBLISHED_IN_SOURCE",
                "amount": "sources/" + pj + " (total)",
            }
        )
        add(
            row_id=f"{s}|{ex}|{et}|2026",
            ticker=s,
            issuer="iShares/BlackRock",
            event_type=et,
            ex_date=ex,
            record_date=pd_(x["record_date"]),
            payable_date=pd_(x["payable_date"]),
            amount_str=x["total"],
            amount_decimal=dec(tot),
            income_str=x["income"],
            st_cap_gain_str=x["st_cap_gains"],
            lt_cap_gain_str=x["lt_cap_gains"],
            roc_str=x["return_of_capital"],
            frequency="Monthly",
            cusip=P[s]["identity"].get("cusip"),
            source_kind="PRIOR_SEALED_PROJECTION_OF_ISSUER_PRODUCT_PAGE",
            source_url=URLS[s],
            source_file="sources/" + pj,
            doc_sha256=pjsha,
            date_field_provenance=prov,
            notes=f"projection of sealed product HTML sha {P[s]['sha256']} fetched 2026-11-07 ~13:45 SGT (Phase 1, ledger treasury_sip_audit_plan_20261107); distributions table only; 2026 YTD not yet in an annual summary",
        )
# ---- splits (issuer docs)
pu, ph, pf = src("split/statestreet_pr_20251120_five_sector_splits.html")
for t in ("XLK", "XLU", "XLY"):
    fu, fh, ff = src(f"split/form8937_{t}_2025.pdf")
    prov = json.dumps(
        {
            "ex_date": f"{pf} ('trade at post-split price effective December 5, 2025'); {ff} (date of action December 5, 2025)",
            "record_date": f"{pf} ('shareholders of record as of the market close on December 2, 2025')",
            "payable_date": f"{pf} ('payable after market close on December 4, 2025')",
            "declaration_date": f"{pf} (press release dated November 20, 2025 announcing the split)",
            "ratio": f"{pf}; {ff} ('2:1 Share Split')",
        }
    )
    add(
        row_id=f"{t}|2025-12-05|SPLIT",
        ticker=t,
        issuer="SSGA/Select Sector SPDR Trust",
        event_type="SPLIT",
        ex_date=dt.date(2025, 12, 5),
        record_date=dt.date(2025, 12, 2),
        payable_date=dt.date(2025, 12, 4),
        declaration_date=dt.date(2025, 11, 20),
        split_ratio_str="2:1",
        split_new_per_old=Decimal(2),
        source_kind="ISSUER_PRESS_RELEASE+IRS_FORM_8937",
        source_url=pu + " | " + fu,
        source_file=pf + " | " + ff,
        doc_sha256=ph + " | " + fh,
        date_field_provenance=prov,
        notes="2-for-1; no CUSIP change per press release",
    )
rows.sort(key=lambda r: (r["ticker"], r["ex_date"], r["event_type"], r["row_id"]))
ids = [r["row_id"] for r in rows]
assert len(ids) == len(set(ids)), "dup row_id"
tbl = pa.Table.from_pylist(rows, schema=SCHEMA)
# ---- reconciliation vs v1.3 (read-only)
dv = pq.read_table(f"{V13}/dividends.parquet").to_pylist()
spl = pq.read_table(f"{V13}/splits.parquet").to_pylist()
T9 = SPDR + ISH
v13: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
for r in dv:
    if r["symbol"] in T9:
        v13.setdefault((r["symbol"], r["ex_date"]), []).append(r)
iss: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
for r in rows:
    if r["event_type"] in ("CASH_DIST", "CAP_GAIN"):
        iss.setdefault((r["ticker"], r["ex_date"]), []).append(r)
V13_LAST = dt.date(2026, 10, 28)
recon: list[dict[str, Any]] = []
for k in sorted(set(v13) | set(iss)):
    issuer_rows = iss.get(k, [])
    b = v13.get(k, [])
    isum = sum((r["amount_decimal"] for r in issuer_rows), Decimal(0)) if issuer_rows else None
    vsum = sum((Decimal(repr(r["rate"])) for r in b), Decimal(0)) if b else None
    st = []
    if not issuer_rows:
        st.append("V13_ONLY_NO_ISSUER_ROW")
    if not b:
        st.append("ISSUER_ONLY_AFTER_V13_CUTOFF" if k[1] > V13_LAST else "ISSUER_ONLY_MISSING_IN_V13")
    if issuer_rows and b:
        if isum != vsum:
            st.append("AMOUNT_DIFF")
        if len(b) > 1:
            st.append(f"V13_{len(b)}_ROWS_SAME_EX")
        if len(issuer_rows) > 1:
            st.append(f"ISSUER_{len(issuer_rows)}_ROWS_SAME_EX")
        ir = {r["record_date"] for r in issuer_rows}
        ip = {r["payable_date"] for r in issuer_rows}
        vr = {r["record_date"] for r in b}
        vp = {r["payable_date"] for r in b}
        if None in vr:
            st.append("V13_RECORD_NULL")
        elif vr != ir:
            st.append("RECORD_DIFF")
        if None in vp:
            st.append("V13_PAYABLE_NULL")
        elif vp != ip:
            st.append("PAYABLE_DIFF")
    recon.append(
        dict(
            ticker=k[0],
            ex_date=k[1],
            status="MATCH" if not st else "|".join(st),
            issuer_amount_str="|".join(r["amount_str"].strip() for r in issuer_rows) or None,
            issuer_amount_sum=isum,
            v13_rate_str="|".join(repr(r["rate"]) for r in b) or None,
            v13_rate_sum=vsum,
            amount_abs_diff=(abs(cast(Decimal, isum) - cast(Decimal, vsum)) if (issuer_rows and b) else None),
            issuer_record="|".join(sorted({str(r["record_date"]) for r in issuer_rows})) or None,
            v13_record="|".join(sorted({str(r["record_date"]) for r in b})) or None,
            issuer_payable="|".join(sorted({str(r["payable_date"]) for r in issuer_rows})) or None,
            v13_payable="|".join(sorted({str(r["payable_date"]) for r in b})) or None,
            v13_ids="|".join(r["id"] for r in b) or None,
            issuer_row_ids="|".join(r["row_id"] for r in issuer_rows) or None,
        )
    )
RS = pa.schema(
    [
        ("ticker", pa.string()),
        ("ex_date", pa.date32()),
        ("status", pa.string()),
        ("issuer_amount_str", pa.string()),
        ("issuer_amount_sum", D9),
        ("v13_rate_str", pa.string()),
        ("v13_rate_sum", D9),
        ("amount_abs_diff", D9),
        ("issuer_record", pa.string()),
        ("v13_record", pa.string()),
        ("issuer_payable", pa.string()),
        ("v13_payable", pa.string()),
        ("v13_ids", pa.string()),
        ("issuer_row_ids", pa.string()),
    ]
)
rtbl = pa.Table.from_pylist(recon, schema=RS)
# ---- split resolution, all 11 sector SPDRs
press_five = {"XLK", "XLY", "XLE", "XLU", "XLB"}
f8937 = {t: (byfile.get(f"sources/split/form8937_{t}_2025.pdf") is not None) for t in ALL11}
f8937_status = {}
for r in LOG:
    m = re.search(r"select-sector-spdr-etf-2025\.pdf$", r["url"])
    if m:
        for t in ALL11:
            nm = {
                "XLB": "materials",
                "XLC": "communication-services",
                "XLE": "energy",
                "XLF": "financial",
                "XLI": "industrial",
                "XLK": "technology",
                "XLP": "consumer-staples",
                "XLRE": "real-estate",
                "XLU": "utilities",
                "XLV": "health-care",
                "XLY": "consumer-discretionary",
            }[t]
            if f"state-street-{nm}-select-sector" in r["url"]:
                f8937_status[t] = r["status"]
v13s = {r["symbol"]: r for r in spl if r["symbol"] in ALL11 and r["ex_date"] == dt.date(2025, 12, 5)}
srows = []
for t in ALL11:
    iss_split = t in press_five
    split = v13s.get(t)
    vratio = (Decimal(repr(split["new_rate"])) / Decimal(repr(split["old_rate"]))) if split else None
    srows.append(
        dict(
            ticker=t,
            issuer_split_2025_12_05=iss_split,
            issuer_ratio="2:1" if iss_split else None,
            issuer_ex_date=dt.date(2025, 12, 5) if iss_split else None,
            issuer_record_date=dt.date(2025, 12, 2) if iss_split else None,
            issuer_payable_date=dt.date(2025, 12, 4) if iss_split else None,
            press_release_lists=iss_split,
            form8937_2025_http_status=f8937_status.get(t),
            v13_split_present=split is not None,
            v13_type=split["type"] if split else None,
            v13_old_rate=repr(split["old_rate"]) if split else None,
            v13_new_rate=repr(split["new_rate"]) if split else None,
            v13_new_per_old=vratio,
            v13_record=str(split["record_date"]) if split else None,
            v13_payable=str(split["payable_date"]) if split else None,
            status=(
                "MATCH_SPLIT"
                if (iss_split and split is not None and vratio == 2 and split["record_date"] == dt.date(2025, 12, 2))
                else "MATCH_SPLIT_DATE_FIELD_DIFF"
                if (iss_split and split is not None and vratio == 2)
                else "MATCH_NO_SPLIT"
                if (not iss_split and split is None)
                else "MISMATCH"
            ),
        )
    )
SS = pa.schema(
    [
        ("ticker", pa.string()),
        ("issuer_split_2025_12_05", pa.bool_()),
        ("issuer_ratio", pa.string()),
        ("issuer_ex_date", pa.date32()),
        ("issuer_record_date", pa.date32()),
        ("issuer_payable_date", pa.date32()),
        ("press_release_lists", pa.bool_()),
        ("form8937_2025_http_status", pa.int32()),
        ("v13_split_present", pa.bool_()),
        ("v13_type", pa.string()),
        ("v13_old_rate", pa.string()),
        ("v13_new_rate", pa.string()),
        ("v13_new_per_old", D9),
        ("v13_record", pa.string()),
        ("v13_payable", pa.string()),
        ("status", pa.string()),
    ]
)
stbl = pa.Table.from_pylist(srows, schema=SS)
# ---- also v1.3 splits for the 9 tickers 2016+ vs issuer
other = [dict(symbol=r["symbol"], type=r["type"], ex=str(r["ex_date"])) for r in spl if r["symbol"] in T9]
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
args = ap.parse_args()
os.makedirs(args.out, exist_ok=False)


def w(t: pa.Table, name: str) -> None:
    pq.write_table(t, os.path.join(args.out, name + ".parquet"))
    pacsv.write_csv(t, os.path.join(args.out, name + ".csv"))
    rb = pq.read_table(os.path.join(args.out, name + ".parquet"))
    assert rb.schema.equals(t.schema) and rb.equals(t), name
    rc = pacsv.read_csv(
        os.path.join(args.out, name + ".csv"),
        convert_options=pacsv.ConvertOptions(
            column_types=t.schema, strings_can_be_null=True, quoted_strings_can_be_null=False
        ),
    ).select(t.schema.names)
    assert rc.num_rows == t.num_rows, name
    for c in t.schema.names:
        assert rc.column(c).cast(t.schema.field(c).type).equals(t.column(c)), (name, c)


w(tbl, "ledger")
w(rtbl, "reconciliation_vs_v13")
w(stbl, "split_resolution_sector_spdr_11")
from collections import Counter

summ = dict(
    ledger_rows=tbl.num_rows,
    per_ticker=dict(Counter(r["ticker"] for r in rows)),
    per_ticker_type=dict(Counter(f"{r['ticker']}|{r['event_type']}" for r in rows)),
    recon_status=dict(Counter(r["status"] for r in recon)),
    split_status=dict(Counter(r["status"] for r in srows)),
    v13_splits_9=other,
    ex_min={t: str(min(r["ex_date"] for r in rows if r["ticker"] == t)) for t in T9},
    ex_max={t: str(max(r["ex_date"] for r in rows if r["ticker"] == t)) for t in T9},
    declaration_date_nonnull=sum(r["declaration_date"] is not None for r in rows),
)
json.dump(summ, open(os.path.join(args.out, "build_summary.json"), "w"), indent=1, default=str)
print(json.dumps(summ, default=str))
