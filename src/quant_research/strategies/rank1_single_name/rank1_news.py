"""Exact parent04 extraction kernels on FABRICATED in-memory records only."""
from dataclasses import dataclass
from html.parser import HTMLParser
import html,re,hashlib,json,math
from urllib.parse import urlsplit,urlunsplit
from decimal import Decimal
from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, clock, usable_at, ET, hash_shape

NEUTRAL="tax taxes cost costs capital capitals board boards liability liabilities foreign vice vices mine mines cancer cancers crude tire tires".split()
EXCLUSIONS=("earnings","eps","quarterly results","financial results","guidance","dividend","buyback","merger","acquisition","rumor","rumour","sponsored","opinion","roundup","round-up","recap")
ANALYST=("upgrades","downgrades","initiates","reinstates","maintains","reiterates","price target")
RATINGS=sorted(("strong buy","outperform","overweight","positive","buy"),key=lambda x:(-len(x),x))
STOP=set("this that with from will have been company shares stock".split())

def phrases(text,items):
    return any(re.search(r"(?<![A-Za-z0-9])"+r"\s+".join(map(re.escape,x.split()))+r"(?![A-Za-z0-9])",text,re.I) for x in items)

class _Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.hidden=[];self.nodes=[]
    def handle_starttag(self,tag,attrs):
        if tag in {"script","style"}:self.hidden.append(tag)
    def handle_endtag(self,tag):
        if tag in self.hidden:
            i=len(self.hidden)-1-self.hidden[::-1].index(tag);self.hidden=self.hidden[:i]
    def handle_data(self,data):
        if not self.hidden:self.nodes.append(data)

def normalize(text):
    if text is None:return ""
    if not isinstance(text,str):raise Blocked("text type")
    p=_Text();p.feed(text);p.close()
    return " ".join(html.unescape(" ".join(p.nodes)).split())

def literal(text,alias):
    return bool(re.search(r"(?<![A-Za-z0-9])"+re.escape(alias)+r"(?![A-Za-z0-9])",text,re.I))

def canonical(url):
    if not url:return None
    try:
        u=urlsplit(url)
        if not u.scheme or not u.hostname:raise ValueError()
        # Preserve userinfo/port/path case; lowercase scheme and host ONLY.
        host=u.hostname.lower();host=("["+host+"]") if ":" in host else host
        auth=u.netloc.rsplit("@",1)[0]+"@" if "@" in u.netloc else ""
        port=(":"+str(u.port)) if u.port is not None else ""
        return urlunsplit((u.scheme.lower(),auth+host+port,u.path.rstrip("/"),"",""))
    except (ValueError,TypeError) as e:raise Blocked("malformed URL; no guessed canonical") from e

def tokens(text):return {s for s in re.findall("[a-z]+",text.lower()) if len(s)>=4 and s not in STOP}
def jaccard(a,b):
    a,b=tokens(a),tokens(b);return len(a&b)/len(a|b) if a|b else 0

@dataclass(frozen=True)
class Alias:
    issuer:str
    literal:str
    ticker:bool
    valid_from:str
    valid_to:str
    known_at:str
    def valid(self,t):return clock(self.valid_from)<=t<clock(self.valid_to) and clock(self.known_at)<=t

@dataclass(frozen=True)
class Story:
    id:str
    headline:str
    summary:object
    symbols:tuple
    created:str
    updated:str
    retrieved:str
    url:object=None
    source:str="benzinga"
    synthetic_only:bool=False
    payload_version_hash:object=None

@dataclass(frozen=True)
class Prepared:
    story:Story
    issuer:str
    headline:str
    summary:str
    k:object

@dataclass(frozen=True)
class Candidate:
    issuer:str
    ticker:str
    action_id:str
    k:object
    score:Decimal
    background_ids:tuple
    synthetic_only:bool=True

class FinanceScorer:
    """Pinned-artifact interface tested with VIRTUAL mock bytes/analyzers only.
    Actual VADER execution remains prohibited; no import/install fallback.
    """
    COMPONENTS={"vader_fin.py","METADATA","RECORD","__init__.py","vaderSentiment.py","vader_lexicon.txt","emoji_utf8_lexicon.txt","LICENSE","runtime_lock","neutral_list"}
    def __init__(self,analyzer,virtual_bytes,pins,mock=False):
        if mock is not True:raise Blocked("actual scorer package/runtime not accepted; production disabled")
        if set(virtual_bytes)!=self.COMPONENTS or set(pins)!=self.COMPONENTS:raise Blocked("all scorer component pins required")
        for k in self.COMPONENTS:
            if hashlib.sha256(virtual_bytes[k]).hexdigest()!=pins[k]:raise Blocked("scorer byte mismatch")
        metadata=virtual_bytes["METADATA"].decode()
        if not re.search(r"^Name: vaderSentiment$",metadata,re.M) or not re.search(r"^Version: 3\.3\.2$",metadata,re.M):raise Blocked("not requested package/version")
        words=[line.strip() for line in virtual_bytes["neutral_list"].decode().splitlines() if line.strip() and not line.startswith("#")]
        if words!=NEUTRAL:raise Blocked("neutral list changed")
        self.analyzer=analyzer
        for w in NEUTRAL:self.analyzer.lexicon.pop(w,None)
    def score(self,text):
        v=self.analyzer.polarity_scores(text)["compound"]
        if isinstance(v,bool) or not isinstance(v,(float,int,Decimal)) or not math.isfinite(v) or not -1<=v<=1:raise Blocked("invalid compound")
        return Decimal(str(v))  # retain returned rounding; no new rescale/round

class FixedFixtureScorer:
    def __init__(self,values):self.values=values;self.calls=[]
    def score(self,text):
        self.calls.append(text)
        if text not in self.values:raise Blocked("no fabricated score supplied; cannot call actual scorer")
        v=Decimal(str(self.values[text]))
        if not v.is_finite() or not -1<=v<=1:raise Blocked("invalid fabricated score")
        return v

def final_versions(stories):
    by={}
    for s in stories:
        if s.synthetic_only is not True:raise Blocked("fabricated story marker required")
        if not isinstance(s.id,str) or not s.id:raise Blocked("provider string ID required")
        usable_at(s.created,s.updated,s.retrieved,48) # clock validation before resolution
        if s.payload_version_hash is not None and not hash_shape(s.payload_version_hash):raise Blocked("invalid supplied payload/version hash")
        if s.id in by:
            old=by[s.id]
            if clock(s.updated)==clock(old.updated):
                if s.payload_version_hash is not None and old.payload_version_hash is not None and s.payload_version_hash!=old.payload_version_hash:raise Blocked("same clock conflicting supplied payload hashes; no body access required")
                payload=lambda x:(x.headline,x.summary,x.symbols,x.url,x.source,x.created)
                if payload(s)!=payload(old):raise Blocked("same ID/updated clock different payload conflict")
            if clock(s.updated)>clock(old.updated):by[s.id]=s
        else:by[s.id]=s
    return tuple(by.values())

class NewsCompiler:
    def __init__(self,calendar,aliases,selected,scorer):
        self.calendar=calendar;self.aliases=tuple(aliases);self.selected=dict(selected);self.scorer=scorer
        if any(not i.startswith("SYNTH_") for i in selected):raise Blocked("fabricated cohort namespace")
    def prepare(self,stories,config):
        out=[]
        for s in final_versions(stories):
            k=usable_at(s.created,s.updated,s.retrieved,config.delay,config.never_edited)
            if k is None or s.source.casefold()!="benzinga" or len(s.symbols)!=1:continue
            c=clock(s.created)
            hits={a.issuer for a in self.aliases if a.ticker and a.literal.casefold()==s.symbols[0].casefold() and a.valid(c)}
            if len(hits)!=1:raise Blocked("unknown/ambiguous tagged issuer identity")
            issuer=next(iter(hits))
            if issuer not in self.selected:continue
            # Selected frozen class must itself be valid at usable time, not current ticker.
            if not any(a.issuer==issuer and a.ticker and a.literal==self.selected[issuer] and a.valid(k) for a in self.aliases):raise Blocked("selected class unavailable at usable time")
            h,summary=normalize(s.headline),normalize(s.summary)
            if not h or phrases(h+" "+summary,EXCLUSIONS):continue
            out.append(Prepared(s,issuer,h,summary,k))
        return tuple(out)
    def action(self,p):
        h=p.headline
        if phrases(h,("initiates","reinstates","maintains","reiterates")) or (phrases(h,("upgrades",)) and phrases(h,("downgrades",))):return None
        m=re.fullmatch(r"(.+?)\s+(upgrades|downgrades)\s+(.+?)\s+to\s+(.+)",h,re.I)
        if not m:return None
        broker=" ".join("".join(c for c in m[1].lower() if c.isalnum() or c.isspace()).split())
        if not broker:return None
        names={a.issuer for a in self.aliases if a.valid(clock(p.story.created)) and literal(m[3],a.literal)}
        if names!={p.issuer}:return None
        direction=m[2].lower();dest=m[4].strip()
        if direction=="upgrades" and not any(re.match(re.escape(r)+r"(?![A-Za-z0-9])",dest,re.I) for r in RATINGS):return None
        return broker,direction
    def _bucket(self,k):
        if k>=self.calendar.cutoff(self.calendar.sessions[-1]):return len(self.calendar.sessions)
        s=self.calendar.earliest(k);return self.calendar.sessions.index(s)
    def _anchor(self,k):
        d=k.astimezone(ET).date()
        for i,s in enumerate(self.calendar.sessions):
            if s.day>=d:return i
        raise Insufficient("anchor calendar exhausted")
    def candidates(self,prepared,config,index,complete_buckets):
        acts={}
        for p in prepared:
            if self._bucket(p.k)!=index:continue
            parsed=self.action(p)
            if parsed:
                broker,direction=parsed;key=(p.issuer,broker,direction,clock(p.story.created).astimezone(ET).date())
                if key not in acts or (p.k,p.story.id)<(acts[key].k,acts[key].story.id):acts[key]=p
        veto={p.issuer for key,p in acts.items() if key[2]=="downgrades"};chosen={}
        for key,a in sorted(acts.items(),key=lambda x:(x[1].k,x[1].story.id)):
            if key[2]!="upgrades" or a.issuer in veto or a.issuer in chosen:continue
            if index<20 or not set(range(index-20,index)).issubset(complete_buckets.get(a.issuer,set())):raise Insufficient("20 prior complete buckets required")
            anchor=self._anchor(a.k);lo=anchor-config.background
            if lo<1:raise Insufficient("background history/cutoff warmup absent")
            bg=[p for p in prepared if p.issuer==a.issuer and p.k<a.k and p.summary and not phrases(p.headline,ANALYST) and lo<=self._bucket(p.k)<anchor]
            keep=[];urls=set()
            for p in sorted(bg,key=lambda p:(p.k,p.story.id)):
                u=canonical(p.story.url)
                if u and u in urls:continue
                if any(jaccard(p.headline,q.headline)>=.80 for q in keep):continue
                keep.append(p)
                if u:urls.add(u)
            if len(keep)<config.stories or len({clock(p.story.created).astimezone(ET).date() for p in keep})<2:continue
            mean=sum((self.scorer.score(p.headline+". "+p.summary) for p in keep),Decimal(0))/len(keep)
            if mean<=Decimal(config.tone):chosen[a.issuer]=Candidate(a.issuer,self.selected[a.issuer],a.story.id,a.k,-mean,tuple(p.story.id for p in keep))
        return tuple(sorted(chosen.values(),key=lambda c:(-c.score,c.ticker)))
