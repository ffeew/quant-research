from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import json, glob
# DESK_RULES #5 (2026-10-30 02:12 SGT): every table below was built from RETIRED sources (statarb daily_bars.json, data.json)
# before the rule; kept for the audit trail. New runs use src="store" (riskmodels_wf/volcap_wf/gp_wf defaults).
L = [f"> **Built from RETIRED data sources (pre data-provenance rule): statarb daily_bars.json (deprecated) and data.json. "
     "Audit trail only; not a current result. See out/RETIRED_SOURCES.md.**\n"]
names = {"wf_statarb_L120_w": "A. statarb bars, L120, weekly", "wf_statarb_L120_m": "B. statarb bars, L120, monthly (21d)",
         "wf_statarb_L252_m": "C. statarb bars, L252, monthly", "wf_datajson_L120_w": "D. data.json, L120, weekly",
         "wf_datajson_L120_m": "E. data.json, L120, monthly", "wf_datajson_L60_w": "F. data.json, L60, weekly"}
for key, title in names.items():
    d = json.load(open(f"out/{key}.json"))
    m = d["meta"]
    L.append(f"\n#### {title}: N={m['universe_n']}, OOS {m['oos_start']}..{m['oos_end']} ({m['oos_days']} days, {m['n_rebal']} rebalances)\n")
    L.append("| Method | Ret % | Vol % [95% CI] | Sharpe [95% CI] | MaxDD % | Turnover %/yr | Cost bp/yr (10bp) | Sharpe (TCA cost) | Fcst vol % | Real/Fcst | Bias stat [95% CI] | mean LW δ* |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, v in d["table"].items():
        c = d["ci95"][k]
        dl = "" if v["lw_delta_mean"] is None else f"{v['lw_delta_mean']:.3f}"
        L.append(f"| {k} | {v['ann_ret']*100:.2f} | {v['ann_vol']*100:.2f} [{c['vol'][0]*100:.2f}, {c['vol'][1]*100:.2f}] | {v['sharpe']:.2f} [{c['sharpe'][0]:.2f}, {c['sharpe'][1]:.2f}] | {v['max_dd']*100:.2f} | {v['turnover_ann_oneway']*100:.0f} | {v['cost_drag_ann']*1e4:.1f} | {v['tca_sharpe']:.2f} | {v['fc_vol']*100:.2f} | {v['real_over_fc']:.2f} | {v['bias_stat']:.2f} [{c['bias'][0]:.2f}, {c['bias'][1]:.2f}] | {dl} |")
    L.append("\nDifferences vs MV-LW (stationary block bootstrap 95% CI; p = share of draws > 0):\n")
    for k, v in d["diff_vs_MV_LW_ci95_pgt0"].items():
        L.append(f"- {k} − MV-LW: Δvol [{v['dvol'][0]*100:.2f}, {v['dvol'][1]*100:.2f}] pp (p>0 = {v['dvol'][2]:.3f}); ΔSharpe [{v['dsharpe'][0]:.2f}, {v['dsharpe'][1]:.2f}] (p>0 = {v['dsharpe'][2]:.3f})")
g = json.load(open("out/gp_wf.json"))
L.append("\n### GP-A: partial trading on risk portfolios (L120, weekly)\n")
L.append("| Data | Method | τ | Turnover x/yr | Cost bp/yr (10bp) | Cost bp/yr (TCA) | Vol % | Sharpe (10bp) | Sharpe (TCA) | TE to target % | OOS |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|")
for r in g["partA"]:
    L.append(f"| {r['src']} | {r['method']} | {r['tau']:.3f} | {r['turnover_ann']:.2f} | {r['cost_bp_10']:.1f} | {r['cost_bp_tca']:.1f} | {r['vol']*100:.2f} | {r['sr_10']:.2f} | {r['sr_tca']:.2f} | {r['te_to_target']*100:.2f} | {r['oos']} |")
L.append("\n### GP-B: long/short signal book (MOM_12_1, RS63, TREND, REV5; statarb bars; TCA cost + 25 bp/yr borrow)\n")
L.append("| Variant | Turnover x/yr | Cost+borrow bp/yr | Gross ret % | Net ret % | Vol % | Sharpe gross | Sharpe net | MaxDD % | TE to full-rebalance % |")
L.append("|---|---|---|---|---|---|---|---|---|---|")
for r in g["partB"]:
    L.append(f"| {r['variant']} | {r['turnover_ann']:.2f} | {r['cost_bp_ann']:.1f} | {r['gross_ret']*100:.2f} | {r['net_ret']*100:.2f} | {r['vol']*100:.2f} | {r['sr_gross']:.2f} | {r['sr_net']:.2f} | {r['max_dd']*100:.2f} | {r['te_to_full']*100:.2f} |")
L.append(f"\nOOS {g['partB'][0]['oos']}. Mean φ_k (1 − 5-day rank autocorrelation): " + ", ".join(f"{k} {v:.3f}" for k, v in (g.get("phi_mean_statarb") or g.get("phi_mean")).items()))
L.append("GP map (ℓ → a/γ, τ): " + ", ".join(f"ℓ={k}: ({v[0]:.3f}, {v[1]:.4f})" for k, v in g["gp_map"].items()))
open("out/tables.md", "w").write("\n".join(L) + "\n")
