# fiscal_diag.py - prereg v5 §2 step 4 fiscal-label diagnostic, DEV metadata only
# (earnings_dev.csv + transcript LABELS/status from coverage_transcripts.tsv; no transcript file opened).
from __future__ import annotations

import calendar
import datetime as dt
from typing import Any

import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

OUT = f"{_QR.DESK_DIR}/research/original/sentiment_returns_dev_20261111"
E = pd.read_csv(f"{_QR.DATA_DIR}/av_returns_events_20261111/partitioned/dev/earnings_dev.csv", dtype=str)
C = pd.read_csv(f"{_QR.DATA_DIR}/av_sentiment_20261110/clean/coverage_transcripts.tsv", sep="\t", dtype=str)
E["f"] = pd.to_datetime(E.fiscalDateEnding).dt.date
E["r"] = pd.to_datetime(E.reportedDate).dt.date


def me(y: int, m: int) -> dt.date:
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def annual_end(rows: pd.DataFrame, Y: int, m: int) -> dt.date | None:
    t = me(Y, m)
    c = rows[(rows.f >= t - dt.timedelta(7)) & (rows.f <= t + dt.timedelta(7))]
    return c.f.iloc[0] if len(c) == 1 else None


def match(rows: pd.DataFrame, Y: int, n: int, m: int) -> str:
    a1 = annual_end(rows, Y, m)
    a0 = annual_end(rows, Y - 1, m)
    if a1 is None or a0 is None:
        return "no_annual_end"
    q = rows[(rows.f > a0) & (rows.f <= a1)].sort_values("f")
    if len(q) != 4:
        return f"fy_rows_{len(q)}"
    row = q.iloc[n - 1]
    lag = (row.r - row.f).days
    if not (0 <= lag <= 100):
        return f"lag_{lag}"
    return "OK"


out: list[dict[str, Any]] = []
summ: list[dict[str, Any]] = []
for sym, rows in E.groupby("symbol"):
    rows = rows.reset_index(drop=True)
    maxf = rows.f.max()
    recent = rows[rows.f >= dt.date(2019, 1, 1)]
    resid = sorted(
        set(recent.f.map(lambda d: (d + dt.timedelta(7)).month if d.day < 8 else d.month))
    )  # quarter-end months seen
    labs = C[
        (C.symbol == sym) & C.status.str.startswith("present") & (C.quarter >= "2021Q4") & (C.quarter <= "2025Q3")
    ].quarter.tolist()
    for m in resid:
        res = {"OK": 0}
        offby = []
        den = 0
        notdev = 0
        reasons: dict[str, int] = {}
        for L in labs:
            Y, n = int(L[:4]), int(L[5])
            Eq = me(Y if (m - 3 * (4 - n)) > 0 else Y - 1, (m - 3 * (4 - n) - 1) % 12 + 1)
            if Eq > maxf:
                notdev += 1
                continue
            den += 1
            s0 = match(rows, Y, n, m)
            if s0 == "OK":
                res["OK"] += 1
            else:
                reasons[s0] = reasons.get(s0, 0) + 1
            sm = match(rows, Y - 1, n, m)
            sp = match(rows, Y + 1, n, m)
            if m != 12 and s0 != "OK" and (sm == "OK" or sp == "OK"):
                offby.append(f"{L}(-1:{sm},+1:{sp})")
            out.append(
                dict(
                    symbol=sym,
                    fy_end_month_candidate=m,
                    label=L,
                    quarter_end_endyear=str(Eq),
                    endyear=s0,
                    shift_minus1=sm,
                    shift_plus1=sp,
                )
            )
        rate = res["OK"] / den if den else float("nan")
        summ.append(
            dict(
                symbol=sym,
                fy_end_month_candidate=m,
                n_candidates=len(resid),
                dev_labels=den,
                not_dev_mappable=notdev,
                matched=res["OK"],
                match_rate=round(rate, 4),
                below_90=rate < 0.9,
                offbyone_findings=len(offby),
                offbyone_list=";".join(offby),
                fail_reasons=";".join(f"{k}:{v}" for k, v in reasons.items()),
            )
        )
pd.DataFrame(out).to_csv(f"{OUT}/FISCAL_DIAGNOSTIC_labels.tsv", sep="\t", index=False)
S = pd.DataFrame(summ)
S.to_csv(f"{OUT}/FISCAL_DIAGNOSTIC.tsv", sep="\t", index=False)
cost = E[(E.symbol == "COST") & (E.r < E.f)]
print("COST flagged:", cost[["symbol", "fiscalDateEnding", "reportedDate", "reportTime"]].to_string(index=False))
neg = E[E.r < E.f]
print("all reportedDate<fiscalDateEnding rows:", len(neg))
print(S.groupby("n_candidates").symbol.nunique())
print(
    S[
        ["symbol", "fy_end_month_candidate", "dev_labels", "matched", "match_rate", "offbyone_findings", "fail_reasons"]
    ].to_string(index=False)
)
