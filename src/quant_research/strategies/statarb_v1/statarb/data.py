"""Reusable panel loader for stat-arb research. READ-ONLY access to $QR_DATA_DIR (Data Engineer dataset).

load_panel(source="cio_data") -> Panel with wide DataFrames (index = session date, columns = symbol):
  open, close (split+div adjusted), dollar_vol (raw close*raw volume, SIP consolidated), member (PIT S&P 500 bool),
  sector (Series symbol->GICS sector; former members imputed, see impute_sectors), etf_close (sector ETFs + SPY).
Only source="cio_data" (Dmitri's store) is allowed (desk rule #5, 2026-10-30). The old IEX fallbacks
(statarb/data/daily_bars.json, $QR_DESK_DIR/data.json) are retired; live data only via data/lib/desk_data_client.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pandas as pd

from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)

CIO = Path(f"{_QR.DATA_DIR}")
SECTOR_ETF = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
ETFS = [*list(SECTOR_ETF.values()), "SPY"]


@dataclass
class Panel:
    open: pd.DataFrame
    close: pd.DataFrame
    dollar_vol: pd.DataFrame
    member: pd.DataFrame
    sector: pd.Series
    etf_close: pd.DataFrame
    etf_open: pd.DataFrame
    source: str
    notes: list[str] = field(default_factory=list)
    bad: pd.DataFrame | None = None  # True on (date, symbol) whose close-to-close return is a flagged jump

    @property
    def ret_cc(self) -> pd.DataFrame:  # close(t-1)->close(t), aligned at t; flagged jumps -> NaN
        r = self.close.pct_change(fill_method=None)
        return r.mask(self.bad) if self.bad is not None else r

    @property
    def px_clean(
        self,
    ) -> pd.DataFrame:  # price index rebuilt from jump-filtered returns (safe for level-based models on raw bars)
        r = self.ret_cc
        idx = (1 + r.fillna(0.0)).cumprod()
        return idx.where(self.close.notna())


def _read_dir(d: Path, cols: Sequence[str]) -> pd.DataFrame:
    frames = []
    for f in sorted(d.glob("*.parquet")):
        frames.append(pd.read_parquet(f, columns=["symbol", "session_date", *cols]))
    df = pd.concat(frames, ignore_index=True)
    df["session_date"] = pd.to_datetime(df["session_date"])
    return df


def _wide(df: pd.DataFrame, col: str) -> pd.DataFrame:
    return df.pivot_table(index="session_date", columns="symbol", values=col, aggfunc="last").sort_index()


def _membership(dates: pd.Index, symbols: pd.Index) -> pd.DataFrame:
    mem = pd.read_parquet(CIO / "universe" / "sp500_membership.parquet")
    m = pd.DataFrame(False, index=dates, columns=symbols)
    for _, r in mem.iterrows():
        s = r["symbol"]
        if s not in m.columns:
            continue
        st = pd.Timestamp(r["start_date"]) if r["start_date"] is not None and pd.notna(r["start_date"]) else dates[0]
        en = (
            pd.Timestamp(r["end_date"])
            if r["end_date"] is not None and pd.notna(r["end_date"])
            else cast(pd.Timestamp, dates[-1]) + pd.Timedelta(days=1)
        )
        m.loc[(m.index >= st) & (m.index < en), s] = True
    return m


def impute_sectors(sector: pd.Series, ret: pd.DataFrame, etf_ret: pd.DataFrame, member: pd.DataFrame) -> pd.Series:
    """GICS is only known for CURRENT members. Former members get the sector whose ETF has the highest
    return correlation over the stock's own membership period (data-driven; a classification shortcut,
    flagged as caveat; uses only that stock's own history, not future P&L)."""
    sec = sector.copy()
    etf_by = {v: k for k, v in SECTOR_ETF.items()}
    for s in ret.columns:
        if s in sec.index and isinstance(sec[s], str):
            continue
        mm = member.get(s, None)
        r = ret[s][mm] if mm is not None else ret[s]
        best: str | None = None
        bc = -2.0
        for e in SECTOR_ETF.values():
            if e not in etf_ret:
                continue
            x = pd.concat([r, etf_ret[e]], axis=1).dropna()
            if len(x) < 60:
                continue
            c = cast(float, x.corr().iloc[0, 1])
            if c > bc:
                best, bc = etf_by[e], c
        if best:
            sec[s] = best
    return sec


def flag_jumps(
    close: pd.DataFrame,
    abs_ret: float = 0.40,
    ratios: Sequence[float] = (2, 3, 4, 5, 10),
    tol: float = 0.03,
) -> pd.DataFrame:
    """Flag split-sized or implausible 1-day moves: |ret| > abs_ret, or price ratio within tol of a split ratio
    (either direction) when |ret| > 20%."""
    rel = close / close.shift(1)
    bad = (rel - 1).abs() > abs_ret
    for r in ratios:
        for x in (r, 1.0 / r):
            bad |= ((rel / x - 1).abs() < tol) & ((rel - 1).abs() > 0.2)
    return bad.fillna(False)


def load_panel(
    source: str = "cio_data",
    start: str = "2016-01-01",
    end: str | None = None,
    price_set: str = "adjusted",
    jump_filter: bool = True,
    jump_abs_ret: float = 0.40,
    split_ratios: Sequence[float] = (2, 3, 4, 5, 10),
    split_tol: float = 0.03,
) -> Panel:
    notes: list[str] = []
    if source == "cio_data":
        raw = _read_dir(CIO / "bars" / "daily" / "raw", ["open", "close", "volume"])
        if price_set == "adjusted":
            adj = _read_dir(CIO / "bars" / "daily" / "adjusted", ["open", "close"])
            o, c = _wide(adj, "open"), _wide(adj, "close")
        elif price_set == "total_return":
            tr = pd.read_parquet(
                CIO / "bars" / "daily" / "total_return" / "daily_total_return.parquet",
                columns=["symbol", "session_date", "open_adj", "close_adj", "tr_index_best"],
            )
            tr["session_date"] = pd.to_datetime(tr["session_date"])
            c = _wide(tr, "tr_index_best")
            o = c * _wide(tr, "open_adj") / _wide(tr, "close_adj")  # open on the TR scale
        elif price_set == "raw":
            o, c = _wide(raw, "open"), _wide(raw, "close")
        else:
            raise ValueError(price_set)
        dv = _wide(raw.assign(dv=raw["close"] * raw["volume"]), "dv")
        notes.append(
            f"cio_data: Alpaca SIP daily bars, price_set={price_set}; $ADV from raw close*raw volume; PIT S&P500 membership"
        )
        cur = pd.read_parquet(CIO / "universe" / "universe.parquet").set_index("symbol")[
            "gics_sector"
        ]  # current GICS snapshot
    else:
        raise ValueError(
            f"source={source!r} is retired (desk rule #5, 2026-10-30): history must come from Dmitri's store "
            f"(source='cio_data'); statarb/data/daily_bars.json and {_QR.DESK_DIR}/data.json are deprecated for research."
        )
    c = c.loc[start:end]
    o = o.reindex_like(c)
    dv = dv.reindex_like(c)
    etf_cols = [e for e in ETFS if e in c.columns]
    etf_close, etf_open = c[etf_cols], o[etf_cols]
    nonetf = [s for s in c.columns if s not in ETFS]
    try:
        u = pd.read_parquet(CIO / "universe" / "universe.parquet")
        etf_like = set(u.loc[u.role == "etf", "symbol"])
    except Exception:
        etf_like = set()
    nonetf = [s for s in nonetf if s not in etf_like and "/" not in s]
    c, o, dv = c[nonetf], o[nonetf], dv[nonetf]
    if source == "cio_data":
        member = _membership(c.index, c.columns)
    else:
        member = c.notna()
        notes.append("membership = data availability (survivorship-biased: today's large caps only)")
    member &= c.notna()
    bad = (
        flag_jumps(c, jump_abs_ret, split_ratios, split_tol)
        if jump_filter
        else pd.DataFrame(False, index=c.index, columns=c.columns)
    )
    notes.append(
        f"jump filter={'on' if jump_filter else 'off'}: {int((bad & member).sum().sum())} member-days flagged (|ret|>{jump_abs_ret:.0%} or split-ratio-sized); excluded from signals and P&L"
    )
    sector = cur.reindex(c.columns)
    n_missing = sector.isna().sum()
    sector = impute_sectors(
        sector, c.pct_change(fill_method=None).mask(bad), etf_close.pct_change(fill_method=None), member
    )
    notes.append(f"sector: current GICS; {n_missing} symbols (former members) imputed by max-corr sector ETF")
    return Panel(o, c, dv, member, sector, etf_close, etf_open, source, notes, bad)
