"""Render RESULTS.md from out_pit/ and out_current/ results.json."""

from __future__ import annotations

import json


def f(x: float | None, pct: bool = True) -> str:
    return "" if x is None else (f"{x * 1e4:+.1f} bp" if pct else f"{x}")


out = [
    "# News-sentiment prototype: results",
    "",
    "Returns are per daily cohort, in bp: r1 = open(d)→open(d+1); r5 = open(d)→open(d+5), an overlapping 5-day return, not per day. Net uses Tomas v1.1 at the open by liquidity bucket, one round trip per leg per cohort, plus borrow. t-stats are clustered by calendar month. FF5+Mom alpha uses daily factors for d and d+1 and Newey-West(5).",
    "X posts are excluded: X has no history (archive-forward only).",
    "",
]
for name, d, note in (
    (
        "A. Point-in-time S&P 500 universe (PROVISIONAL)",
        "out_pit",
        "**Provisional.** This uses Dmitri's PIT membership, which has the known issues in the validation `data_issues.json` (SNDK reuse is dropped here). Former members also have no GICS sector, so they drop out of the sector scores.",
    ),
    ("B. Current constituents (SURVIVOR-BIASED comparison)", "out_current", ""),
):
    j = json.load(open(f"{d}/results.json"))
    g = j["diag"]
    out += [
        f"## {name}",
        "",
        note,
        "",
        f"Sample: {g['n_months_loaded']} months of news, {g['months_loaded'][0]} to {g['months_loaded'][-1]}. Articles with ≤3 tagged symbols: {g['articles_after_filter']}. Symbols: {g['symbols']}. Analyst-headline share: {g['analyst_article_share']}. Spec families: {g['spec_variants']}.",
        "",
        "| component / spec | test | N days | hit rate | mean gross | t | mean net | FF5+Mom alpha (t) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k, v in j["results"].items():
        for kk, vv in v.items():
            if not isinstance(vv, dict) or "n_days" not in vv or not vv.get("hit_rate"):
                continue
            a = v.get(f"FF5Mom_alpha_{kk.rsplit('_', 1)[0]}_r1") if kk.endswith("r1") else None
            out.append(
                f"| {k} | {kk} | {vv['n_days']} | {vv['hit_rate']:.1%} | {f(vv['mean_gross'])} | {vv['t_month_clustered']} | {f(vv.get('mean_net_tomas_v1_1'))} | {f(a['alpha']) + ' (' + str(a['t_alpha_nw']) + ')' if a else ''} |"
            )
    out.append("")
out += [
    "Statistics reported per universe: 4 text specs × (2 tests × 2 horizons + 2 alphas) + 2 analyst × (2 horizons + 1 alpha) + 3 sector × 2 horizons = 36. Across both universes that is 72. One or two |t| near 2 are expected by chance."
]
open("RESULTS.md", "w").write("\n".join(out) + "\n")
