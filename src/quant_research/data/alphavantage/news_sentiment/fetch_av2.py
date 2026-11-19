from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
# v2 fetcher, $QR_DATA_DIR/av_sentiment_20261110. Adds Jeremy's 23:19 SGT approval: +600 split calls
# (total SPLIT calls <= 800 incl. R1's 158), half-month -> weekly re-split, R1 re-split pass (R1b).
# News runs split smaller (R2a..R4b) to stay under 35 min. Metadata parse only: len(feed). No scores read.
# Usage: python3 -I -B $QR_DATA_DIR/av_sentiment_20261110/fetch_av2.py <R1b|R2a|R2b|R3a|R3b|R4a|R4b|R6|R7|R8>
import os, sys, json, time, hashlib, calendar, datetime, urllib.request, urllib.parse, urllib.error
D = f'{_QR.DATA_DIR}/av_sentiment_20261110'
LOG = D + '/CALLS.log'
G1 = 'AAPL MSFT NVDA AMZN GOOGL META TSLA JPM V MA UNH JNJ XOM'.split()
RUNS = {'R1b': ('resplit', G1),
        'R2a': ('news', 'CVX PG HD LLY ABBV MRK PFE'.split()), 'R2b': ('news', 'KO PEP COST WMT BAC WFC'.split()),
        'R3a': ('news', 'GS MS C AVGO ORCL CSCO ADBE'.split()), 'R3b': ('news', 'CRM AMD INTC QCOM TXN NFLX'.split()),
        'R4a': ('news', 'DIS CMCSA T VZ NKE MCD SBUX'.split()), 'R4b': ('news', 'BA CAT GE HON SPY QQQ'.split()),
        'R6': ('tr', 'CVX PG HD LLY ABBV MRK PFE KO PEP COST WMT BAC WFC'.split()),
        'R7': ('tr', 'GS MS C AVGO ORCL CSCO ADBE CRM AMD INTC QCOM TXN'.split()),
        'R8': ('tr', 'NFLX DIS CMCSA T VZ NKE MCD SBUX BA CAT GE HON'.split())}
MONTHS = [(y, m) for y in range(2022, 2027) for m in range(1, 13) if (2022, 3) <= (y, m) <= (2026, 10)]
QUARTERS = [(y, q) for y in range(2010, 2027) for q in range(1, 5) if (y, q) <= (2026, 3)]
assert len(MONTHS) == 56 and len(QUARTERS) == 67
MIN_GAP, DEADLINE, RETRY_CAP, SPLIT_CAP, BACKOFF = 1.5, 33 * 60, 100, 800, (60, 120)
KEY = os.environ.get('ALPHAVANTAGE_API_KEY', '')

class Stop(Exception): pass
class Deadline(Exception): pass

def utc(): return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def wexcl(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, 'wb') as f: f.write(data)

def logline(fields):
    with open(LOG, 'a', encoding='utf-8') as f: f.write('\t'.join(str(x) for x in fields) + '\n')

def feed_len(body):
    try:
        j = json.loads(body)
        return len(j['feed']) if isinstance(j, dict) and isinstance(j.get('feed'), list) else -1
    except Exception:
        return -1

class Runner:
    def __init__(self, run):
        self.run, self.t0, self.last = run, time.monotonic(), 0.0
        self.retries, self.consec, self.stats = 0, 0, {}
        self.splits = 0
        with open(LOG, encoding='utf-8') as f:
            for l in f:
                c = l.split('\t')
                if len(c) > 3 and c[2] == 'SPLIT' and c[3] != '-': self.splits += 1
    def elapsed(self): return time.monotonic() - self.t0
    def bump(self, k): self.stats[k] = self.stats.get(k, 0) + 1
    def get(self, params):
        wait = MIN_GAP - (time.monotonic() - self.last)
        if wait > 0: time.sleep(wait)
        self.last = time.monotonic()
        q = dict(params); q['apikey'] = KEY
        url = 'https://www.alphavantage.co/query?' + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return r.status, r.read(), ''
        except urllib.error.HTTPError as e:
            try: b = e.read()
            except Exception: b = b''
            return e.code, b, 'HTTPError'
        except Exception as e:
            return 0, b'', type(e).__name__
    def call(self, endpoint, params, base, kind, holdout):
        if self.elapsed() > DEADLINE: raise Deadline()
        pstr = urllib.parse.urlencode(params)
        if kind == 'SPLIT' and self.splits >= SPLIT_CAP:
            logline([utc(), self.run, 'SPLIT', '-', endpoint, pstr, '-', 0, '-', 'SPLIT_CAP_REACHED:budget', holdout, '-'])
            self.bump('SPLIT_CAP_REACHED:budget'); return None
        throttled_all = True
        for attempt in (1, 2, 3):
            if attempt > 1:
                if self.retries >= RETRY_CAP or self.elapsed() + BACKOFF[attempt - 2] > DEADLINE: break
                self.retries += 1; time.sleep(BACKOFF[attempt - 2])
            if kind == 'SPLIT': self.splits += 1
            status, body, err = self.get(params)
            path = base + ('.json' if attempt == 1 else '.attempt%d.json' % attempt)
            sha = hashlib.sha256(body).hexdigest() if body else '-'
            if body: wexcl(path, body)
            small, low = len(body) < 4096, body.lower()
            if b'apikey' in low and b'invalid' in low and small: outcome = 'INVALID_KEY'
            elif status != 200: outcome = 'ERROR'
            elif small and (b'"Information"' in body or b'"Note"' in body): outcome = 'THROTTLED'
            elif small and b'"Error Message"' in body: outcome = 'ERROR'
            elif not body: outcome = 'ERROR'
            else: outcome = 'OK'
            if outcome != 'THROTTLED': throttled_all = False
            logline([utc(), self.run, kind, attempt, endpoint, pstr, status, len(body), sha,
                     outcome + ((':' + err) if err else ''), holdout, path if body else '-'])
            if outcome == 'INVALID_KEY': raise Stop('invalid key or entitlement message')
            if outcome == 'OK':
                self.consec = 0; self.bump('OK'); return body
        logline([utc(), self.run, kind, '-', endpoint, pstr, '-', 0, '-', 'MISSING', holdout, '-'])
        self.bump('MISSING')
        if throttled_all:
            self.consec += 1
            if self.consec >= 3: raise Stop('3 consecutive throttled calls')
        else: self.consec = 0
        return None

def nparams(s, y, m, a, b):
    return {'function': 'NEWS_SENTIMENT', 'tickers': s, 'time_from': '%04d%02d%02dT0000' % (y, m, a),
            'time_to': '%04d%02d%02dT2359' % (y, m, b), 'limit': '1000', 'sort': 'EARLIEST'}

def halves(y, m):
    last = calendar.monthrange(y, m)[1]
    return [('h1', 1, 15, [('w1', 1, 7), ('w2', 8, 15)]), ('h2', 16, last, [('w1', 16, 23), ('w2', 24, last)])]

def weekly(R, s, y, m, tag, weeks):
    base = '%s/raw/news/%s/%04d-%02d' % (D, s, y, m)
    for wt, a, b in weeks:
        wb = R.call('NEWS_SENTIMENT', nparams(s, y, m, a, b), '%s.%s%s' % (base, tag, wt), 'SPLIT', 'holdout')
        if wb is not None and feed_len(wb) >= 1000:
            logline([utc(), R.run, 'SPLIT', '-', 'NEWS_SENTIMENT', 'tickers=%s window=%04d-%02d-%02d..%02d' % (s, y, m, a, b),
                     '-', 0, '-', 'SPLIT_CAP_REACHED:weekly_full', 'holdout', '-']); R.bump('weekly_full')

def news_month(R, s, y, m):
    last = calendar.monthrange(y, m)[1]
    base = '%s/raw/news/%s/%04d-%02d' % (D, s, y, m)
    body = R.call('NEWS_SENTIMENT', nparams(s, y, m, 1, last), base, 'PRIMARY', 'holdout')
    if body is None or feed_len(body) < 1000: return
    for tag, a, b, weeks in halves(y, m):
        hb = R.call('NEWS_SENTIMENT', nparams(s, y, m, a, b), '%s.%s' % (base, tag), 'SPLIT', 'holdout')
        if hb is not None and feed_len(hb) >= 1000: weekly(R, s, y, m, tag, weeks)

def resplit_items():
    # R1 half-month files that were OK in CALLS.log; re-split those at the cap
    out = []
    with open(LOG, encoding='utf-8') as f:
        for l in f:
            c = l.rstrip('\n').split('\t')
            if len(c) >= 12 and c[1] == 'R1' and c[2] == 'SPLIT' and c[9] == 'OK': out.append(c[11])
    return out

def main():
    run = sys.argv[1]
    if run not in RUNS: print('REFUSED: unknown run'); return 4
    if not KEY: print('NO_KEY'); return 4
    try: wexcl('%s/RUN_%s.started' % (D, run), (utc() + '\n').encode())
    except FileExistsError: print('REFUSED: run already started once'); return 4
    kind, syms = RUNS[run]
    R = Runner(run)
    if kind == 'news': items = [(s, y, m) for s in syms for (y, m) in MONTHS]
    elif kind == 'tr': items = [(s, y, q) for s in syms for (y, q) in QUARTERS]
    else: items = resplit_items()
    rc, note, i = 0, 'done', 0
    try:
        for i, it in enumerate(items):
            if kind == 'news': news_month(R, *it)
            elif kind == 'tr':
                s, y, q = it
                R.call('EARNINGS_CALL_TRANSCRIPT', {'function': 'EARNINGS_CALL_TRANSCRIPT', 'symbol': s, 'quarter': '%dQ%d' % (y, q)},
                       '%s/raw/transcripts/%s/%dQ%d' % (D, s, y, q), 'PRIMARY', 'holdout' if (y, q) >= (2016, 1) else 'pre')
            else:
                path = it
                with open(path, 'rb') as f: n = feed_len(f.read())
                if n < 1000: continue
                fn = os.path.basename(path)            # YYYY-MM.hN.json
                ym, tag = fn.split('.')[0], fn.split('.')[1]
                s = os.path.basename(os.path.dirname(path)); y, m = int(ym[:4]), int(ym[5:7])
                weeks = [h[3] for h in halves(y, m) if h[0] == tag][0]
                weekly(R, s, y, m, tag, weeks)
    except Deadline:
        for rest in items[i:]:
            logline([utc(), run, 'PRIMARY', '-', '-', 'item=%s' % (rest,), '-', 0, '-', 'NOT_ATTEMPTED', '-', '-'])
        rc, note = 3, 'deadline stop at item %d of %d' % (i, len(items))
    except Stop as e:
        rc, note = 2, 'designed stop: %s' % e
    summ = '%s %s items=%d stats=%s retries=%d splits_total=%d elapsed_s=%d %s\n' % (
        run, kind, len(items), json.dumps(R.stats, sort_keys=True), R.retries, R.splits, R.elapsed(), note)
    wexcl('%s/RUN_%s.done' % (D, run), summ.encode())
    print(summ, end=''); return rc

if __name__ == '__main__': sys.exit(main())
