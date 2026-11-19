"""Loaders for public factor data saved in ../_public_data (Ken French library, AQR BAB). Dave."""

from __future__ import annotations

import io
import pathlib
from typing import cast

import pandas as pd

D = pathlib.Path(__file__).resolve().parent.parent / "_public_data"


def _ff_block(fname: str, first_header_contains: str = ",") -> pd.DataFrame:
    """Read the first (monthly or daily, value-weighted) block of a Ken French CSV. Returns decimal returns."""
    lines = (D / fname).read_text(errors="ignore").splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().startswith(",") or l.strip().lower().startswith(",mkt"))
    out = [lines[start]]
    for l in lines[start + 1 :]:
        s = l.strip()
        if not s or not s[0].isdigit():
            break
        tok = s.split(",")[0].strip()
        if len(tok) not in (6, 8):  # annual block (YYYY) -> stop
            break
        out.append(l)
    df = pd.read_csv(io.StringIO("\n".join(out)), index_col=0)
    df.columns = [c.strip() for c in df.columns]
    idx = df.index.astype(str).str.strip()
    fmtd = "%Y%m%d" if len(idx[0]) == 8 else "%Y%m"
    df.index = pd.to_datetime(idx, format=fmtd)
    if fmtd == "%Y%m":
        df.index = df.index + pd.offsets.MonthEnd(0)
    import numpy as np

    df = df.apply(pd.to_numeric, errors="coerce").astype(float).replace([-99.99, -999.0], np.nan)
    return cast(pd.DataFrame, df / 100.0)


def ff3_monthly() -> pd.DataFrame:
    return _ff_block("F-F_Research_Data_Factors.csv")


def ff3_daily() -> pd.DataFrame:
    return _ff_block("F-F_Research_Data_Factors_daily.csv")


def ff5_monthly() -> pd.DataFrame:
    return _ff_block("F-F_Research_Data_5_Factors_2x3.csv")


def umd_monthly() -> pd.DataFrame:
    return _ff_block("F-F_Momentum_Factor.csv")


def strev_monthly() -> pd.DataFrame:
    return _ff_block("F-F_ST_Reversal_Factor.csv")


def ind49_vw_monthly() -> pd.DataFrame:
    return _ff_block("49_Industry_Portfolios.csv")  # first block = value-weighted monthly


def bab_usa_monthly() -> pd.Series:
    df = pd.read_excel(D / "AQR_BAB_Equity_Factors_Monthly.xlsx", "BAB Factors", header=18)
    df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y", errors="coerce")
    s = df.set_index("DATE")["USA"].dropna().astype(float)
    s.index = s.index + pd.offsets.MonthEnd(0)
    return s
