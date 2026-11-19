"""Fabricated-only integration facade; no disk/data acquisition or production activation."""
from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, configurations, report, evaluate_synthetic_dev, DevSummary
from quant_research.strategies.rank1_single_name.rank1_news import NewsCompiler
from quant_research.strategies.rank1_single_name.rank1_book import FixtureBook
from quant_research.strategies.rank1_single_name.rank1_gates import sharpe
from statistics import mean

def evaluate_fabricated_card(market,ir,cost,aliases,selected,stories,scorer_factory,start,end,complete_buckets,synthetic_only=False):
    if synthetic_only is not True:raise Blocked("NO real-data evaluator in this bundle")
    output={name:{} for name in ("primary","global_2x","shock")}
    for cfg in configurations():
        for ledger in output:
            compiler=NewsCompiler(market.cal,aliases,selected,scorer_factory())
            prepared=compiler.prepare(stories,cfg)
            book=FixtureBook(market,ir,cost,cfg,start,end,"NONCASH_BUFFER_PINNED_RF",True)
            book.run(lambda t:compiler.candidates(prepared,cfg,t,complete_buckets),ledger)
            output[ledger][cfg.id]=book
    summaries={}
    for cfg in configurations():
        p,s=output["primary"][cfg.id],output["global_2x"][cfg.id]
        summaries[cfg.id]=DevSummary(len(p.trades),p.occupied_blocks(),float(mean(t.primary_or_path_net_excess for t in p.trades)) if p.trades else 0.,float(mean(t.primary_or_path_net_excess for t in s.trades)) if s.trades else 0.)
    gate=evaluate_synthetic_dev(summaries,True)
    return dict(synthetic_only=True,books=output,dev_gate=gate,claim_labels=gate["claim_labels"],production_enabled=False,capture_active=False,
                claim_label_context=gate["claim_label_context"],pending_semantics=["Q4 signed estimator receipt SATISFIED; Dmitri actual TR-basis certification OPEN; no mock adoption"])

def select_fixture_universe(membership_as_known,selection_clock,ending_session,prior20_sessions,rows,synthetic_only=False):
    from quant_research.strategies.rank1_single_name.rank1_core import clock
    from decimal import Decimal as D
    from statistics import median
    if synthetic_only is not True:raise Blocked("fabricated ex-ante selector only")
    if clock(membership_as_known)>clock(selection_clock):raise Blocked("retrospective membership")
    if len(prior20_sessions)!=20 or len(set(prior20_sessions))!=20 or tuple(sorted(prior20_sessions))!=tuple(prior20_sessions) or prior20_sessions[-1]!=ending_session:raise Blocked("exact prior20 ending sessions required")
    classes={}
    for row in rows:
        if row.get("synthetic_only") is not True or not row["issuer"].startswith("SYNTH_"):raise Blocked("fabricated universe rows")
        if row["session"] not in prior20_sessions or clock(row["known_at"])>clock(selection_clock) or row.get("SIP") is not True or row.get("split_treatment_evidenced") is not True:raise Blocked("liquidity/vintage proof invalid")
        key=row["issuer"],row["ticker"]
        if row["session"] in classes.setdefault(key,{}):raise Blocked("duplicate liquidity session")
        close,volume=D(str(row["unadjusted_close"])),D(str(row["volume"]))
        if not close.is_finite() or not volume.is_finite() or min(close,volume)<=0:raise Blocked("invalid liquidity input")
        classes[key][row["session"]]=close*volume
    selected={}
    for (issuer,ticker),values in classes.items():
        if set(values)!=set(prior20_sessions):raise Blocked("missing selection observation")
        adv=median(values.values())
        if adv<D(1000000000):continue
        if issuer not in selected or (-adv,ticker)<(-selected[issuer][1],selected[issuer][0]):selected[issuer]=(ticker,adv)
    return tuple((issuer,ticker,adv) for issuer,(ticker,adv) in sorted(selected.items(),key=lambda r:(-r[1][1],r[1][0]))[:100])


def evaluate_fabricated_oos(card,factor_rows,labels,units,missing_codes,N,sigma,reference_receipt,family_receipt,concentration_policy,synthetic_only=False):
    """Full numeric wiring on fabricated books. Missing PCG64 remains a binding insufficiency.
    No source file read; external data/semantic authority is ALWAYS blocked.
    """
    from quant_research.strategies.rank1_single_name import rank1_inference as inf
    from quant_research.strategies.rank1_single_name import rank1_gates as gates
    if synthetic_only is not True or card.get("synthetic_only") is not True:raise Blocked("fabricated OOS only")
    books=card["books"];base=books["primary"]["H48"];days=tuple(r["day"] for r in base.rows)
    columns={}
    for key,b in books["primary"].items():
        if tuple(r["day"] for r in b.rows)!=days:raise Blocked("all23 native books must retain identical sessions")
        columns[key]=tuple(float(r["excess"]) for r in b.rows)
    matrix=inf.SyntheticMatrix(days,columns,True)
    numeric=[];reg=[];diagnostics={};common_missing=[]
    for key in ("H48","H120"):
        b=books["primary"][key]
        if len(factor_rows)!=len(b.rows):raise Blocked("factor/native date coverage mismatch")
        prepared=[]
        allowed={"day","synthetic_only",*(k for k in inf.FACTOR_FIELDS if k!="z")}
        for row,native in zip(factor_rows,b.rows):
            if set(row)!=allowed or row["day"]!=native["day"].isoformat():raise Blocked("factor schema/date mismatch; z must come from holdings")
            prepared.append(dict(row,z=float(native["z"])))
        factors=inf.join_synthetic_factors(days,prepared,units,missing_codes,True)
        if any(str(r["RF"])!=str(float(n["rf"])) for r,n in zip(factors,b.rows)):raise Blocked("factor RF must equal native study RF after once-only normalization")
        alpha=dsr=None
        try:alpha=inf.nw20_synthetic(columns[key],factors,True)["detail"]["alpha_t"]
        except Insufficient:common_missing.append(key+" regression insufficient")
        try:dsr=inf.dsr_synthetic(matrix,key,N,sigma,reference_receipt,family_receipt)["detail"]["DSR"]
        except Insufficient:common_missing.append(key+" DSR insufficient")
        qn,fn=gates.baseline_numbers(b,books["global_2x"][key],alpha,dsr,None)
        numeric.append(([key+": "+s for s in qn],[key+": "+s for s in fn]))
        q,f,detail=gates.regimes_covid_concentration(b,books["global_2x"][key],books["shock"][key],labels[key],concentration_policy)
        reg.append(([key+": "+s for s in q],[key+": "+s for s in f]));diagnostics[key]=detail
    pbo=None
    try:pbo=inf.pbo_synthetic(matrix)["detail"]["pbo"]
    except Insufficient:common_missing.append("card23 PBO insufficient")
    robustness=gates.robustness_numbers(books["primary"],books["global_2x"])
    merged_reg=([x for q,_ in reg for x in q]+common_missing,[x for _,f in reg for x in f],diagnostics)
    result=gates.aggregate_oos(numeric,robustness,merged_reg,pbo,False,False)
    result["bootstrap_dependency"]="MISSING_APPROVED_EXACT_PCG64_LOCK; not executed"
    result["card_columns"]=23;result["family_floor"]=177
    return result


LOCKED_PLAN={
 "DEV_start":"2016-01-04","DEV_end":"2019-12-31",
 "embargo_start":"2020-01-02","embargo_end":"2020-02-28",
 "evaluation_start":"2020-03-02","evaluation_end":"2025-05-22",
 "news_warmup_start":"2015-11-02","news_warmup_end":"2015-12-31",
 "seen_tail_start":"2025-06-02","seen_tail_end":"2026-10-30",
 "U2015_selection_ET":"2015-12-31T16:00:00-05:00","liquidity_end":"2015-12-30",
 "card_configs":23,"family_floor":177,"optional_in_PBO":False,"optional_activated":False}

def validate_locked_plan_metadata(plan):
    if not isinstance(plan,dict) or plan!=LOCKED_PLAN or any(type(plan[k]) is not type(v) for k,v in LOCKED_PLAN.items()):raise Blocked("frozen dates/universe/count/option metadata changed; no tuning or reselection")
    return True # METADATA EQUALITY ONLY, never an authorization or actual freeze
