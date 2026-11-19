"""Derive daily total-return series from RAW bars + Alpaca corporate actions, validated against
Alpaca's adjustment=all bars.
  ret_price_t = close_t * split_ratio_t / close_{t-1} - 1            (split-adjusted price return)
  ret_total_t = (close_t + div_t) * split_ratio_t / close_{t-1} - 1  (cash dividend reinvested at ex-date close)
where split_ratio_t = new_rate/old_rate for splits with ex_date == t (product if several), div_t = sum of
cash dividend `rate` with ex_date == t (per post-split share; Alpaca rates are per share on ex-date).
tr_index = cumprod(1+ret_total) per symbol starting at 1.0.
alpaca_adj_ret = close_adj_t/close_adj_{t-1} - 1 from adjustment=all; abs_diff_bps = |ret_total - alpaca_adj_ret| in bps.
Spin-offs / mergers are NOT reinvested (flagged via `other_action` column) -> ret_total understates on spin-off ex-dates.
Output: data/bars/daily/total_return/daily_total_return.parquet (all symbols, one file) + validation summary in qa/.
Columns ret_total_best/tr_index_best = recommended (Alpaca adjusted close-to-close); tr_mismatch_gt50bps flags disagreement.
Fully recomputed each run (fast, local only)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import DATA, update_manifest, write_parquet
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)


def main() -> None:
    raw = pd.read_parquet(
        DATA / "bars/daily/raw", columns=["symbol", "session_date", "timestamp_utc", "close", "volume"]
    )
    adj = pd.read_parquet(
        DATA / "bars/daily/adjusted", columns=["symbol", "session_date", "close", "open", "high", "low", "volume"]
    )
    ca = pd.read_parquet(DATA / "corporate_actions/all_actions.parquet")
    spl = ca[ca.type.isin(["forward_splits", "reverse_splits", "unit_splits"])].copy()
    spl["r"] = spl.new_rate / spl.old_rate
    spl = spl.groupby(["symbol", "ex_date"]).r.prod().rename("split_ratio").reset_index()
    div = ca[ca.type == "cash_dividends"].groupby(["symbol", "ex_date"]).rate.sum().rename("div_cash").reset_index()
    spin = ca[ca.type.isin(["spin_offs"])].rename(columns={"source_symbol": "symbol_"})
    oth = set(zip(spin.get("symbol_", pd.Series(dtype=str)), spin.ex_date))
    df = raw.rename(columns={"close": "close_raw", "volume": "volume_raw"}).merge(
        adj.rename(
            columns={
                "close": "close_adj",
                "open": "open_adj",
                "high": "high_adj",
                "low": "low_adj",
                "volume": "volume_adj",
            }
        ),
        on=["symbol", "session_date"],
        how="left",
    )
    spl = spl.rename(columns={"ex_date": "session_date"})
    div = div.rename(columns={"ex_date": "session_date"})
    df = df.merge(spl, on=["symbol", "session_date"], how="left").merge(div, on=["symbol", "session_date"], how="left")
    df["split_ratio"] = df.split_ratio.fillna(1.0)
    df["div_cash"] = df.div_cash.fillna(0.0)
    df = df.sort_values(["symbol", "session_date"]).reset_index(drop=True)
    prev = df.groupby("symbol").close_raw.shift()
    df["ret_price"] = df.close_raw * df.split_ratio / prev - 1
    df["ret_total"] = (df.close_raw + df.div_cash) * df.split_ratio / prev - 1
    df["alpaca_adj_ret"] = df.groupby("symbol").close_adj.pct_change(fill_method=None)  # type: ignore[call-arg]  # pandas GroupBy.pct_change accepts fill_method
    df["abs_diff_bps"] = (df.ret_total - df.alpaca_adj_ret).abs() * 1e4
    df["other_action"] = [(s, d) in oth for s, d in zip(df.symbol, df.session_date)]
    df["tr_index"] = (1 + df.ret_total.fillna(0)).groupby(df.symbol).cumprod()
    # Recommended research return: Alpaca adjustment=all (also handles spin-offs and corporate actions filed under
    # historical tickers, which our symbol-keyed CA join misses). Rows where the two disagree by >50bps are flagged.
    df["tr_mismatch_gt50bps"] = df.abs_diff_bps > 50
    df["ret_total_best"] = df.alpaca_adj_ret.where(df.alpaca_adj_ret.notna(), df.ret_total)
    df["tr_index_best"] = (1 + df.ret_total_best.fillna(0)).groupby(df.symbol).cumprod()
    write_parquet(df, DATA / "bars/daily/total_return/daily_total_return.parquet")
    v = df.dropna(subset=["abs_diff_bps"])
    ex = v[v.div_cash > 0]
    bad = v[v.abs_diff_bps > 50]
    summ: dict[str, Any] = {
        "rows": len(df),
        "symbols": int(df.symbol.nunique()),
        "first": df.session_date.min(),
        "last": df.session_date.max(),
        "validated_rows": len(v),
        "median_abs_diff_bps": float(v.abs_diff_bps.median()),
        "p99_abs_diff_bps": float(v.abs_diff_bps.quantile(0.99)),
        "div_exdate_rows": len(ex),
        "div_exdate_median_abs_diff_bps": float(ex.abs_diff_bps.median()),
        "div_exdate_p95_abs_diff_bps": float(ex.abs_diff_bps.quantile(0.95)),
        "rows_diff_gt_50bps": len(bad),
        "symbols_diff_gt_50bps": int(bad.symbol.nunique()),
    }
    today = dt.date.today().isoformat()
    write_parquet(bad.reset_index(drop=True), DATA / "qa" / f"{today}_total_return_mismatch_gt50bps.parquet")
    lines = [
        f"# Total-return validation {today}",
        "",
        *[f"- {k}: {v_}" for k, v_ in summ.items()],
        "",
        "## Largest mismatches (>50bps)",
        bad.sort_values("abs_diff_bps", ascending=False)
        .head(30)[
            [
                "symbol",
                "session_date",
                "ret_total",
                "alpaca_adj_ret",
                "split_ratio",
                "div_cash",
                "other_action",
                "abs_diff_bps",
            ]
        ]
        .to_markdown(index=False),
    ]
    (DATA / "qa" / f"total_return_validation_{today}.md").write_text("\n".join(lines) + "\n")
    update_manifest("total_return", summ)
    print("\n".join(lines))


def _staleness(*names: str) -> None:
    """Write data/staleness/<name>.json from on-disk observation maxima (lib/staleness.py). Never changes exit code."""
    try:
        import sys as _s

        _s.path.insert(0, f"{_QR.DATA_DIR}/lib")
        from quant_research.data.client import staleness

        for n in names:
            staleness.record(n)
    except Exception as e:
        print(f"STALENESS record failed: {e}", file=__import__("sys").stderr)


if __name__ == "__main__":
    main()
    _staleness("total_return")
