"""Standalone Rank1 contract kernels. SYNTHETIC RESEARCH TOOLING; NOT AN UNLOCK.
No network, scorer, archive, parquet or production-data reader is implemented.
"""
from dataclasses import dataclass
from datetime import datetime, date, timedelta, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import math
import re

ET = ZoneInfo("America/New_York")
SHORT_LABEL = "Addendum A incremental value NOT MET; may reflect post-earnings drift"
FULL_LABEL = ("CONDITIONAL HISTORICAL RESEARCH EVIDENCE: STANDARD Addendum A incremental value NOT MET "
              "(no earnings-surprise control); may reflect post-earnings-announcement drift.")
D3_PREFIX = "fixed D3 claim limitation (not a test result)"
FAMILY_FLOOR = 177
REQUIRED_EVIDENCE = frozenset({"B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B11", "B13",
                             "NB2", "NB3", "NB4", "P1", "RIGHTS"})

class Blocked(ValueError):
    """An absent/invalid contract is not a negative investment finding."""

class Insufficient(Blocked):
    pass

def report(disposition, detail):
    if disposition not in {"BLOCKED", "INSUFFICIENT", "FAIL", "SYNTHETIC_ONLY_PASS"}:
        raise Blocked("Production PASS is not supported by this bundle")
    return {"disposition": disposition, "synthetic_only": True, "detail": detail,
            "claim_label_context": D3_PREFIX, "claim_labels": [SHORT_LABEL, FULL_LABEL], "capture_active": False,
            "paper_trade_promote_capital_allowed": False}

def hash_shape(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

def clock(value):
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError, OverflowError) as e:
        raise Blocked("missing/malformed clock") from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise Blocked("zoneless clock")
    try:
        return t.astimezone(timezone.utc)
    except (ValueError,OverflowError) as e:
        raise Blocked("clock normalization overflow") from e

def usable_at(created, updated, retrieved, delay_hours, never_edited=False):
    if type(delay_hours) is not int or delay_hours not in (48, 120):
        raise Blocked("only registered H48/H120 clocks")
    c, u, r = map(clock, (created, updated, retrieved))
    if not c <= u <= r:
        raise Blocked("require created <= updated <= retrieval; no historical first_seen claim")
    if never_edited and (u-c).total_seconds() > 1:
        return None  # exclusion BEFORE any action/background aggregation
    try:
        return max(c, u) + timedelta(hours=delay_hours)
    except OverflowError as e:
        raise Blocked("knowledge-clock overflow") from e

@dataclass(frozen=True)
class Session:
    day: date
    open: datetime
    close: datetime

class Calendar:
    """Caller supplies regular sessions; no invented business-day/holiday inference."""
    def __init__(self, sessions):
        self.sessions = tuple(sessions)
        if not self.sessions or list(self.sessions) != sorted(self.sessions, key=lambda x:x.day):
            raise Blocked("empty/unsorted calendar")
        if len({s.day for s in self.sessions}) != len(self.sessions):
            raise Blocked("duplicate calendar session")
        for s in self.sessions:
            if s.open.tzinfo is None or s.close.tzinfo is None:
                raise Blocked("calendar clocks need zones")
            o, c = s.open.astimezone(ET), s.close.astimezone(ET)
            if o.date()!=s.day or c.date()!=s.day or o.time()!=time(9,30) or c<=o:
                raise Blocked("regular open/date mismatch")
    @staticmethod
    def cutoff(s):
        return datetime.combine(s.day, time(9,25), ET)
    def earliest(self, k):
        if k is None or k.tzinfo is None:
            raise Blocked("no usable knowledge clock")
        for s in self.sessions:
            if k < self.cutoff(s):  # EQUALITY IS NOT ELIGIBLE
                if s.open <= k:
                    raise Blocked("no-earlier-availability assertion")
                return s
        raise Insufficient("calendar horizon exhausted; never advance dates implicitly")

@dataclass(frozen=True)
class Config:
    id: str
    delay: int
    tone: str = "-0.20"
    background: int = 5
    stories: int = 3
    hold: int = 10
    never_edited: bool = False

def configurations():
    out = [Config("H48",48), Config("H120",120), Config("NE48",48,never_edited=True)]
    for h in (48,120):
        for suffix, changes in (
            ("TONE08",dict(tone="-0.16")),("TONE12",dict(tone="-0.24")),
            ("BG08",dict(background=4)),("BG12",dict(background=6)),
            ("STORIES08",dict(stories=2)),("STORIES12",dict(stories=4)),
            ("HOLD08",dict(hold=8)),("HOLD12",dict(hold=12)),
            ("JOINT08",dict(tone="-0.16",background=4,stories=2,hold=8)),
            ("JOINT12",dict(tone="-0.24",background=6,stories=4,hold=12))):
            out.append(Config(f"H{h}_{suffix}",h,**changes))
    return tuple(out)

# All are synthetic proof objects, NOT trusted human signatures or real freeze receipts.
# Their purpose is unit-testing dependency/byte comparisons without reading a real gate.
def validate_mock_gate(g, virtual_documents):
    if g.get("synthetic_only") is not True:
        raise Blocked("mock gate only; no real freeze operation")
    if g.get("joint_unseal") or g.get("metadata_bypass"):
        raise Blocked("WAIT route only; no joint or metadata-only bypass")
    spec = g.get("sector_spec_sha256")
    if not hash_shape(spec) or g.get("sector_freeze_token") != spec:
        raise Blocked("sector freeze token must equal sector prereg SHA")
    log = g.get("sector_runlog", {})
    if log.get("status") != "complete" or log.get("prereg_sha256") != spec:
        raise Blocked("missing/mismatched complete sector RUNLOG")
    if not hash_shape(log.get("receipt_sha256")):
        raise Blocked("RUNLOG bytes receipt absent")
    evidence = g.get("evidence", {})
    if not REQUIRED_EVIDENCE.issubset(evidence):
        raise Blocked("missing evidence; closure cannot be asserted by absent fields")
    for key in REQUIRED_EVIDENCE:
        e = evidence[key]
        if e.get("status") != "VERIFIED_MOCK" or e.get("approved_by") != "SYNTHETIC_VICTOR":
            raise Blocked("unverified mock receipt")
        name = e.get("document_id")
        if name not in virtual_documents or not hash_shape(e.get("sha256")):
            raise Blocked("missing immutable document pin")
        if hashlib.sha256(virtual_documents[name]).hexdigest() != e["sha256"]:
            raise Blocked("mock document bytes mismatch")
    if type(g.get("family_N")) is not int or g["family_N"] < FAMILY_FLOOR:
        raise Blocked("signed full family N must include unconditional +1; >=177")
    if g.get("pbo_columns") != 23:
        raise Blocked("exactly 23 current card columns, not full-family or option")
    if g.get("p1_owner_authorized_at_freeze") is not True:
        raise Blocked("P1 owner confirmation/current freeze re-pin pending")
    if g.get("tomas_binding_signature_verified") is not True or g.get("victor_cost_pin_at_freeze") is not True:
        raise Blocked("signed cost applicability plus Victor freeze pin required")
    return True

class BoundedFixtureLoader:
    """Only explicit synthetic JSON fixtures in the bundle's fixtures directory.
    Gate validation precedes even resolving a requested payload path. No production reader.
    Limit is 256KiB / 2,000 records. No dynamic code or arbitrary file import.
    """
    ROOT = Path(__file__).resolve().parent / "fixtures"
    def __init__(self, gate, virtual_documents):
        self.gate, self.virtual_documents = gate, virtual_documents
    def load(self, path):
        validate_mock_gate(self.gate, self.virtual_documents)
        p = Path(path)
        if p.is_symlink() or self.ROOT.is_symlink():
            raise Blocked("symlink payload/root denied")
        resolved = p.resolve()
        if resolved.parent != self.ROOT.resolve() or resolved.suffix != ".json":
            raise Blocked("only immediate bundle fixtures/*.json permitted")
        if resolved.stat().st_size > 262144:
            raise Blocked("oversize fixture")
        def no_duplicate(pairs):
            d={}
            for k,v in pairs:
                if k in d: raise Blocked("duplicate JSON field")
                d[k]=v
            return d
        try:
            payload=json.loads(resolved.read_text(), object_pairs_hook=no_duplicate,
                               parse_constant=lambda _: (_ for _ in ()).throw(Blocked("nonfinite JSON")))
        except (json.JSONDecodeError, UnicodeError) as e:
            raise Blocked("malformed fixture JSON") from e
        if not isinstance(payload,dict):
            raise Blocked("object fixture required")
        if payload.get("synthetic_only") is not True or payload.get("schema") != "rank1.fabricated.clock.v1":
            raise Blocked("fixture marker/schema required")
        rows=payload.get("records")
        if not isinstance(rows,list) or len(rows)>2000:
            raise Blocked("invalid fixture cardinality")
        for row in rows:
            if not isinstance(row,dict) or row.get("synthetic_only") is not True:
                raise Blocked("every record explicitly synthetic")
            if not re.fullmatch(r"SYNTH_[A-Z0-9_]+",row.get("issuer","")):
                raise Blocked("fabricated issuer namespace required")
            for key in ("created_at","updated_at","retrieved_at"):
                if clock(row.get(key)).year < 2090:
                    raise Blocked("fixtures must use invented 2090+ clocks, not study/history")
            usable_at(row["created_at"],row["updated_at"],row["retrieved_at"],48)
        return payload

def production_entrypoint(*args, **kwargs):
    # Deliberate non-bypassable cap: metadata dictionaries cannot self-authorize real data.
    # No file is opened. Future authenticated receipt verifier & full evaluator are missing.
    raise Blocked("PRODUCTION DISABLED: no authorized integration, evidence verifier, freeze or RUNLOG adoption")

@dataclass(frozen=True)
class DevSummary:
    trades: int
    occupied_blocks: int
    primary_mean_matched_excess: float
    stress_mean_matched_excess: float

def evaluate_synthetic_dev(summaries, synthetic_only=False):
    """Summary-level DEV gate only, NOT a portfolio simulator or holdout-opening operation."""
    if synthetic_only is not True:
        raise Blocked("only fabricated test summaries accepted")
    if set(summaries) != {c.id for c in configurations()}:
        return report("BLOCKED","require all 23 IDs including duplicates/empty configurations")
    insufficient=[]; failed=[]
    for key,s in summaries.items():
        if type(s.trades) is not int or type(s.occupied_blocks) is not int or min(s.trades,s.occupied_blocks)<0:
            return report("BLOCKED","invalid count")
        base=key in {"H48","H120","NE48"}
        if s.trades<(30 if base else 15) or s.occupied_blocks<(12 if base else 6):
            insufficient.append(key)
        if base:
            vals=(s.primary_mean_matched_excess,s.stress_mean_matched_excess)
            if any(not math.isfinite(v) for v in vals):
                insufficient.append(key)
            elif any(v<=0 for v in vals):
                failed.append(key)
    if insufficient:
        return report("INSUFFICIENT",{"ids":sorted(set(insufficient)),"other_failures":sorted(failed),"holdout_opened":False})
    if failed:
        return report("FAIL",{"ids":sorted(failed),"holdout_opened":False})
    return report("SYNTHETIC_ONLY_PASS",{"holdout_opened":False,"production_authority":False})
