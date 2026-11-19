"""Fabricated-only inference kernels. No portfolio/production evaluator or data reader.
CSCV D1 uses EXACT 23 columns. Full-family search is charged via signed N>=177.
Bootstrap PCG64 and full OOS/risk/regime gates are deliberately NOT IMPLEMENTED.
"""
from dataclasses import dataclass
from datetime import date
from itertools import combinations
import math
from statistics import NormalDist
from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, configurations, report, hash_shape

IDS=tuple(sorted(c.id for c in configurations()))
FACTOR_FIELDS=("Mkt-RF","SMB","HML","RMW","CMA","Mom","ST_Rev","RF","z")
REGRESSORS=("Mkt-RF","SMB","HML","RMW","CMA","Mom","ST_Rev","z")

def fabricated_dates(days):
    if not days or any(not isinstance(d,date) or d.year<2090 or d.weekday()>4 for d in days):
        raise Blocked("invented 2090+ weekday session dates only; not historical sessions")
    if tuple(sorted(set(days)))!=tuple(days):
        raise Blocked("unique sorted explicit session dates required")

@dataclass(frozen=True)
class SyntheticMatrix:
    days: tuple
    columns: dict
    synthetic_only: bool = False
    def validate(self):
        if self.synthetic_only is not True: raise Blocked("fabricated matrix marker required")
        fabricated_dates(self.days)
        if set(self.columns)!=set(IDS): raise Blocked("card matrix must retain EXACT23 IDs")
        for x in self.columns.values():
            if len(x)!=len(self.days) or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in x):
                raise Blocked("native complete aligned finite series required; no fill/drop")
        return self

def partitions(T):
    if type(T) is not int or T<16: raise Insufficient("16 chronological partitions required")
    q,r=divmod(T,16); out=[]; start=0
    for i in range(16):
        end=start+q+(i<r);out.append((start,end));start=end
    return tuple(out)

def scoring_segments(parts, selected):
    labels=[i in selected for i in range(16)]
    pieces={True:[],False:[]}
    for i,(a,b) in enumerate(parts):
        lo=a+(20 if i and labels[i]!=labels[i-1] else 0)
        hi=b-(20 if i<15 and labels[i]!=labels[i+1] else 0)
        if hi>lo: pieces[labels[i]].append((lo,hi))
    return pieces[True],pieces[False]

def _sharpe(prefix, segments):
    lows=[];highs=[]
    for a,b in segments:
        level=(b-a).bit_length()-1;span=1<<level
        lows.append(min(prefix[2][level][a],prefix[2][level][b-span]))
        highs.append(max(prefix[3][level][a],prefix[3][level][b-span]))
    if min(lows)==max(highs): return -math.inf  # exact constant detection, not cancellation
    n=sum(b-a for a,b in segments)
    s=sum(prefix[0][b]-prefix[0][a] for a,b in segments)
    sq=sum(prefix[1][b]-prefix[1][a] for a,b in segments)
    var=(sq-s*s/n)/(n-1)
    if var<=0: return -math.inf
    return s/n/math.sqrt(var)*math.sqrt(252)

def pbo_synthetic(matrix):
    matrix.validate()
    parts=partitions(len(matrix.days)); pref={}
    for key in IDS:
        a=[0.0];b=[0.0]
        for x in matrix.columns[key]:a.append(a[-1]+x);b.append(b[-1]+x*x)
        lo=[list(matrix.columns[key])];hi=[list(matrix.columns[key])]
        span=1
        while span*2<=len(matrix.days):
            lo.append([min(lo[-1][i],lo[-1][i+span]) for i in range(len(matrix.days)-span*2+1)])
            hi.append([max(hi[-1][i],hi[-1][i+span]) for i in range(len(matrix.days)-span*2+1)])
            span*=2
        pref[key]=(a,b,lo,hi)
    trials=[];bad=0
    for iset in combinations(range(16),8):  # all 12,870 ORIENTED splits
        ins,outs=scoring_segments(parts,set(iset))
        if min(sum(b-a for a,b in ins),sum(b-a for a,b in outs))<100:
            raise Insufficient("invalid CSCV split; cannot discard it")
        scores={k:_sharpe(pref[k],ins) for k in IDS}
        if max(scores.values())==-math.inf:raise Insufficient("all IS columns constant")
        winner=min(IDS,key=lambda k:(-scores[k],k))
        os={k:_sharpe(pref[k],outs) for k in IDS}
        if max(os.values())==-math.inf:raise Insufficient("all OOS columns constant")
        s=os[winner]
        rank=1+sum(v<s for v in os.values())+(sum(v==s for v in os.values())-1)/2
        omega=rank/24
        lam=math.log(omega/(1-omega));bad+=lam<=0
        # Partition boundaries + IS partition indices uniquely reconstruct every purge row.
        trials.append({"IS_partitions":iset,"winner":winner,"OOS_midrank":rank,"lambda":lam})
    assert len(trials)==12870
    pbo=bad/12870
    return report("SYNTHETIC_ONLY_PASS" if pbo<.2 else "FAIL",
                  {"pbo":pbo,"column_count":23,"split_count":len(trials),"partitions":parts,
                   "splits":trials,"stronger_stability":pbo<=.05,"winner_adopted":False})

def join_synthetic_factors(days,rows,units,missing_codes,synthetic_only=False):
    if synthetic_only is not True:raise Blocked("synthetic factor fixture only")
    fabricated_dates(days)
    if units not in {"raw_percent","decimal"} or missing_codes is None:
        raise Blocked("explicit source units and missing-code receipt required")
    by={}
    for row in rows:
        if row.get("synthetic_only") is not True or set(row)!={"day","synthetic_only",*FACTOR_FIELDS}:
            raise Blocked("exact fabricated daily-factor schema required, including actual ST_Rev and z")
        day=row["day"]
        if day in by:raise Blocked("duplicate factor date")
        values={}
        for k in FACTOR_FIELDS:
            v=row[k]
            if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or v in missing_codes:
                raise Blocked("missing/nonfinite/provider sentinel; no fill")
            values[k]=v/(100 if units=="raw_percent" and k!="z" else 1)
        by[day]=values
    wanted={d.isoformat() for d in days}
    if set(by)!=wanted:raise Blocked("exact daily-session join required, no intersection shrinkage")
    return tuple(by[d.isoformat()] for d in days)

def _inverse(A):
    n=len(A); aug=[list(row)+[float(i==j) for j in range(n)] for i,row in enumerate(A)]
    for j in range(n):
        pivot=max(range(j,n),key=lambda i:abs(aug[i][j]))
        if abs(aug[pivot][j])<1e-12*max(1.0,max(abs(v) for row in A for v in row)):
            raise Insufficient("rank deficient or numerically unstable regression")
        aug[j],aug[pivot]=aug[pivot],aug[j]
        div=aug[j][j];aug[j]=[v/div for v in aug[j]]
        for i in range(n):
            if i!=j:
                v=aug[i][j];aug[i]=[a-v*b for a,b in zip(aug[i],aug[j])]
    return [row[n:] for row in aug]

def _mul(A,B):
    return [[sum(a*b for a,b in zip(row,col)) for col in zip(*B)] for row in A]

def _transpose(A):return list(map(list,zip(*A)))

def nw20_synthetic(y, factor_rows, synthetic_only=False):
    """One fixed FF5+Mom+actual ST_Rev+z model. Input y is already RF-excess.
    Standardize regressors for conditioning, transform covariance/intercept back exactly.
    Kernel only: no source, vintage, lagged-holdings-z or daily-book evidence is asserted.
    """
    if synthetic_only is not True:raise Blocked("fabricated regression inputs only")
    T=len(y);p=9
    if T<=p+20 or len(factor_rows)!=T:raise Insufficient("require T>p+20 and exact row alignment")
    if any(not math.isfinite(v) for v in y):raise Blocked("nonfinite dependent series")
    raw=[[r[k] for k in REGRESSORS] for r in factor_rows]
    if any(not math.isfinite(v) for row in raw for v in row):raise Blocked("nonfinite factor")
    means=[sum(col)/T for col in zip(*raw)]
    scales=[math.sqrt(sum((row[j]-means[j])**2 for row in raw)/T) for j in range(8)]
    if min(scales)<=0:raise Insufficient("constant design column")
    X=[[1.0]+[(row[j]-means[j])/scales[j] for j in range(8)] for row in raw]
    xt=_transpose(X);inv=_inverse(_mul(xt,X))
    beta=[row[0] for row in _mul(inv,_mul(xt,[[v] for v in y]))]
    e=[v-sum(a*b for a,b in zip(row,beta)) for row,v in zip(X,y)]
    xe=[[v*e[t] for v in X[t]] for t in range(T)]
    meat=[[sum(xe[t][i]*xe[t][j] for t in range(T)) for j in range(p)] for i in range(p)]
    for lag in range(1,21):
        w=1-lag/21
        for i in range(p):
            for j in range(p):
                meat[i][j]+=w*sum(xe[t][i]*xe[t-lag][j]+xe[t-lag][i]*xe[t][j] for t in range(lag,T))
    cov=_mul(_mul(inv,meat),inv)
    adj=T/(T-p)
    cov=[[v*adj for v in row] for row in cov]
    # alpha_original = beta0 - sum(beta_std*mean/std), including covariance cross terms.
    transform=[[1]+[-m/s for m,s in zip(means,scales)]]
    for j in range(8):transform.append([0]+[1/scales[j] if i==j else 0 for i in range(8)])
    b=[row[0] for row in _mul(transform,[[v] for v in beta])]
    finalcov=_mul(_mul(transform,cov),_transpose(transform))
    variance=finalcov[0][0]
    if variance<=0 or not math.isfinite(variance):raise Insufficient("nonpositive alpha variance")
    t=b[0]/math.sqrt(variance)
    return report("SYNTHETIC_ONLY_PASS" if t>=3 else "FAIL",{"T":T,"p":p,"lags":20,
                  "regressors":["intercept",*REGRESSORS],"betas":b,"covariance":finalcov,
                  "alpha_t":t,"finite_sample_factor":adj})

def dsr_synthetic(matrix,key,N,sigma_ann,reference_receipt,family_receipt=None):
    matrix.validate()
    if key not in {"H48","H120"}:raise Blocked("gating DSR only baseline clocks")
    if type(N) is not int or N<177:raise Blocked("family N must include unconditional reservation")
    if not reference_receipt or reference_receipt.get("synthetic_only") is not True or reference_receipt.get("prototype_count")!=72 or not hash_shape(reference_receipt.get("sha256")):
        raise Blocked("validated fixed72 reference receipt missing; no fallback sigma")
    if not isinstance(sigma_ann,(float,int)) or not math.isfinite(sigma_ann) or sigma_ann<.5:
        raise Blocked("reference sigma_ann >=0.5 from receipt required")
    if reference_receipt.get("sigma_ann")!=sigma_ann:
        raise Blocked("sigma must match the reference receipt")
    if not family_receipt or family_receipt.get("synthetic_only") is not True or family_receipt.get("family_N")!=N or not hash_shape(family_receipt.get("sha256")):
        raise Blocked("matching reconciled full-family mock receipt required")
    x=matrix.columns[key];T=len(x)
    if T<=21:raise Insufficient("insufficient serial-lag history")
    mean=sum(x)/T;dev=[v-mean for v in x];pop=sum(v*v for v in dev)/T
    if pop<=0:raise Insufficient("zero variance")
    sd=math.sqrt(pop*T/(T-1));sr=mean/sd
    skew=sum(v**3 for v in dev)/T/pop**1.5
    kurt=sum(v**4 for v in dev)/T/pop**2
    ac=sum((1-lag/T)*max(sum(dev[t]*dev[t-lag] for t in range(lag,T))/T/pop,0) for lag in range(1,21))
    teff=max(2,min(T,T/(1+2*ac)))
    norm=NormalDist();gamma=.5772156649015329
    sr0=sigma_ann*((1-gamma)*norm.inv_cdf(1-1/N)+gamma*norm.inv_cdf(1-1/(math.e*N)))
    denom=1-skew*sr+((kurt-1)/4)*sr*sr
    if denom<=0 or not math.isfinite(denom):raise Insufficient("DSR denominator invalid")
    dsr=norm.cdf((sr-sr0/math.sqrt(252))*math.sqrt(teff-1)/math.sqrt(denom))
    return report("SYNTHETIC_ONLY_PASS" if dsr>=.95 else "FAIL",{"DSR":dsr,"N":N,"sigma_ann":sigma_ann,
                  "SR0_annual":sr0,"SR_daily":sr,"T":T,"T_eff":teff,"skew":skew,"kurtosis":kurt})

def bootstrap_pcg64(*args,**kwargs):
    raise Blocked("NOT IMPLEMENTED: approved NumPy/PCG64 runtime pins and 10,000-block bootstrap integration absent")

def full_oos_evaluator(*args,**kwargs):
    raise Blocked("NOT IMPLEMENTED: portfolio/scorer/calendar/identity/regime/bootstrap/full-gate integration absent")
