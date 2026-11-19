# dev_run.py - DEV-only run of sealed prereg v5: fiscal-label diagnostic + H1a/H1b DEV stats.
# No HOLDOUT/raw files, no news month >= 2025-01, no transcript files opened.
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from typing import Any, cast
from zoneinfo import ZoneInfo

import exchange_calendars as xc
import numpy as np
import pandas as pd
from scipy import stats

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

OUT = f"{_QR.DESK_DIR}/research/original/sentiment_returns_dev_20261111"
RET = f"{_QR.DATA_DIR}/av_returns_events_20261111/partitioned/dev"
CLEAN = f"{_QR.DATA_DIR}/av_sentiment_20261110/clean"
NY = ZoneInfo("America/New_York")
UTC = dt.UTC
LOG = open(f"{OUT}/dev_run.log", "w")


def log(*a: object) -> None:
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.write(s + "\n")
    LOG.flush()


log("exchange_calendars", xc.__version__, "pandas", pd.__version__, "numpy", np.__version__)
assert xc.__version__ == "4.13.2"

# ---------------- inputs ----------------
daily = pd.read_csv(f"{RET}/daily_dev.csv")
earn = pd.read_csv(f"{RET}/earnings_dev.csv", dtype=str)
assert len(daily) == 49317 and len(earn) == 5279
assert daily["date"].max() <= "2024-12-31"
cal = xc.get_calendar("XNYS")
sess = [d.strftime("%Y-%m-%d") for d in cal.sessions_in_range("2021-03-01", "2024-12-31")]
assert sorted(daily["date"].unique()) == sess, "XNYS sessions != daily_dev dates"
log("sessions", len(sess), sess[0], sess[-1])
px = daily.pivot(index="date", columns="symbol", values="adjusted_close").loc[sess]
assert px.notna().all().all()
r = px / px.shift(1) - 1.0  # adjusted_close ratios only
STOCKS = sorted(c for c in px.columns if c != "SPY")
assert len(STOCKS) == 50
# beta for decision session t: OLS on exactly 252 daily returns ending t-1
rm = r["SPY"]
cov = r[STOCKS].rolling(252, min_periods=252).cov(rm)
var = rm.rolling(252, min_periods=252).var()
beta = cov.div(var, axis=0).shift(1)  # value at t uses returns through t-1
sidx = {d: i for i, d in enumerate(sess)}

# ---------------- coverage metadata ----------------
cov_news = pd.read_csv(f"{CLEAN}/coverage_news.tsv", sep="\t", dtype=str)
cov_news = cov_news[cov_news["month"] <= "2024-12"]
sums = {}
for line in open(f"{CLEAN}/SHA256SUMS"):
    h, p = line.strip().split(None, 1)
    sums[p.lstrip("*").lstrip("./")] = h

months = [f"{y}-{m:02d}" for y in (2022, 2023, 2024) for m in range(1, 13) if f"{y}-{m:02d}" >= "2022-03"]
assert months[-1] == "2024-12" and len(months) == 34
DEV_CUTOFF = dt.datetime(2024, 12, 31, 16, 0, tzinfo=NY)  # last DEV close
cov0 = set()
capped = {}  # (sym, month)
items = []  # sym, utc_epoch_UTCreading, utc_epoch_ETreading, score, rel
cnt = dict(
    files=0, sha_ok=0, items_total=0, kept_rel=0, no_entry=0, low_rel=0, unparseable=0, multi_entry=0, after_cutoff=0
)
for sym in STOCKS:
    for mth in months:
        rel_path = f"news/{sym}/{mth}.json"
        assert mth <= "2024-12"
        b = open(f"{CLEAN}/{rel_path}", "rb").read()
        cnt["files"] += 1
        if hashlib.sha256(b).hexdigest() != sums[rel_path]:
            log("SHA MISMATCH", rel_path)
            sys.exit(2)
        cnt["sha_ok"] += 1
        d = json.loads(b)
        if (
            d["coverage"] == "coverage=0"
            or d["coverage"].startswith("coverage=0")
            or (len(d["feed"]) == 0 and d["coverage"] != "ok")
        ):
            cov0.add((sym, mth))
        if d["capped_windows"]:
            capped[(sym, mth)] = d["capped_windows"]
        for it in d["feed"]:
            cnt["items_total"] += 1
            tp = it["time_published"]
            naive = dt.datetime.strptime(tp, "%Y%m%dT%H%M%S")
            t_utc = naive.replace(tzinfo=UTC)
            t_et = naive.replace(tzinfo=NY)
            if t_utc > DEV_CUTOFF or t_et > DEV_CUTOFF:
                cnt["after_cutoff"] += 1
                continue
            ents = [e for e in it.get("ticker_sentiment", []) if e.get("ticker") == sym]
            if not ents:
                cnt["no_entry"] += 1
                continue
            if len(ents) > 1:
                cnt["multi_entry"] += 1
            e = ents[0]
            try:
                rel = float(e["relevance_score"])
                s = float(e["ticker_sentiment_score"])
                if not (np.isfinite(rel) and np.isfinite(s)):
                    raise ValueError
            except Exception:
                cnt["unparseable"] += 1
                continue
            if rel < 0.50:
                cnt["low_rel"] += 1
                continue
            cnt["kept_rel"] += 1
            items.append((sym, t_utc.timestamp(), t_et.timestamp(), s, rel))
# cross-check coverage flags against coverage_news.tsv
tsv0 = set(
    zip(
        cov_news.loc[cov_news.coverage == "coverage=0", "symbol"],
        cov_news.loc[cov_news.coverage == "coverage=0", "month"],
    )
)
tsv0 = {k for k in tsv0 if k[0] in STOCKS}
tsvcap = {k for k in zip(cov_news.symbol, cov_news.month, cov_news.capped_windows) if k[0] in STOCKS and k[2] != "-"}
log("coverage0 (stocks, DEV months) file:", sorted(cov0), "tsv:", sorted(tsv0))
assert cov0 == tsv0
log("capped (stocks, DEV months) file:", capped, "tsv:", tsvcap)
assert len(capped) == 0 and len(tsvcap) == 0
log("news counts", cnt)
IT = pd.DataFrame(items, columns=["sym", "tu", "te", "s", "rel"])


def cutoff(d: str) -> float:  # 15:30 ET on session d, as epoch
    y, m, dd = map(int, d.split("-"))
    return dt.datetime(y, m, dd, 15, 30, tzinfo=NY).timestamp()


def month_set(start_ep: float, end_ep: float) -> set[str]:
    # conservative overlap: any calendar month touched by [start-1d, end+1d] in nominal dates
    a = dt.datetime.fromtimestamp(start_ep, NY).date() - dt.timedelta(days=1)
    b = dt.datetime.fromtimestamp(end_ep, NY).date() + dt.timedelta(days=1)
    out: set[str] = set()
    x = a.replace(day=1)
    while x <= b:
        out.add(f"{x.year}-{x.month:02d}")
        x = (x + dt.timedelta(days=32)).replace(day=1)
    return out


# ---------------- periods ----------------
def build_periods(kind: str) -> list[dict[str, Any]]:
    if kind == "H1b":
        dec = [d for d in sess if "2022-03-01" <= d <= "2024-12-31"]
        prev = {d: sess[sidx[d] - 1] for d in dec}
        nxt = {d: (sess[sidx[d] + 1] if sidx[d] + 1 < len(sess) else None) for d in dec}
    else:
        # week membership from the XNYS CALENDAR (no data) extended to 2025-01-10 so the week of 2024-12-30
        # gets its true decision session 2025-01-03 (prereg §0); no data dated >= 2025-01-01 is read.
        calx = [d.strftime("%Y-%m-%d") for d in cal.sessions_in_range("2021-03-01", "2025-01-10")]
        wk: dict[tuple[int, int], str] = {}
        for d in calx:
            k = dt.date.fromisoformat(d).isocalendar()[:2]
            wk[k] = d  # last session of ISO week
        alld = sorted(wk.values())
        dec = [d for d in alld if "2022-03-01" <= d <= "2024-12-31"]
        prev = {d: alld[alld.index(d) - 1] for d in dec}
        nx = {d: (alld[alld.index(d) + 1] if alld.index(d) + 1 < len(alld) else None) for d in dec}
        nxt = nx
    P: list[dict[str, Any]] = []
    for d in dec:
        P.append(dict(dec=d, ws=cutoff(prev[d]), we=cutoff(d), nxt=nxt[d], prev=prev[d]))
    return P


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


def run(kind: str, reading: str) -> dict[str, Any]:
    minn = 3 if kind == "H1a" else 2
    L = 4 if kind == "H1a" else 5
    col = "tu" if reading == "UTC" else "te"
    P = build_periods(kind)
    ex: dict[str, Any] = dict(
        cal_dates=len(P),
        pre_coverage_dates=0,
        purged_dates_B3B8=0,
        period_lt20=0,
        obs_pre_coverage=0,
        obs_purged=0,
        obs_coverage0=0,
        obs_capped=0,
        obs_below_min=0,
        obs_missing_target=0,
        obs_in_dropped_period=0,
        obs_scored=0,
    )
    rows: list[dict[str, Any]] = []
    srt = IT.sort_values(col)
    tcol = cast(np.ndarray, srt[col].values)
    for p in P:
        if p["ws"] < dt.datetime(2022, 3, 1, 0, 0, tzinfo=NY).timestamp() - 0:  # window starts before coverage start
            # coverage starts 2022-03 (nominal); window start before 2022-03-01 00:00 ET -> drop (prereg §0)
            ex["pre_coverage_dates"] += 1
            ex["obs_pre_coverage"] += 50
            continue
        if p["nxt"] is None or p["nxt"] > "2024-12-31":
            ex["purged_dates_B3B8"] += 1
            ex["obs_purged"] += 50
            ex.setdefault("purged_list", []).append(p["dec"])
            continue
        lo, hi = np.searchsorted(tcol, p["ws"], "right"), np.searchsorted(tcol, p["we"], "right")
        w = srt.iloc[lo:hi]
        g = (
            w.groupby("sym").apply(
                lambda z: pd.Series({"n": len(z), "S": np.average(z["s"], weights=z["rel"])}),
                include_groups=False,  # type: ignore[call-overload]  # pandas-stubs GroupBy.apply omits include_groups
            )
            if len(w)
            else pd.DataFrame(columns=["n", "S"])
        )
        ms = month_set(p["ws"], p["we"])
        assert p["nxt"] <= "2024-12-31"
        i0, i1 = sidx[p["dec"]], sidx[p["nxt"]]
        gross = (1 + r.iloc[i0 + 1 : i1 + 1]).prod() - 1  # close(dec) -> close(next)
        b = beta.iloc[i0]
        recs = []
        for sym in STOCKS:
            if any((sym, m) in cov0 for m in ms):
                ex["obs_coverage0"] += 1
                continue
            if any((sym, m) in capped for m in ms):
                ex["obs_capped"] += 1
                continue
            if sym not in g.index or cast(float, g.loc[sym, "n"]) < minn:
                ex["obs_below_min"] += 1
                continue
            if not np.isfinite(b[sym]) or not np.isfinite(gross[sym]):
                ex["obs_missing_target"] += 1
                continue
            recs.append((sym, g.loc[sym, "S"], gross[sym] - b[sym] * gross["SPY"], gross[sym]))
        if len(recs) < 20:
            ex["period_lt20"] += 1
            ex["obs_in_dropped_period"] += len(recs)
            continue
        df = pd.DataFrame(recs, columns=["sym", "S", "y", "raw"])
        ic = stats.spearmanr(df["S"], df["y"]).statistic
        n = len(df)
        k = n // 5
        o = df.sort_values(["S", "sym"]).reset_index(drop=True)
        short, longs = o.iloc[:k], o.iloc[-k:]
        rows.append(
            dict(
                dec=p["dec"],
                nxt=p["nxt"],
                n=n,
                k=k,
                ic=ic,
                ls_raw=longs["raw"].mean() - short["raw"].mean(),
                ls_badj=longs["y"].mean() - short["y"].mean(),
                L=list(longs["sym"]),
                Sh=list(short["sym"]),
            )
        )
        ex["obs_scored"] += n
    R = pd.DataFrame(rows)
    # costs: weights +1/k long, -1/k short; turnover vs previous period's weights (0 if previous scheduled period not scored)
    allP = [p["dec"] for p in P]
    scored = set(R["dec"])
    wprev: dict[str, float] = {}
    to: list[float] = []
    Ri = {row.dec: row for row in R.itertuples()}
    for d in allP:
        if d in scored:
            row = Ri[d]
            k_names = cast(int, row.k)
            wn = dict.fromkeys(cast(list[str], row.L), 1 / k_names)
            wn.update(dict.fromkeys(cast(list[str], row.Sh), -1 / k_names))
        else:
            wn = {}
        t = sum(abs(wn.get(s, 0) - wprev.get(s, 0)) for s in set(wn) | set(wprev))
        if d in scored:
            to.append(t)
        elif t > 0 and to:
            to[-1] += t  # closing trade into an unscored period charged to the last scored period
        wprev = wn
    R["turnover"] = to
    T = len(R)
    mic = R["ic"].mean()
    t = nw_t(R["ic"], L)
    p_ = 1 - stats.t.cdf(t, df=T - 1)
    res = dict(
        hypothesis=kind,
        reading=reading,
        periods=T,
        df=T - 1,
        mean_ic=mic,
        ic_sd=R["ic"].std(ddof=1),
        nw_lag=L,
        nw_t=t,
        p_one_sided=p_,
        ls_gross_raw_mean=R["ls_raw"].mean(),
        ls_net10_raw_mean=(R["ls_raw"] - 0.0010 * R["turnover"]).mean(),
        ls_net20_raw_mean=(R["ls_raw"] - 0.0020 * R["turnover"]).mean(),
        ls_gross_betaadj_mean=R["ls_badj"].mean(),
        ls_net10_betaadj_mean=(R["ls_badj"] - 0.0010 * R["turnover"]).mean(),
        mean_turnover=R["turnover"].mean(),
        mean_n=R["n"].mean(),
        min_n=int(R["n"].min()),
        mean_k=R["k"].mean(),
        first_dec=R["dec"].iloc[0],
        last_dec=R["dec"].iloc[-1],
        symbol_obs_scored=int(ex["obs_scored"]),
        counts=ex,
    )
    res["A2_DEV"] = "PASS(sign)" if mic > 0 else "FAIL"
    R.drop(columns=["L", "Sh"]).to_csv(f"{OUT}/periods_{kind}_{reading}.tsv", sep="\t", index=False)
    return res


results: dict[str, Any] = {}
for kind in ("H1a", "H1b"):
    for rd in ("UTC", "ET"):
        res = run(kind, rd)
        results[f"{kind}_{rd}"] = res
        log(kind, rd, json.dumps(dict(res.items()), default=float))
json.dump(results, open(f"{OUT}/_results_raw.json", "w"), indent=1, default=float)
