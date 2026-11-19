"""Stage 1: PIT S&P 500 member intervals (2015-01-01 onward) -> CIK segments, via Dmitri's ticker_cik_map.
Output: work/member_cik_segments.parquet, work/unmapped.parquet. Read-only on $QR_DESK_DIR/data."""

from __future__ import annotations

import itertools
import os

import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

D = f"{_QR.DATA_DIR}"
START = pd.Timestamp("2015-01-01")
TODAY = pd.Timestamp("2026-10-30")
SRC_RANK = {
    "manual_verified_edgar": 0,
    "alpaca_name_change": 1,
    "wikipedia_sp500_cik": 2,
    "sec_company_tickers": 3,
    "edgar_submissions": 4,
    "efts_name_search": 5,
}
CONF_RANK = {"high": 0, "medium": 1, "low": 2}
os.makedirs("work", exist_ok=True)


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    mem = pd.read_parquet(f"{D}/universe/sp500_membership.parquet")
    mem["s"] = pd.to_datetime(mem.start_date_filled)
    mem["e"] = pd.to_datetime(mem.end_date)  # [start, end)
    mem = mem[mem.e.isna() | (mem.e > START)].copy()
    mem["s_eff"] = mem.s.clip(lower=START)  # type: ignore[call-overload]  # lower bound is a session timestamp
    mem["e_eff"] = mem.e.fillna(TODAY + pd.Timedelta(days=1))
    ref = pd.read_parquet(f"{D}/reference/ticker_cik_map.parquet").dropna(subset=["cik"]).copy()
    ref["vf"] = pd.to_datetime(ref.valid_from)
    ref["vt"] = pd.to_datetime(ref.valid_to)
    ref["sr"] = ref.source.map(SRC_RANK).fillna(9)
    ref["cr"] = ref.confidence.map(CONF_RANK).fillna(9)
    # efts_name_search / manual_verified_edgar ranges are bar-store coverage (first..last Alpaca bar, from 2016-01-04),
    # not ticker-validity dates (Dmitri README s11), so they are treated as open; identity is checked in ee_validate.py.
    cov = ref.source.isin(["efts_name_search", "manual_verified_edgar"])
    ref.loc[cov, ["vf", "vt"]] = pd.NaT
    ref["dated"] = ref.vf.notna() | ref.vt.notna()
    return mem, ref


def segments(mem: pd.DataFrame, ref: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    out, unm = [], []
    for _, m in mem.iterrows():
        c = ref[ref.ticker == m.symbol]
        c = c[(c.vf.isna() | (c.vf < m.e_eff)) & (c.vt.isna() | (c.vt > m.s_eff))]
        if c.empty:
            unm.append(dict(symbol=m.symbol, start=m.s_eff, end=m.e_eff))
            continue
        bps = sorted({m.s_eff, m.e_eff} | {x for x in pd.concat([c.vf, c.vt]).dropna() if m.s_eff < x < m.e_eff})
        for a, b in itertools.pairwise(bps):
            v = c[(c.vf.isna() | (c.vf <= a)) & (c.vt.isna() | (c.vt > a))]
            if v.empty:
                unm.append(dict(symbol=m.symbol, start=a, end=b))
                continue
            # dated rows (explicit history) beat undated 'current' rows; then source, then confidence
            v = v.assign(nd=~v.dated).sort_values(["nd", "sr", "cr"])
            best = v.iloc[0]
            out.append(
                dict(
                    symbol=m.symbol,
                    seg_start=a,
                    seg_end=b,
                    cik=int(best.cik),
                    map_source=best.source,
                    map_confidence=best.confidence,
                    map_method=best.match_method,
                    n_cik_candidates=v.cik.nunique(),
                    alt_ciks=",".join(str(x) for x in sorted(set(v.cik.astype(int)) - {int(best.cik)})),
                )
            )
    return pd.DataFrame(out), pd.DataFrame(unm)


if __name__ == "__main__":
    mem, ref = load()
    seg, unm = segments(mem, ref)
    seg.to_parquet("work/member_cik_segments.parquet")
    unm.to_parquet("work/unmapped.parquet")
    print("member intervals", len(mem), "symbols", mem.symbol.nunique())
    print("segments", len(seg), "unique ciks", seg.cik.nunique(), "conflicts", (seg.n_cik_candidates > 1).sum())
    print("unmapped", len(unm), sorted(unm.symbol.unique()) if len(unm) else [])
    print(seg[seg.n_cik_candidates > 1].to_string())
