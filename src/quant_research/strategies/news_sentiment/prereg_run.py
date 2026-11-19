"""prereg_run.py: the ONE gating run for PREREG_sector_lm_5d.md (implements §4-§8 exactly; DRAFT until freeze).

STATUS: written 2026-10-30, NOT EXECUTED. Per desk instructions (no returns or signal statistics before freeze) it has
only been syntax-checked and run in --check mode (artefact/hash checks; reads no text, prices or returns).
2026-11-06 ~22:30 SGT: §5 control adapters wired (REV5, MOM12-1, ANNSHARE from v1 event table, SUE loader/aggregation
against a PROPOSED input contract pending the derivatives researcher). Tested only on synthetic data (tests/test_controls_asof.py).

Usage:
  python prereg_run.py --check                 # artefact + hash checks only
  NEWS_OOS_UNLOCK=<sha> python prereg_run.py   # gating run; refuses unless PREREG is frozen and all hashes match
Writes out_prereg/<prereg_sha12>/... and, on completion, PREREG_sector_lm_5d.RUNLOG.json (which unseals card work,
see $QR_DESK_DIR/equity/holdout_guard.py). Refuses to run twice for the same PREREG hash.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import html
import itertools
import json
import os
import re
import sys
from collections import namedtuple
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol, cast

import numpy as np
import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
from quant_research.utils.pins import desk_pin

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, f"{_QR.DESK_DIR}/equity")
sys.path.insert(0, f"{_QR.COSTS_DIR}")
from quant_research.data import desk_data as _desk_data
from quant_research.strategies.news_sentiment import holdout_guard as hg


class _DeskStore(Protocol):
    """calendar, membership, and BARS_DIR are read here and not declared on the typed desk_data module."""

    BARS_DIR: str

    def calendar(self) -> pd.DatetimeIndex: ...
    def membership(self) -> pd.DataFrame: ...
    def universe(self) -> pd.DataFrame: ...


dd = cast(_DeskStore, _desk_data)

PREREG, PREREG_SHA, MANIFEST = "PREREG_sector_lm_5d.md", "PREREG_sector_lm_5d.sha256", "PREREG_manifest.txt"
COST_MODEL = f"{_QR.COSTS_DIR}/cost_model.py"
COST_MODEL_SHA = desk_pin("strategies.news_sentiment.prereg_run", "COST_MODEL_SHA")  # TCA owner v1.1
COST_DOC = f"{_QR.DESK_DIR}/tca/cost_model.md"
COST_DOC_SHA = desk_pin("strategies.news_sentiment.prereg_run", "COST_DOC_SHA")
LM_POS_SHA = "6fb159d5a3b69e553edbc237c8d14551eafa5f71bb819a3807153489b7f6ab75"
LM_NEG_SHA = "58fb732dd47af8b95a62abaa417039681b1c4d61035fa2b06022dc08c559d564"
VADER_LEX_SHA = "1ec9c6e9ee19aade328f8beb393a6afa71a5bb3acf7d3cc22d4ef568df374bf5"
VADER_PY_SHA = "25cd814d23000b41c0e242d99960832c6620b3f1b844469173404500ce63206b"
VADER_FIN_OVERRIDE_SHA = (
    "4e1ff542f8f3b4f38c10839679637c6597c7fb9d61f66a8689f6952c945d7632"  # lexicon/vader_finance_neutral_v1.txt
)
VADER_FIN_PY_SHA = "0b8506ea47193fac39b93b3022bdb7d7dfff827d99a19ded0b219360e279a6ca"  # vader_fin.py
N_FAMILY = 153
N_HYPEFADE = 153 + 192  # Review decisions 2026-10-30
SUE_PATH = f"{_QR.DATA_DIR}/derived/sue_xbrl.parquet"  # The derivatives researcher; stamped at 10-Q/10-K acceptance
EVENTS_DIR = f"{_QR.DESK_DIR}/equity/earnings_events"  # see EVENTS_PATH/EVENTS_SHA (§5 block); never globbed
OOS = (
    pd.Timestamp("2016-01-05"),
    pd.Timestamp("2025-05-22"),
)  # formation dates (first OOS month may move per §3 floor)
SEEN = (pd.Timestamp("2025-06-02"), pd.Timestamp("2026-10-30"))
ETFS = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}
ANALYST = re.compile(r"\b(Upgrades|Downgrades|Initiates Coverage|Reinstates|Maintains|Reiterates|Price Target)\b")
PRIMARY = dict(hold=5, k=3, min_stocks=3, min_sectors=6, scorer="lm", filt=True, window="overnight_full")
NEIGH = dict(hold=(4, 6), k=(2, 4), min_stocks=(2, 4), min_sectors=(5, 7))
# LIMITS v0.3.5 sizing: 5 sleeves x 6 ETFs; per-sleeve gross g with 5g/6 <= 9.5% (H1 buffer) -> g = 11.4%; total 57% <= 58% (H3 buffer)
SLEEVE_GROSS, EQUITY_USD = 0.114, 100_000.0
# Borrow (TCA owner ethan_cost_inputs.md §3, validation look-ahead decision): primary 1%/yr (STANDARD GC floor), 2x stress = 2%/yr
# via cost_mult=2; 10%/yr unknown-borrow GATE (G11) because historical ETB flags are unknown (flags exist only from 2026-10-30, and
# today's flags are NOT applied to history). 25 bp/yr is a reference only and is not used. Calendar-day / 360 basis.
BORROW_BASE, BORROW_HTB_SENS = 0.01, 0.10
# Review 2026-11-06: (2) the 2x run = 2x the PRIMARY cost (here: no uplift, so primary = Base); cost_mult multiplies the
# primary per-side cost and borrow. (5) + decision: the 10%/yr unknown-borrow run is a REQUIRED gate (G11) for the
# ETF shorts too: net Sharpe > 0 with borrow=BORROW_HTB_SENS, else FAIL on costs. Today's ETB flags / ETF liquidity are
# not historical evidence. 1% base and 2% sensitivity remain diagnostics. (3) none of these add trials.
COST_MULT_PRIMARY, COST_MULT_STRESS = 1.0, 2.0
HTB_GATE_APPLIES = True  # Review 2026-11-06: applies to SPDR ETF shorts (G11)
HTB_GATE_RULE = "sharpe(simulate(..., borrow=BORROW_HTB_SENS)) > 0 else FAIL_ON_COSTS"
COSTS_INPUTS_SHA = desk_pin("strategies.news_sentiment.prereg_run", "COSTS_INPUTS_SHA")


# The TCA owner's cost inputs are required inputs (no default): the .md and the measured-costs folder.
def costs_inputs() -> str:
    """The cost-inputs .md (pinned by COSTS_INPUTS_SHA); $QR_COSTS_INPUTS, required."""
    return _QR.required_env("QR_COSTS_INPUTS", "the TCA owner's cost-inputs .md (COSTS_INPUTS_SHA)")


def costs_inputs_dir() -> str:
    """The folder holding the COSTS_FILE_SHA files; $QR_COSTS_INPUTS_DIR, required."""
    return _QR.required_env("QR_COSTS_INPUTS_DIR", "the TCA owner's measured-costs folder (COSTS_FILE_SHA)")


COSTS_FILE_SHA = {
    "asset_flags_paper.json": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.asset_flags_paper.json"),
    "bucket_costs.csv": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.bucket_costs.csv"),
    "card_costs.json": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.card_costs.json"),
    "card_costs.py": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.card_costs.py"),
    "cost_tables.py": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.cost_tables.py"),
    "etf_costs.csv": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.etf_costs.csv"),
    "open_vs_mid.py": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.open_vs_mid.py"),
    "open_vs_mid_raw.csv": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.open_vs_mid_raw.csv"),
    "per_side_costs.csv": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.per_side_costs.csv"),
    "run.log": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.run.log"),
    "sample_meta.json": desk_pin("strategies.news_sentiment.prereg_run", "COSTS_FILE_SHA.sample_meta.json"),
}


def sha(p: str) -> str:
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def check(strict: bool) -> bool:
    """Artefact checks. strict=True (gating run) requires everything; False just reports."""
    rep: dict[str, str] = {}
    ok = True

    def need(name: str, cond: object, detail: str = "") -> None:
        nonlocal ok
        rep[name] = ("OK" if cond else "MISSING/MISMATCH") + (f" {detail}" if detail else "")
        ok &= bool(cond)

    need("prereg_frozen(.sha256 matches)", hg.prereg_frozen())
    need(
        "unlock_env_matches", os.environ.get("NEWS_OOS_UNLOCK", "") == (sha(PREREG) if os.path.exists(PREREG) else None)
    )
    need("cost_model.py v1.1", sha(COST_MODEL) == COST_MODEL_SHA)
    need("cost_model.md v1.1", sha(COST_DOC) == COST_DOC_SHA)
    need("ethan_cost_inputs.md", sha(costs_inputs()) == COSTS_INPUTS_SHA)
    costs_dir = costs_inputs_dir()
    for fn, h in COSTS_FILE_SHA.items():
        need(f"tca/ethan_inputs/{fn}", sha(os.path.join(costs_dir, fn)) == h)
    need("lm_positive", sha("lexicon/lm_positive.txt") == LM_POS_SHA)
    need("lm_negative", sha("lexicon/lm_negative.txt") == LM_NEG_SHA)
    try:
        import vaderSentiment.vaderSentiment as vs  # noqa: N813  # package is CamelCase; vs is the local handle

        vd = os.path.dirname(cast(str, vs.__file__))
        need("vader_lexicon", sha(f"{vd}/vader_lexicon.txt") == VADER_LEX_SHA)
        need("vaderSentiment.py", sha(vs.__file__) == VADER_PY_SHA)
        need(
            "vader_finance_neutral_v1",
            sha(os.path.join(HERE, "lexicon/vader_finance_neutral_v1.txt")) == VADER_FIN_OVERRIDE_SHA,
        )
        need("vader_fin.py", sha(os.path.join(HERE, "vader_fin.py")) == VADER_FIN_PY_SHA)
    except ImportError:
        need("vaderSentiment installed", False)
    need("sue_xbrl.parquet present", os.path.exists(SUE_PATH))
    need(
        "sue_xbrl sha pinned (pending the derivatives researcher)",
        SUE_SHA is not None and os.path.exists(SUE_PATH) and sha(SUE_PATH) == SUE_SHA,
    )
    need(
        "earnings_events v1 (explicit path, pinned sha)", os.path.exists(EVENTS_PATH) and sha(EVENTS_PATH) == EVENTS_SHA
    )
    if os.path.exists(MANIFEST):
        lines = [l.split() for l in open(MANIFEST) if l.strip() and not l.startswith("#")]
        bad = [p for h, p in lines if not os.path.exists(p) or sha(p) != h]
        need("manifest files match", not bad, f"{len(bad)} bad of {len(lines)}")
        listed = {p for _, p in lines}
        on_disk = set(glob.glob("raw/*.jsonl") + glob.glob("raw_alias/*.jsonl"))
        need("manifest covers ALL fetched months (X6 iv)", on_disk <= listed, f"{len(on_disk - listed)} unlisted")
        need("manifest is not provisional", "PROVISIONAL" not in open(MANIFEST).read())
    else:
        need("manifest", False)
    if os.path.exists(hg.RUNLOG):
        need("not already run for this hash", json.load(open(hg.RUNLOG)).get("prereg_sha256") != sha(PREREG))
    print(json.dumps(rep, indent=1))
    if strict and not ok:
        sys.exit("prereg_run: artefact checks failed; refusing to run")
    return ok


# ---------------------------------------------------------------- data (only after check passes)
def load_articles() -> pd.DataFrame:
    al = pd.read_csv("aliases.csv")
    amap = dict(zip(al.iloc[:, 0], al.iloc[:, 1]))
    rows: list[tuple[Any, Any, Any, list[Any], str]] = []
    for fn in sorted(glob.glob("raw/*.jsonl") + glob.glob("raw_alias/*.jsonl")):
        for l in open(fn):
            r = cast(dict[str, Any], json.loads(l))
            s = cast(list[Any], r.get("symbols", []))
            if not 1 <= len(s) <= 3 or ANALYST.search(r.get("headline", "") or ""):
                continue
            rows.append(
                (
                    r["id"],
                    r["created_at"],
                    r["updated_at"],
                    [amap.get(x, x) for x in s],
                    html.unescape((r.get("headline") or "") + ". " + (r.get("summary") or "")),
                )
            )
    a = pd.DataFrame(rows, columns=["id", "created", "updated", "syms", "text"]).drop_duplicates("id")
    for c in ("created", "updated"):
        a[c] = pd.to_datetime(a[c], utc=True).dt.tz_convert("America/New_York")
    cal = dd.calendar()
    ny = "America/New_York"
    cut = pd.DatetimeIndex([pd.Timestamp(s).tz_localize(ny) + pd.Timedelta(hours=9, minutes=25) for s in cal])
    opn_prev = pd.DatetimeIndex(
        [pd.NaT] + [pd.Timestamp(s).tz_localize(ny) + pd.Timedelta(hours=9, minutes=30) for s in cal[:-1]]
    )
    cls_prev = pd.DatetimeIndex([pd.NaT] + [pd.Timestamp(s).tz_localize(ny) + pd.Timedelta(hours=16) for s in cal[:-1]])
    pos = cut.searchsorted(a.created, side="right")
    keep = (pos > 0) & (pos < len(cut))
    a = a[keep].copy()
    pos = pos[keep]
    a["session"] = cal[pos]
    a["cutoff"] = cut[pos]
    a["in_full"] = a.created >= opn_prev[pos]  # [09:30 d-1, 09:25 d)
    a["in_overnight"] = a.created >= cls_prev[pos]  # [16:00 d-1, 09:25 d)  (§9.3)
    a["edited_after_cutoff"] = a.updated >= a.cutoff
    pos_w = set(open("lexicon/lm_positive.txt").read().split())
    neg_w = set(open("lexicon/lm_negative.txt").read().split())

    def lm(t: str) -> float:
        w = re.findall(r"[A-Za-z]+", t.upper())
        p = sum(x in pos_w for x in w)
        n = sum(x in neg_w for x in w)
        return (p - n) / (p + n) if p + n else 0.0

    from quant_research.features import (
        vader_fin,  # VADER 3.3.2 minus the pinned finance-domain neutralisation list (PREREG §0)
    )

    va = vader_fin.analyzer()
    a["lm"] = a.text.map(lm)
    a["vader"] = a.text.map(lambda t: va.polarity_scores(t)["compound"])
    x = a.drop(columns="text").explode("syms").rename(columns={"syms": "sym"})
    m = dd.membership()
    x = x.merge(m[["symbol", "start", "end"]], left_on="sym", right_on="symbol")
    x = x[(x.session >= x.start) & (x.session < x.end)].drop_duplicates(["id", "sym"])
    x["sector"] = x.sym.map(dd.universe().drop_duplicates("symbol").set_index("symbol").gics_sector)
    return x.dropna(subset=["sector"])


def etf_bars() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for s in [*list(ETFS.values()), "SPY"]:
        b = pd.read_parquet(
            f"{dd.BARS_DIR}/{s}.parquet", columns=["session_date", "open", "high", "low", "close", "volume"]
        )
        b["session_date"] = pd.to_datetime(b.session_date)
        b = b.drop_duplicates("session_date").set_index("session_date").sort_index()
        tr = pd.concat([b.high - b.low, (b.high - b.close.shift()).abs(), (b.low - b.close.shift()).abs()], axis=1).max(
            axis=1
        )
        b["atr14_prev"] = tr.rolling(14).mean().shift(1)  # known before the open of d
        b["adv20_usd_prev"] = (b.close * b.volume).rolling(20).mean().shift(1)
        out[s] = b
    return out


def sector_scores(x: pd.DataFrame, p: Mapping[str, Any]) -> pd.DataFrame:
    y = x[x.in_overnight] if p["window"] == "overnight" else x[x.in_full]
    if p["filt"]:
        y = y[~y.edited_after_cutoff]
    st = y.groupby(["session", "sector", "sym"])[p["scorer"]].mean().reset_index()
    g = st.groupby(["session", "sector"])[p["scorer"]].agg(["mean", "size"])
    return cast(pd.DataFrame, g[g["size"] >= p["min_stocks"]]["mean"].unstack())


_COSTS_SIDE: pd.DataFrame | None = None


def costs_per_side(sym: str) -> tuple[float, float]:
    """the TCA owner's measured per-side costs (tca/ethan_inputs/per_side_costs.csv): (base at the open, base_mktlim continuous)."""
    global _COSTS_SIDE
    if _COSTS_SIDE is None:
        _COSTS_SIDE = pd.read_csv(os.path.join(costs_inputs_dir(), "per_side_costs.csv")).set_index("name")
    if sym in _COSTS_SIDE.index:
        return float(cast(Any, _COSTS_SIDE.at[sym, "base"])), float(cast(Any, _COSTS_SIDE.at[sym, "base_mktlim"]))
    return 0.0, 0.0


def leg_cost_bps(
    b: pd.DataFrame,
    d: object,
    notional: float,
    half_spread_mult: float,
    sym: str | None = None,
    venue: str = "open",
) -> float:
    """One-way bps = max(TCA owner v1.1 model at `venue`, STANDARD §5 liquid-ETF floor 2 bp + FULL normal half-spread,
    The TCA owner's measured per-side Base for this ETF). venue='open' for MOO entries/exits; 'continuous' for stop exits
    (the TCA owner: stops fill at continuous-session cost plus gap; the gap is already in the stop fill price).
    The 0.5x open half-spread multiplier is an unverified assumption; the floor binds until the SPY pilot (2-9 Nov) reports."""
    from quant_research.backtest.costs import cost_model as cm

    px = cast(float, b.at[d, "open"])
    adv_sh = cast(float, b.at[d, "adv20_usd_prev"]) / px
    hs_bucket = cm.BUCKETS[cm.liq_bucket(adv_sh * px)][1]
    spread = (
        2 * hs_bucket * (half_spread_mult / 0.5 if venue == "open" else 1.0)
    )  # open applies 0.5x; mult 1.0 => 1.0x stress
    t = cm.trade_cost("buy", px, int(notional // px), adv_sh, spread_bps=spread, venue=venue)
    base_open, base_cont = costs_per_side(sym) if sym else (0.0, 0.0)
    return max(t["total_bps"], 2.0 + hs_bucket, base_open if venue == "open" else base_cont)


def simulate(
    L: pd.DataFrame,
    bars: Mapping[str, pd.DataFrame],
    p: Mapping[str, Any],
    cost_mult: float = 1.0,
    hs_mult: float = 0.5,
    borrow: float = BORROW_BASE,
    stops: bool = True,
    net: bool = True,
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily strategy return on equity (LIMITS-sized), 5 overlapping sleeves (hold h), 2xATR(14) stops."""
    cal = dd.calendar()
    idx = {d: i for i, d in enumerate(cal)}
    h, k = cast(int, p["hold"]), cast(int, p["k"])
    legs_by_day: dict[pd.Timestamp, list[tuple[str, float]]] = {}
    for raw_d, row in L.iterrows():
        d = cast(pd.Timestamp, raw_d)
        if d not in idx or idx[d] + h >= len(cal):
            continue
        e = cal[idx[d] + h]
        elig: list[tuple[str, Any]] = []
        for s, v in row.dropna().items():
            sector = cast(str, s)
            etf = ETFS.get(sector)
            if etf and d in bars[etf].index and e in bars[etf].index:
                elig.append((sector, v))
        if len(elig) < p["min_sectors"]:
            continue
        elig.sort(key=lambda t: (-t[1], ETFS[t[0]]))
        longs = [ETFS[s] for s, _ in elig[:k]]
        shorts = [ETFS[s] for s, _ in sorted(elig, key=lambda t: (t[1], ETFS[t[0]]))[:k]]
        w = SLEEVE_GROSS / (2 * k) / (h / 5)  # keeps 5g/6 <= 9.5% at h=5; scales for neighbourhood holds
        legs_by_day[d] = [(t, +w) for t in longs] + [(t, -w) for t in shorts]
    r = pd.Series(0.0, index=cal)
    trades: list[dict[str, Any]] = []
    for d, legs in legs_by_day.items():
        i0 = idx[d]
        for t, w in legs:
            b = bars[t]
            entry = cast(float, b.at[d, "open"])
            stop_dist = 2 * cast(float, b.at[d, "atr14_prev"])
            sh = int(abs(w) * EQUITY_USD // entry)  # whole shares only (no fractional on opg/cls)
            if sh == 0:
                continue
            w = np.sign(w) * sh * entry / EQUITY_USD
            exit_px, exit_day = None, cal[i0 + h]
            for j in range(i0, i0 + h):
                dj = cal[j]
                if dj not in b.index:
                    continue
                if stops:
                    lvl = entry - np.sign(w) * stop_dist
                    hit = (b.at[dj, "low"] <= lvl) if w > 0 else (b.at[dj, "high"] >= lvl)
                    if hit:
                        gap = (b.at[dj, "open"] <= lvl) if w > 0 else (b.at[dj, "open"] >= lvl)
                        exit_px = b.at[dj, "open"] if (gap and j > i0) else lvl
                        exit_day = dj
                        break
            if exit_px is None:
                exit_px = b.at[exit_day, "open"] if exit_day in b.index else np.nan
            gross = np.sign(w) * (cast(float, exit_px) / entry - 1)
            stopped = exit_day != cal[i0 + h]
            cal_days = max(1, (pd.Timestamp(exit_day) - pd.Timestamp(d)).days)
            c = 0.0
            if net:
                notional = abs(w) * EQUITY_USD
                c_in = leg_cost_bps(b, d, notional, hs_mult, sym=t, venue="open")
                c_out = leg_cost_bps(b, d, notional, hs_mult, sym=t, venue="continuous" if stopped else "open")
                c = cost_mult * (c_in + c_out) / 1e4
                if w < 0:
                    c += cost_mult * borrow * cal_days / 360
            pnl = abs(w) * (gross - c)
            # booked at exit (conservative for Sharpe timing; sleeves non-overlapping per leg)
            r.loc[exit_day] += cast(float, pnl)  # type: ignore[call-overload]  # pandas-stubs loc rejects a DatetimeIndex label
            trades.append(
                dict(
                    form=d,
                    etf=t,
                    w=w,
                    entry=entry,
                    exit_day=exit_day,
                    exit_px=exit_px,
                    gross=gross,
                    cost=c,
                    stopped=stopped,
                )
            )
    return r, pd.DataFrame(trades)


def sharpe(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan


def dsr(sr_ann: float, T: float, skew: float, kurt: float, N: float, sigma_sr: float) -> tuple[float, float]:
    from scipy.stats import norm

    g = 0.5772156649
    sr0 = sigma_sr * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * np.e)))
    sr, s0 = sr_ann / np.sqrt(252), sr0 / np.sqrt(252)
    return float(norm.cdf((sr - s0) * np.sqrt(T - 1) / np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2))), sr0


def pbo_cscv(M: pd.DataFrame, S: int = 16) -> float:
    """Bailey et al. CSCV: M = T x n_variants daily returns; returns PBO."""
    M = M.dropna()
    blocks = np.array_split(np.arange(len(M)), S)
    lam: list[Any] = []
    for comb in itertools.combinations(range(S), S // 2):
        tr = np.concatenate([blocks[i] for i in comb])
        te = np.concatenate([blocks[i] for i in range(S) if i not in comb])
        is_sr = M.iloc[tr].mean() / M.iloc[tr].std()
        os_sr = M.iloc[te].mean() / M.iloc[te].std()
        best = is_sr.idxmax()
        rank = cast(float, os_sr.rank().loc[cast(Any, best)]) / (len(os_sr) + 1)
        lam.append(np.log(rank / (1 - rank)))
    return float(np.mean(np.array(lam) <= 0))


# ---------------------------------------------------------------- §5 controls: as-of adapters (wired 2026-11-06 ~22:30 SGT)
# Nothing in this block runs in --check mode. The loaders (load_events / load_sue / controls) refuse unless
# check(strict=True) has passed in this process (_STRICT_OK); the pure panel functions take DataFrames and are unit-tested on
# SYNTHETIC data only (tests/test_controls_asof.py). No prices, calendars, event rows or SUE rows are read by --check.
#
# Event table choice: v1 (pinned below), not v2. Reason: ANNSHARE needs only accession, cik, acceptance_utc,
# session_date_0925, in_sp500 and index_symbols. The review ACCEPTED v1 for timestamps + PIT membership
# (the internal review record); v2 is a CONDITIONAL accept with promotion blockers open
# and, by the review's own check, has identical acceptance/session timing for all 31,467 accessions, so v2 adds nothing ANNSHARE
# uses. v1 also carries none of v2's later-availability fields (ex99_available_*, cluster lags), so they cannot leak in.
# Only the explicit v1 path is read (never a glob over versioned tables, which would duplicate accessions), and only
# EVENT_COLS; ex99_*, exhibit, cluster, lag and other retrospective columns are never loaded or used as predictors.
EVENTS_PATH = f"{_QR.DESK_DIR}/equity/earnings_events/earnings_events_8k202.parquet"
EVENTS_SHA = (
    desk_pin("strategies.news_sentiment.prereg_run", "EVENTS_SHA")  # v1, validation PIT decision (timestamps/PIT only)
)
EVENT_COLS = ["accession", "cik", "acceptance_utc", "session_date_0925", "in_sp500", "index_symbols"]
SUE_SHA: str | None = (
    None  # PENDING the derivatives researcher: final sue_xbrl.parquet hash. None => strict check fails closed; never filled from a guess.
)
NY = "America/New_York"
CUTOFF = pd.Timedelta(hours=9, minutes=25)  # §4.3/§5: info usable at d only if strictly before 09:25 ET of d
ANN_LOOKBACK = (
    5  # §5 literal: s(tau) in [d-5, d] in sessions, i.e. ages 0..5 (6 sessions incl. d). See README blocker 3.
)
SUE_LOOKBACK = 62  # §5 "within the last 63 sessions": ages 0..62 = 63 sessions incl. d. See README blocker 3.
CONTROL_LONG_HIGH = {
    "REV5": False,
    "MOM12_1": True,
    "SUE": True,
}  # REV5 longs the 3 lowest (§5); others long the highest
CONTROL_MISSING_POLICY: str | None = (
    None  # §5 "same eligible sectors": if a control is undefined for a sector that is eligible in L,
)
# the run RAISES (no invented fill / drop). Needs a validation decision before freeze (README).
_STRICT_OK = False


class ControlInputError(ValueError):
    pass  # schema / absent / ambiguous / duplicate inputs (fail closed)


class IdentityConflict(ValueError):
    pass  # one event mapped to >1 eligible firm, or a firm spanning sectors


class SemanticReviewNeeded(ValueError):
    pass  # e.g. SUE knowledge time before its 8-K acceptance: flag, never assume


def _require_strict() -> None:
    if not _STRICT_OK:
        raise RuntimeError("as-of control adapters run only after check(strict=True) has passed")


def _sessions(cal: pd.DatetimeIndex | Sequence[pd.Timestamp]) -> pd.DatetimeIndex:
    """DatetimeIndex(cal). The stub constructor rejects this union; the value is unchanged."""
    return pd.DatetimeIndex(cast(pd.DatetimeIndex, cal))


def cutoffs_utc(cal: pd.DatetimeIndex | Sequence[pd.Timestamp]) -> pd.DatetimeIndex:
    """09:25 ET of each session in UTC (DST via America/New_York). cal: sorted naive session dates."""
    cal = _sessions(cal)
    if not cal.is_monotonic_increasing or cal.has_duplicates:
        raise ControlInputError("calendar not strictly increasing")
    return (cal.normalize() + CUTOFF).tz_localize(NY).tz_convert("UTC")


def first_session_after(
    ts_utc: pd.DatetimeIndex | pd.Series, cal: pd.DatetimeIndex | Sequence[pd.Timestamp]
) -> np.ndarray[Any, np.dtype[np.intp]]:
    """s(tau) = first session whose 09:25 ET cutoff is STRICTLY after tau. A tau exactly at 09:25:00 ET maps to the NEXT
    session. Returns integer positions into cal; -1 = not placeable (tau at/after the last cutoff, or before the FIRST cutoff, where
    the true session could precede the calendar). -1 rows are never visible."""
    ts = pd.DatetimeIndex(cast(pd.DatetimeIndex, ts_utc))
    if ts.tz is None:
        raise ControlInputError("timestamps must be tz-aware UTC")
    pos = cutoffs_utc(cal).searchsorted(ts.tz_convert("UTC"), side="right")
    return np.where((pos > 0) & (pos < len(cal)), pos, -1)


def _split_symbols(v: object) -> list[str]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return []
    toks = [t.strip() for t in str(v).split(",")]
    if any(t == "" for t in toks):
        raise ControlInputError(f"malformed index_symbols {v!r}")
    return sorted(set(toks))  # 'SW,SW' -> ['SW']: a symbol listed twice counts once


def firm_map(universe: pd.DataFrame) -> pd.DataFrame:
    """Eligible-symbol map from the CURRENT-GICS universe (PREREG §3; PIT GICS replaces it if it exists at freeze).
    firm key = 'CIK:<universe cik>' so share classes (GOOGL/GOOG, FOXA/FOX, NWSA/NWS) are ONE firm; 'SYM:<symbol>' only when
    the universe has no CIK. Symbols without a sector (former members, ETFs) are not eligible (§11)."""
    u = universe[universe.gics_sector.notna()]
    if u.symbol.duplicated().any():
        raise ControlInputError("universe has duplicate symbols")
    fk = [f"CIK:{int(c)}" if pd.notna(c) else f"SYM:{s}" for s, c in zip(u.symbol, u.cik)]
    fm = pd.DataFrame({"symbol": u.symbol.values, "sector": u.gics_sector.values, "firm": fk})
    bad = fm.groupby("firm").sector.nunique()
    bad = bad[bad > 1]
    if len(bad):
        raise IdentityConflict(f"firm keys spanning >1 sector: {list(bad.index)}")
    return fm.set_index("symbol")


def eligible_firms(
    dates: Sequence[pd.Timestamp] | pd.DatetimeIndex, membership: pd.DataFrame, fm: pd.DataFrame
) -> dict[pd.Timestamp, dict[Any, set[Any]]]:
    """{d: {sector: set(firm)}}: PIT members at d (start <= d < end, desk_data convention) with a sector; firm-deduplicated."""
    m = membership[membership.symbol.isin(fm.index)]
    out: dict[pd.Timestamp, dict[Any, set[Any]]] = {}
    for d in _sessions(dates):
        live = m[(m.start <= d) & (m.end > d)].symbol.unique()
        sec: dict[Any, set[Any]] = {}
        for s in live:
            sec.setdefault(fm.at[s, "sector"], set()).add(fm.at[s, "firm"])
        out[d] = sec
    return out


class _EventView(Protocol):
    @property
    def accession(self) -> object: ...
    @property
    def index_symbols(self) -> object: ...
    @property
    def cik(self) -> object: ...


def event_firms(row: _EventView, fm: pd.DataFrame, diag: dict[str, int]) -> set[str]:
    """Eligible firm keys credited by one event. Primary: index_symbols (PIT symbols sharing the filer CIK that day).
    Fallback ONLY when index_symbols is empty: the universe firm whose CIK equals the event CIK (never ticker_at_event).
    >1 distinct eligible firm from one event -> IdentityConflict (fail closed; no guessing which firm filed)."""
    syms = _split_symbols(row.index_symbols)
    if syms:
        firms = {cast(str, fm.at[s, "firm"]) for s in syms if s in fm.index}
        if not firms:
            diag["events_no_eligible_symbol"] += 1
    else:
        firms = {f"CIK:{int(cast(Any, row.cik))}"} & set(cast(Iterable[str], fm.firm))
        diag["events_cik_fallback_used" if firms else "events_unattributed"] += 1
    if len(firms) > 1:
        raise IdentityConflict(f"accession {row.accession}: index_symbols {syms} map to firms {sorted(firms)}")
    return firms


_EvRow = namedtuple("_EvRow", "accession index_symbols cik")


def validate_events(ev: pd.DataFrame, cal: pd.DatetimeIndex | Sequence[pd.Timestamp]) -> pd.DataFrame:
    """Schema + timing checks on the event table (only EVENT_COLS). Recomputes s(tau) independently with the STRICT 09:25 ET
    rule and requires it to equal the reviewed session_date_0925 for every in_sp500 event inside the calendar."""
    miss = [c for c in EVENT_COLS if c not in ev.columns]
    if miss:
        raise ControlInputError(f"event table missing {miss}")
    ev = ev[EVENT_COLS].copy()
    if ev.accession.isna().any() or ev.accession.duplicated().any():
        raise ControlInputError("event accessions null/duplicated")
    if not isinstance(ev.acceptance_utc.dtype, pd.DatetimeTZDtype) or str(ev.acceptance_utc.dt.tz) != "UTC":
        raise ControlInputError("acceptance_utc must be tz-aware UTC")
    if ev.acceptance_utc.isna().any():
        raise ControlInputError("acceptance_utc has nulls")
    if ev.in_sp500.dtype != bool:
        raise ControlInputError("in_sp500 must be bool")
    cal = _sessions(cal)
    ev["s_pos"] = first_session_after(ev.acceptance_utc, cal)
    inside = ev.in_sp500 & (ev.s_pos >= 0)
    rec = cal[cast(Any, ev.loc[inside, "s_pos"].values)]
    rev = pd.to_datetime(ev.loc[inside, "session_date_0925"]).values
    bad = rec.values != rev
    if bad.any():
        raise ControlInputError(f"{int(bad.sum())} in_sp500 events: strict-09:25 session != session_date_0925")
    return ev


def annshare_panel(
    ev: pd.DataFrame,
    cal: pd.DatetimeIndex | Sequence[pd.Timestamp],
    dates: Sequence[pd.Timestamp] | pd.DatetimeIndex,
    membership: pd.DataFrame,
    fm: pd.DataFrame,
) -> pd.DataFrame:
    """§5 ANNSHARE_{k,d} = (# eligible sector-k firms with an in_sp500 8-K 2.02 event whose s(tau) is in [d-5, d])
    / (# eligible sector-k firms at d). Firm-level (share classes once). Sector with eligible firms and no events -> 0.0;
    sector with NO eligible firms -> NaN (undefined, not zero). Only in_sp500 events; no ex99/lag/retrospective fields."""
    cal = _sessions(cal)
    pos = {d: i for i, d in enumerate(cal)}
    ev = validate_events(ev, cal)
    diag = {"events_no_eligible_symbol": 0, "events_cik_fallback_used": 0, "events_unattributed": 0}
    hits: dict[int, set[str]] = {}  # session position -> set(firm) with s(tau) == that session
    for r in ev[ev.in_sp500 & (ev.s_pos >= 0)].itertuples():
        for f in event_firms(r, fm, diag):
            hits.setdefault(int(cast(Any, r.s_pos)), set()).add(f)
    elig = eligible_firms(dates, membership, fm)
    rows: dict[pd.Timestamp, dict[Any, float]] = {}
    for d in _sessions(dates):
        if d not in pos:
            raise ControlInputError(f"formation date {d.date()} not a calendar session")
        i = pos[d]
        seen = set().union(*[hits.get(j, set()) for j in range(max(0, i - ANN_LOOKBACK), i + 1)])
        rows[d] = {k: len(f & seen) / len(f) for k, f in elig[d].items() if f}
    out = pd.DataFrame.from_dict(rows, orient="index").reindex(columns=sorted(set(fm.sector))).sort_index()
    out.attrs["diag"] = diag
    return out


# SUE input contract (PROPOSED by the sentiment researcher from SUE_NOTE.md §6; not yet accepted by the SUE owner). Grain: one row per 8-K 2.02 event.
SUE_REQUIRED = {
    "accession": "8-K Item 2.02 accession in the pinned event table (join key; unique)",
    "sue": "float; NaN = not computable (row ignored); +/-inf rejected",
    "xbrl_knowledge_time_utc": "tz-aware UTC acceptance of the 10-Q/10-K that FIRST reported the quarter",
}
SUE_OPTIONAL = {
    "cik": "int; must equal the event-table CIK of `accession`",
    "symbol": "str; must be one of the event's index_symbols",
    "xbrl_accn": "str; unique where present (one first-reporting filing per event)",
    "fiscal_period_end": "date; (firm, fiscal_period_end) unique (first-reported only)",
}
SUE_SYNONYMS = {
    "accession": {"accn", "accession_8k", "event_accession", "accession_number", "accession_no"},
    "sue": {"SUE", "sue_q", "sue_value", "sue_gaap"},
    "xbrl_knowledge_time_utc": {
        "knowledge_time",
        "knowledge_time_utc",
        "xbrl_knowledge_time",
        "available_at",
        "xbrl_available_at",
        "xbrl_acceptance_utc",
        "acceptance_utc",
        "filed",
    },
    "cik": {"CIK", "cik_str"},
    "symbol": {"ticker", "index_symbols", "sym"},
}


def validate_sue(sue: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Strict loader-side validation; never guesses a column. Raises on absent/ambiguous columns, wrong dtypes, duplicates,
    unknown accessions, CIK/symbol mismatches; raises SemanticReviewNeeded if a knowledge time precedes its 8-K acceptance
    (SUE_NOTE §2 says the 10-Q/10-K arrives AFTER the 8-K; earlier would mean a wrong join/grain, so it is flagged, not used)."""
    cols = set(sue.columns)
    for c, syn in SUE_SYNONYMS.items():
        found = sorted(cols & syn)
        if c in cols and found:
            raise ControlInputError(f"ambiguous: '{c}' and synonym(s) {found} both present")
        if c in SUE_REQUIRED and c not in cols:
            raise ControlInputError(
                f"required column '{c}' absent" + (f" (found {found}; not guessing)" if found else "")
            )
    x = sue.copy()
    if (
        not (pd.api.types.is_object_dtype(x.accession) or pd.api.types.is_string_dtype(x.accession))
        or x.accession.isna().any()
    ):
        raise ControlInputError("accession must be non-null strings")
    if x.accession.duplicated().any():
        raise ControlInputError(f"duplicate accession rows: {sorted(x.accession[x.accession.duplicated()])[:5]}")
    if not pd.api.types.is_float_dtype(x.sue):
        raise ControlInputError("sue must be float")
    if np.isinf(x.sue).any():
        raise ControlInputError("sue has +/-inf")
    kt = x.xbrl_knowledge_time_utc
    if not isinstance(kt.dtype, pd.DatetimeTZDtype) or str(kt.dt.tz) != "UTC":
        raise ControlInputError("xbrl_knowledge_time_utc must be tz-aware UTC")
    if kt[x.sue.notna()].isna().any():
        raise ControlInputError("finite sue with null xbrl_knowledge_time_utc")
    if "xbrl_accn" in cols and x.xbrl_accn.dropna().duplicated().any():
        raise ControlInputError("xbrl_accn reused by >1 event row (join grain)")
    e = ev.set_index("accession")
    unk = sorted(set(x.accession) - set(e.index))
    if unk:
        raise ControlInputError(f"{len(unk)} SUE accessions not in the pinned event table, e.g. {unk[:3]}")
    x["ev_acceptance_utc"] = x.accession.map(e.acceptance_utc)  # tz-aware UTC kept (no .values)
    if "cik" in cols and (x.cik.values != e.loc[x.accession, "cik"].values).any():
        raise ControlInputError("cik != event-table cik")
    if "symbol" in cols:
        ok = [s in _split_symbols(e.at[a, "index_symbols"]) for a, s in zip(x.accession, x.symbol)]
        if not all(ok):
            raise ControlInputError("symbol not among the event's index_symbols")
    early = x[kt < x.ev_acceptance_utc]
    if len(early):
        raise SemanticReviewNeeded(
            f"{len(early)} SUE knowledge times precede their 8-K acceptance, e.g. {list(early.accession[:3])}"
        )
    return x


def sue_sector_panel(
    sue: pd.DataFrame,
    ev: pd.DataFrame,
    cal: pd.DatetimeIndex | Sequence[pd.Timestamp],
    dates: Sequence[pd.Timestamp] | pd.DatetimeIndex,
    membership: pd.DataFrame,
    fm: pd.DataFrame,
) -> pd.DataFrame:
    """§5 SUE_{k,d} = mean over eligible sector-k firms of each firm's MOST RECENT SUE whose first-reported knowledge time is
    strictly before 09:25 ET of d (first-tradable session s <= d) and with s within the last 63 sessions (ages 0..62).
    Sector with eligible firms but no eligible SUE -> 0.0 (the only zero); no eligible firms -> NaN. Input row order is
    irrelevant (selection by knowledge time). Two usable rows for one firm at the same knowledge time -> raise."""
    cal = _sessions(cal)
    pos = {d: i for i, d in enumerate(cal)}
    ev = validate_events(ev, cal)
    x = validate_sue(sue, ev)
    x = x[x.sue.notna()].copy()
    x["s_pos"] = first_session_after(x.xbrl_knowledge_time_utc, cal)
    x = x[x.s_pos >= 0]  # knowledge after the last cutoff: never visible
    diag = {"events_no_eligible_symbol": 0, "events_cik_fallback_used": 0, "events_unattributed": 0}
    evi = ev.set_index("accession")
    firms: list[str | None] = []
    for a in x.accession:
        r = evi.loc[a]
        f = event_firms(_EvRow(a, r.index_symbols, r.cik), fm, diag)
        firms.append(next(iter(f)) if f else None)
    x["firm"] = firms
    x = x[x.firm.notna()]
    if x.duplicated(["firm", "xbrl_knowledge_time_utc"]).any():
        raise ControlInputError("two SUE rows for one firm at one knowledge time")
    if (
        "fiscal_period_end" in x.columns
        and x.dropna(subset=["fiscal_period_end"]).duplicated(["firm", "fiscal_period_end"]).any()
    ):
        raise ControlInputError("(firm, fiscal_period_end) repeated: first-reported values only")
    x = x.sort_values(["firm", "xbrl_knowledge_time_utc"])
    by_firm = {f: g for f, g in x.groupby("firm")}
    elig = eligible_firms(dates, membership, fm)
    rows: dict[pd.Timestamp, dict[Any, float]] = {}
    for d in _sessions(dates):
        if d not in pos:
            raise ControlInputError(f"formation date {d.date()} not a calendar session")
        i = pos[d]
        row: dict[Any, float] = {}
        for k, fs in elig[d].items():
            if not fs:
                continue
            vals = []
            for f in fs:
                g = by_firm.get(f)
                if g is None:
                    continue
                g = g[(g.s_pos <= i) & (g.s_pos >= i - SUE_LOOKBACK)]
                if len(g):
                    vals.append(float(g.sue.iloc[-1]))  # most recent knowledge time
            row[k] = float(np.mean(vals)) if vals else 0.0
        rows[d] = row
    out = pd.DataFrame.from_dict(rows, orient="index").reindex(columns=sorted(set(fm.sector))).sort_index()
    out.attrs["diag"] = diag
    return out


def sue_not_public_share(
    sue: pd.DataFrame, ev: pd.DataFrame, cal: pd.DatetimeIndex | Sequence[pd.Timestamp], d: object
) -> float:
    """§5 report: share of in_sp500 8-K 2.02 events with s(tau) in [d-5, d] whose own SUE row (same accession) was not yet
    visible at d (absent, NaN, or first-tradable session after d). Diagnostic only."""
    cal = _sessions(cal)
    i = cast(int, cal.get_loc(pd.Timestamp(cast(Any, d))))
    ev = validate_events(ev, cal)
    w = ev[ev.in_sp500 & (ev.s_pos >= 0) & (ev.s_pos <= i) & (ev.s_pos >= i - ANN_LOOKBACK)]
    if not len(w):
        return np.nan
    x = validate_sue(sue, ev)
    x = x[x.sue.notna()]
    sp = dict(zip(x.accession, first_session_after(x.xbrl_knowledge_time_utc, cal)))
    return float(np.mean([not (a in sp and 0 <= sp[a] <= i) for a in w.accession]))


def on_primary_eligibility(L: pd.DataFrame, X: pd.DataFrame, name: str) -> pd.DataFrame:
    """§5 'same eligible sectors': restrict control X to the cells where the primary L is eligible. A control that is
    undefined where L is eligible RAISES (CONTROL_MISSING_POLICY is None): no zero-fill, no silent drop."""
    Xa = X.reindex(index=L.index, columns=L.columns).where(L.notna())
    gap = L.notna() & Xa.isna()
    if gap.values.any() and CONTROL_MISSING_POLICY is None:
        raise ControlInputError(
            f"{name}: undefined on {int(gap.values.sum())} primary-eligible sector-days; needs a decision"
        )
    return Xa


def leg_difference(X: pd.DataFrame, cohorts: Mapping[Any, tuple[Sequence[Any], Sequence[Any]]]) -> pd.Series:
    """Long-minus-short difference of a control over a formed cohort: cohorts = {d: (long_sectors, short_sectors)}
    (from the §4 primary). Days with no formed cohort (< min_sectors eligible) are absent, not zero."""
    out: dict[Any, Any] = {}
    for d, (lo, sh) in cohorts.items():
        a, b = X.loc[d, list(lo)], X.loc[d, list(sh)]
        if a.isna().any() or b.isna().any():
            raise ControlInputError(f"control undefined on a formed leg at {d}")
        out[d] = a.mean() - b.mean()  # no NaN-skipping means
    return pd.Series(out, dtype=float)


def load_events() -> pd.DataFrame:
    _require_strict()
    if sha(EVENTS_PATH) != EVENTS_SHA:
        raise ControlInputError("event table hash != pinned v1")
    return pd.read_parquet(EVENTS_PATH, columns=EVENT_COLS)


def load_sue() -> pd.DataFrame:
    _require_strict()
    if SUE_SHA is None or not os.path.exists(SUE_PATH) or sha(SUE_PATH) != SUE_SHA:
        raise ControlInputError("SUE table absent or unpinned")
    return pd.read_parquet(SUE_PATH)


def controls(
    bars: Mapping[str, pd.DataFrame],
    cal: pd.DatetimeIndex | Sequence[pd.Timestamp],
    dates: Sequence[pd.Timestamp] | pd.DatetimeIndex,
) -> dict[str, pd.DataFrame]:
    """§5 controls as panels (formation date x sector): REV5, MOM12_1 (sector ETF opens; returned only after strict
    checks), SUE, ANNSHARE. Ranking/simulation reuse §4 (CONTROL_LONG_HIGH, on_primary_eligibility, leg_difference)."""
    _require_strict()
    cal = _sessions(cal)
    inv = {v: k for k, v in ETFS.items()}
    o = pd.DataFrame({t: bars[t].open for t in ETFS.values()}).reindex(cal).rename(columns=inv)
    rev5 = (o / o.shift(5) - 1).reindex(cast(Any, dates))  # open(d-5) -> open(d)
    mom = (o.shift(21) / o.shift(252) - 1).reindex(cast(Any, dates))  # open(d-252) -> open(d-21)
    m, fm = dd.membership(), firm_map(dd.universe())
    ev = load_events()
    return dict(
        REV5=rev5,
        MOM12_1=mom,
        ANNSHARE=annshare_panel(ev, cal, dates, m, fm),
        SUE=sue_sector_panel(load_sue(), ev, cal, dates, m, fm),
    )


def main() -> None:
    global _STRICT_OK
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        check(strict=False)
        return  # hashes/metadata only: no prices, calendars, events, SUE, controls
    _STRICT_OK = bool(check(strict=True))
    raise SystemExit(
        "prereg_run: §5 controls are wired (controls()); the §6-§8 gate assembly / RUNLOG step is not yet "
        "written, so this DRAFT stops here by design. Nothing was computed."
    )


if __name__ == "__main__":
    main()
