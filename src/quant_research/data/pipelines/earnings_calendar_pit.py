"""Point-in-time next-earnings lookup per symbol per NYSE session -> earnings/next_earnings_lookup.parquet

For each (symbol, as_of_date) the next earnings event on or after as_of_date, with timing and the reaction session.
Source precedence per as_of_date:
  1) forward_snapshot  - the latest Nasdaq forward snapshot taken on/before as_of_date (earnings/forward/snapshots/*.parquet).
                         True point-in-time: only what the calendar showed then. Available from the first snapshot date onward.
  2) realized_event    - the next realized event in earnings/earnings_events.parquet (EDGAR 8-K 2.02 acceptance time,
                         Nasdaq history, 10-Q/10-K fallback). HINDSIGHT on the date: the date itself was usually public
                         weeks before, but we did not capture when it became known. Used for as_of dates before snapshots
                         began (and after the last snapshot when a realized event exists).
  3) estimated_from_history - last realized event + median spacing of the symbol's last 8 events (no other information).
reaction session: BMO / INTRADAY(8-K) -> report session; AMC -> next session; UNKNOWN -> report session (conservative:
earliest session the information can hit the price; next_reaction_session_latest gives the AMC reading).
Library helper: lib/earnings_lookup.py next_earnings(symbol, as_of_date).
CLI: python earnings_calendar_pit.py   (rebuild only; earnings_forward.py calls it after each snapshot)
"""
import datetime as dt
import numpy as np, pandas as pd
from quant_research.data.pipelines.common import DATA, write_parquet, update_manifest, log, calendar

FWD = DATA / "earnings/forward/snapshots"


def build_lookup():
    cal = calendar("2016-01-01", (dt.date.today() + dt.timedelta(days=400)).isoformat())
    sess = pd.Index(sorted(cal["date"]))
    def on_or_after(d): i = sess.searchsorted(d); return sess[i] if i < len(sess) else None
    def after(d): i = sess.searchsorted(d, side="right"); return sess[i] if i < len(sess) else None
    u = pd.read_parquet(DATA / "universe/universe.parquet"); syms = sorted(set(u.loc[u.role != "etf", "symbol"]))
    today = dt.date.today()
    asof_days = sess[(sess >= dt.date(2016, 1, 4)) & (sess <= on_or_after(today))]
    grid = pd.MultiIndex.from_product([syms, asof_days], names=["symbol", "as_of_date"]).to_frame(index=False)

    # realized events (one per symbol-day, best source first)
    ev = pd.read_parquet(DATA / "earnings/earnings_events.parquet")
    ev = ev[ev.symbol.isin(syms)].copy()
    ev["d"] = pd.to_datetime(ev.announce_date_et).dt.date
    pr = ev.source.astype(str).map(lambda s: 0 if s.startswith("edgar_8k") else (1 if s.startswith("nasdaq") else 2))
    ev = ev.assign(p=pr).sort_values(["symbol", "d", "p"]).drop_duplicates(["symbol", "d"])
    ev = ev[ev.d <= today] if "nasdaq_scheduled" in set(ev.source) else ev
    R = pd.DataFrame({"symbol": ev.symbol, "next_earnings_date": ev.d, "next_earnings_timing": ev.timing,
                      "next_reaction_session": ev.reaction_session, "src_detail": ev.source,
                      "known_at_utc": pd.to_datetime(ev.knowledge_time_utc, utc=True, errors="coerce")})
    R = R[R.next_earnings_date <= today]

    def fwd_join(g, E):
        a = g.assign(k=pd.to_datetime(g.as_of_date)).sort_values("k")
        e = E.assign(k=pd.to_datetime(E.next_earnings_date)).sort_values("k")
        return pd.merge_asof(a, e.drop(columns=["symbol"]).assign(symbol=e.symbol), on="k", by="symbol", direction="forward").drop(columns="k")

    out = fwd_join(grid, R); out["method"] = np.where(out.next_earnings_date.notna(), "realized_event", None)
    out["date_status"] = np.where(out.next_earnings_date.notna(), "realized", None)

    # forward snapshots (PIT)
    snaps = sorted(FWD.glob("*.parquet")) if FWD.exists() else []
    n_snap_rows = 0
    if snaps:
        S = pd.concat([pd.read_parquet(f) for f in snaps], ignore_index=True)
        S["snapshot_date"] = pd.to_datetime(S.snapshot_date_utc).dt.date
        fill = []
        for sd, g in S.groupby("snapshot_date"):
            nxt = [x for x in sorted(S.snapshot_date.unique()) if x > sd]
            hi = nxt[0] if nxt else dt.date(2100, 1, 1)
            days = asof_days[(asof_days >= sd) & (asof_days < hi)]
            if not len(days): continue
            g2 = g.assign(next_earnings_date=g.report_date)
            g2["next_reaction_session"] = [on_or_after(d) if t in ("BMO", "UNKNOWN") else after(d) for d, t in zip(g2.report_date, g2.timing)]
            E = g2[["symbol", "next_earnings_date", "timing", "next_reaction_session", "date_status", "fetched_at_utc"]].rename(
                columns={"timing": "next_earnings_timing", "fetched_at_utc": "known_at_utc"})
            gg = pd.MultiIndex.from_product([syms, days], names=["symbol", "as_of_date"]).to_frame(index=False)
            j = fwd_join(gg, E).dropna(subset=["next_earnings_date"]); j["method"] = "forward_snapshot"; j["src_detail"] = f"nasdaq_snapshot_{sd}"
            fill.append(j)
        if fill:
            F = pd.concat(fill, ignore_index=True); n_snap_rows = len(F)
            key = ["symbol", "as_of_date"]
            out = out.set_index(key); F = F.set_index(key)
            out.update(F[["next_earnings_date", "next_earnings_timing", "next_reaction_session", "date_status", "known_at_utc", "method", "src_detail"]])
            out = out.reset_index()

    # history-based estimate where still empty
    gaps = R.sort_values(["symbol", "next_earnings_date"]).groupby("symbol").next_earnings_date.apply(
        lambda s: pd.Series(pd.to_datetime(s).diff().dt.days.dropna().tail(8)).median())
    last = R.groupby("symbol").next_earnings_date.max()
    miss = out.next_earnings_date.isna() & out.symbol.isin(last.index)
    est = [last[s] + dt.timedelta(days=int(gaps.get(s))) if pd.notna(gaps.get(s)) else None for s in out.loc[miss, "symbol"]]
    est = [e if (e is None or e >= a) else None for e, a in zip(est, out.loc[miss, "as_of_date"])]
    est = [on_or_after(e) if e is not None else None for e in est]   # estimates land on a NYSE session
    out.loc[miss, "next_earnings_date"] = est
    m2 = miss & out.next_earnings_date.notna()
    out.loc[m2, "method"] = "estimated_from_history"; out.loc[m2, "date_status"] = "estimated_from_history"; out.loc[m2, "next_earnings_timing"] = "UNKNOWN"
    out.loc[m2, "next_reaction_session"] = [on_or_after(d) for d in out.loc[m2, "next_earnings_date"]]
    # reaction session as dates, latest reading for UNKNOWN
    out["next_reaction_session"] = pd.to_datetime(out.next_reaction_session).dt.date
    out["next_earnings_date"] = pd.to_datetime(out.next_earnings_date).dt.date
    out["next_reaction_session_latest"] = [after(d) if (t == "UNKNOWN" and pd.notna(d)) else r for d, t, r in
                                           zip(out.next_earnings_date, out.next_earnings_timing, out.next_reaction_session)]
    pos = {d: i for i, d in enumerate(sess)}
    out["sessions_to_reaction"] = [pos.get(r, np.nan) - pos[a] if pd.notna(r) else np.nan for a, r in zip(out.as_of_date, out.next_reaction_session)]
    out = out[["symbol", "as_of_date", "next_earnings_date", "next_earnings_timing", "next_reaction_session", "next_reaction_session_latest",
               "sessions_to_reaction", "date_status", "method", "src_detail", "known_at_utc"]].sort_values(["symbol", "as_of_date"])
    write_parquet(out, DATA / "earnings/next_earnings_lookup.parquet")
    info = {"rows": len(out), "symbols": int(out.symbol.nunique()), "as_of_range": [str(out.as_of_date.min()), str(out.as_of_date.max())],
            "method_counts": out.method.fillna("none").value_counts().to_dict(), "forward_snapshot_files": len(snaps),
            "forward_snapshot_rows_applied": n_snap_rows,
            "today_coverage": out[out.as_of_date == out.as_of_date.max()].method.fillna("none").value_counts().to_dict()}
    log.info("lookup %s", info)
    update_manifest("next_earnings_lookup", info)
    return info


if __name__ == "__main__":
    build_lookup()
