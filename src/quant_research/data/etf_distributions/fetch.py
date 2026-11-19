#!/usr/bin/env python3
"""Narrow issuer-document fetcher. Saves raw bytes + ledger line. Never prints body."""
import sys, os, json, time, hashlib, datetime, re, requests
ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "sources"); LOG = os.path.join(ROOT, "fetch_log.jsonl")
UA = "CIO desk research research-contact@example.com"
def fetch(url, name, accept=None):
    os.makedirs(os.path.dirname(os.path.join(SRC, name)), exist_ok=True)
    t0 = datetime.datetime.now(datetime.timezone.utc)
    rec = {"url": url, "file": "sources/" + name, "fetch_utc": t0.isoformat()}
    try:
        h = {"User-Agent": UA}
        if accept: h["Accept"] = accept
        r = requests.get(url, headers=h, timeout=60, allow_redirects=True)
        rec.update(status=r.status_code, final_url=r.url, content_type=r.headers.get("content-type"), bytes=len(r.content))
        if r.status_code == 200:
            p = os.path.join(SRC, name)
            if os.path.exists(p): raise SystemExit("refuse overwrite " + p)
            with open(p, "xb") as f: f.write(r.content)
            rec["sha256"] = hashlib.sha256(r.content).hexdigest()
        else:
            rec["sha256"] = None; rec["file"] = None
    except Exception as e:
        rec.update(status=None, error=repr(e)[:300], sha256=None, file=None)
    with open(LOG, "a") as f: f.write(json.dumps(rec) + "\n")
    print(json.dumps({k: rec.get(k) for k in ("status","bytes","content_type","file","sha256")}))
    time.sleep(1.2)
    return rec
if __name__ == "__main__":
    for line in sys.stdin:
        line=line.strip()
        if not line or line.startswith("#"): continue
        url, name = line.split()[:2]; fetch(url, name)
