"""QA for daily bars + corporate actions. Writes data/qa/qa_report_<date>.md and flagged-row parquet files.
Checks: duplicates, missing sessions vs Alpaca NYSE calendar (within each symbol's first..last bar),
non-positive / inconsistent OHLC, zero volume, big raw jumps vs split table, big adjusted jumps
(should not contain split-like jumps), raw/adjusted factor changes not explained by corporate actions,
staleness vs last completed session, universe symbols without bars."""
import datetime as dt
import numpy as np, pandas as pd
from quant_research.data.pipelines.common import DATA, START, calendar, last_completed_session, write_parquet, update_manifest, log

QA = DATA / "qa"
JUMP = 0.40  # |close/prev_close - 1| threshold


def load(adj):
    return pd.read_parquet(DATA / "bars" / "daily" / adj).sort_values(["symbol", "session_date"]).reset_index(drop=True)


def main():
    QA.mkdir(exist_ok=True)
    today = dt.date.today().isoformat()
    cal = calendar(START); session = last_completed_session(cal)
    sessions = pd.Index(sorted(d for d in cal["date"] if d <= session))
    u = pd.read_parquet(DATA / "universe" / "universe.parquet")
    ca = pd.read_parquet(DATA / "corporate_actions" / "all_actions.parquet")
    spl = pd.read_parquet(DATA / "corporate_actions" / "splits.parquet")
    lines = [f"# Data QA report {today} (generated {pd.Timestamp.now(tz='Asia/Singapore'):%Y-%m-%d %H:%M} SGT)", "",
             f"Last completed NYSE session: {session}. Calendar sessions {sessions[0]}..{sessions[-1]} ({len(sessions)}).", ""]
    flags = {}
    for adj in ["raw", "adjusted"]:
        df = load(adj)
        lines += [f"## bars/daily/{adj}", f"- rows {len(df):,}, symbols {df.symbol.nunique()}, sessions {df.session_date.min()}..{df.session_date.max()}"]
        dup = df[df.duplicated(["symbol", "session_date"], keep=False)]
        lines.append(f"- duplicate (symbol, session_date) rows: {len(dup)}")
        bad = df[(df[["open","high","low","close"]] <= 0).any(axis=1) | (df.high < df.low) |
                 (df.close > df.high * 1.0001) | (df.close < df.low * 0.9999) | (df.open > df.high * 1.0001) | (df.open < df.low * 0.9999)]
        lines.append(f"- non-positive or inconsistent OHLC rows: {len(bad)}")
        zv = df[df.volume <= 0]; lines.append(f"- zero-volume rows: {len(zv)}")
        nonsess = df[~df.session_date.isin(set(sessions))]
        lines.append(f"- bars on non-session dates: {len(nonsess)}")
        # missing sessions within each symbol's life
        miss = []
        for s, g in df.groupby("symbol"):
            exp = sessions[(sessions >= g.session_date.min()) & (sessions <= g.session_date.max())]
            m = exp.difference(pd.Index(g.session_date))
            if len(m): miss.append((s, len(m), len(exp), str(m[0]), str(m[-1])))
        miss = pd.DataFrame(miss, columns=["symbol", "n_missing", "n_expected", "first_missing", "last_missing"]).sort_values("n_missing", ascending=False)
        lines.append(f"- symbols with missing sessions inside their bar range: {len(miss)} (total missing {int(miss.n_missing.sum()) if len(miss) else 0})")
        if len(miss): lines += ["  top: " + ", ".join(f"{r.symbol}({r.n_missing})" for r in miss.head(15).itertuples())]
        stale = df.groupby("symbol").session_date.max()
        stale = stale[stale < session]
        active = set(u.loc[u.alpaca_status == "active", "symbol"])
        stale_active = stale[stale.index.isin(active)]
        lines.append(f"- symbols whose last bar < {session}: {len(stale)} (of which Alpaca-active: {len(stale_active)}: {', '.join(f'{k}@{v}' for k, v in stale_active.items())})")
        # jumps
        df["ret"] = df.groupby("symbol").close.pct_change()
        df["prev_date"] = df.groupby("symbol").session_date.shift()
        j = df[df.ret.abs() > JUMP][["symbol", "prev_date", "session_date", "ret", "close"]].copy()
        if adj == "raw":
            sk = set(zip(spl.symbol, spl.ex_date))
            j["split_on_ex_date"] = [(s, d) in sk for s, d in zip(j.symbol, j.session_date)]
            un = j[~j.split_on_ex_date]
            lines.append(f"- raw |ret|>{JUMP:.0%}: {len(j)} ({j.split_on_ex_date.sum()} explained by a split ex_date; {len(un)} unexplained)")
        else:
            un = j
            lines.append(f"- adjusted |ret|>{JUMP:.0%} (should be genuine moves, not splits): {len(j)}")
        if len(un): lines += ["  " + "; ".join(f"{r.symbol} {r.session_date} {r.ret:+.1%}" for r in un.head(40).itertuples())]
        lines.append("")
        flags[adj] = dict(dup=dup, bad_ohlc=bad, zero_volume=zv, missing_sessions=miss, jumps=j)
    # raw vs adjusted factor consistency
    r = load("raw")[["symbol", "session_date", "close"]]; a = load("adjusted")[["symbol", "session_date", "close"]]
    m = r.merge(a, on=["symbol", "session_date"], suffixes=("_raw", "_adj"))
    m["f"] = m.close_adj / m.close_raw
    m["fchg"] = m.groupby("symbol").f.pct_change()
    ev = set(zip(ca.get("symbol"), ca.ex_date)) if "symbol" in ca else set()
    big = m[m.fchg.abs() > 0.002].copy()
    big["explained"] = [(s, d) in ev for s, d in zip(big.symbol, big.session_date)]
    # factor changes the day AFTER the last pre-ex bar: ex_date may fall on that session -> check by session_date
    une = big[~big.explained]
    lines += ["## raw vs adjusted consistency",
              f"- matched rows {len(m):,}; adjustment-factor changes >0.2%: {len(big)}; not on a known corporate-action ex_date: {len(une)}"]
    if len(une): lines.append("  " + "; ".join(f"{x.symbol} {x.session_date} {x.fchg:+.2%}" for x in une.head(30).itertuples()))
    nob = sorted(set(u.symbol) - set(r.symbol))
    lines += ["", "## Coverage", f"- universe symbols: {len(u)}; with bars: {r.symbol.nunique()}; without bars ({len(nob)}): {', '.join(nob)}"]
    lines += ["", "## Corporate actions", f"- rows by type: {ca.type.value_counts().to_dict()}",
              f"- duplicate ids: {int(ca.id.duplicated().sum())}",
              f"- cash dividends with missing record_date: {int(ca[(ca.type=='cash_dividends')].record_date.isna().sum())}, missing payable_date: {int(ca[(ca.type=='cash_dividends')].payable_date.isna().sum())}"]
    (QA / f"qa_report_{today}.md").write_text("\n".join(lines) + "\n")
    for adj, fl in flags.items():
        for k, v in fl.items():
            if len(v): write_parquet(v.reset_index(drop=True), QA / f"{today}_{adj}_{k}.parquet")
    if len(une): write_parquet(une.reset_index(drop=True), QA / f"{today}_factor_changes_unexplained.parquet")
    update_manifest("qa", {"report": str(QA / f"qa_report_{today}.md")})
    print("\n".join(lines))


if __name__ == "__main__":
    main()
