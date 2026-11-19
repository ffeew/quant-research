"""Pinned loaders. Each verifies its pin before opening; parquet reads use read-time date filters."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import Any

import pandas as pd

from .config import HarnessConfig
from .guards import (
    Blocked,
    assert_no_rows_after,
    load_final_list,
    read_pinned_bytes,
    verify_pinned_file,
    verify_sums_line,
)
from .splits import EMBARGO1, LOAD0


def _pq() -> Any:
    import pyarrow.parquet as pq  # local import

    return pq


def load_bars_tr(cfg: HarnessConfig, filter_end: date, load_start: date = LOAD0) -> dict[str, pd.DataFrame]:
    """PRIMARY returns: total return via the DEV-only cut. The cut must be listed in its pinned SUMS
    and hold no row after the embargo end; rows past filter_end never survive."""
    if filter_end > EMBARGO1:
        raise Blocked("REFUSING: TR source is a DEV-only cut; no holdout TR source is bound.")
    cut, sums = cfg.pin("tr_dev_cut"), cfg.pin("tr_dev_cut_sums")
    verify_sums_line(sums.path, sums.sha256, cut.path, cut.sha256)
    p = verify_pinned_file("tr_dev_cut", cut.path, cut.sha256)
    pq = _pq()
    if pq.read_table(p, columns=["session_date"], filters=[("session_date", ">", EMBARGO1)]).num_rows:
        raise Blocked("REFUSING: TR DEV cut holds rows after the embargo end (not a DEV-only cut).")
    tr = pq.read_table(
        p,
        columns=["symbol", "session_date", "close_raw", "volume_raw", "ret_total_best", "tr_index_best"],
        filters=[("session_date", "<=", filter_end)],
    ).to_pandas()
    tr["session_date"] = pd.to_datetime(tr["session_date"])
    tr = tr[(tr.session_date >= pd.Timestamp(load_start)) & (tr.session_date <= pd.Timestamp(filter_end))]
    assert_no_rows_after(tr.session_date, filter_end, "TR bars")
    return bars_from_long(tr)


def bars_from_long(tr: pd.DataFrame) -> dict[str, pd.DataFrame]:
    def piv(col: str) -> pd.DataFrame:
        return tr.pivot(index="session_date", columns="symbol", values=col)

    return {"R": piv("ret_total_best"), "TRI": piv("tr_index_best"), "PX": piv("close_raw"), "VOL": piv("volume_raw")}


def load_earnings(cfg: HarnessConfig, filter_end: date) -> pd.DataFrame:
    if filter_end > EMBARGO1:
        raise Blocked("REFUSING: earnings source is a DEV-only cut; no holdout source is bound.")
    pin = cfg.pin("earnings_dev_cut")
    p = verify_pinned_file("earnings_dev_cut", pin.path, pin.sha256)
    ev: pd.DataFrame = _pq().read_table(p, filters=[("announce_date_et", "<=", filter_end)]).to_pandas()
    return ev


def load_gics(cfg: HarnessConfig) -> tuple[pd.Series, pd.Series]:
    pin = cfg.pin("universe_gics")
    uni = _pq().read_table(verify_pinned_file("universe_gics", pin.path, pin.sha256)).to_pandas()
    if not {"symbol", "gics_sub_industry", "gics_sector"} <= set(uni.columns):
        raise Blocked("REFUSING: universe input lacks symbol/gics_sub_industry/gics_sector.")
    u = uni.set_index("symbol")
    return u.gics_sub_industry.dropna(), u.gics_sector.dropna()


def load_parquet_pinned(cfg: HarnessConfig, name: str) -> pd.DataFrame:
    pin = cfg.pin(name)
    df: pd.DataFrame = _pq().read_table(verify_pinned_file(name, pin.path, pin.sha256)).to_pandas()
    return df


def load_json_pinned(cfg: HarnessConfig, name: str) -> Any:
    pin = cfg.pin(name)
    return json.loads(read_pinned_bytes(name, pin.path, pin.sha256).decode("utf-8"))


def load_symbol_set(cfg: HarnessConfig, name: str, delimiter: str) -> set[str]:
    pin = cfg.pin(name)
    text = read_pinned_bytes(name, pin.path, pin.sha256).decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    if rows and "symbol" not in rows[0]:
        raise Blocked(f"REFUSING: input {name!r} has no symbol column.")
    return {r["symbol"] for r in rows}


def load_identity(cfg: HarnessConfig) -> dict[str, Any]:
    """Accepted identity basis (hash-only gate), then the identity list re-checked at use."""
    b = cfg.pin("identity_basis_sums")
    verify_pinned_file("identity_basis_sums", b.path, b.sha256)
    il = cfg.pin("identity_list")
    return load_final_list(il.path, il.sha256)


class FileAcquirerCloses:
    """Accepted acquirer closes from a pinned parquet; sessions from the XNYS calendar."""

    def __init__(self, cfg: HarnessConfig):
        pin = cfg.pin("acquirer_closes")
        p = verify_pinned_file("acquirer_closes", pin.path, pin.sha256)
        self._df = _pq().read_table(p, filters=[("session_date", "<=", EMBARGO1)]).to_pandas()
        self._df["session_date"] = pd.to_datetime(self._df["session_date"])

    @staticmethod
    def _guard(end: pd.Timestamp) -> None:
        if pd.Timestamp(end) > pd.Timestamp(EMBARGO1):
            raise Blocked("BLOCK H1: acquirer-close window reaches past the embargo end (no holdout rows).")

    def sessions(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        self._guard(end)
        import exchange_calendars as xcals

        s = xcals.get_calendar("XNYS").sessions_in_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize())
        return pd.DatetimeIndex(s.tz_localize(None) if s.tz is not None else s)

    def accepted_acquirer_closes(self, acquirer_id: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
        self._guard(end)
        d = self._df[
            (self._df["symbol"] == acquirer_id) & (self._df.session_date >= start) & (self._df.session_date <= end)
        ]
        return pd.Series(d["close"].astype(float).values, index=d.session_date, name=acquirer_id).sort_index()
