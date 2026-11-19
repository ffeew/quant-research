"""Rank1 cost arithmetic kernels, signed-spec constants, synthetic tests only.
No source-data reader. Caller inputs are explicitly fabricated in the test suite.
Fee math follows pinned fee_exact_v4.py, reimplemented locally (never imported/executed).
"""
from decimal import Decimal, localcontext
from fractions import Fraction
from datetime import date
import math
import re
from quant_research.strategies.rank1_single_name.rank1_core import Blocked, hash_shape

D=Decimal

def rational(x):
    if isinstance(x,(bool,float)) or not isinstance(x,(str,int,Decimal,Fraction)):
        raise Blocked("exact decimal/rational required, no float/bool")
    if isinstance(x,str) and re.fullmatch(r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",x.strip()) is None:
        raise Blocked("canonical nonnegative decimal string required")
    try:
        v=Fraction(x)
    except (ValueError,OverflowError,ZeroDivisionError) as e:
        raise Blocked("invalid finite rational") from e
    if v<0: raise Blocked("negative input")
    return v

def decimal(x):
    f=rational(x)
    with localcontext() as ctx:
        ctx.prec=50
        return D(f.numerator)/D(f.denominator)

def cents(x):
    return Fraction(math.ceil(rational(x)*100),100)

def iso_day(s):
    try:
        d=date.fromisoformat(s)
    except (ValueError,TypeError) as e:
        raise Blocked("invalid session date") from e
    if d.isoformat()!=s: raise Blocked("canonical YYYY-MM-DD required")
    return s

def fee_lookup(fees, component, side, day):
    iso_day(day)
    if side not in {"buy","sell"}: raise Blocked("invalid side")
    rows=[r for r in fees["intervals"] if r["component"]==component and r["side"]==side
          and r["effective_from"]<=day<=r["effective_to"]]
    if len(rows)!=1: raise Blocked("fee interval missing/overlapping; no extrapolation")
    row=rows[0]
    rate=rational(row["simulation_rate"])
    if component=="SEC_SECTION_31" and side=="sell":
        guards=[g for g in fees["sec_transition_guards"] if day in g["guard_sessions"]]
        if len(guards)>1: raise Blocked("overlapping SEC guards")
        if guards: rate=rational(guards[0]["guard_rate"])
    cap=row.get("cap_usd_per_trade")
    return rate, None if cap is None else rational(cap)

def fill_fees(fees,side,day,qty,price):
    q,p=rational(qty),rational(price)
    if q.denominator!=1 or q<=0 or p<=0: raise Blocked("positive whole shares/price required")
    out={}
    for comp in ("SEC_SECTION_31","FINRA_TAF","CAT"):
        rate,cap=fee_lookup(fees,comp,side,day)
        raw=rate*q*p if comp=="SEC_SECTION_31" else rate*q
        if comp=="FINRA_TAF" and cap is not None: raw=min(raw,cap)
        out[comp]=cents(raw)  # per component, PER FILL; never aggregate then round
    return out

def fee_bps(fees,side,day,fills,reference_notional):
    q=rational(reference_notional)
    if q<=0 or not fills: raise Blocked("positive leg notional/fills required")
    total=sum((sum(fill_fees(fees,side,day,qt,px).values(),Fraction()) for qt,px in fills),Fraction())
    return total/q*10000  # no additional independent fee stress; stress the final c once

# Exact one-way basis-point inputs from signed schedule 27a77d7d...94263, not new TCA.
DEFAULT=tuple(map(D,("2.75","5","12","30")))
FIXED=tuple(map(D,("5","5","10","20")))
PAPER=tuple(map(D,("2","4","8","15")))
UPLIFT=tuple(map(D,("15.1","28.6","52.9","73.8")))
ENTRY_MIN=tuple(map(D,("20","28.6","52.9","80")))
EXIT_MIN=tuple(map(D,("20","20","22","50")))

def bucket(adv):
    a=decimal(adv)
    if a<=0: raise Blocked("no valid ADV; cannot invent liquidity")
    if a>D("1000000000"): return 0
    if a>D("200000000"): return 1
    if a>=D("50000000"): return 2  # exactly 200M is L3; 1B is L2
    return 3

def halfspread0931(value,unit,basis,source_sha):
    if basis!="09:31" or not hash_shape(source_sha):
        raise Blocked("09:31 time/source evidence missing; no substitute")
    v=decimal(value)
    if v<=0: raise Blocked("missing/zero measurement not a default-only pass")
    if unit=="full_relative_bp": return v/D(2)
    if unit=="half_bp": return v
    raise Blocked("spread units not certified; no dollar-spread/mid inference")

def _c(adv,sigma,notional,f_bp,entry,m0931_half=None,forced_bucket=None):
    with localcontext() as ctx:
        ctx.prec=50
        a,q,s,f=map(decimal,(adv,notional,sigma,f_bp))
        if q<=0: raise Blocked("positive notional required; lagged sigma may be verified zero")
        b=bucket(a)
        if forced_bucket is not None:
            if type(forced_bucket) is not int or not b<=forced_bucket<=3:
                raise Blocked("terminal fallback may only raise bucket")
            b=forced_bucket
        if entry and (m0931_half is None or decimal(m0931_half)<=0):
            raise Blocked("entry 09:31 benchmark required even when 2h binds")
        h=max(2*DEFAULT[b],decimal(m0931_half)) if entry else DEFAULT[b]
        impact=s*(q/a).sqrt()*10000
        floor=FIXED[b]+h
        model=f+h+impact+PAPER[b]
        c=max(D(20),floor,model,UPLIFT[b] if entry else D(0),ENTRY_MIN[b] if entry else EXIT_MIN[b])
        return {"bucket":b,"h_eff_bp":h,"impact_bp":impact,"fee_bp":f,"c_bp":c}

def leg_cost(adv,sigma,notional,f_bp,entry,measurement=None):
    if type(entry) is not bool: raise Blocked("entry must be boolean")
    # Verify measurement identity/units/time for EVERY ordinary leg (signed fail-closed term).
    if measurement is None: raise Blocked("09:31 benchmark/source evidence absent")
    half=halfspread0931(**measurement)
    return _c(adv,sigma,notional,f_bp,entry,half)

def all_in_bp(c,ledger,day):
    iso_day(day)
    c=decimal(c)
    if c<20: raise Blocked("signed c floor cannot be lowered")
    if ledger=="primary": mult=1
    elif ledger=="global_2x": mult=2
    elif ledger=="shock": mult=2 if "2020-03-02"<=day<="2020-06-30" else 1
    else: raise Blocked("undeclared cost ledger; no combined/global-shock 4c")
    return mult*c+D(10)  # epistemic buffer outside c and NOT doubled

def terminal_cost(entry_notional,entry_adv,entry_sigma,day,ledger,identity_proof,effective_time_proof,
                  terminal_adv=None,terminal_sigma=None,last_adv=None,measurement=None):
    if identity_proof is not True or effective_time_proof is not True:
        raise Blocked("terminal identity and effective-time evidence mandatory")
    n=decimal(entry_notional)
    if n<=0: raise Blocked("entry notional must be positive")
    if entry_adv is None and terminal_adv is None:
        raise Blocked("ADV missing at both points")
    if measurement is None: raise Blocked("verified benchmark/source required for terminal bucket")
    halfspread0931(**measurement)
    fallback=terminal_adv is None or terminal_sigma is None
    if fallback:
        if entry_adv is None or entry_sigma is None: raise Blocked("fallback lagged inputs missing")
        b=min(bucket(entry_adv)+1,3)
        if last_adv is not None: b=max(b,bucket(last_adv))
        # Entry/default sigma assumption; entry ADV is used for impact, never an invented quote.
        c=_c(entry_adv,entry_sigma,n,0,False,forced_bucket=b)
    else:
        c=_c(terminal_adv,terminal_sigma,n,0,False)
    bp=all_in_bp(c["c_bp"],ledger,day)
    return {**c,"all_in_bp":bp,"cost_usd":n*bp/D(10000),"economic_writeoff_usd":-n,
            "fee_bp":D(0),"fallback_count":int(fallback),"basis":"ORIGINAL_ENTRY_NOTIONAL"}
