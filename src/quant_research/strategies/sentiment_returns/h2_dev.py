# h2_dev.py - H2 (earnings-call tone surprise -> post-event drift +2..+21), EXPLORATORY, DEV ONLY, per sealed prereg v5
# Decisions: erratum (S3/S4 due-quarter rule), S6b readback (H2 may proceed on DEV only).
# Inputs: DEV partition only, clean transcripts (checksummed) opened only for due labels mapped to
# day 0 <= 2024-11-29 (scored window end) - never any other transcript; S6b labels (checksummed).
# Helper logic (XNYS sessions, adjusted_close ratios, 252-return beta ending t-1, NW t, Student-t p) is COPIED from
# dev_run.py - not imported, because dev_run.py executes at import and writes into its own folder.
# Fiscal mapping (fy_state) COPIED from fiscal_diag_s6b.py and cross-checked against the S6b labels tsv.
# No holdout, no raw/, no news, no network, no env vars.
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import platform
import sys
from typing import Any, cast

import exchange_calendars as xc
import numpy as np
import pandas as pd
from scipy import stats

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

NOTE = "50 DEV calls excluded as not-yet-due (erratum 7584b5b5, S6b readback b4652cef)"
HDR = "EXPLORATORY: cannot PASS; DEV only; for review"
OUT = f"{_QR.DESK_DIR}/research/original/sentiment_returns_h2_dev_20261111"
RET = f"{_QR.DATA_DIR}/av_returns_events_20261111/partitioned/dev"
CLEAN = f"{_QR.DATA_DIR}/av_sentiment_20261110/clean"
S6B = f"{_QR.DESK_DIR}/research/original/sentiment_returns_fiscal_diag_s6b_20261111"
PA = f"{_QR.DATA_DIR}/av_annual_fye_dev_20261111/annual_fye_dev.csv"
A6 = f"{_QR.DESK_DIR}/research/original/sentiment_returns_prereg_20261111/MISSING_TRANSCRIPTS_A6.tsv"
LOG = open(f"{OUT}/h2_dev.log", "x")


def log(*a: object) -> None:
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


log(HDR)
log(NOTE)
log(
    "interpreter",
    sys.executable,
    "flags isolated",
    sys.flags.isolated,
    "dont_write_bytecode",
    sys.flags.dont_write_bytecode,
)
log(
    "python",
    platform.python_version(),
    "pandas",
    pd.__version__,
    "numpy",
    np.__version__,
    "scipy",
    __import__("scipy").__version__,
    "exchange_calendars",
    xc.__version__,
)
assert xc.__version__ == "4.13.2"


def sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


PIN = {
    f"{RET}/daily_dev.csv": None,
    f"{RET}/earnings_dev.csv": desk_pin("strategies.sentiment_returns.h2_dev", "PIN[1]"),
    PA: desk_pin("strategies.sentiment_returns.h2_dev", "PIN[2]"),
    f"{S6B}/FYE_MONTH_FROZEN.tsv": desk_pin("strategies.sentiment_returns.h2_dev", "PIN[3]"),
    f"{RET}/SHA256SUMS": desk_pin("strategies.sentiment_returns.h2_dev", "PIN[4]"),
    f"{S6B}/SHA256SUMS": desk_pin("strategies.sentiment_returns.h2_dev", "PIN[5]"),
    f"{CLEAN}/SHA256SUMS": desk_pin("strategies.sentiment_returns.h2_dev", "PIN[6]"),
    f"{_QR.DESK_DIR}/research/original/sentiment_returns_prereg_20261111/PREREG_DRAFT_v5.md": desk_pin(
        "strategies.sentiment_returns.h2_dev", "PIN[7]"
    ),
    A6: desk_pin("strategies.sentiment_returns.h2_dev", "PIN[8]"),
    f"{_QR.DESK_DIR}/research/original/sentiment_returns_dev_20261111/dev_run.py": desk_pin(
        "strategies.sentiment_returns.h2_dev", "PIN[9]"
    ),
}


def sums(p: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in open(p):
        h, q = line.strip().split(None, 1)
        found[q.lstrip("*").lstrip("./")] = h
    return found


devsums = sums(f"{RET}/SHA256SUMS")
s6bsums = sums(f"{S6B}/SHA256SUMS")
csums = sums(f"{CLEAN}/SHA256SUMS")
PIN[f"{RET}/daily_dev.csv"] = devsums["daily_dev.csv"]
assert devsums["earnings_dev.csv"] == PIN[f"{RET}/earnings_dev.csv"]
for f in ("FISCAL_DIAGNOSTIC_S6B_labels.tsv", "NOT_YET_DUE.tsv"):
    PIN[f"{S6B}/{f}"] = s6bsums[f]
PIN[f"{CLEAN}/coverage_transcripts.tsv"] = csums["coverage_transcripts.tsv"]
for p, h in PIN.items():
    d = sha(p)
    log("input", p, d)
    if d != h:
        log("SHA MISMATCH", p)
        sys.exit(2)

# ---------------- returns / beta (copied from dev_run.py) ----------------
daily = pd.read_csv(f"{RET}/daily_dev.csv")
E = pd.read_csv(f"{RET}/earnings_dev.csv", dtype=str)
assert (
    len(daily) == 49317
    and len(E) == 5279
    and daily["date"].max() <= "2024-12-31"
    and E.reportedDate.max() <= "2024-12-31"
)
cal = xc.get_calendar("XNYS")
sess = [d.strftime("%Y-%m-%d") for d in cal.sessions_in_range("2021-03-01", "2024-12-31")]
assert sorted(daily["date"].unique()) == sess
px = daily.pivot(index="date", columns="symbol", values="adjusted_close").loc[sess]
assert px.notna().all().all()
r = px / px.shift(1) - 1.0
STOCKS = sorted(c for c in px.columns if c != "SPY")
assert len(STOCKS) == 50
rm = r["SPY"]
covm = r[STOCKS].rolling(252, min_periods=252).cov(rm)
var = rm.rolling(252, min_periods=252).var()
beta = covm.div(var, axis=0).shift(1)  # value at t uses returns through t-1
sidx = {d: i for i, d in enumerate(sess)}


def nw_t(x: Any, L: int) -> float:
    x = np.asarray(x, float)
    T = len(x)
    m = x.mean()
    u = x - m
    lrv = (u @ u) / T
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        lrv += 2 * w * (u[l:] @ u[:-l]) / T
    return cast(float, m / np.sqrt(lrv / T))


# ---------------- fiscal mapping (copied from fiscal_diag_s6b.py, EDGE 2024-12-31) ----------------
EDGE = dt.date(2024, 12, 31)
LAG = 100
A = pd.read_csv(PA, dtype=str)
A["f"] = pd.to_datetime(A.fiscalDateEnding).dt.date
E["f"] = pd.to_datetime(E.fiscalDateEnding).dt.date
E["r"] = pd.to_datetime(E.reportedDate).dt.date
F = pd.read_csv(f"{S6B}/FYE_MONTH_FROZEN.tsv", sep="\t", dtype=str)
M = {x.symbol: int(cast(str, x.fye_month)) for x in F.itertuples() if x.status == "FROZEN"}
assert len(M) == 50


def me(y: int, m: int) -> dt.date:
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def qend(Y: int, m: int, n: int) -> dt.date:
    k = m - 3 * (4 - n)
    return me(Y if k > 0 else Y - 1, (k - 1) % 12 + 1)


def due(Y: int, m: int, n: int) -> bool:
    return qend(Y, m, n) + dt.timedelta(LAG) <= EDGE


def ann_end(s: str, Y: int) -> tuple[dt.date | None, int]:
    c = A[(A.symbol == s) & (A.f.map(lambda d: d.year) == Y)]
    return (c.f.iloc[0] if len(c) == 1 else None), len(c)


def fy_state(s: str, Y: int) -> dict[str, Any]:
    m = M[s]
    a1, n1 = ann_end(s, Y)
    a0, n0 = ann_end(s, Y - 1)
    rows = E[E.symbol == s]
    dq = [n for n in range(1, 5) if due(Y, m, n)]
    k = len(dq)
    d: dict[str, Any] = dict(Y=Y, k=k, due_q=dq)
    if n1 > 1 or n0 > 1:
        d.update(ok=False, why="label_nonunique", qmap=None)
        return d
    if a0 is None:
        d.update(ok=False, why="no_annual_end_Ym1", qmap=None)
        return d
    if k == 4:
        if a1 is None or a1 > EDGE:
            d.update(ok=False, why="closed_no_annual_row", qmap=None)
            return d
        q = rows[(rows.f > a0) & (rows.f <= a1)].sort_values("f")
        ok = len(q) == 4
        why = "" if ok else f"closed_rows_{len(q)}"
        if ok and abs((q.f.iloc[-1] - a1).days) > 7:
            ok = False
            why = "q4_not_within_7d_of_annual"
        if ok and q.f.nunique() != 4:
            ok = False
            why = "closed_rows_not_unique"
        d.update(
            ok=ok, why=why, qmap={n: (q.iloc[n - 1] if n <= len(q) else None) for n in range(1, 5)} if ok else None
        )
        return d
    upper = a1 if a1 is not None else me(Y, m) + dt.timedelta(7)
    b = [a0] + [qend(Y, m, n) + dt.timedelta(7) for n in (1, 2, 3)] + [upper]
    q = rows[(rows.f > a0) & (rows.f <= upper)].sort_values("f")
    qmap: dict[int, Any] = {}
    problems: list[str] = []
    for n in range(1, 5):
        qn = q[(q.f > b[n - 1]) & (q.f <= b[n])]
        if len(qn) > 1:
            problems.append(f"Q{n}_nonunique")
            qmap[n] = None
            continue
        row = qn.iloc[0] if len(qn) == 1 else None
        qmap[n] = row
        if n in dq:
            if row is None:
                problems.append(f"Q{n}_due_no_row")
            elif not (0 <= (row.r - row.f).days <= LAG):
                problems.append(f"Q{n}_due_lag")
    d.update(ok=not problems, why=";".join(problems), qmap=qmap)
    return d


LB = pd.read_csv(f"{S6B}/FISCAL_DIAGNOSTIC_S6B_labels.tsv", sep="\t", dtype=str)
NYD = pd.read_csv(f"{S6B}/NOT_YET_DUE.tsv", sep="\t", dtype=str)
assert len(LB) == 587 and (LB.endyear == "OK").all() and len(NYD) == 213
n_nyd_present = int((NYD.row_present == "y").sum())
assert n_nyd_present == 50
nyd_keys = set(zip(NYD.symbol, NYD.label))
assert not (nyd_keys & set(zip(LB.symbol, LB.label)))
C = pd.read_csv(f"{CLEAN}/coverage_transcripts.tsv", sep="\t", dtype=str)
cstat = {(x.symbol, x.quarter): x.status for x in C.itertuples()}


def day0_of(rd: str, rt: str) -> str:
    d = pd.Timestamp(rd)
    if rt == "pre-market":
        s0 = cal.date_to_session(d, "next")
    else:
        s0 = cal.date_to_session(
            d + pd.Timedelta(days=1), "next"
        )  # post-market, or missing/unknown -> post-market (§2)
    return cast(str, s0.strftime("%Y-%m-%d"))


def tq(d: str) -> str:
    return f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"


ev = []
cnt = dict(
    due_labels=len(LB),
    not_yet_due_rows_total=len(NYD),
    not_yet_due_present_excluded=n_nyd_present,
    missing_transcript_due=0,
    reporttime_defaulted=0,
    mapping_crosscheck_fail=0,
    opened=0,
    opened_sha_ok=0,
)
for x in LB.itertuples():
    s, L = cast(str, x.symbol), cast(str, x.label)
    Y, n = int(L[:4]), int(L[5])
    m = M[s]
    assert int(cast(str, x.m)) == m and due(Y, m, n)
    st = fy_state(s, Y)
    row = st["qmap"].get(n) if st["ok"] else None
    if row is None or not (0 <= (row.r - row.f).days <= LAG) or str(qend(Y, m, n)) != cast(str, x.nominal_quarter_end):
        cnt["mapping_crosscheck_fail"] += 1
        log("MAPPING CROSSCHECK FAIL", s, L)
        sys.exit(3)
    rt = row.reportTime if row.reportTime in ("pre-market", "post-market") else "unknown"
    if rt == "unknown":
        cnt["reporttime_defaulted"] += 1
    d0 = day0_of(str(row.r), rt)
    status = cstat.get((s, L), "absent_from_index")
    ev.append(
        dict(
            symbol=s,
            label=L,
            fiscalDateEnding=str(row.f),
            reportedDate=str(row.r),
            reportTime=rt,
            day0=d0,
            transcript_status=status,
        )
    )
EV = pd.DataFrame(ev)
SC_LO, SC_HI = "2022-03-01", "2024-11-29"


def win(d0: str) -> tuple[str, str]:
    if d0 not in sidx:
        return "", ""
    i = sidx[d0]
    if i + 21 >= len(sess):
        return (cast(str, sess[i + 2]) if i + 2 < len(sess) else "post-2024"), "post-2024-12-31"
    return cast(str, sess[i + 2]), cast(str, sess[i + 21])


EV["ret_start"], EV["ret_end"] = zip(*[win(d) for d in EV.day0])
EV.loc[EV.day0 < sess[0], ["ret_start", "ret_end"]] = ""
# ---------------- tone: open ONLY transcripts of due labels with day 0 <= 2024-11-29 (scored window end) ----------------
tone = {}
ntone_entries = {}
for x in EV.itertuples():
    transcript_status = cast(str, x.transcript_status)
    day0 = cast(str, x.day0)
    if not transcript_status.startswith("present"):
        cnt["missing_transcript_due"] += 1
        continue
    if day0 > SC_HI:
        continue  # purged (B3/B8) or later: not opened
    assert day0 <= "2024-12-31"
    rel = f"transcripts/{x.symbol}/{x.label}.json"
    b = open(f"{CLEAN}/{rel}", "rb").read()
    cnt["opened"] += 1
    if hashlib.sha256(b).hexdigest() != csums[rel]:
        log("SHA MISMATCH", rel)
        sys.exit(4)
    cnt["opened_sha_ok"] += 1
    doc: Any = json.loads(b)
    assert doc.get("symbol") == x.symbol and doc.get("quarter") == x.label
    v: list[float] = []
    for e in doc.get("transcript") or []:
        try:
            sent = float(e.get("sentiment"))
            if np.isfinite(sent):
                v.append(sent)
        except Exception:
            pass
    ntone_entries[(x.symbol, x.label)] = len(v)
    tone[(x.symbol, x.label)] = float(np.mean(v)) if len(v) >= 10 else np.nan
EV["n_parseable"] = [ntone_entries.get(k, "") for k in zip(EV.symbol, EV.label)]
EV["tone"] = [tone.get(k, np.nan) for k in zip(EV.symbol, EV.label)]
# surprise: tone - mean of previous 4 available calls (ordered by day 0; available = due-mapped, present, tone non-missing), >= 2
EV = EV.sort_values(["symbol", "day0", "label"]).reset_index(drop=True)
sur: list[float] = []
nprior: list[int] = []
for _i, evrow in EV.iterrows():
    pr = EV[(EV.symbol == evrow.symbol) & (EV.day0 < evrow.day0) & EV.tone.notna()].tail(4)
    nprior.append(len(pr))
    sur.append(evrow.tone - pr.tone.mean() if (len(pr) >= 2 and np.isfinite(evrow.tone)) else np.nan)
EV["n_prior"] = nprior
EV["surprise"] = sur
# ---------------- status per event ----------------
why: list[str] = []
for x in EV.itertuples():
    transcript_status = cast(str, x.transcript_status)
    day0 = cast(str, x.day0)
    if not transcript_status.startswith("present"):
        why.append("excl_missing_transcript")
    elif day0 < SC_LO:
        why.append("baseline_only_day0_before_2022-03-01")
    elif day0 > SC_HI:
        why.append("excl_straddle_B3B8_window_ends_after_2024-12-31")
    elif not np.isfinite(cast(float, x.tone)):
        why.append("excl_tone_below_10_parseable")
    elif not np.isfinite(cast(float, x.surprise)):
        why.append("excl_lt2_prior_calls")
    else:
        why.append("candidate")
EV["status"] = why
ys: list[float] = []
yr: list[float] = []
for x in EV.itertuples():
    if x.status != "candidate":
        ys.append(np.nan)
        yr.append(np.nan)
        continue
    symbol = cast(str, x.symbol)
    i0 = sidx[cast(str, x.day0)]
    g = (1 + r.iloc[i0 + 2 : i0 + 22]).prod() - 1
    bb = beta.iloc[i0][symbol]
    assert sess[i0 + 21] <= "2024-12-31" and len(r.iloc[i0 + 2 : i0 + 22]) == 20
    if not (np.isfinite(bb) and np.isfinite(g[symbol])):
        ys.append(np.nan)
        yr.append(np.nan)
        continue
    ys.append(g[symbol] - bb * g["SPY"])
    yr.append(g[symbol])
EV["target_betaadj"] = ys
EV["ret_raw"] = yr
EV.loc[(EV.status == "candidate") & EV.target_betaadj.isna(), "status"] = "excl_missing_target"
EV["quarter_day0"] = EV.day0.map(tq)
qn = EV[EV.status == "candidate"].groupby("quarter_day0").size()
small = set(qn[qn < 20].index)
EV.loc[(EV.status == "candidate") & EV.quarter_day0.isin(small), "status"] = "excl_quarter_lt20_events"
EV.loc[EV.status == "candidate", "status"] = "included"


# ---------------- per-quarter stats ----------------
def stats_for(D: pd.DataFrame, tag: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for q, g in D[D.status == "included"].groupby("quarter_day0"):
        n = len(g)
        k = n // 5
        o = g.sort_values(["surprise", "symbol", "label"]).reset_index(drop=True)
        sh, lo = o.iloc[:k], o.iloc[-k:]
        rows.append(
            dict(
                quarter=q,
                n=n,
                k=k,
                n_symbols=g.symbol.nunique(),
                ic=stats.spearmanr(g.surprise, g.target_betaadj).statistic,
                ls_raw=lo.ret_raw.mean() - sh.ret_raw.mean(),
                ls_badj=lo.target_betaadj.mean() - sh.target_betaadj.mean(),
            )
        )
    R = pd.DataFrame(rows)
    T = len(R)
    mic = R.ic.mean()
    t = nw_t(R.ic, 1)
    p_ = 1 - stats.t.cdf(t, df=T - 1)
    TO = 4.0  # flat book each quarter: enter 2 (gross) and exit 2
    res = dict(
        spec=tag,
        periods=T,
        df=T - 1,
        mean_ic=mic,
        ic_sd=R.ic.std(ddof=1),
        nw_lag=1,
        nw_t=t,
        p_one_sided=p_,
        ls_gross_raw_mean=R.ls_raw.mean(),
        ls_net10_raw_mean=(R.ls_raw - 0.0010 * TO).mean(),
        ls_net20_raw_mean=(R.ls_raw - 0.0020 * TO).mean(),
        ls_gross_betaadj_mean=R.ls_badj.mean(),
        ls_net10_betaadj_mean=(R.ls_badj - 0.0010 * TO).mean(),
        turnover_per_quarter=TO,
        events_scored=int(R.n.sum()),
        mean_n=R.n.mean(),
        min_n=int(R.n.min()),
        mean_k=R.k.mean(),
        first_quarter=R.quarter.iloc[0],
        last_quarter=R.quarter.iloc[-1],
        verdict="EXPLORATORY - cannot PASS",
    )
    return R, res


R, res = stats_for(EV, "H2_main")
# R-RT: excluding reportTime missing/unknown (count may be 0)
EVrt = EV.copy()
EVrt.loc[EVrt.reportTime == "unknown", "status"] = "excl_RRT"
Rrt, resrt = stats_for(EVrt, "H2_R-RT")
# ---------------- counts ----------------
st_counts = EV.status.value_counts().to_dict()
dropped_q = {q: int(qn[q]) for q in sorted(small)}
a6 = pd.read_csv(A6, sep="\t", dtype=str)
a6w = {
    "in_window_2021Q4_2025Q3": int((a6.in_H2_window_2021Q4_2025Q3 == "yes").sum()),
    "total": len(a6),
    "by_category": a6.category.value_counts().to_dict(),
}
labwin = C[(C.symbol.isin(STOCKS)) & (C.quarter >= "2021Q4") & (C.quarter <= "2025Q3")]
miss_win_index = int((~labwin.status.str.startswith("present")).sum())
dev_used_missing = cnt["missing_transcript_due"]
counts = dict(
    cnt,
    status_counts=st_counts,
    quarters_dropped_lt20=dropped_q,
    missing_transcripts=dict(
        DEV_due_labels_used=dev_used_missing, H2_label_window_2021Q4_2025Q3_coverage_index=miss_win_index, A6_table=a6w
    ),
    straddle_B3B8=int((EV.status == "excl_straddle_B3B8_window_ends_after_2024-12-31").sum()),
    reporttime_counts=EV.reportTime.value_counts().to_dict(),
    events_with_same_symbol_twice_in_quarter=int(
        EV[EV.status == "included"].groupby(["quarter_day0", "symbol"]).size().gt(1).sum()
    ),
)
for k_, v_ in counts.items():
    log("count", k_, json.dumps(v_, default=str))
OUTRES = dict(
    header=HDR,
    note=NOTE,
    exploratory="exploratory - not a confirmatory test; never PASS; not in Holm family (A5)",
    proxy="event date = AV EARNINGS reportedDate+reportTime PROXY, not a verified call timestamp",
    caveats=["survivorship-biased universe: any positive result is an upper bound", "not verified point-in-time"],
    readings={"UTC": res, "ET": dict(res)},
    readings_note="H2 uses no news timestamps; UTC and ET readings are identical by construction; A4 materiality: no difference (delta IC = 0)",
    R_RT=resrt,
    counts=counts,
)
json.dump(OUTRES, open(f"{OUT}/H2_DEV_STATS.json", "x"), indent=1, default=float)
for rd in ("UTC", "ET"):
    log("H2 DEV", rd, json.dumps(res, default=float))
log("H2 R-RT", json.dumps(resrt, default=float))
with open(f"{OUT}/H2_DEV_periods.tsv", "x") as fh:
    fh.write(
        f"# {HDR}. {NOTE}. exploratory - not a confirmatory test. Identical under UTC and ET readings (no news timestamps in H2).\n"
    )
    R.to_csv(fh, sep="\t", index=False)
cols = [
    "symbol",
    "label",
    "fiscalDateEnding",
    "reportedDate",
    "reportTime",
    "day0",
    "quarter_day0",
    "ret_start",
    "ret_end",
    "transcript_status",
    "n_parseable",
    "tone",
    "n_prior",
    "surprise",
    "ret_raw",
    "target_betaadj",
    "status",
]
with open(f"{OUT}/H2_DEV_events.tsv", "x") as fh:
    fh.write(
        f"# {HDR}. {NOTE}. No transcript text. ret window = sessions +2..+21 (close(+1)->close(+21)). "
        f"Purged/straddle events: transcript not opened, tone blank.\n"
    )
    EV[cols].to_csv(fh, sep="\t", index=False)
log("done")
