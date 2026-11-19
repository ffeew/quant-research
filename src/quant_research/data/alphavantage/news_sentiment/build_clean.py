from __future__ import annotations

import collections

# Builds $QR_DATA_DIR/av_sentiment_20261110/clean per Jeremy's cleaning rules 1-7 (11 Nov 2026).
# Fields READ for decisions: news 'feed', item 'url', item 'time_published'; transcripts 'transcript' (length only).
# Item objects are copied verbatim; sentiment/relevance/text are never read, aggregated or printed.
import json
import os
import shutil
import sys
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

D = f"{_QR.DATA_DIR}/av_sentiment_20261110"
C = D + "/clean"
RP = D + "/raw_repull_20261111"
rows = [l.rstrip("\n").split("\t") for l in open(D + "/CALLS.log", encoding="utf-8")]
rows = [r for r in rows if len(r) >= 12]
okp = {r[11]: r[5] for r in rows if r[9] == "OK"}  # accepted path -> params
allfiles = [r[11] for r in rows if r[11] not in ("-", "")]
MALFORMED = {
    D + "/raw/news/DIS/2025-07.json": RP + "/DIS_news_2025-07.json",
    D + "/raw/transcripts/VZ/2026Q2.json": RP + "/VZ_transcript_2026Q2.json",
}
REPULL_PARAMS = "time_from=20250701T0000&time_to=20250731T2359"
capped = set()
for r in rows:
    if r[9] == "SPLIT_CAP_REACHED:weekly_full":
        sym = r[5].split("tickers=")[1].split(" ")[0]
        w = r[5].split("window=")[1]  # YYYY-MM-DD..DD
        capped.add((sym, w[:7], w))


def win(params: str) -> tuple[str, str]:
    q = dict(x.split("=", 1) for x in params.split("&"))
    return q["time_from"][:8] + "T000000", q["time_to"][:8] + "T235959"


excluded: list[tuple[str, str]] = []  # (path, reason)
news: collections.defaultdict[tuple[str, str], dict[str, str]] = collections.defaultdict(dict)
tr: dict[tuple[str, str], str] = {}
for src_path in allfiles:
    if src_path not in okp:
        excluded.append(
            (
                src_path,
                "retry attempt or Error Message body (not accepted)"
                if ".attempt" in src_path or src_path.endswith(".json")
                else "not accepted",
            )
        )
        continue
    if "/raw/news/" in src_path:
        parts = os.path.basename(src_path)[:-5].split(".")
        news[(src_path.split("/")[-2], parts[0])]["M" if len(parts) == 1 else parts[1]] = src_path
    else:
        tr[(src_path.split("/")[-2], os.path.basename(src_path)[:-5])] = src_path
# pass 1: effective sets, window + dedup asserts
plan: dict[tuple[str, str], list[tuple[str, str]]] = {}
out_win = 0
dup_month = 0
seen_sym: collections.defaultdict[str, dict[Any, Any]] = collections.defaultdict(dict)
for (sym, ym), tags in sorted(news.items()):
    use: list[str] = []
    for h in ("h1", "h2"):
        windows = [tags[h + x] for x in ("w1", "w2") if h + x in tags]
        use += windows if windows else ([tags[h]] if h in tags else [])
    if not use:
        use = [tags["M"]]
    for p in tags.values():
        if p not in use:
            excluded.append((p, "superseded by finer window (rule 1)"))
    src = []
    for p in use:
        if p in MALFORMED:
            excluded.append((p, "malformed 2-byte {} body (rule 5); replaced by raw_repull_20261111 if valid"))
            src.append((MALFORMED[p], REPULL_PARAMS))
        else:
            src.append((p, okp[p]))
    plan[(sym, ym)] = src
    for p, params in src:
        lo, hi = win(params)
        for it in json.load(open(p, "rb"))["feed"]:
            t, u = it.get("time_published"), it.get("url")
            if not (t and lo <= t <= hi):
                out_win += 1
            if u in seen_sym[sym]:
                dup_month += 1
            else:
                seen_sym[sym][u] = t
print("pass1 out_of_window=%d duplicate_urls=%d" % (out_win, dup_month))
if out_win or dup_month:
    print("DESIGNED STOP: nonzero counts; nothing written")
    sys.exit(2)
# pass 2: write
os.makedirs(C)
written = []


def wj(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "x") as f:
        json.dump(obj, f, ensure_ascii=False)
    written.append(path)


cov = open(C + "/coverage_news.tsv", "x")
written.append(C + "/coverage_news.tsv")
cov.write("symbol\tmonth\tfiles_used\titems\tcoverage\tcapped_windows\tsource_files\n")


def _blank_manifest() -> dict[str, Any]:
    return {"months": [], "ok": 0, "capped": 0, "cov0": 0, "items": 0, "tq": [], "tmiss": 0}


man: collections.defaultdict[str, dict[str, Any]] = collections.defaultdict(_blank_manifest)
for (sym, ym), src in sorted(plan.items()):
    items = []
    for p, _ in src:
        items += json.load(open(p, "rb"))["feed"]
    items.sort(key=lambda it: it["time_published"])
    cw = sorted(w for (s, m, w) in capped if s == sym and m == ym)
    flag = "coverage=0" if not items else ("capped_incomplete" if cw else "ok")
    if any(p.startswith(RP) for p, _ in src) and flag == "ok":
        flag = "ok_repulled"
    rel = [os.path.relpath(p, D) for p, _ in src]
    wj(
        "%s/news/%s/%s.json" % (C, sym, ym),
        {"symbol": sym, "month": ym, "coverage": flag, "capped_windows": cw, "source_files": rel, "feed": items},
    )
    cov.write("\t".join([sym, ym, str(len(src)), str(len(items)), flag, ",".join(cw) or "-", ",".join(rel)]) + "\n")
    m = man[sym]
    m["months"].append(ym)
    m["items"] += len(items)
    m["ok" if flag.startswith("ok") else ("capped" if flag == "capped_incomplete" else "cov0")] += 1
cov.close()


def tstatus(sym: str, q: str, n: int) -> str:
    y = int(q[:4])
    if (sym == "META" and q < "2012Q2") or (sym == "ABBV" and y <= 2012) or (sym == "TSLA" and y == 2010):
        return "missing_empty_expected"
    if (sym == "UNH" and q <= "2012Q4") or sym == "WMT" or (sym == "HD" and q == "2026Q2"):
        return "missing_empty_unexplained"
    return "missing_empty"


tc = open(C + "/coverage_transcripts.tsv", "x")
written.append(C + "/coverage_transcripts.tsv")
tc.write("symbol\tquarter\tstatus\tentries\tsource_file\n")
syms = sorted({s for s, _ in tr} | {"LLY", "AMD"})
quarters = ["%dQ%d" % (y, q) for y in range(2010, 2027) for q in range(1, 5) if (y, q) <= (2026, 3)]
for sym in syms:
    for q in quarters:
        tpath = tr.get((sym, q))
        st, n, srcp = None, 0, "-"
        if tpath is None:
            st = "missing_error"
        else:
            if tpath in MALFORMED:
                excluded.append((tpath, "malformed 2-byte {} body (rule 5); replaced by raw_repull_20261111 if valid"))
                tpath = MALFORMED[tpath]
            t = json.load(open(tpath, "rb")).get("transcript")
            n = len(t) if isinstance(t, list) else 0
            if n > 0:
                dst = "%s/transcripts/%s/%s.json" % (C, sym, q)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(tpath, dst)
                written.append(dst)
                st = "present_repulled" if tpath.startswith(RP) else "present"
                srcp = os.path.relpath(tpath, D)
            else:
                st = tstatus(sym, q, n)
                excluded.append((tpath, "valid empty transcript = missing, not zero (rule 3): " + st))
        tc.write("\t".join([sym, q, st, str(n), srcp]) + "\n")
        m = man[sym]
        if st.startswith("present"):
            m["tq"].append(q)
        else:
            m["tmiss"] += 1
tc.close()
mf = open(C + "/MANIFEST.tsv", "x")
written.append(C + "/MANIFEST.tsv")
mf.write(
    "symbol\tnews_first_month\tnews_last_month\tnews_months\tmonths_ok\tmonths_capped_incomplete\tmonths_coverage0\tnews_items\ttr_first_q\ttr_last_q\ttr_present\ttr_missing\n"
)
for sym, m in sorted(man.items()):
    mf.write(
        "\t".join(
            map(
                str,
                [
                    sym,
                    min(m["months"]) if m["months"] else "-",
                    max(m["months"]) if m["months"] else "-",
                    len(m["months"]),
                    m["ok"],
                    m["capped"],
                    m["cov0"],
                    m["items"],
                    min(m["tq"]) if m["tq"] else "-",
                    max(m["tq"]) if m["tq"] else "-",
                    len(m["tq"]),
                    m["tmiss"] if m["tq"] or m["tmiss"] else 0,
                ],
            )
        )
        + "\n"
    )
mf.close()
ex = open(C + "/EXCLUDED.tsv", "x")
written.append(C + "/EXCLUDED.tsv")
ex.write("raw_file\treason\n")
for p, why in sorted(set(excluded)):
    ex.write("%s\t%s\n" % (os.path.relpath(p, D), why))
ex.close()
cn = collections.Counter(l.split("\t")[4] for l in open(C + "/coverage_news.tsv") if not l.startswith("symbol"))
ct = collections.Counter(l.split("\t")[2] for l in open(C + "/coverage_transcripts.tsv") if not l.startswith("symbol"))
er = collections.Counter(w.split(":")[0].split(" (")[0] for _, w in set(excluded))
s = {
    "news_months": dict(cn),
    "news_items": sum(m["items"] for m in man.values()),
    "transcripts": dict(ct),
    "excluded_files": dict(er),
    "excluded_total": len(set(excluded)),
    "out_of_window_dropped": out_win,
    "dup_urls_dropped": dup_month,
    "files_written": len(written),
}
open(C + "/_counts.json", "x").write(json.dumps(s, indent=1))
written.append(C + "/_counts.json")
open("/tmp/clean_written.txt", "w").write("\n".join(written) + "\n")
print(json.dumps(s, indent=1))
