from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
# fiscal_diag_s6b.py - S6b rerun of prereg v5 §2 step-4 fiscal-label diagnostic under Victor ruling 2495e0cd (S1,S2,S4,S5)
# as amended by Erratum 1 (7584b5b5...099b; S3 and S4 denominator replaced by the DUE-quarter rule).
# Based on fiscal_diag_s6.py (e238440f); only S3/S4 logic changed, plus: S2 months are READ from the frozen table
# FYE_MONTH_FROZEN.tsv (67d7eab8, copied byte-for-byte) and cross-checked against the S1 recomputation; EDGE is a parameter.
# DEV metadata only: annual FYE cut, earnings_dev.csv, transcript LABELS/status from coverage_transcripts.tsv (index only).
# No transcript file opened. No returns, no sentiment, no holdout, no network.
import calendar, datetime as dt, hashlib, sys, pandas as pd
OUT=f'{_QR.DESK_DIR}/research/original/sentiment_returns_fiscal_diag_s6b_20261111'
PA=f'{_QR.DATA_DIR}/av_annual_fye_dev_20261111/annual_fye_dev.csv'
PE=f'{_QR.DATA_DIR}/av_returns_events_20261111/partitioned/dev/earnings_dev.csv'
PC=f'{_QR.DATA_DIR}/av_sentiment_20261110/clean/coverage_transcripts.tsv'
PF=f'{OUT}/FYE_MONTH_FROZEN.tsv'
SHA={PA:'c6b8a9507e9d27255e1ecbe767f8f8538da7023175662b7fff73f01dd347f351',
     PE:'cb6a4e6fa7ba0a98850f38a717f6510a8ef9b80c91076edb8815beb96b473982',  # per dev/SHA256SUMS (b835e488), checked before run
     PF:'67d7eab8140fb62a64983df54b2ca775acae0ad39d5d3d185fd96aed705ec326',
     PC:None}
for p,h in SHA.items():
    d=hashlib.sha256(open(p,'rb').read()).hexdigest(); print('input',p,d)
    if h and d!=h: sys.exit(f'sha mismatch {p}')
# ---- EDGE parameter. Same rule applies at the OOS edge 2026-10-31 with the frozen months, but that needs HOLDOUT inputs,
# which this script must never read: refuse any edge after the DEV edge.
EDGE=dt.date.fromisoformat(sys.argv[1]) if len(sys.argv)>1 else dt.date(2024,12,31)
if EDGE>dt.date(2024,12,31): sys.exit('EDGE after DEV edge 2024-12-31 not allowed here (OOS edge needs released HOLDOUT inputs)')
LAG=100  # sealed lag bound (days)
LAB_LO,LAB_HI='2021Q4','2025Q3'
print('EDGE',EDGE,'LAG',LAG,'due iff quarter_end +',LAG,'d <=',EDGE,'i.e. quarter_end <=',EDGE-dt.timedelta(LAG))
A=pd.read_csv(PA,dtype=str); E=pd.read_csv(PE,dtype=str); C=pd.read_csv(PC,sep='\t',dtype=str)
A['f']=pd.to_datetime(A.fiscalDateEnding).dt.date
E['f']=pd.to_datetime(E.fiscalDateEnding).dt.date; E['r']=pd.to_datetime(E.reportedDate).dt.date
def me(y,m): return dt.date(y,m,calendar.monthrange(y,m)[1])
def qend(Y,m,n):  # nominal month-end of quarter n of FY Y (end-year convention, FY ends month m of year Y)
    k=m-3*(4-n); return me(Y if k>0 else Y-1,(k-1)%12+1)
def due(Y,m,n): return qend(Y,m,n)+dt.timedelta(LAG)<=EDGE   # Erratum S3: dates + lag bound only
def due_date(Y,m,n): return qend(Y,m,n)+dt.timedelta(LAG)
# ---- S1/S2: frozen m read from FYE_MONTH_FROZEN.tsv (67d7eab8); recomputed from DEV annual rows as a cross-check only
syms=sorted(set(E.symbol)|set(A.symbol)|set(C.symbol))
F=pd.read_csv(PF,sep='\t',dtype=str)
M={r.symbol:int(r.fye_month) for r in F.itertuples() if r.status=='FROZEN'}
for s in syms:
    ms=sorted(set(d.month for d in A[A.symbol==s].f))
    if s in M and ms!=[M[s]]: sys.exit(f'frozen month mismatch {s} {M[s]} vs {ms}')
print('frozen months read:',len(M),'cross-check vs S1 recomputation: OK')
def ann_end(s,Y):
    c=A[(A.symbol==s)&(A.f.map(lambda d:d.year)==Y)]
    return (c.f.iloc[0] if len(c)==1 else None), len(c)
def fy_state(s,Y):
    """FY Y of symbol s under Erratum-1 S3. Returns dict with kind, k (due quarters), ok, why, qmap {n: row or None}."""
    m=M[s]; a1,n1=ann_end(s,Y); a0,n0=ann_end(s,Y-1); rows=E[E.symbol==s]
    dq=[n for n in range(1,5) if due(Y,m,n)]; k=len(dq)
    d=dict(Y=Y,ann_rows_Y=n1,ann_rows_Ym1=n0,k=k,due_q=dq)
    if n1>1 or n0>1: d.update(kind='label_nonunique',ok=False,why=f'annual_rows_Y{n1}_Ym1{n0}',qmap=None); return d
    if a0 is None: d.update(kind='no_prev_annual',ok=False,why='no_annual_end_Ym1',qmap=None); return d
    if k==4:   # CLOSED: all 4 quarters due (S6 closed-year check otherwise unchanged)
        if a1 is None or a1>EDGE: d.update(kind='closed',ok=False,why='closed_no_annual_row',qmap=None); return d
        q=rows[(rows.f>a0)&(rows.f<=a1)].sort_values('f')
        ok=len(q)==4; why='' if ok else f'closed_rows_{len(q)}'
        if ok and abs((q.f.iloc[-1]-a1).days)>7: ok=False; why='q4_not_within_7d_of_annual'
        if ok and q.f.nunique()!=4: ok=False; why='closed_rows_not_unique'
        qmap={n:(q.iloc[n-1] if n<=len(q) else None) for n in range(1,5)} if ok else None
        d.update(kind='closed',n=len(q),ok=ok,why=why,qmap=qmap,end=a1); return d
    # NOT CLOSED: k due quarters need exactly one unique row each (lag 0..LAG); a not-yet-due quarter's row, if present,
    # must map uniquely; if absent, not a failure. Row->quarter assignment by date windows (52/53-week tolerant):
    # quarter n window = (b[n-1], b[n]], b0 = prior annual end, b1..b3 = nominal quarter-end + 7 d, b4 = annual end if
    # present else nominal FY end + 7 d.
    upper=a1 if a1 is not None else me(Y,m)+dt.timedelta(7)
    b=[a0]+[qend(Y,m,n)+dt.timedelta(7) for n in (1,2,3)]+[upper]
    q=rows[(rows.f>a0)&(rows.f<=upper)].sort_values('f')
    qmap={}; why=[]
    for n in range(1,5):
        qn=q[(q.f>b[n-1])&(q.f<=b[n])]
        if len(qn)>1: why.append(f'Q{n}_rows_{len(qn)}_nonunique'); qmap[n]=None; continue
        qmap[n]=qn.iloc[0] if len(qn)==1 else None
        if n in dq:
            if len(qn)==0: why.append(f'Q{n}_due_no_row')
            elif not(0<=(qmap[n].r-qmap[n].f).days<=LAG): why.append(f'Q{n}_due_lag_{(qmap[n].r-qmap[n].f).days}')
    d.update(kind='open',n=len(q),ok=not why,why=';'.join(why),qmap=qmap,end=upper,
             notdue_present=[n for n in range(1,5) if n not in dq and qmap.get(n) is not None]); return d
def match(s,Y,n):
    m=M[s]
    if not due(Y,m,n): return 'not_due'
    st=fy_state(s,Y)
    if not st['ok']: return 'fy_'+st['why']
    row=st['qmap'].get(n)
    if row is None: return 'no_row_n'
    lag=(row.r-row.f).days
    return 'OK' if 0<=lag<=LAG else f'lag_{lag}'
tab=[]; lab=[]; nyd=[]
for s in syms:
    if s not in M:
        tab.append(dict(symbol=s,m='',h2_eligible='NO_excluded_S4' if not len(A[A.symbol==s]) else 'NO_ambiguous_m')); continue
    m=M[s]; rows=E[E.symbol==s]
    labs=sorted(C[(C.symbol==s)&C.status.str.startswith('present')&(C.quarter>=LAB_LO)&(C.quarter<=LAB_HI)].quarter)
    Ys=sorted(set(int(L[:4]) for L in labs))
    # S3 scope: label-window FYs plus FYs up to EDGE.year+1, each with >=1 nominal quarter-end on/before edge
    scope=sorted(Y for Y in set(Ys)|set(range(min(Ys+[EDGE.year]),EDGE.year+2)) if any(qend(Y,m,n)<=EDGE for n in range(1,5)))
    closed_fail=[]; open_fail=[]; open_info=[]; closed_n=0; uniq_bad=[]
    for Y in scope:
        st=fy_state(s,Y)
        if st['ann_rows_Y']>1 or st['ann_rows_Ym1']>1: uniq_bad.append(f'FY{Y}')
        if st['kind']=='closed':
            closed_n+=1
            if not st['ok']: closed_fail.append(f"FY{Y}:{st['why']}")
        elif st['kind']=='open':
            open_info.append(f"FY{Y} k={st['k']} rows={st['n']} notdue_present=Q{','.join(map(str,st['notdue_present'])) or '-'}")
            if not st['ok']: open_fail.append(f"FY{Y}:{st['why']}")
        else: closed_fail.append(f"FY{Y}:{st['why']}")
    hist_fail=[]
    for Y in sorted(set(d.year for d in A[A.symbol==s].f)):
        st=fy_state(s,Y)
        if st['kind']=='closed' and not st['ok']: hist_fail.append(f"FY{Y}:{st['why']}")
    lv=rows[[not(0<=(r-f).days<=LAG) for f,r in zip(rows.f,rows.r)]]
    # step 4 (Erratum S4): numerator and denominator = labels of DUE quarters only; not-yet-due labels listed in NOT_YET_DUE
    den=ok=0; nd=0; nd_le_edge=0; reasons={}; offby=[]
    for L in labs:
        Y,n=int(L[:4]),int(L[5])
        if not due(Y,m,n):
            st=fy_state(s,Y); row=st['qmap'].get(n) if st.get('qmap') else None
            nd+=1; nd_le_edge+=qend(Y,m,n)<=EDGE
            nyd.append(dict(symbol=s,m=m,label=L,quarter_end=str(qend(Y,m,n)),due_date=str(due_date(Y,m,n)),
                quarter_end_le_edge='y' if qend(Y,m,n)<=EDGE else 'n',row_present='y' if row is not None else 'n',
                row_fiscalDateEnding=str(row.f) if row is not None else '',row_reportedDate=str(row.r) if row is not None else '',
                fy_state_ok=str(st['ok']),fy_state_why=st['why']))
            continue
        den+=1; r0=match(s,Y,n)
        if r0=='OK': ok+=1
        else: reasons[r0]=reasons.get(r0,0)+1
        rm=rp=''
        if m!=12:
            rm=match(s,Y-1,n); rp=match(s,Y+1,n)
            if r0!='OK' and (rm=='OK' or rp=='OK'): offby.append(f'{L}(-1:{rm},+1:{rp})')
        lab.append(dict(symbol=s,m=m,label=L,nominal_quarter_end=str(qend(Y,m,n)),due_date=str(due_date(Y,m,n)),endyear=r0,shift_minus1=rm,shift_plus1=rp))
    if m!=12:  # 4b "more valid matches" variant over due labels
        dl=[L for L in labs if due(int(L[:4]),m,int(L[5]))]
        cm=sum(match(s,int(L[:4])-1,int(L[5]))=='OK' for L in dl)
        cp=sum(match(s,int(L[:4])+1,int(L[5]))=='OK' for L in dl)
        if cm>ok or cp>ok: offby.append(f'more_valid_shifted(-1:{cm},+1:{cp},end:{ok})')
    else: cm=cp=''
    rate=ok/den if den else float('nan')
    s3_pass=(not closed_fail) and (not open_fail) and not uniq_bad
    s4fail=(ok<den) or bool(offby) or not(rate>=0.9)
    tab.append(dict(symbol=s,m=m,quarterly_rows_dev=len(rows),n_annual_rows=len(A[A.symbol==s]),
        s3_fys=f'FY{scope[0]}-FY{scope[-1]}' if scope else '',
        closed_years_checked=closed_n,closed_year_pass='PASS' if not closed_fail else 'FAIL',closed_year_fail=';'.join(closed_fail),
        open_years=' | '.join(open_info),open_year_pass='PASS' if not open_fail else 'FAIL',open_year_fail=';'.join(open_fail),
        lag_violations_all_dev_rows=len(lv),lag_violation_rows=';'.join(f'{f}/{r}' for f,r in zip(lv.fiscalDateEnding,lv.reportedDate)),
        label_uniqueness='PASS' if not uniq_bad else 'FAIL:'+';'.join(uniq_bad),
        s3_pass='PASS' if s3_pass else 'FAIL',
        step4_labels_due=den,step4_labels_not_yet_due=nd,not_yet_due_qend_le_edge=nd_le_edge,step4_matched=ok,step4_match_rate=round(rate,4),
        step4_fail_reasons=';'.join(f'{k}:{v}' for k,v in sorted(reasons.items())),
        shift_m1_valid=cm,shift_p1_valid=cp,offbyone_findings=len(offby),offbyone_list=';'.join(offby),
        step4_status='REPORT_TO_VICTOR' if s4fail else 'PASS',
        hist_closed_year_fail_info=';'.join(hist_fail),
        h2_eligible='YES' if (s3_pass and not s4fail) else 'NO_pending_victor'))
T=pd.DataFrame(tab); T.to_csv(f'{OUT}/FISCAL_DIAGNOSTIC_S6B.tsv',sep='\t',index=False)
pd.DataFrame(lab).to_csv(f'{OUT}/FISCAL_DIAGNOSTIC_S6B_labels.tsv',sep='\t',index=False)
N=pd.DataFrame(nyd); N.to_csv(f'{OUT}/NOT_YET_DUE.tsv',sep='\t',index=False)
cost=E[(E.symbol=='COST')&(E.r<E.f)]
print('COST rows reportedDate<fiscalDateEnding:'); print(cost[['symbol','fiscalDateEnding','reportedDate','reportTime']].to_string(index=False))
print('all DEV rows with reportedDate<fiscalDateEnding:',int((E.r<E.f).sum()))
print('symbols:',len(syms),'frozen m:',len(M))
for c in ['closed_year_pass','open_year_pass','label_uniqueness','s3_pass','step4_status','h2_eligible']: print(c,dict(T[c].value_counts()))
print('H2 eligible:',' '.join(T[T.h2_eligible=='YES'].symbol))
print('NOT_YET_DUE rows:',len(N),'| quarter_end<=edge:',int((N.quarter_end_le_edge=='y').sum()),'| row_present y:',int((N.row_present=='y').sum()))
print('step4 labels due total:',int(T.step4_labels_due.sum()),'matched:',int(T.step4_matched.sum()))
print(T.drop(columns=['lag_violation_rows','hist_closed_year_fail_info']).to_string(index=False))
print('NOT_YET_DUE:'); print(N.to_string(index=False))
