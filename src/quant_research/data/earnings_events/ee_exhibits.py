"""Stage 5: EX-99 press-release exhibit per event from the accession's -index-headers.html
(index.json lists file names only, without document TYPE, so it cannot identify EX-99.1 reliably).
SEC fair access: same UA, <= 8 req/s. Raw headers saved gzip'd, write-once. EPS is NOT parsed here."""
import gzip, html, os, re, sys, time, json, hashlib, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from quant_research.data.earnings_events.ee_fetch import S, MIN_INTERVAL, _last
RAW = "raw/sec_index_headers"; MAN = f"{RAW}/MANIFEST.jsonl"
os.makedirs(RAW, exist_ok=True)

_lock = threading.Lock(); _next = [0.0]
def _throttle():  # global limiter shared by worker threads: one request per MIN_INTERVAL (8/s)
    with _lock:
        t = max(time.time(), _next[0]); _next[0] = t + MIN_INTERVAL
    d = t - time.time()
    if d > 0: time.sleep(d)

def get_headers(cik, acc):
    p = f"{RAW}/{acc}.html.gz"
    if os.path.exists(p): return gzip.open(p).read().decode("latin-1")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{acc}-index-headers.html"
    for attempt in range(6):
        _throttle()
        try:
            r = S.get(url, timeout=30)
        except Exception as ex:
            print("retry", acc, type(ex).__name__, flush=True); time.sleep(2 ** attempt + 1); continue
        if r.status_code == 200: break
        if r.status_code == 404: return None
        print("http", r.status_code, acc, flush=True); time.sleep(2 ** attempt + 1)
    else:
        return None
    with gzip.open(p + ".tmp", "wb") as f: f.write(r.content)
    os.replace(p + ".tmp", p)
    with _lock, open(MAN, "a") as f:
        f.write(json.dumps(dict(url=url, sha256=hashlib.sha256(r.content).hexdigest(),
                                retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())) + "\n")
    return r.content.decode("latin-1")

DOC = re.compile(r"<DOCUMENT>(.*?)(?=<DOCUMENT>|\Z)", re.S)
def field(block, name):
    m = re.search(rf"<{name}>([^\n<]*)", block); return m.group(1).strip() if m else ""

PR = re.compile(r"press|release|earn|result|quarter|financial", re.I)
def pick(txt):
    docs = [dict(type=field(b, "TYPE").upper(), filename=field(b, "FILENAME"), desc=field(b, "DESCRIPTION"))
            for b in DOC.findall(html.unescape(txt))]
    exh = [d for d in docs if d["type"].startswith("EX-")]
    ex99 = [d for d in exh if d["type"].startswith("EX-99")]
    choice, rule = None, None
    for d in ex99:
        if d["type"] in ("EX-99.1", "EX-99.01", "EX-99.(1)", "EX-99.1A"): choice, rule = d, "EX-99.1"; break
    if choice is None:
        pr = [d for d in ex99 if PR.search(d["desc"] + " " + d["filename"])]
        if pr: choice, rule = pr[0], "EX-99.x press-release keyword"
        elif ex99: choice, rule = ex99[0], "first EX-99.x"
    return len(exh), choice, rule, len(docs)

_done = [0]
def one(c, a):
    txt = get_headers(c, a)
    with _lock:
        _done[0] += 1
        if _done[0] % 1000 == 0: print(_done[0], round(time.time() - T0[0]), flush=True)
    if txt is None:
        return dict(accession=a, ex99_url=None, ex99_filename=None, ex99_type=None, ex99_description=None,
                    ex99_rule="index-headers unavailable", exhibit_count=None)
    n, ch, rule, nd = pick(txt)
    base = f"https://www.sec.gov/Archives/edgar/data/{c}/{a.replace('-', '')}/"
    return dict(accession=a, exhibit_count=n,
                ex99_filename=ch["filename"] if ch else None, ex99_url=base + ch["filename"] if ch else None,
                ex99_type=ch["type"] if ch else None, ex99_description=ch["desc"] if ch else None,
                ex99_rule=rule or "no EX-99 exhibit")
T0 = [time.time()]

if __name__ == "__main__":
    k = pd.read_parquet("work/events_core.parquet")
    order = k[k.in_sp500].sort_values("acceptance_utc")  # v1: exhibits for in-index events only (speed); others left null
    print("events", len(order), flush=True)
    with ThreadPoolExecutor(16) as ex:
        out = list(ex.map(lambda ca: one(*ca), zip(order.cik, order.accession)))
    pd.DataFrame(out).to_parquet("work/exhibits.parquet")
    print("done", len(out), round(time.time() - T0[0]), "s", flush=True)
