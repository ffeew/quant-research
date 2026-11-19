"""Supplied signed-cost/IR contracts. No filesystem, imports of market readers or fetches."""
from dataclasses import dataclass
from datetime import datetime,time
from decimal import Decimal as D
import hashlib,json,re
from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, clock, ET
from quant_research.strategies.rank1_single_name import rank1_cost as costs

class SignedCostAdapter:
    def __init__(self,raw,expected_sha,virtual_sources,mock=False,sigma_contract=None):
        if mock is not True:raise Blocked("production signed-schema adapter adoption disabled")
        if hashlib.sha256(raw).hexdigest()!=expected_sha:raise Blocked("cost schedule bytes differ")
        self.sigma_contract=sigma_contract
        self.s=json.loads(raw,parse_float=D)
        s=self.s
        if s.get("synthetic_only") is not True:raise Blocked("fabricated metadata only in this workstream")
        if s.get("schema")!="rank1_single_name_cost_binding/1" or s.get("status")!="BINDING_RAISE_ONLY_SIGNED":raise Blocked("binding signed schema required")
        if s.get("signed_by")!="SYNTHETIC_TOMAS" or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} SGT",s.get("signed_at","")):raise Blocked("mock signature/timestamp missing")
        if not s.get("statement") or "raise-only" not in s["statement"]:raise Blocked("raise-only statement missing")
        if s.get("units")!="bp per leg (one-way); round trip = actual entry leg + actual exit leg":raise Blocked("cost units mismatch")
        v=s.get("validity",{})
        if v.get("from")!="Rank1 freeze (Victor pin)" or v.get("until")!="Rank1 evaluation receipt" or v.get("no_expiry_before_evaluation_receipt") is not True:raise Blocked("cost expiry conflict")
        if not s.get("sources"):raise Blocked("cost source pins absent")
        for key,src in s["sources"].items():
            if key not in virtual_sources or hashlib.sha256(virtual_sources[key]).hexdigest()!=src.get("sha256"):raise Blocked("cost source hash mismatch")
        self.fees=s.get("fees",{})
        if not self.fees.get("intervals") or "sec_transition_guards" not in self.fees:raise Blocked("dated fee schema missing")
        for side in ("buy","sell"):
            for comp in ("SEC_SECTION_31","FINRA_TAF","CAT"):
                rows=sorted((r for r in self.fees["intervals"] if r["component"]==comp and r["side"]==side),key=lambda r:r["effective_from"])
                if not rows:raise Blocked("fee side/component absent")
                previous=None
                for row in rows:
                    a,b=row["effective_from"],row["effective_to"];costs.iso_day(a);costs.iso_day(b)
                    if a>b or previous is not None and a<=previous:raise Blocked("overlapping/reversed fee range")
                    costs.rational(row["simulation_rate"]);previous=b
        if "S12_ETHAN_COST_INPUTS" not in s["sources"]:raise Blocked("signed 09:31 source-chain identity missing")
        self.benchmark_sha=s["sources"]["S12_ETHAN_COST_INPUTS"]["sha256"]
        self.bucket=s.get("bucket_lower_bounds_bp",{})
        for i in range(4):
            row=self.bucket.get("L"+str(i+1),{})
            for key,want in (("h_default_half_bp",costs.DEFAULT[i]),("b_paper_bp",costs.PAPER[i])):
                if D(str(row.get(key,-1)))!=want:raise Blocked("unsigned model change")
            if D(str(row.get("entry_c_lower_bound_bp",-1)))<costs.ENTRY_MIN[i] or D(str(row.get("exit_c_lower_bound_bp",-1)))<costs.EXIT_MIN[i]:raise Blocked("signed minima lowered")
            costs.halfspread0931(row.get("m0931_half_bp"),"half_bp","09:31",self.benchmark_sha)
    def sigma_estimator_pin(self):
        from quant_research.strategies.rank1_single_name.rank1_sigma import validate_contract, SIGMA_DEFINITION_SHA256
        validate_contract(self.sigma_contract)
        return SIGMA_DEFINITION_SHA256
    def cash_terminal_leg(self,day,qty,consideration,adv,sigma,ledger):
        # Conservative ordinary SELL fee applied to consideration; no caller fee API.
        px=D(str(consideration))
        if px<=0:raise Blocked("positive cash terminal consideration required")
        result=self.leg("sell",day,qty,px,adv,sigma,ledger)
        if result["fee_bp"]<=0:raise Blocked("Q6 nonzero cash terminal fee=0 REFUSED")
        return result
    def measurement(self,adv):
        row=self.bucket["L"+str(costs.bucket(adv)+1)]
        return dict(value=str(row["m0931_half_bp"]),unit="half_bp",basis="09:31",source_sha=self.benchmark_sha)
    def leg(self,side,day,qty,price,adv,sigma,ledger):
        n=D(str(qty))*D(str(price))
        f=costs.fee_bps(self.fees,side,day,[(str(qty),str(price))],str(n))
        if side=="sell" and f<=0:raise Blocked("Q6 positive sale total fee=0 REFUSED; legitimate zero components stay valid")
        r=costs.leg_cost(str(adv),str(sigma),str(n),f,side=="buy",self.measurement(adv))
        b=costs.bucket(adv);row=self.bucket["L"+str(b+1)]
        r["c_bp"]=max(r["c_bp"],D(str(row["entry_c_lower_bound_bp" if side=="buy" else "exit_c_lower_bound_bp"])))
        r["all_in_bp"]=costs.all_in_bp(r["c_bp"],ledger,day)
        r["transaction_usd"]=n*(r["all_in_bp"]-10)/10000
        r["buffer_usd"]=n*D(10)/10000
        r["all_in_usd"]=r["transaction_usd"]+r["buffer_usd"]
        return r
    def bounded_terminal(self,n,entry_adv,entry_sigma,last_adv,day,ledger,identity,time_proof):
        r=costs.terminal_cost(str(n),str(entry_adv),str(entry_sigma),day,ledger,identity,time_proof,last_adv=last_adv,measurement=self.measurement(entry_adv))
        row=self.bucket["L"+str(r["bucket"]+1)]
        r["c_bp"]=max(r["c_bp"],D(str(row["exit_c_lower_bound_bp"])))
        r["all_in_bp"]=costs.all_in_bp(r["c_bp"],ledger,day)
        r["transaction_usd"]=D(str(n))*(r["all_in_bp"]-10)/10000
        r["buffer_usd"]=D(str(n))*10/10000
        r["all_in_usd"]=r["transaction_usd"]+r["buffer_usd"]
        return r

@dataclass(frozen=True)
class IRSnapshot:
    issuer:str
    version:str
    known_at:str
    next_release:str
    coverage_through:str
    date_only:bool=False
    synthetic_only:bool=False
    def release(self):
        if self.date_only:
            from datetime import date
            return datetime.combine(date.fromisoformat(self.next_release),time(0),ET)
        return clock(self.next_release)

class IRCalendar:
    def __init__(self,rows):
        self.rows=tuple(rows)
        for r in rows:
            if r.synthetic_only is not True or not r.issuer.startswith("SYNTH_"):raise Blocked("fabricated IR only")
            clock(r.known_at);clock(r.coverage_through);r.release()
    def at(self,issuer,cutoff,planned_exit):
        rows=[r for r in self.rows if r.issuer==issuer and clock(r.known_at)<cutoff]
        if not rows:raise Blocked("as-known positive IR schedule missing")
        latest=max(clock(r.known_at) for r in rows);latest_rows=[r for r in rows if clock(r.known_at)==latest]
        if len({(r.next_release,r.coverage_through,r.date_only) for r in latest_rows})!=1:raise Blocked("IR tied-clock conflict")
        row=min(latest_rows,key=lambda r:r.version)
        if clock(row.coverage_through)<planned_exit:raise Blocked("IR coverage does not extend through planned exit")
        return row
    def admit(self,issuer,cutoff,exit_open):return self.at(issuer,cutoff,exit_open).release()>exit_open
    def force_exit(self,issuer,cutoff,exit_open,current_open=None):return self.at(issuer,cutoff,max(exit_open,current_open or exit_open)).release()<=exit_open
