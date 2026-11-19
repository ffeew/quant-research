import json,glob,sys
for f in sorted(glob.glob('out/wf_*.json')):
    d=json.load(open(f)); m=d['meta']
    print(f"\n== {f}: N={m['universe_n']} OOS {m['oos_start']}..{m['oos_end']} days={m['oos_days']} rebals={m['n_rebal']}")
    print(f"{'method':8} {'ret':>7} {'vol':>6} {'SR':>6} {'maxDD':>7} {'turn/yr':>7} {'costbp':>6} {'fcvol':>6} {'r/f':>5} {'bias':>5} {'delta':>5}  volCI  SRCI  biasCI")
    for k,v in d['table'].items():
        c=d['ci95'][k]
        print(f"{k:8} {v['ann_ret']*100:7.2f} {v['ann_vol']*100:6.2f} {v['sharpe']:6.2f} {v['max_dd']*100:7.2f} {v['turnover_ann_oneway']*100:7.0f} {v['cost_drag_ann']*1e4:6.1f} {v['fc_vol']*100:6.2f} {v['real_over_fc']:5.2f} {v['bias_stat']:5.2f} {v['lw_delta_mean'] if v['lw_delta_mean'] is None else round(v['lw_delta_mean'],3)!s:>5}  [{c['vol'][0]*100:.2f},{c['vol'][1]*100:.2f}] [{c['sharpe'][0]:.2f},{c['sharpe'][1]:.2f}] [{c['bias'][0]:.2f},{c['bias'][1]:.2f}]")
    for k,v in d['diff_vs_MV_LW_ci95_pgt0'].items():
        print(f"   {k}-LW dvol[{v['dvol'][0]*100:.2f},{v['dvol'][1]*100:.2f}] p>0={v['dvol'][2]:.3f}  dSR[{v['dsharpe'][0]:.2f},{v['dsharpe'][1]:.2f}] p>0={v['dsharpe'][2]:.3f}")
