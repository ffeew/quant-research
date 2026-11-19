"""Pre-2016 daily history for the macro/ETF trend sleeve (Maya) from a FREE PUBLIC source (Yahoo Finance via yfinance),
because Alpaca SIP daily bars start 2016-01-04 (verified: start=2005 returns first bar 2016-01-04; IEX returns nothing).

Outputs (never mixed silently with Alpaca data):
  bars/daily/extended/yahoo/<SYM>.parquet        raw Yahoo rows (source='yahoo_finance_yfinance'), from 2005-01-01 or inception
  bars/daily/extended/etf_total_return_spliced.parquet
        session_date, symbol, ret_total, source ('yahoo' before the first Alpaca return, 'alpaca_sip' after), tr_index,
        splice_ok (validation gate passed). If the gate fails, Yahoo rows are still stored but splice_ok=False.
  qa/extended_overlap_validation_<date>.md/.parquet   overlap (2016+) Yahoo vs Alpaca ret_total_best: corr, mean diff ...
Yahoo 'Adj Close' = split+dividend adjusted (CRSP-style multiplicative), RESTATED retroactively -> not point-in-time.
Idempotent: full re-download each run (a few seconds per ticker)."""

from __future__ import annotations

import datetime as dt
import warnings
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import DATA, log, update_manifest, write_parquet

warnings.filterwarnings("ignore")
import yfinance as yf

TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "EFA",
    "EWJ",
    "EWG",
    "EWU",
    "EEM",
    "SHY",
    "IEF",
    "TLT",
    "GLD",
    "SLV",
    "USO",
    "UNG",
    "DBA",
    "DBC",
    "UUP",
    "FXE",
    "FXY",
    "FXB",
    "FXA",
    "FXC",
    "EWZ",
    "FXI",
    "INDA",
    "EWY",
    "EWT",
    "EWA",
    "EWC",
    "AGG",
    "BND",
    "TIP",
    "LQD",
    "HYG",
    "BWX",
    "CPER",
    "BIL",
]
OUT = DATA / "bars" / "daily" / "extended"
GATE = {
    "min_corr": 0.99,
    "max_abs_mean_diff_bps": 1.0,
    "max_median_abs_diff_bps": 5.0,
    "or_p99_abs_diff_bps_le": 5.0,
}  # low-vol series (T-bills): corr is noise-dominated, so tight p99 agreement also passes


def fetch(sym: str) -> pd.DataFrame | None:
    h = yf.Ticker(sym).history(start="2005-01-01", auto_adjust=False, actions=True, raise_errors=True)
    if h.empty:
        return None
    h = h.reset_index().rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close_split_adj",
            "Adj Close": "adj_close",
            "Volume": "volume",
            "Dividends": "dividend",
            "Stock Splits": "split",
            "Capital Gains": "capital_gains",
        }
    )
    h["session_date"] = pd.to_datetime(h["date"]).dt.tz_localize(None).dt.date
    h = h.drop(columns="date")
    h.insert(0, "symbol", sym)
    h["source"] = "yahoo_finance_yfinance"
    h["fetched_at_utc"] = pd.Timestamp.now(tz="UTC")
    return h  # type: ignore[no-any-return]  # yfinance history frame


def main() -> None:
    (OUT / "yahoo").mkdir(parents=True, exist_ok=True)
    tr = pd.read_parquet(
        DATA / "bars/daily/total_return/daily_total_return.parquet",
        columns=["symbol", "session_date", "ret_total_best"],
    )
    tr = tr[tr.symbol.isin(TICKERS)]
    val: list[dict[str, Any]] = []
    spliced: list[pd.DataFrame] = []
    fails: dict[str, str] = {}
    for s in TICKERS:
        try:
            h = fetch(s)
        except Exception as e:
            fails[s] = repr(e)[:200]
            log.warning("%s yahoo failed: %s", s, fails[s])
            continue
        if h is None:
            fails[s] = "empty"
            continue
        write_parquet(h, OUT / "yahoo" / f"{s}.parquet")
        y = h[["session_date", "adj_close"]].dropna().sort_values("session_date")
        y["ret_y"] = y["adj_close"].pct_change()
        a = tr[tr.symbol == s][["session_date", "ret_total_best"]].dropna()
        m = y.merge(a, on="session_date").dropna()
        d = (m["ret_y"] - m["ret_total_best"]) * 1e4
        cum_y = float((1 + m["ret_y"]).prod()) - 1  # type: ignore[arg-type]  # Series.prod is a numeric scalar
        cum_a = float((1 + m["ret_total_best"]).prod()) - 1  # type: ignore[arg-type]  # Series.prod is a numeric scalar
        yrs = len(m) / 252
        r: dict[str, Any] = {
            "symbol": s,
            "yahoo_inception": y["session_date"].min(),
            "yahoo_rows": len(y),
            "overlap_days": len(m),
            "corr": m["ret_y"].corr(m["ret_total_best"]),
            "mean_diff_bps": d.mean(),
            "median_abs_diff_bps": d.abs().median(),
            "p99_abs_diff_bps": d.abs().quantile(0.99),
            "days_gt_50bps": int((d.abs() > 50).sum()),
            "ann_tr_yahoo": (1 + cum_y) ** (1 / yrs) - 1,
            "ann_tr_alpaca": (1 + cum_a) ** (1 / yrs) - 1,
        }
        r["ann_diff_bps"] = (r["ann_tr_yahoo"] - r["ann_tr_alpaca"]) * 1e4
        ex = m[~pd.to_datetime(m["session_date"]).dt.strftime("%Y-%m").eq("2020-03")]
        r["corr_ex_2020_03"] = ex["ret_y"].corr(ex["ret_total_best"])
        tight = (
            r["p99_abs_diff_bps"] <= GATE["or_p99_abs_diff_bps_le"]
        )  # Mar-2020 closing-print dislocations dominate some bond ETFs
        r["splice_ok_ex_2020_03"] = bool(
            (r["corr_ex_2020_03"] >= GATE["min_corr"] or tight)
            and abs(r["mean_diff_bps"]) <= GATE["max_abs_mean_diff_bps"]
            and r["median_abs_diff_bps"] <= GATE["max_median_abs_diff_bps"]
        )
        r["splice_ok"] = bool(
            (r["corr"] >= GATE["min_corr"] or tight)
            and abs(r["mean_diff_bps"]) <= GATE["max_abs_mean_diff_bps"]
            and r["median_abs_diff_bps"] <= GATE["max_median_abs_diff_bps"]
        )
        r["pre2016_years"] = (
            (pd.Timestamp(a["session_date"].min()) - pd.Timestamp(r["yahoo_inception"])).days / 365.25
            if len(a)
            else None
        )
        val.append(r)
        first_a = a["session_date"].min()
        pre = (
            y[y.session_date < first_a][["session_date", "ret_y"]]
            .rename(columns={"ret_y": "ret_total"})
            .assign(source="yahoo")
        )
        post = a.rename(columns={"ret_total_best": "ret_total"}).assign(source="alpaca_sip")
        sp = pd.concat([pre, post]).dropna(subset=["ret_total"]).sort_values("session_date")
        sp["symbol"] = s
        sp["splice_ok"] = r["splice_ok"]
        sp["splice_ok_ex_2020_03"] = r["splice_ok_ex_2020_03"]
        sp["tr_index"] = (1 + sp["ret_total"]).cumprod()
        spliced.append(sp)
        log.info(
            "%s inception %s corr %.5f mean %.2fbp ok=%s",
            s,
            r["yahoo_inception"],
            r["corr"],
            r["mean_diff_bps"],
            r["splice_ok"],
        )
    v = pd.DataFrame(val)
    today = dt.date.today().isoformat()
    write_parquet(v, DATA / "qa" / f"extended_overlap_validation_{today}.parquet")
    write_parquet(
        pd.concat(spliced)[
            ["session_date", "symbol", "ret_total", "source", "tr_index", "splice_ok", "splice_ok_ex_2020_03"]
        ].reset_index(drop=True),
        OUT / "etf_total_return_spliced.parquet",
    )
    with open(DATA / "qa" / f"extended_overlap_validation_{today}.md", "w") as f:
        f.write(
            f"# Yahoo (yfinance Adj Close) vs Alpaca SIP ret_total_best, overlap 2016-01-05..; built {today}\n\n"
            f"Gate for splice_ok: {GATE}. Failures: {fails or 'none'}\n\n" + v.round(5).to_markdown(index=False) + "\n"
        )
    update_manifest(
        "extended_bars",
        {
            "source": "yahoo_finance_yfinance",
            "tickers": len(TICKERS),
            "ok": int(v.splice_ok.sum()),
            "failed": fails,
            "not_spliced": v.loc[~v.splice_ok, "symbol"].tolist(),
        },
    )


if __name__ == "__main__":
    main()
