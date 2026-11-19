"""derive.py - IV-gap v2 DEV readout derivations. Reads ONLY the sealed run-dir CSVs
(no reader, AV or chain calls). Applies prereg r3 s7 rules verbatim:
reported cell iff n>=20; usable iff drop_rate<=0.10 in a non-killed symbol-year;
kill iff symbol-year drop_rate over all kept legs > 0.10. No new thresholds."""

from __future__ import annotations

import csv
import hashlib
import os
import statistics
import sys
from collections.abc import Callable
from typing import Any

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

RUN = f"{_QR.DESK_DIR}/research/original/iv_gap_v2_run_r2_20261113"
OUT = sys.argv[1]
EXP = {"SHA256SUMS": desk_pin("strategies.iv_gap.derive", "EXP.SHA256SUMS")}


def sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


assert sha(os.path.join(RUN, "SHA256SUMS")) == EXP["SHA256SUMS"], "STOP sha"
for line in open(os.path.join(RUN, "SHA256SUMS")):
    h, f = line.split()
    assert sha(os.path.join(RUN, f.lstrip("*"))) == h, "STOP sha " + f
rd: Callable[[str], list[dict[str, str]]] = lambda f: list(csv.DictReader(open(os.path.join(RUN, f), newline="")))
cov, gs, par, san = rd("coverage.csv"), rd("gap_stats.csv"), rd("parity_violations.csv"), rd("sanity_bidask.csv")
DROP_MAX = 0.10
NMIN = 20
key: Callable[[dict[str, str]], tuple[str, int]] = lambda r: (r["symbol"], int(r["year"]))
# symbol-year kill + effective sample
sy: dict[tuple[str, int], dict[str, Any]] = {}
for r in cov:
    kept = int(r["contracts_kept"])
    fr = float(r["flag_rate"])
    dr = float(r["drop_rate"])
    sy[key(r)] = dict(
        symbol=r["symbol"],
        year=int(r["year"]),
        sampled_days=int(r["sampled_days"]),
        no_date=int(r["no_date"]),
        no_underlying=int(r["no_underlying"]),
        contracts_seen=int(r["contracts_seen"]),
        contracts_kept=kept,
        coverage_kept_over_seen=r["coverage_kept_over_seen"],
        flagged_derived=round(fr * kept),
        dropped_derived=round(dr * kept),
        flag_rate=r["flag_rate"],
        drop_rate=r["drop_rate"],
        kill=int(dr > DROP_MAX),
        kill_test="FAIL(kill)" if dr > DROP_MAX else "PASS(no kill)",
    )
# cross-check: gap_stats symbol_year rows equal coverage rates
for r in gs:
    if r["level"] == "symbol_year":
        s = sy[key(r)]
        assert (
            int(r["n"]) == s["contracts_kept"] and r["drop_rate"] == s["drop_rate"] and r["flag_rate"] == s["flag_rate"]
        ), "STOP inconsistent " + str(key(r))
cells = [r for r in gs if r["level"] == "cell"]
rows: list[dict[str, Any]] = []
for r in cells:
    n = int(r["n"])
    rep = n >= NMIN
    blank = r["drop_rate"] == ""
    assert blank == (not rep), "STOP floor mismatch %s" % r
    killed = sy[key(r)]["kill"]
    drop: float | None = float(r["drop_rate"]) if rep else None
    if killed:
        reading = "iii_killed"
    elif not rep:
        reading = "ii_n_lt_20"
    elif drop is not None and drop > DROP_MAX:
        reading = "ii_drop_gt_10pct"
    else:
        reading = "i_usable"
    rows.append(
        dict(
            symbol=r["symbol"],
            year=r["year"],
            type=r["type"],
            moneyness_bucket=r["moneyness_bucket"],
            dte_bucket=r["dte_bucket"],
            n=n,
            reported=int(rep),
            flag_rate=r["flag_rate"],
            drop_rate=r["drop_rate"],
            symbol_year_killed=killed,
            cell_drop_le_10pct=("" if drop is None else int(drop <= DROP_MAX)),
            usable=int(reading == "i_usable"),
            reading=reading,
        )
    )


def w(name: str, rs: list[dict[str, Any]]) -> None:
    with open(os.path.join(OUT, name), "w", newline="") as f:
        d = csv.DictWriter(f, fieldnames=list(rs[0].keys()), lineterminator="\n")
        d.writeheader()
        d.writerows(rs)


w("cell_usable.csv", rows)
w("symbol_year_kill.csv", [sy[k] for k in sorted(sy)])
# summaries
summ: list[dict[str, Any]] = []
for t in ("ALL", "C", "P"):
    rt = [r for r in rows if r["type"] == t]
    reported = [r for r in rt if r["reported"]]
    nk = [r for r in reported if not r["symbol_year_killed"]]
    us = [r for r in rt if r["usable"]]
    summ.append(
        dict(
            type=t,
            cells_total=len(rt),
            cells_reported_n_ge_20=len(reported),
            cells_reported_in_nonkilled_sy=len(nk),
            cells_usable=len(us),
            usable_share_of_reported=f"{len(us) / len(reported):.4f}",
            usable_share_of_all_cells=f"{len(us) / len(rt):.4f}",
            usable_share_of_reported_nonkilled=f"{len(us) / len(nk):.4f}",
            reported_cells_drop_le_10pct_incl_killed=sum(1 for r in reported if r["cell_drop_le_10pct"] == 1),
        )
    )
w("usable_summary.csv", summ)
# per symbol-year usable counts by type
psy: list[dict[str, Any]] = []
for k in sorted(sy):
    d = dict(symbol=k[0], year=k[1], kill=sy[k]["kill"])
    for t in ("ALL", "C", "P"):
        rt = [r for r in rows if (r["symbol"], int(r["year"])) == k and r["type"] == t]
        d[f"{t}_cells"] = len(rt)
        d[f"{t}_reported"] = sum(r["reported"] for r in rt)
        d[f"{t}_usable"] = sum(r["usable"] for r in rt)
    psy.append(d)
w("usable_by_symbol_year.csv", psy)


# distributions of cell flag/drop rates (reported cells), by type and killed status
def q(v: list[float]) -> list[str]:
    v = sorted(v)
    qs = statistics.quantiles(v, n=4, method="inclusive") if len(v) > 1 else [v[0]] * 3
    return [f"{v[0]:.4f}", f"{qs[0]:.4f}", f"{qs[1]:.4f}", f"{qs[2]:.4f}", f"{v[-1]:.4f}"]


dist: list[dict[str, Any]] = []
for t in ("ALL", "C", "P"):
    for grp, sel in (
        ("all_reported", lambda r: True),
        ("nonkilled_sy", lambda r: not r["symbol_year_killed"]),
        ("killed_sy", lambda r: r["symbol_year_killed"]),
    ):
        rr = [r for r in rows if r["type"] == t and r["reported"] and sel(r)]
        for m in ("flag_rate", "drop_rate"):
            mn, p25, med, p75, mx = q([float(r[m]) for r in rr])
            dist.append(
                dict(type=t, group=grp, metric=m, n_cells=len(rr), min=mn, p25=p25, median=med, p75=p75, max=mx)
            )
w("rate_distributions.csv", dist)
# parity per symbol-year (sum over DTE buckets of the prereg s4b rows)
pv: dict[tuple[str, int], list[int]] = {}
for r in par:
    a = pv.setdefault(key(r), [0, 0])
    a[0] += int(r["pairs_tested"])
    a[1] += int(r["violations"])
w(
    "parity_by_symbol_year.csv",
    [
        dict(symbol=k[0], year=k[1], pairs_tested=a[0], violations=a[1], rate=f"{a[1] / a[0]:.6f}" if a[0] else "")
        for k, a in sorted(pv.items())
    ],
)
print("OK")
for s in summ:
    print(s)
for d in psy:
    print(d)
for d in dist:
    print(d)
for k, a in sorted(pv.items()):
    print(k, a, round(a[1] / a[0], 4))
