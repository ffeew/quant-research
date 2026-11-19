"""Carry data-coverage inventory. Coverage/availability only: computes NO returns or performance.
Never opens bars/daily/extended/ (sealed) or releases/*/bars/daily/extended/."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, json, glob, os, hashlib
import pandas as pd, numpy as np
sys.path.insert(0, f'{_QR.DATA_DIR}/lib'); from quant_research.data.client import desk_data_client as ddc
D=f'{_QR.DATA_DIR}'
out={}
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
# --- ALFRED groups
for g,d in [('treasury','macro/treasury'),('treasury_extra','macro/treasury'),('g10_3m','macro/carry/g10_3m'),('credit','sentiment/credit')]:
    v=pd.read_parquet(f'{D}/{d}/{g}_vintages_20261030.parquet')
    f=pd.read_parquet(f'{D}/{d}/{g}_pit_first_available_20261030.parquet')
    rows={}
    for s,x in f.groupby('series_id'):
        xv=x.dropna(subset=['value'])
        lag=(pd.to_datetime(x.loc[~x.pre_alfred,'available_at_et'].astype(str).str[:19])-pd.to_datetime(x.loc[~x.pre_alfred,'observation_date'])).dt.days
        rows[s]=dict(obs_start=str(x.observation_date.min())[:10],obs_end=str(x.observation_date.max())[:10],
                     n_obs=int(len(x)),n_nan_first=int(x.value.isna().sum()),n_pre_alfred=int(x.pre_alfred.sum()),
                     last_pre_alfred_obs=str(x.loc[x.pre_alfred,'observation_date'].max())[:10] if x.pre_alfred.any() else None,
                     first_avail_et=str(x.available_at_et.min()),last_avail_et=str(x.available_at_et.max()),
                     median_lag_days_genuine=float(lag.median()) if len(lag) else None,
                     n_vintage_rows=int((v.series_id==s).sum()),n_revised=int(x.revised.sum()) if 'revised' in x else None)
    out[g]=rows
# --- as-of spot checks via the sanctioned loader (store reads)
chk={}
a=ddc.alfred_asof('DGS30','2020-07-01 17:00'); a=a.set_index('observation_date')['value'] if 'observation_date' in a else a
b=ddc.alfred_asof('DGS30','2020-08-01 17:00'); b=b.set_index('observation_date')['value'] if 'observation_date' in b else b
m=(pd.to_datetime(a.index)>= '2004-06-01')&(pd.to_datetime(a.index)<'2004-07-01')
chk['DGS30_2004-06_nonNaN_asof_2020-07-01']=int(a[m].notna().sum()); 
m2=(pd.to_datetime(b.index)>= '2004-06-01')&(pd.to_datetime(b.index)<'2004-07-01')
chk['DGS30_2004-06_nonNaN_asof_2020-08-01']=int(b[m2].notna().sum())
for s in ['IR3TIB01EZM156N','IR3TIB01GBM156N','IR3TIB01JPM156N','IR3TIB01USM156N']:
    z=ddc.alfred_asof(s,'2026-10-29 17:00')
    z=z.set_index('observation_date')['value'] if 'observation_date' in z else z
    chk[f'{s}_last_obs_asof_2026-10-29']=str(pd.to_datetime(z.dropna().index).max())[:10]
out['asof_checks']=chk
# --- ETFs in non-extended 2016+ daily bars
etfs="SPY QQQ IWM DIA XLB XLC XLE XLF XLI XLK XLP XLRE XLU XLV XLY SMH EFA EEM EWJ EWZ FXI EWG EWU INDA EWY EWT EWA EWC TLT IEF SHY LQD HYG TIP AGG BND BIL GLD SLV USO DBC UNG DBA UUP FXE FXY FXB FXA FXC IEI BWX IGOV EMB SHV SCHP GOVT VGSH VGIT VGLT EDV ZROZ SPTL CPER PDBC GSG FXF".split()
snap=pd.read_parquet(f'{D}/assets/snapshots/assets_2026-10-29.parquet')
snap=snap.set_index('symbol') if 'symbol' in snap else snap
divs=pd.read_parquet(f'{D}/corporate_actions/dividends.parquet')
symcol='symbol' if 'symbol' in divs else divs.columns[0]
e={}
for s in etfs:
    p=f'{D}/bars/daily/adjusted/{s}.parquet'
    if not os.path.exists(p): e[s]=dict(in_store=False); continue
    b=pd.read_parquet(p,columns=['session_date','close','volume'])
    rp=f'{D}/bars/daily/raw/{s}.parquet'; r=pd.read_parquet(rp,columns=['session_date','close','volume'])
    r=r.sort_values('session_date'); dv=(r.close*r.volume).tail(252)
    row=dict(in_store=True,start=str(b.session_date.min())[:10],end=str(b.session_date.max())[:10],rows=len(b),
             median_dollar_vol_last252_musd=round(float(dv.median())/1e6,1),
             n_dividends=int((divs[symcol]==s).sum()))
    if s in snap.index:
        q=snap.loc[s]; row.update(shortable=bool(q.get('shortable')),easy_to_borrow=bool(q.get('easy_to_borrow')),tradable=bool(q.get('tradable')))
    e[s]=row
out['etfs']=e
out['hashes']={p:sha(f'{D}/{p}') for p in ['bars/daily/total_return/daily_total_return.parquet','assets/snapshots/assets_2026-10-29.parquet','corporate_actions/dividends.parquet','VERSION'] }
out['VERSION']=open(f'{D}/VERSION').read().strip()
json.dump(out,open('inventory_check_output.json','w'),indent=1,default=str)
print(json.dumps(out,indent=1,default=str))
