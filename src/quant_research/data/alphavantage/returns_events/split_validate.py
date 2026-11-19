from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json

# Pinned stage-2 script (checks P1-P6 + X2; boundary). No network.
# HOLDOUT values are held in memory only; only counts/shas reach stdout or files other than holdout/*.csv.
# stderr is captured into a buffer and included in the negtest; exceptions print type name only.
import os
import sys
import tempfile
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

D = dt.date
ONE = dt.timedelta(days=1)
DEV_END = D(2024, 12, 31)
HO_START = D(2025, 1, 1)
HO_END = D(2026, 10, 31)
RANGE_START = D(2021, 3, 1)


def easter(y: int) -> dt.date:
    a = y % 19
    b = y // 100
    c = y % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mo = (h + l - 7 * m + 114) // 31
    da = ((h + l - 7 * m + 114) % 31) + 1
    return D(y, mo, da)


def nth(y: int, mo: int, wd: int, n: int) -> dt.date:
    d = D(y, mo, 1)
    d += dt.timedelta(days=(wd - d.weekday()) % 7)
    return d + dt.timedelta(days=7 * (n - 1))


def last(y: int, mo: int, wd: int) -> dt.date:
    d = D(y, mo + 1, 1) - ONE
    return d - dt.timedelta(days=(d.weekday() - wd) % 7)


def obs(d: dt.date) -> dt.date:
    return d - ONE if d.weekday() == 5 else (d + ONE if d.weekday() == 6 else d)


def holidays(y: int) -> set[dt.date]:
    h = {
        nth(y, 1, 0, 3),
        nth(y, 2, 0, 3),
        easter(y) - 2 * ONE,
        last(y, 5, 0),
        obs(D(y, 7, 4)),
        nth(y, 9, 0, 1),
        nth(y, 11, 3, 4),
        obs(D(y, 12, 25)),
    }
    n = D(y, 1, 1)
    if n.weekday() == 6:
        h.add(D(y, 1, 2))
    elif n.weekday() != 5:
        h.add(n)
    if y >= 2022:
        h.add(obs(D(y, 6, 19)))
    if y == 2025:
        h.add(D(2025, 1, 9))
    return h


def sessions(a: dt.date, b: dt.date) -> set[dt.date]:
    H = set().union(*[holidays(y) for y in range(a.year, b.year + 1)])
    out = set()
    d = a
    while d <= b:
        if d.weekday() < 5 and d not in H:
            out.add(d)
        d += ONE
    return out


SES_DEV = sessions(RANGE_START, DEV_END)
SES_HO = sessions(HO_START, HO_END)


def pdate(s: str) -> dt.date | None:
    try:
        return D.fromisoformat(s)
    except Exception:
        return None


def part(d: dt.date) -> str:
    return "pre" if d < RANGE_START else "dev" if d <= DEV_END else "ho" if d <= HO_END else "post"


def epart(d: dt.date) -> str:
    return "dev" if d <= DEV_END else "ho" if d <= HO_END else "post"


def load(p: str, dups: list[str]) -> Any:
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen = set()
        for k, _ in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return dict(pairs)

    return json.loads(open(p, "rb").read(), object_pairs_hook=hook)


def wcsv(p: str, hdr: list[str], rows: list[list[object]]) -> None:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(hdr)
        w.writerows(rows)


def wtxt(p: str, t: str) -> None:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    os.write(fd, t.encode())
    os.close(fd)


def sums(d: str) -> str:
    fs = sorted(f for f in os.listdir(d) if f != "SHA256SUMS")
    t = "".join(f"{hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest()}  {f}\n" for f in fs)
    wtxt(os.path.join(d, "SHA256SUMS"), t)
    return hashlib.sha256(t.encode()).hexdigest()


F = ["1. open", "2. high", "3. low", "4. close", "5. adjusted close", "7. dividend amount", "8. split coefficient"]


def run(base: str, out_base: str, errbuf: Any) -> int:
    OUT = []

    def o(*a: object) -> None:
        OUT.append(" ".join(map(str, a)))

    raw = os.path.join(base, "raw")
    syms = sorted(f[:-5] for f in os.listdir(os.path.join(raw, "daily")) if f.endswith(".json") and ".attempt" not in f)
    stocks = [s for s in syms if s != "SPY"]
    for sub in ("dev", "holdout", "meta"):
        os.mkdir(os.path.join(out_base, sub))
    drows: dict[str, list[list[Any]]] = {"dev": [], "ho": []}
    erows: dict[str, list[list[Any]]] = {"dev": [], "ho": []}
    hoval: set[str] = set()
    hodates: set[str] = set()
    devval: set[str] = set()
    dev_rep: list[str] = []
    ho_rep: list[list[Any]] = []
    cnt = []
    fileerr = []
    maxdev = {}
    minho = None
    for s in syms:
        dups: list[str] = []
        try:
            j = load(os.path.join(raw, "daily", s + ".json"), dups)
            ok_sym = j.get("Meta Data", {}).get("2. Symbol") == s
            ts = j["Time Series (Daily)"]
        except Exception as e:
            fileerr.append(f"daily {s} {type(e).__name__}")
            continue
        if not ok_sym:
            fileerr.append(f"daily {s} symbol_mismatch")
        c = {"pre": 0, "dev": 0, "ho": 0, "post": 0, "baddate": 0}
        chk = {p: {"missing_fields": 0, "nonpos": 0, "bad_split": 0, "dup_dates": 0} for p in ("dev", "ho")}
        devnotes = []
        got: dict[str, set[dt.date]] = {"dev": set(), "ho": set()}
        for k in dups:
            dd = pdate(k)
            if dd and part(dd) in chk:
                chk[part(dd)]["dup_dates"] += 1
            if dd and part(dd) == "dev":
                devnotes.append(f"dup {k}")
        for k, v in ts.items():
            dd = pdate(k)
            if not dd:
                c["baddate"] += 1
                continue
            p = part(dd)
            c[p] += 1
            if p not in ("dev", "ho"):
                continue
            got[p].add(dd)
            if not all(f in v for f in F):
                chk[p]["missing_fields"] += 1
                continue
            try:
                px = [float(v[f]) for f in F[:5]]
                sc = float(v["8. split coefficient"])
                dv = float(v["7. dividend amount"])
                np_ = min(px) <= 0 or dv < 0
                bs = not (0.02 <= sc <= 50)
            except Exception:
                np_ = True
                bs = True
            if np_:
                chk[p]["nonpos"] += 1
            if bs:
                chk[p]["bad_split"] += 1
            row = [s, k, v["4. close"], v["5. adjusted close"], v["7. dividend amount"], v["8. split coefficient"]]
            drows[p].append(row)
            if p == "ho":
                hodates.add(k)
                hoval.update(x for x in row[2:] if len(x) >= 6)
            else:
                devval.update(x for x in row[2:])
                if np_:
                    devnotes.append(f"nonpos {k}")
                if bs or sc != 1.0:
                    devnotes.append(f"split {k} {v['8. split coefficient']}")
        miss = {"dev": len(SES_DEV - got["dev"]), "ho": len(SES_HO - got["ho"])}
        extra = {"dev": len(got["dev"] - SES_DEV), "ho": len(got["ho"] - SES_HO)}
        for d0 in sorted(SES_DEV - got["dev"]):
            devnotes.append(f"missing_session {d0}")
        for d0 in sorted(got["dev"] - SES_DEV):
            devnotes.append(f"extra_date {d0}")
        maxdev[s] = max(got["dev"]).isoformat() if got["dev"] else "NA"
        if got["ho"]:
            m = min(got["ho"])
            minho = m if minho is None or m < minho else minho
        dev_rep.append(
            f"{s}\trows={c['dev']}\tmissing={miss['dev']}\textra={extra['dev']}\t"
            + "\t".join(f"{k}={v}" for k, v in chk["dev"].items())
            + "\t"
            + "; ".join(devnotes)
        )
        ho_rep.append(
            [s, "daily", c["ho"], miss["ho"], extra["ho"]]
            + [chk["ho"][k] for k in ("missing_fields", "nonpos", "bad_split", "dup_dates")]
        )
        cnt.append(
            [s, "daily", len(ts), c["pre"], c["dev"], c["ho"], c["post"], c["baddate"], int(len(ts) == sum(c.values()))]
        )
    for s in stocks:
        dups = []
        try:
            j = load(os.path.join(raw, "earnings", s + ".json"), dups)
            q = j["quarterlyEarnings"]
            if j.get("symbol") != s:
                fileerr.append(f"earnings {s} symbol_mismatch")
        except Exception as e:
            fileerr.append(f"earnings {s} {type(e).__name__}")
            continue
        c = {"dev": 0, "ho": 0, "post": 0, "undated": 0}
        bad = {"dev": 0, "ho": 0}
        seen: dict[tuple[str, str], int] = {}
        for r in q:
            dd = pdate(r.get("reportedDate", ""))
            if not dd:
                c["undated"] += 1
                continue
            p = epart(dd)
            c[p] += 1
            if p == "post":
                continue
            fe = r.get("fiscalDateEnding", "")
            seen[(p, fe)] = seen.get((p, fe), 0) + 1
            if pdate(fe) is None or r.get("reportTime", "") not in ("pre-market", "post-market", ""):
                bad[p] += 1
            erows[p].append([s, fe, r.get("reportedDate", ""), r.get("reportTime", "")])
            if p == "ho":
                hodates.add(r["reportedDate"])
                hodates.add(fe) if pdate(fe) and pdate(fe) > DEV_END else None  # type: ignore[operator]  # second pdate call is a date when truthy
        dupfe = {p: sum(v - 1 for (pp, _), v in seen.items() if pp == p) for p in ("dev", "ho")}
        dev_rep.append(
            f"{s}\tearnings\trows={c['dev']}\tbad={bad['dev']}\tdup_fiscal={dupfe['dev']}\tundated={c['undated']}"
        )
        ho_rep.append([s, "earnings", c["ho"], "", "", bad["ho"], "", "", dupfe["ho"]])
        cnt.append(
            [s, "earnings", len(q), "", c["dev"], c["ho"], c["post"], c["undated"], int(len(q) == sum(c.values()))]
        )
    sec = []
    for s in stocks:
        try:
            j = load(os.path.join(raw, "overview", s + ".json"), [])
            if j.get("Symbol") != s:
                fileerr.append(f"overview {s} symbol_mismatch")
            sec.append([s, j.get("Sector", ""), j.get("Industry", ""), "2026-11-11 snapshot (look-ahead)"])
        except Exception as e:
            fileerr.append(f"overview {s} {type(e).__name__}")
    # routing asserts
    assert all(D.fromisoformat(r[1]) <= DEV_END for r in drows["dev"]) and all(
        HO_START <= D.fromisoformat(r[1]) <= HO_END for r in drows["ho"]
    )
    assert all(D.fromisoformat(r[2]) <= DEV_END for r in erows["dev"]) and all(
        HO_START <= D.fromisoformat(r[2]) <= HO_END for r in erows["ho"]
    )
    hd = ["symbol", "date", "close", "adjusted_close", "dividend", "split_coefficient"]
    he = ["symbol", "fiscalDateEnding", "reportedDate", "reportTime"]
    wcsv(os.path.join(out_base, "dev", "daily_dev.csv"), hd, drows["dev"])
    wcsv(os.path.join(out_base, "dev", "earnings_dev.csv"), he, erows["dev"])
    wcsv(os.path.join(out_base, "holdout", "daily_holdout.csv"), hd, drows["ho"])
    wcsv(os.path.join(out_base, "holdout", "earnings_holdout.csv"), he, erows["ho"])
    wcsv(os.path.join(out_base, "meta", "sectors.csv"), ["symbol", "Sector", "Industry", "note"], sec)
    sd = sums(os.path.join(out_base, "dev"))
    sh = sums(os.path.join(out_base, "holdout"))
    sm = sums(os.path.join(out_base, "meta"))
    ho_txt = io.StringIO()
    w = csv.writer(ho_txt, delimiter="\t", lineterminator="\n")
    w.writerow(
        [
            "symbol",
            "kind",
            "rows",
            "missing_sessions",
            "extra_dates",
            "missing_fields_or_bad",
            "nonpos",
            "bad_split",
            "dup",
        ]
    )
    w.writerows(ho_rep)
    cn_txt = io.StringIO()
    w = csv.writer(cn_txt, delimiter="\t", lineterminator="\n")
    w.writerow(
        ["symbol", "kind", "raw_rows", "pre_range", "dev", "holdout", "post_range", "bad_or_undated", "identity_ok"]
    )
    w.writerows(cnt)
    gmin = minho.isoformat() if minho else "NA"
    o("files_symbols", len(syms), "stocks", len(stocks), "file_errors", len(fileerr), ";".join(fileerr))
    o("dev_daily_rows", len(drows["dev"]), "dev_earnings_rows", len(erows["dev"]), "dev_SUMS", sd)
    o("holdout_daily_rows", len(drows["ho"]), "holdout_earnings_rows", len(erows["ho"]), "holdout_SUMS", sh)
    o("meta_sectors_rows", len(sec), "meta_SUMS", sm)
    o(
        "max_DEV_date_global",
        max(v for v in maxdev.values() if v != "NA"),
        "symbols_maxdev_2024-12-31",
        sum(v == "2024-12-31" for v in maxdev.values()),
        "min_HOLDOUT_date",
        gmin,
    )
    for k, i in (("missing_sessions", 3), ("extra_dates", 4), ("nonpos", 6), ("bad_split", 7)):
        o("holdout_daily_fail", k, sum(r[i] for r in ho_rep if r[1] == "daily"))
    o(
        "holdout_daily_fail missing_fields",
        sum(r[5] for r in ho_rep if r[1] == "daily"),
        "dup_dates",
        sum(r[8] for r in ho_rep if r[1] == "daily"),
    )
    o(
        "holdout_earnings_fail bad",
        sum(r[5] for r in ho_rep if r[1] == "earnings"),
        "dup_fiscal",
        sum(r[8] for r in ho_rep if r[1] == "earnings"),
    )
    texts = {
        "stdout": "\n".join(OUT),
        "VALIDATION_HOLDOUT.tsv": ho_txt.getvalue(),
        "COUNTS.tsv": cn_txt.getvalue(),
        "VALIDATION_DEV.tsv": "\n".join(dev_rep) + "\n",
        "stderr": errbuf.getvalue(),
    }
    hval = hoval - devval
    hdates = hodates - {gmin}

    def leaks(t: str, vals: bool = True) -> int:
        toks = set(t.replace("\t", " ").replace(";", " ").replace(",", " ").replace("=", " ").split())
        return len(toks & hdates) + (len(toks & hval) if vals else 0)

    tok = next(iter(hdates or hval), None)
    control = (tok is None) or leaks("x " + tok + " y") > 0
    nl = {k: leaks(v, vals=(k != "VALIDATION_DEV.tsv")) for k, v in texts.items()}
    ok = control and all(v == 0 for v in nl.values())
    o(
        "NEGTEST",
        "PASS" if ok else "FAIL",
        "control_detects_planted_token",
        control,
        "leak_counts",
        json.dumps(nl, sort_keys=True),
    )
    if not ok:
        print("NEGTEST FAIL; reports not written")
        return 6
    for k in ("VALIDATION_HOLDOUT.tsv", "COUNTS.tsv", "VALIDATION_DEV.tsv"):
        wtxt(os.path.join(out_base, k), texts[k])
    wtxt(os.path.join(out_base, "RUN.log"), "\n".join(OUT) + "\n")
    wtxt(os.path.join(out_base, "RUN.stderr"), texts["stderr"])
    print("\n".join(OUT))
    return 0


def guarded(base: str, out: str, errbuf: Any) -> int:
    old = sys.stderr
    sys.stderr = errbuf
    try:
        return run(base, out, errbuf)
    except Exception as e:
        sys.__stdout__.write(f"ERROR {type(e).__name__} (message suppressed)\n")  # type: ignore[union-attr]  # __stdout__ is set while the process runs
        return 7
    finally:
        sys.stderr = old


def selftest() -> None:
    import random

    random.seed(1)
    t = tempfile.mkdtemp()
    raw = os.path.join(t, "raw")
    for sub in ("daily", "earnings", "overview"):
        os.makedirs(os.path.join(raw, sub))
    allses = sorted(sessions(D(2021, 1, 4), D(2026, 11, 10)))
    for s in ("AAA", "SPY"):
        ts = {}
        for i, d in enumerate(allses):
            if s == "AAA" and d == D(2025, 3, 3):
                continue
            v = f"{100 + i * 0.0137:.4f}"
            ts[d.isoformat()] = {
                "1. open": v,
                "2. high": v,
                "3. low": v,
                "4. close": v,
                "5. adjusted close": v,
                "6. volume": "100",
                "7. dividend amount": "0.0000",
                "8. split coefficient": "2.0" if d == D(2023, 6, 1) else "1.0",
            }
        if s == "AAA":
            ts["2022-05-02"]["4. close"] = "-1.0000"
        json.dump(
            {"Meta Data": {"2. Symbol": s}, "Time Series (Daily)": ts},
            open(os.path.join(raw, "daily", s + ".json"), "w"),
        )
    json.dump(
        {
            "symbol": "AAA",
            "quarterlyEarnings": [
                {"fiscalDateEnding": "2025-03-31", "reportedDate": "2025-04-24", "reportTime": "post-market"},
                {"fiscalDateEnding": "2024-09-30", "reportedDate": "2024-10-24", "reportTime": "pre-market"},
            ],
        },
        open(os.path.join(raw, "earnings", "AAA.json"), "w"),
    )
    json.dump({"Symbol": "AAA", "Sector": "X", "Industry": "Y"}, open(os.path.join(raw, "overview", "AAA.json"), "w"))
    o = os.path.join(t, "out")
    os.mkdir(o)
    rc = guarded(t, o, io.StringIO())
    hr = list(csv.reader(open(os.path.join(o, "holdout", "daily_holdout.csv"))))
    assert rc == 0 and min(r[1] for r in hr[1:]) == "2025-01-02"
    o2 = os.path.join(t, "out_leaktest")
    os.mkdir(o2)
    eb = io.StringIO()
    eb.write("planted 2025-06-02\n")
    rc2 = guarded(t, o2, eb)
    assert rc2 == 6 and not os.path.exists(os.path.join(o2, "RUN.log"))
    print("SELFTEST stderr_leak_control rc", rc2, "(expected 6)")
    print("SELFTEST", "PASS" if rc == 0 and rc2 == 6 else "FAIL", t)


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    elif sys.argv[1:] == ["--run"]:
        B = f"{_QR.DATA_DIR}/av_returns_events_20261111"
        O = B + "/partitioned"
        os.mkdir(O)
        sys.exit(guarded(B, O, io.StringIO()))
    else:
        print("usage: --selftest | --run")
        sys.exit(2)
