"""Controls & robustness for backtest.py results. Controls are benchmarks, NOT candidate rules (not counted in N)."""
import json, math, numpy as np, pandas as pd
from statistics import NormalDist
from quant_research.strategies.pead_gap.backtest_core import *
Z=NormalDist(); g=0.5772156649
pnl=pd.read_csv("daily_pnl_R_all_variants.csv",index_col=0,parse_dates=True)
res=pd.read_csv("results_summary.csv")
out={}
spy=C["SPY"].pct_change().reindex(pnl.index)
def sh(x): return float(x.mean()/x.std()*math.sqrt(252))
for per,lo,hi in (("IS",None,SPLIT),("OOS",SPLIT+pd.Timedelta(days=1),None)):
    out[f"SPY_buyhold_sharpe_{per}"]=round(sh(spy.loc[lo:hi].dropna()),3)
# beta / alpha of each variant daily P&L vs SPY (OLS, HAC-free simple t)
beta={}
for v in pnl.columns:
    for per,lo,hi in (("IS",None,SPLIT),("OOS",SPLIT+pd.Timedelta(days=1),None)):
        y=pnl[v].loc[lo:hi]; x=spy.loc[lo:hi]; m=x.notna(); y,x=y[m],x[m]
        X=np.c_[np.ones(len(x)),x.values]; b,*_=np.linalg.lstsq(X,y.values,rcond=None)
        e=y.values-X@b; s2=e@e/(len(y)-2); se=np.sqrt(np.diag(s2*np.linalg.inv(X.T@X)))
        resid_sr=float(np.mean(e+b[0])/np.std(e)*math.sqrt(252))
        beta[f"{v}|{per}"]=dict(beta_R_per_1pct_SPY=round(b[1]/100,3),alpha_R_per_day=round(b[0],4),alpha_t=round(b[0]/se[0],2),
                                corr=round(float(np.corrcoef(x,y)[0,1]),3),beta_hedged_sharpe=round(resid_sr,3))
pd.DataFrame(beta).T.to_csv("diag_beta_vs_spy.csv")
# Control: unconditional long/short bracket entries on every name every 5th trading day (same exits/costs)
ctl={1:[],-1:[]}
for i in range(FIRST,len(cal)-1,5):
    for s in C.columns:
        if np.isnan(C[s].iat[i]): continue
        for side in (1,-1):
            t=sim_bracket(s,i,side)
            if t: ctl[side].append(t)
rows=[]
for side,tr in ctl.items():
    for per,lo,hi in (("IS",None,SPLIT),("OOS",SPLIT+pd.Timedelta(days=1),None)):
        ts=[t for t in tr if (lo is None or t["sig"]>=lo) and (hi is None or t["sig"]<=hi)]
        rows.append(dict(control=f"uncond_bracket_{'L' if side>0 else 'S'}",period=per,**tstats(ts)))
# Control for trend filter alone: long bracket on every name above 50&200 every 5th day (what PEAD_trend_L must beat)
tr=[sim_bracket(s,i,1) for i in range(FIRST,len(cal)-1,5) for s in C.columns if ABOVE[s].iat[i]]
tr=[t for t in tr if t]
for per,lo,hi in (("IS",None,SPLIT),("OOS",SPLIT+pd.Timedelta(days=1),None)):
    ts=[t for t in tr if (lo is None or t["sig"]>=lo) and (hi is None or t["sig"]<=hi)]
    rows.append(dict(control="trend_only_bracket_L(above50&200)",period=per,**tstats(ts)))
# monthly hold control: all names long, monthly hold, R=2xATR (equal-risk universe)
tr=[]
for a,b in zip(month_end,month_end[1:]+[len(cal)-1]):
    i=a+1; j=min(b+1,len(cal)-1)
    for s in C.columns:
        E=O[s].iat[i]; atr=ATR[s].iat[a]; X=O[s].iat[j]
        if E>0 and atr>0 and X>0: tr.append(mk(s,a,i,j,1,E,X,2*atr,"rebal"))
for per,lo,hi in (("IS",None,SPLIT),("OOS",SPLIT+pd.Timedelta(days=1),None)):
    ts=[t for t in tr if (lo is None or t["sig"]>=lo) and (hi is None or t["sig"]<=hi)]
    rows.append(dict(control="all_names_monthly_hold_L(equal-risk)",period=per,**tstats(ts)))
pd.DataFrame(rows).to_csv("diag_controls.csv",index=False)
# Welch t: PEAD_trend_L vs trend-only control, MOM_monthly_L vs all-names monthly control (OOS)
ta=pd.read_csv("trades_all_variants.csv",parse_dates=["sig"])
def welch(a,b):
    a,b=np.asarray(a),np.asarray(b); return round(float((a.mean()-b.mean())/math.sqrt(a.var(ddof=1)/len(a)+b.var(ddof=1)/len(b))),2)
for v,ctlname,ctr in (("PEAD_trend_L","trend_only",[t for t in [sim_bracket(s,i,1) for i in range(FIRST,len(cal)-1,5) for s in C.columns if ABOVE[s].iat[i]] if t]),
                      ("PEAD_raw_L","uncond_L",ctl[1]),("MOM_monthly_L","all_monthly",tr)):
    for per,lo,hi in (("IS",None,SPLIT),("OOS",SPLIT+pd.Timedelta(days=1),None)):
        a=ta[(ta.variant==v)&(ta.sig>=(lo or pd.Timestamp(0)))&(ta.sig<=(hi or pd.Timestamp("2100-01-01")))].R
        b=[t["R"] for t in ctr if (lo is None or t["sig"]>=lo) and (hi is None or t["sig"]<=hi)]
        out[f"excess_expR_{v}_vs_{ctlname}_{per}"]=dict(variant=round(float(a.mean()),4),control=round(float(np.mean(b)),4),welch_t=welch(a,b))
# DSR sensitivities
oos=res[res.period=="OOS"].set_index("variant")
def dsr(best,pool,N=None):
    srs=oos.loc[pool,"sr_daily"].astype(float); N=N or len(pool); v=float(srs.var(ddof=1))
    s0=math.sqrt(v)*((1-g)*Z.inv_cdf(1-1/N)+g*Z.inv_cdf(1-1/(N*math.e)))
    b=oos.loc[best]; sr=float(b.sr_daily); T=int(b.days)
    return dict(N=N,best=best,sr_ann=round(sr*math.sqrt(252),3),sr0_ann=round(s0*math.sqrt(252),3),
                DSR=round(Z.cdf((sr-s0)*math.sqrt(T-1)/math.sqrt(1-b["skew"]*sr+(b["kurt"]-1)/4*sr**2)),4))
allv=list(oos.index); prim=["PEAD_raw_LS","PEAD_trend_LS","MOM_bracket_LS","MOM_monthly_LS"]
longs=[v for v in allv if v.endswith("_L")]
out["DSR_main_N12"]=dsr("PEAD_trend_L",allv)
out["DSR_primary_only_N4(best=PEAD_trend_LS)"]=dsr("PEAD_trend_LS",prim)
out["DSR_long_legs_var_N12"]=dsr("PEAD_trend_L",longs,N=12)
# beta-hedged DSR for best: use residual daily P&L
y=pnl["PEAD_trend_L"].loc[SPLIT+pd.Timedelta(days=1):]; x=spy.loc[y.index].fillna(0)
X=np.c_[np.ones(len(x)),x.values]; b,*_=np.linalg.lstsq(X,y.values,rcond=None); r=y.values-x.values*b[1]
sr=r.mean()/r.std(ddof=1); z=(r-r.mean())/r.std(); sk=float((z**3).mean()); ku=float((z**4).mean())
v=float(oos["sr_daily"].astype(float).var(ddof=1)); N=12
s0=math.sqrt(v)*((1-g)*Z.inv_cdf(1-1/N)+g*Z.inv_cdf(1-1/(N*math.e)))
out["DSR_PEAD_trend_L_beta_hedged_N12"]=dict(sr_ann=round(sr*math.sqrt(252),3),DSR=round(Z.cdf((sr-s0)*math.sqrt(len(r)-1)/math.sqrt(1-sk*sr+(ku-1)/4*sr**2)),4))
json.dump(out,open("diagnostics.json","w"),indent=1,default=float)
print(json.dumps(out,indent=1,default=float)); print(pd.DataFrame(rows).to_string())
b=pd.DataFrame(beta).T; print(b[b.index.str.endswith("OOS")].to_string())
