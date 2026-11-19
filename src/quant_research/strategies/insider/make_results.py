"""Render RESULTS.md from out_pit/results.json and out_current/results.json."""
import json
def tbl(r):
    L = ["| series | N stock-months | N months | hit rate | mean (event) | t (month-clustered) | mean (EW monthly portfolio) | portfolio hit rate | t (portfolio; NW(2) for 3M) |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in r.items():
        if "n_events" in v:
            L.append(f"| {k} | {v['n_events']} | {v['n_months']} | {v['hit_rate']:.1%} | {v['mean_event']*100:+.2f}% | {v['t_event_month_clustered']} | {v['mean_monthly_port']*100:+.2f}% | {v['port_hit_rate']:.1%} | {v['t_port']} |")
    L += ["", "| long-short / subperiod | N months | mean | hit rate | t |", "|---|---|---|---|---|"]
    for k, v in r.items():
        if "n_months" in v and "n_events" not in v:
            L.append(f"| {k} | {v['n_months']} | {v['mean']*100:+.2f}% | {v.get('hit_rate', float('nan')):.1%} | {v['t']} |")
    L += ["", "| FF5+Mom regression (monthly; long-only portfolios use returns minus RF) | N | alpha/month | t (NW2) | betas |", "|---|---|---|---|---|"]
    for k, v in r.items():
        if k.startswith("FF5") and v: L.append(f"| {k} | {v['n']} | {v['alpha']*100:+.2f}% | {v['t_alpha_nw']} | {v['betas']} |")
    return L
out = ["# Insider prototype: results (run 30 Oct 2026, SGT)", "",
       "Filings 2016-01 to 2026-09. Portfolios are equal-weighted and gross of costs. A round trip is about 8–15 bp a month under Tomas v1.1 for L1/L2 names, which is immaterial next to these means. Research only.",
       "xr = excess vs SPY. xe = excess vs the equal-weighted PIT S&P 500. Suffix 1 or 3 = months held.", ""]
for name, d, note in (("A. Point-in-time S&P 500 universe (PROVISIONAL)", "out_pit",
        "**Provisional.** This depends on former members and delisting returns, which have known issues in Dmitri's store (validation `data_issues.json`): 59 members have days without bars; terminal returns were matched for only 47 of 120 delisted names, and the rest use the last close; SNDK ticker reuse is dropped (old SanDisk interval removed; new Sandisk is mapped by CIK)."),
        ("B. Current-constituent universe (SURVIVOR-BIASED comparison)", "out_current",
        "Today's 503 constituents are treated as members for the whole sample. This is upward-biased by construction.")):
    j = json.load(open(f"{d}/results.json")); g = j["diag"]
    out += [f"## {name}", "", note, "", f"Trade rows: {g['by_code_cls']}. Symbols: {g['symbols']}. Mapping: {g['map_via']}. Statistics reported: {g['variants_reported']}.", ""] + tbl(j["results"]) + [""]
open("RESULTS.md", "w").write("\n".join(out) + "\n")
