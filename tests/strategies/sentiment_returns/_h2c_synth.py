"""Synthetic H2-C world: weekday sessions, a small universe, quarterly earnings and transcripts. No real data."""

from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from quant_research.strategies.sentiment_returns.h2c.config import H2CParams, params_from_dict

SYMS = [f"S{i:02d}" for i in range(8)]


def weekdays(lo: str, hi: str) -> list[str]:
    d, e, out = dt.date.fromisoformat(lo), dt.date.fromisoformat(hi), []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(1)
    return out


def params(**over: object) -> H2CParams:
    d = dict(
        universe=SYMS,
        hedge="HEDGE",
        beta_n=20,
        h0=1,
        h1=5,
        lag=100,
        nprior_max=4,
        nprior_min=2,
        tone_min=3,
        q_min_events=4,
        quantile_div=4,
        partitions=dict(
            T=dict(
                lo="2018-01-01",
                hi="2020-12-31",
                score_lo="2019-01-01",
                scored_years=[2019, 2020],
                g0_min_quarters=6,
                purge_window=["2020-11-01", "2020-12-31"],
                purge_boundary="2020",
            )
        ),
    )
    d.update(over)
    return params_from_dict(d)


def dev_params(**over: object) -> H2CParams:
    """``params()`` with partition T shifted to a DEV-style 2014-01-01..2016-12-31 (scored 2015-2016)."""
    d: dict[str, object] = dict(
        partitions=dict(
            T=dict(
                lo="2014-01-01",
                hi="2016-12-31",
                score_lo="2015-01-01",
                scored_years=[2015, 2016],
                g0_min_quarters=6,
                purge_window=["2016-11-01", "2016-12-31"],
                purge_boundary="2016",
            )
        )
    )
    d.update(over)
    return params(**d)


def world(seed: int = 7, planted: float = 0.0, dev: bool = False) -> tuple[H2CParams, dict[str, Any]]:
    """Returns kwargs for run_h2c plus the planted tones. ``planted`` adds planted * surprise to each event's
    post-day0 cumulative return (spread over h1 sessions).

    ``dev=True``: the same world four years earlier, DEV-style (partition 2014-01-01..2016-12-31). Calendar and price
    sessions before the partition are cut to the last ``beta_n + 1`` (the beta warm-up, late 2013), and each symbol
    gets an extra fiscal-2013 Q4 row (fiscalDateEnding 2013-12-31, reported in January 2014) with a transcript."""
    rng = np.random.default_rng(seed)
    sh = -4 if dev else 0
    p = dev_params() if dev else params()
    lo, end = f"{2018 + sh}-01-01", f"{2020 + sh}-12-31"
    cal = weekdays(f"{2017 + sh}-10-02", f"{2021 + sh}-03-31")
    if dev:
        pre = [d for d in cal if d < lo]
        cal = pre[-(p.beta_n + 1) :] + [d for d in cal if d >= lo]
    px_sess = [d for d in cal if d <= end]
    T, N = len(px_sess), len(SYMS)
    mkt = rng.normal(0, 0.01, T)
    betas = rng.uniform(0.5, 1.5, N)
    R = mkt[:, None] * betas[None, :] + rng.normal(0, 0.01, (T, N))
    earnings, keys, tx, tones = [], [], {}, {}
    sidx = {d: i for i, d in enumerate(px_sess)}
    for j, s in enumerate(SYMS):
        hist: list[float] = []
        yq = [(y + sh, q) for y in (2018, 2019, 2020) for q in (1, 2, 3, 4)]
        if dev:
            yq.insert(0, (2013, 4))
        for y, q in yq:
            fde = dt.date(y, 3 * q, 30 if 3 * q in (6, 9) else 31)
            rd = fde + dt.timedelta(20 + j)
            late = rd > dt.date(2020 + sh, 12, 31)
            if late:
                rd = dt.date(2020 + sh, 12, 1)  # in the purge window, no transcript (reported before quarter end)
            rt = "post-market" if (j + q) % 2 else "pre-market"
            tone = float(rng.normal(0, 1))
            earnings.append(
                dict(
                    symbol=s,
                    fiscalDateEnding=fde.isoformat(),
                    reportedDate=rd.isoformat(),
                    reportedEPS="1",
                    estimatedEPS="1",
                    surprise="0",
                    surprisePercentage="0",
                    reportTime=rt,
                )
            )
            lab = f"{y}Q{q}"
            if late:
                continue
            keys.append((s, lab))
            ents = [
                dict(content="x", sentiment=str(tone + rng.normal(0, 1e-3)), speaker="a", title="b") for _ in range(5)
            ]
            ents.append(dict(content="x", sentiment="n/a", speaker="a", title="b"))
            tx[(s, lab)] = dict(symbol=s, quarter=lab, transcript=ents)
            tones[(s, lab)] = tone
            sur = tone - float(np.mean(hist[-4:])) if len(hist) >= 2 else 0.0
            hist.append(tone)
            d0 = rd.isoformat() if rt == "pre-market" else (rd + dt.timedelta(1)).isoformat()
            while d0 not in sidx and d0 <= px_sess[-1]:
                d0 = (dt.date.fromisoformat(d0) + dt.timedelta(1)).isoformat()
            if d0 in sidx:
                i0 = sidx[d0]
                R[i0 + 2 : i0 + 2 + p.h1 - 1, j] += planted * sur / (p.h1 - 1)
    hedge_px = 100 * np.cumprod(1 + mkt)
    PX = 100 * np.cumprod(1 + R, axis=0)
    rows = [
        dict(symbol=s, date=d, adjusted_close=float(PX[i, j]))
        for j, s in enumerate(SYMS)
        for i, d in enumerate(px_sess)
    ]
    rows += [dict(symbol="HEDGE", date=d, adjusted_close=float(hedge_px[i])) for i, d in enumerate(px_sess)]
    kw = dict(
        calendar_sessions=cal,
        price_sessions=px_sess,
        price_rows=rows,
        earnings_rows=earnings,
        transcript_keys=keys,
        load_transcript=lambda s, lab: tx[(s, lab)],
        fye_months=dict.fromkeys(SYMS, 12),
    )
    return p, kw
