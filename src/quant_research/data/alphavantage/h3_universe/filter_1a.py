#!/usr/bin/env python3
"""H3 Stage 1a filters F1-F4 on Source A (UNIVERSE_RULE_H3_v2 s2). Outputs ELIGIBLE_SCAN_H3.txt, EXCLUSION_1a.tsv, COUNTS_1a.tsv (O_EXCL). Regex matching case-insensitive (F3 header)."""

from __future__ import annotations

import collections
import csv
import re

A = "raw/1a/1a-i_active_20210226.csv"
F2 = {"NYSE", "NASDAQ", "NYSE MKT", "NYSE AMERICAN", "AMEX"}
P1 = re.compile(
    r"\b(warrants?|units?|rights?|preferred|pfd|depositary shares? representing .*preferred|notes? due|debentures?|trust preferred|% (series|cumulative))\b",
    re.I,
)
P2 = re.compile(r"\b(fund|etn|exchange traded|trust units?)\b", re.I)
P2X = re.compile(r"\b(Inc|Corp|Co|Ltd|plc|N\.V\.|Holdings)\b", re.I)
O50 = {
    "AAPL",
    "ABBV",
    "ADBE",
    "AMD",
    "AMZN",
    "AVGO",
    "BA",
    "BAC",
    "C",
    "CAT",
    "CMCSA",
    "COST",
    "CRM",
    "CSCO",
    "CVX",
    "DIS",
    "GE",
    "GOOGL",
    "GS",
    "HD",
    "HON",
    "INTC",
    "JNJ",
    "JPM",
    "KO",
    "LLY",
    "MA",
    "MCD",
    "FB",
    "MRK",
    "MS",
    "MSFT",
    "NFLX",
    "NKE",
    "NVDA",
    "ORCL",
    "PEP",
    "PFE",
    "PG",
    "QCOM",
    "SBUX",
    "T",
    "TSLA",
    "TXN",
    "UNH",
    "V",
    "VZ",
    "WFC",
    "WMT",
    "XOM",
    "GOOG",
}
assert len(O50) == 51


def reason(r: dict[str, str]) -> tuple[str, str]:
    s = r["symbol"].strip()
    n = r["name"]
    if r["assetType"].strip() != "Stock":
        return "not_stock", r["assetType"]
    if r["exchange"].strip() not in F2:
        return "exchange_excluded", r["exchange"]
    m = P1.search(n)
    if m:
        return "non_common", "name:" + m.group(0)
    sp = re.split(r"[-.]", s, maxsplit=1)
    if len(sp) == 2 and not re.fullmatch(r"[A-C]", sp[1]):
        return "non_common", "symbol_suffix:" + sp[1]
    m = P2.search(n)
    if m and not P2X.search(n[m.end() :]):
        return "non_common", "name_fund:" + m.group(0)
    if s in O50:
        return "original_50", s
    return "ok", ""


rows = list(csv.DictReader(open(A, newline="")))
c: collections.Counter[str] = collections.Counter()
elig = []
syms = [r["symbol"].strip() for r in rows]
dup = len(syms) - len(set(syms))
odd = sorted({s for s in syms if not re.fullmatch(r"[A-Z0-9.\-]+", s)})
ex = open("EXCLUSION_1a.tsv", "x")
ex.write("symbol\tname\texchange\tassetType\treason\tdriver\n")
for r in rows:
    rs, d = reason(r)
    c[rs] += 1
    if rs == "ok":
        elig.append(r["symbol"].strip())
    else:
        ex.write(f"{r['symbol'].strip()}\t{r['name']}\t{r['exchange']}\t{r['assetType']}\t{rs}\t{d}\n")
ex.close()
elig = sorted(set(elig))
open("ELIGIBLE_SCAN_H3.txt", "x").write("\n".join(elig) + "\n")
with open("COUNTS_1a.tsv", "x") as f:
    f.write(f"sourceA_rows\t{len(rows)}\nduplicate_symbols\t{dup}\nodd_symbol_chars\t{len(odd)}\n")
    for k, v in sorted(c.items()):
        f.write(f"{k}\t{v}\n")
    f.write(f"N1\t{len(elig)}\n")
print(open("COUNTS_1a.tsv").read())
print("odd:", odd[:30])
