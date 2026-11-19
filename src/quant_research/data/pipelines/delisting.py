"""Terminal (delisting) returns for universe names whose bars stop before the last completed session.
Source: our raw SIP bars (last trade close) + Alpaca corporate actions (cash_mergers / stock_mergers /
stock_and_cash_mergers matched on acquiree_symbol, effective_date within -10..+45 days of last bar).
  cash:        terminal_value = rate
  stock:       terminal_value = acquirer_rate/acquiree_rate * acquirer RAW close on first session >= effective_date
  stock+cash:  terminal_value = that + cash_rate
  terminal_return = terminal_value / last_close_raw - 1   (return from last bar close to deal consideration)
No match -> terminal_return null, reason='no_deal_in_alpaca_CA' (bankruptcy/delisting/ticker change: NOT imputed).
All values flagged approximate=True: ignores time value between last bar and payment, CVRs, elections/proration,
fractional-share cash. Alpaca merger CA history starts 2020-04 -> pre-2020 deals unmatched.
suspect=True when |terminal_return|>15% (likely partial consideration).
Output: data/universe/delisting_returns.parquet"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

from quant_research.data.pipelines.common import (
    DATA,
    DATA_URL,
    get,
    last_completed_session,
    log,
    update_manifest,
    write_parquet,
)


def acq_close(sym: str, d: dt.date, cache: dict[str, pd.DataFrame]) -> tuple[float | None, dt.date | None]:
    if sym not in cache:
        f = DATA / "bars/daily/raw" / f"{sym}.parquet"
        if f.exists():
            cache[sym] = pd.read_parquet(f, columns=["session_date", "close"])
        else:
            try:
                j = get(
                    DATA_URL + "/v2/stocks/bars",
                    {
                        "symbols": sym,
                        "timeframe": "1Day",
                        "start": str(d),
                        "end": str(pd.Timestamp(d) + pd.Timedelta(days=15))[:10],
                        "feed": "sip",
                        "adjustment": "raw",
                        "asof": str(d),
                    },
                )
            except RuntimeError:
                j = {}
            b = (j.get("bars") or {}).get(sym, [])
            cache[sym] = pd.DataFrame(
                [
                    {"session_date": pd.Timestamp(x["t"]).tz_convert("America/New_York").date(), "close": x["c"]}
                    for x in b
                ]
            )
    c = cache[sym]
    if c.empty:
        return None, None
    c = c[c.session_date >= d]
    return (float(c.close.iloc[0]), c.session_date.iloc[0]) if len(c) else (None, None)


def main() -> None:
    session = last_completed_session()
    u = pd.read_parquet(DATA / "universe/universe.parquet")
    ca = pd.read_parquet(DATA / "corporate_actions/all_actions.parquet")
    mg = ca[ca.type.isin(["cash_mergers", "stock_mergers", "stock_and_cash_mergers"])].copy()
    mg["effective_date"] = pd.to_datetime(mg.effective_date.fillna(mg.process_date)).dt.date
    rows: list[dict[str, Any]] = []
    cache: dict[str, pd.DataFrame] = {}
    for s, role in zip(u.symbol, u.role):
        f = DATA / "bars/daily/raw" / f"{s}.parquet"
        if not f.exists():
            continue
        b = pd.read_parquet(f, columns=["session_date", "close", "asof_mapping"])
        last_d, last_c = b.session_date.iloc[-1], float(b.close.iloc[-1])
        if (session - last_d).days <= 5:
            continue
        cand = mg[(mg.acquiree_symbol == s)]
        cand = cand[[(-10 <= (e - last_d).days <= 45) for e in cand.effective_date]]
        r = dict(
            symbol=s,
            role=role,
            last_session=last_d,
            last_close_raw=last_c,
            deal_type=None,
            acquirer=None,
            effective_date=None,
            cash_per_share=None,
            acquirer_ratio=None,
            acquirer_close=None,
            acquirer_close_date=None,
            terminal_value=None,
            terminal_return=None,
            reason=None,
            approximate=True,
            ca_id=None,
        )
        if cand.empty:
            r["reason"] = "no_deal_in_alpaca_CA"
        else:
            d = cand.iloc[0]
            r.update(deal_type=d.type, acquirer=d.acquirer_symbol, effective_date=d.effective_date, ca_id=d.id)
            cash = d.rate if d.type == "cash_mergers" else (d.cash_rate if d.type == "stock_and_cash_mergers" else 0.0)
            tv: float | None = float(cash) if pd.notna(cash) else 0.0
            r["cash_per_share"] = cash
            if d.type != "cash_mergers":
                ratio = float(d.acquirer_rate) / float(d.acquiree_rate or 1.0)
                r["acquirer_ratio"] = ratio
                px, pd_ = (
                    acq_close(d.acquirer_symbol, d.effective_date, cache)
                    if isinstance(d.acquirer_symbol, str)
                    else (None, None)
                )
                r.update(acquirer_close=px, acquirer_close_date=pd_)
                tv = tv + ratio * px if px else None  # type: ignore[operator]  # cash leg is a float before the stock add
                if px is None:
                    r["reason"] = "acquirer_price_missing"
            if tv is not None:
                r["terminal_value"] = tv
                r["terminal_return"] = tv / last_c - 1
                r["reason"] = r["reason"] or "matched_deal"
        rows.append(r)
    df = pd.DataFrame(rows)
    # sanity: deal consideration should be close to the last close; large gaps usually mean Alpaca recorded only
    # part of the consideration (e.g. DO 2024: cash leg only, stock leg missing) -> do not trust without checking terms
    df["suspect"] = df.terminal_return.abs() > 0.15
    df.loc[df.suspect, "reason"] = "matched_deal_SUSPECT_partial_terms"
    write_parquet(df, DATA / "universe/delisting_returns.parquet")
    info: dict[str, Any] = {
        "delisted_or_stopped": len(df),
        "matched": int((df.reason == "matched_deal").sum()),
        "by_reason": df.reason.value_counts().to_dict(),
        "unmatched_symbols": df.loc[df.reason != "matched_deal", "symbol"].tolist(),
    }
    update_manifest("delisting_returns", info)
    log.info("%s", info)
    print(df[df.reason == "matched_deal"].terminal_return.describe())


if __name__ == "__main__":
    main()
