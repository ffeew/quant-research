"""Stage 7: coverage by year -> COVERAGE.md (counts only; no returns)."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import pandas as pd
D = f"{_QR.DATA_DIR}"; TODAY = pd.Timestamp("2026-10-30")
mem = pd.read_parquet(f"{D}/universe/sp500_membership.parquet")
mem["s"] = pd.to_datetime(mem.start_date_filled); mem["e"] = pd.to_datetime(mem.end_date).fillna(TODAY + pd.Timedelta(days=1))
seg = pd.read_parquet("work/segments_final.parquet")
ev = pd.read_parquet("earnings_events_8k202.parquet")
m = ev[ev.in_sp500].assign(sym=lambda x: x.index_symbols.str.split(",")).explode("sym")
m["y"] = pd.to_datetime(m.acceptance_et).dt.year
rows, detail = [], []
for y in range(2015, 2027):
    ys, ye = pd.Timestamp(f"{y}-01-01"), min(pd.Timestamp(f"{y+1}-01-01"), TODAY + pd.Timedelta(days=1))
    mm = mem[(mem.s < ye) & (mem.e > ys)]
    syms = sorted(mm.symbol.unique())
    full = set(mm[(mm.s <= ys) & (mm.e >= ye)].symbol)
    sy = seg[(seg.seg_start < ye) & (seg.seg_end > ys)]
    mapped = set(sy[sy.identity_ok].symbol)
    cnt = m[m.y == y].groupby("sym").size()
    c = pd.Series({s: int(cnt.get(s, 0)) for s in syms})
    unm = [s for s in syms if s not in mapped]
    zero = [s for s in syms if s in mapped and c[s] == 0]
    fm = [s for s in full if s in mapped]
    rows.append(dict(year=y, members=len(syms), full_year_members=len(full), unmapped=len(unm),
                     share_ge4_all=round((c >= 4).mean(), 3),
                     share_ge4_fullyear_mapped=round((c[fm] >= 4).mean(), 3) if fm else None,
                     share_ge3_fullyear_mapped=round((c[fm] >= 3).mean(), 3) if fm else None,
                     mapped_members_zero_events=len(zero), events_in_sp500=int(cnt.sum())))
    detail.append((y, unm, zero))
cov = pd.DataFrame(rows); cov.to_csv("coverage_by_year.csv", index=False)
with open("COVERAGE.md", "w") as f:
    f.write("# Coverage by year: earnings_events_8k202 v1\n\n")
    f.write("Members = PIT S&P 500 tickers (Dmitri's `sp500_membership.parquet`) with any membership day in the year; "
            "events = deduped 8-K/8-K/A Item 2.02 events accepted while a member. 2026 is year-to-date (to 2026-10-30), "
            "so ≥ 3 is the comparable bar. Multi-class issuers (GOOG/GOOGL, FOX/FOXA, NWS/NWSA) count once per ticker.\n\n")
    f.write(cov.to_markdown(index=False) + "\n\n## Unmapped members and mapped members with zero events, by year\n\n")
    for y, unm, zero in detail:
        f.write(f"- **{y}** unmapped ({len(unm)}): {', '.join(unm) or '-'}; zero events ({len(zero)}): {', '.join(zero) or '-'}\n")
print(cov.to_string())
