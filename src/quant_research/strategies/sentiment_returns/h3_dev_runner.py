from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
# h3_dev_runner.py v3 (re-freeze 2026-11-13; v2 716e370f, v1 550211dc; v3 adds DV-25 stale terminal bar, Victor L561) - H3 DEV runner for sealed PREREG_H3_DRAFT_v2 (ecce2bbf...) + seal S1-S6 (40ddcc9c...).
# DEV ONLY (closes/events <= 2024-12-31). ONE run, guarded by an atomic LOCK. Raw output goes to Victor first (S6).
# Helper conventions COPIED (not imported) from dev_run.py (80f4bb71...): XNYS sessions, adjusted_close ratios,
# 252-return OLS beta ending t-1, (ws, we] 15:30 ET cutoffs, UTC/ET readings of naive time_published, relevance-weighted
# mean, Bartlett NW t, one-sided Student-t p (df = T-1), +/-1 day month padding; H1b-style entry from flat (h2_dev.py dba0e8fb
# for the guard/pin/exclusive-write pattern). v2 order: env_pin(5) -> config(6) -> S3 calendar(4) -> LOCK-exists(7) -> path guard(3)
# -> PRE-LOCK preflight: every sha(2) + header lines + manifests + F1 universe x-check (8) -> atomic LOCK -> parse; any STOP after LOCK
# exits nonzero BEFORE H3_DEV_RAW.json is written. --dry-check stops after the preflight (no data rows, no LOCK, no output).
import sys, os
EXIT_ENV, EXIT_CFG, EXIT_LOCK, EXIT_SHA, EXIT_PATH, EXIT_CAL, EXIT_PRE, EXIT_DATA = 5, 6, 7, 2, 3, 4, 8, 9
DECL_D = ('Design informed by H1b OOS (L306); HOLDOUT period not regime-blind. '
          'Any H3 PASS = "conditional evidence (period not regime-blind)". Research only; no trading (S1). '
          'MSTR research-only, never paper traded, excluded from every trade list (S2).')
PIN = dict(exe=f'{_QR.DATA_DIR}/.venv/bin/python', exe_real='/usr/bin/python3.13',
           exe_sha='889c603f0d17cb54060951bcf4c4f9b8c9ebd9e52b392c70209bbb9755d797d9', py='3.13.5',
           freeze=f'{_QR.DESK_DIR}/validation/marcus/inc99_venv/PIP_FREEZE.txt',
           freeze_sha='8cb1e190f4a53410d2106bca88be83668d865f20dd474a0e67329ca3e5879768',
           core={'pandas': '3.1.0', 'numpy': '2.5.4', 'scipy': '1.18.1', 'exchange_calendars': '4.13.2'})

def _sha_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''): h.update(ch)
    return h.hexdigest()

def env_check():
    """Exit 5 on ANY mismatch with ENV_PIN_ADDENDUM_H3.md (2bb14197...). Runs before any third-party import."""
    import platform
    from importlib import metadata
    bad = []
    if not sys.flags.isolated: bad.append('python not run with -I')
    if not sys.flags.dont_write_bytecode: bad.append('python not run with -B')
    if sys.executable != PIN['exe']: bad.append(f'sys.executable {sys.executable!r} != {PIN["exe"]}')
    real = os.path.realpath(sys.executable)
    if real != PIN['exe_real']: bad.append(f'realpath {real} != {PIN["exe_real"]}')
    try:
        if _sha_file(real) != PIN['exe_sha']: bad.append('interpreter sha mismatch')
    except OSError as e: bad.append(f'interpreter unreadable {e}')
    if platform.python_version() != PIN['py']: bad.append(f'python {platform.python_version()} != {PIN["py"]}')
    for k, v in PIN['core'].items():
        try:
            got = metadata.version(k)
        except metadata.PackageNotFoundError: got = None
        if got != v: bad.append(f'{k} {got} != {v}')
    try:
        if _sha_file(PIN['freeze']) != PIN['freeze_sha']: bad.append('PIP_FREEZE.txt sha mismatch')
        norm = lambda n: n.lower().replace('-', '_')
        want = {norm(l.split('==')[0]): l.split('==')[1].strip() for l in open(PIN['freeze']).read().split('\n') if '==' in l}
        have = {}
        for d in metadata.distributions():
            if d.metadata['Name']: have[norm(d.metadata['Name'])] = d.version
        if have != want: bad.append(f'installed distributions != freeze: {sorted(set(have.items()) ^ set(want.items()))}')
    except OSError as e: bad.append(f'freeze unreadable {e}')
    if bad:
        sys.stderr.write('ENV_PIN MISMATCH (exit 5): ' + '; '.join(bad) + '\n'); sys.exit(EXIT_ENV)
    import numpy, pandas, scipy, exchange_calendars
    mods = dict(numpy=numpy.__version__, pandas=pandas.__version__, scipy=scipy.__version__, exchange_calendars=exchange_calendars.__version__)
    for k, v in mods.items():
        if v != PIN['core'][k]:
            sys.stderr.write(f'ENV_PIN MISMATCH (exit 5): imported {k} {v}\n'); sys.exit(EXIT_ENV)
    return dict(exe=sys.executable, exe_real=real, exe_sha=PIN['exe_sha'], python=platform.python_version(), flags='-I -B',
                freeze_sha=PIN['freeze_sha'], **mods)

ENV = None
if __name__ == '__main__':
    ENV = env_check()           # FIRST action of a real or test run


import json, re, io, builtins, hashlib, argparse, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from scipy import stats
import exchange_calendars as xc

NY = ZoneInfo('America/New_York'); UTC = dt.timezone.utc
STAGE = f'{_QR.DESK_DIR}/research/original/sentiment_h3_dev_stage_v3_20261113'
ROOT = f'{_QR.DATA_DIR}/av_h3_universe_20261111'
SYNTH_DIR = f'{_QR.SCRATCH_DIR}/scratch/h3_synth_v3_20261113/'
COV_TAGS = ('000_012', '012_024', '024_036', '036_052', '052_068', '068_084', '084_100')
REAL = dict(
    mode='REAL', root=ROOT, n_universe=100,
    p2sums=f'{ROOT}/partition_2/SHA256SUMS', p2sums_sha='9ed2d8cf3e61a77a5de2e748ba6d3b8835cf332f402d1a0e8ce966f65cea7546',
    news_index=f'{ROOT}/partition_2/NEWS_DEV_INDEX.tsv', news_index_sha='373e49bcf93a0f8d58135310fb85204719d8412d95b06ed65654a6c6d13fd8f6',
    rsector=f'{ROOT}/meta/RSECTOR_H3.tsv', rsector_sha='696631a10a13b6bd7fd5dc12b079086db601fef98e4bf906f9592c9a984dced6',   # F2 full sha
    final100=f'{ROOT}/stage1c/FINAL_100_H3.txt', final100_sha='f82830d8e11d984e4d05aef6afd97bfe95828f7601731ef2dce0721d50125d1c',   # F1
    universe_tsv=f'{ROOT}/stage1c/UNIVERSE_H3.tsv', universe_tsv_sha='a5a52c5381e2fb9c12d02bc6e78fe0c42f32b18f1d0a70d4a13eadd976da128d',  # F1 pin (not parsed)
    s1c_sums=f'{ROOT}/stage1c/SHA256SUMS', s1c_sums_sha='4eb2970ee938eb95e38319379bb3ab47abdd1476cb69b57aaa5f07896de4ab33',
    price_csv=f'{ROOT}/partitioned_prices/dev/prices_dev.csv', price_csv_sha='11bd5504f0b887023f3f4281e0a71db707eee1980f88a89b1871469924b2be43',
    dev_meta=f'{ROOT}/partitioned_prices/dev/DEV_META.csv', dev_meta_sha='7d5866f0a2c2a0e1800205392716fe9a2cd4a53a8a582065ad567d0b5e6d27ea',
    price_dev_sums=f'{ROOT}/partitioned_prices/dev/SHA256SUMS', price_dev_sums_sha='4bbf92bf551674fe220c202df143f2d167b96162ed28eeee9c404ce2e54dc199',
    price_top_sums=f'{ROOT}/partitioned_prices/SHA256SUMS', price_top_sums_sha='f436c94230ed638e8f2b787b334f5e89e809ab215db7466f2d32e2314de1e723',
    coverage=[[f'{ROOT}/COVERAGE_2_DEV_news_{t}.tsv', h] for t, h in zip(COV_TAGS, (
        '09a4ae0129e3607185bbe2a9753cd2db263160e6c0be5374a62a26cfaa0dc291', '6195b1d623bd55f100b144ec2de731d03f5825af90930fe4abc1d368328b43a5',
        'ce5ada1462e0616fcc8d3a628ea9f9c3d88f368e0a70379d5aa93f7581a04dc0', '81af1764b517faa18dda89e700c50fa4f3a2b26e78f0eac35b4924ca27f23afe',
        'a4eaa8d864f3156f07ec1e14b1f1c9eec21f64a54df0bb3c62db8767d3f9431e', '403fc46a3dc3d4c30cfccabc20830ae393c738df81c85079ddddc11eabd46d13',
        '1af77136ee0762b88a36cdaba86161414f3ffab50509ad5dbdb85f0c719ff9de'))],
    expect_price_rows=95850, expect_earn_missing=['ATVI', 'ROKU', 'TWTR'], expect_cov_rows=3400,
    lock=f'{_QR.DESK_DIR}/research/original/sentiment_h3_dev_run_20261113.LOCK',
    out=f'{_QR.DESK_DIR}/research/original/sentiment_h3_dev_run_20261113')
CFG_KEYS = ('p2sums', 'p2sums_sha', 'news_index', 'news_index_sha', 'rsector', 'rsector_sha', 'final100', 'final100_sha', 'universe_tsv',
            'universe_tsv_sha', 's1c_sums', 's1c_sums_sha', 'price_csv', 'price_csv_sha', 'dev_meta', 'dev_meta_sha', 'price_dev_sums',
            'price_dev_sums_sha', 'price_top_sums', 'price_top_sums_sha', 'coverage', 'lock', 'out')
HDR = dict(price_csv='symbol,date,open,high,low,close,adjusted_close,volume,dividend,split_coefficient',
           dev_meta='symbol,first_bar,last_bar,rows',
           coverage='symbol\tmonth\tfiles_used\titems\tcoverage\tcapped_windows\tsource_files',
           rsector='symbol\tSector\tIndustry\toverview_missing', news_index='path\tsha256')
# parameters fixed by PREREG v2 sec.2/5 (Q-H4 RESOLVED; no change after the pull)
W_H3, W_X1, MIN_ITEMS, MIN_NAMES, MIN_LEG = 20, 5, 5, 40, 5
LONG_IN, LONG_HOLD, SHORT_IN, SHORT_HOLD = 0.80, 0.60, 0.20, 0.40
REL_MIN, NW_LAG, C10, C20, BETA_N = 0.50, 4, 0.0010, 0.0020, 252
DEV_START, DEV_END = '2021-03-01', '2024-12-31'; RESEARCH_ONLY = {'MSTR'}
MONTHS = [f'{y}-{m:02d}' for y in (2022, 2023, 2024) for m in range(1, 13) if f'{y}-{m:02d}' >= '2022-03']
EXPECT = dict(first_dec='2022-04-01', dev_decisions=144, usable=143, straddle='2024-12-27', last_kept='2024-12-20', returns_before_first=276)
TICK = re.compile(r'^[A-Z][A-Z0-9.\-]{0,9}$')
STALE_EXPECT_N = 2      # DV-25 (Victor L561): expected drops on real data (TWTR 2022-10-28, ATVI 2023-10-13); a different count is REPORTED, not a STOP

# ---------------- path guard ----------------
class Guard:
    deny = ('/holdout', 'NEWS_HOLDOUT_INDEX', 'HOLDOUT_COUNTS', '/raw/2/earnings', '/raw/2/bench', 'verdicts-log.md',
            'kaggle_staging', 'post_20261031')
    news_re = re.compile(r'/news/[^/]+/(\d{4}-\d{2})\.json$')
    pp_re = re.compile(r'/partitioned_prices/([^/]+)/')       # only the dev/ subdir of partitioned_prices may be opened
    def __init__(self, write_dirs):
        self.allowed = set(); self.write_dirs = [os.path.abspath(d) for d in write_dirs]; self.denials = []; self.on = False
    def check(self, p, mode='r'):
        p = os.path.abspath(p)
        why = None
        if any(x in p for x in self.deny): why = 'denylist'
        m = self.news_re.search(p)
        if m and m.group(1) >= '2025-01': why = 'news month >= 2025-01'
        m = self.pp_re.search(p)
        if m and m.group(1) != 'dev': why = 'partitioned_prices subdir other than dev/'
        writing = any(c in mode for c in 'wax+')
        if why is None and p.startswith(f'{_QR.SCRATCH_DIR}/'):
            inw = any(p == d or p.startswith(d + '/') for d in self.write_dirs)
            if writing and not inw: why = 'write outside output dir'
            venv = p.startswith(f'{_QR.DATA_DIR}/.venv/')
            if writing and venv: why = 'write into venv'
            if not writing and not inw and not venv and p not in self.allowed: why = 'not on exact-path allowlist'
        if why:
            self.denials.append((p, why)); raise PermissionError(f'PATH_GUARD refused {p}: {why}')
        return p
    def install(self):
        g = self; orig = builtins.open
        def gopen(file, mode='r', *a, **k):
            if g.on and isinstance(file, (str, bytes, os.PathLike)): g.check(os.fsdecode(file), mode)
            return orig(file, mode, *a, **k)
        builtins.open = gopen; io.open = gopen; self.on = True

# ---------------- calendar (sessions only, no data) ----------------
def calendar_facts():
    cal = xc.get_calendar('XNYS')
    calx = [d.strftime('%Y-%m-%d') for d in cal.sessions_in_range('2021-03-01', '2025-01-10')]
    wk = {}
    for d in calx: wk[dt.date.fromisoformat(d).isocalendar()[:2]] = d     # last session of ISO week
    alld = sorted(wk.values()); ix = {d: i for i, d in enumerate(calx)}
    first_cov = calx[next(i for i, d in enumerate(calx) if d >= '2022-03-01')]
    decs = [d for d in alld if ix[d] - W_H3 >= ix[first_cov] and d <= DEV_END]
    nxt = {d: alld[alld.index(d) + 1] for d in decs}
    usable = [d for d in decs if nxt[d] <= DEV_END]           # B3/B8 straddle drop
    facts = dict(first_dec=decs[0], dev_decisions=len(decs), usable=len(usable), straddle=[d for d in decs if nxt[d] > DEV_END],
                 last_kept=usable[-1], returns_before_first=ix[decs[0]] - ix['2021-03-01'])
    return calx, usable, nxt, facts

def check_calendar(facts):
    exp = dict(EXPECT); got = dict(facts); got['straddle'] = ','.join(got['straddle'])
    diffs = {k: (got[k], v) for k, v in exp.items() if got[k] != v}
    return diffs
def cutoff(d):
    y, m, dd = map(int, d.split('-')); return dt.datetime(y, m, dd, 15, 30, tzinfo=NY).timestamp()

def month_set(start_ep, end_ep):   # copied from dev_run.py: months touched by [start-1d, end+1d]
    a = dt.datetime.fromtimestamp(start_ep, NY).date() - dt.timedelta(days=1)
    b = dt.datetime.fromtimestamp(end_ep, NY).date() + dt.timedelta(days=1)
    out = set(); x = a.replace(day=1)
    while x <= b:
        out.add(f'{x.year}-{x.month:02d}'); x = (x + dt.timedelta(days=32)).replace(day=1)
    return out

def nw_t(x, L):   # copied from dev_run.py
    x = np.asarray(x, float); T = len(x); m = x.mean(); u = x - m
    lrv = (u @ u) / T
    for l in range(1, L + 1):
        w = 1 - l / (L + 1); lrv += 2 * w * (u[l:] @ u[:-l]) / T
    return m / np.sqrt(lrv / T)

def one_sided(x, L=NW_LAG):
    x = np.asarray(x, float); T = len(x)
    if T < 3 or np.allclose(x, x.mean()): return dict(nw_t=None, p_one_sided=None, df=T - 1)
    t = nw_t(x, L); return dict(nw_t=float(t), p_one_sided=float(1 - stats.t.cdf(t, df=T - 1)), df=T - 1)


# ---------------- book logic (pure; hand-checked in synthetic_test.py) ----------------
def band_step(pos, u):
    """pos in {+1,0,-1}; u in (0,1). PREREG v2 sec.2 80/60 band, direct flip at the opposite entry bar."""
    if pos == 1:
        return -1 if u <= SHORT_IN else (0 if u < LONG_HOLD else 1)
    if pos == -1:
        return 1 if u >= LONG_IN else (0 if u > SHORT_HOLD else -1)
    return 1 if u >= LONG_IN else (-1 if u <= SHORT_IN else 0)

def target_weights(state):
    L = [s for s, p in state.items() if p == 1]; S = [s for s, p in state.items() if p == -1]
    if len(L) < MIN_LEG or len(S) < MIN_LEG: return {}, True      # whole book flat (counted)
    w = {s: 1.0 / len(L) for s in L}; w.update({s: -1.0 / len(S) for s in S}); return w, False

def traded_weight(w_new, w_drift):   # sum |w_new - w_drifted| over both legs (L307 A3)
    return float(sum(abs(w_new.get(s, 0.0) - w_drift.get(s, 0.0)) for s in set(w_new) | set(w_drift)))

def drift(w, r):
    """weights drift with returns within each leg (leg renormalised to +1/-1; OQ-5/DV-3, ACCEPTED L557)."""
    out = {}
    for sign in (1, -1):
        leg = {s: abs(x) for s, x in w.items() if np.sign(x) == sign}
        if not leg: continue
        tot = sum(x * (1 + r[s]) for s, x in leg.items())
        for s, x in leg.items(): out[s] = sign * x * (1 + r[s]) / tot
    return out

def leg_return(w, r):
    L = sum(x * r[s] for s, x in w.items() if x > 0); S = sum(-x * r[s] for s, x in w.items() if x < 0)
    return L - S

def run_book(weeks, mode='band'):
    """weeks: list of dict(dec, qual={sym:(S,u)} = BOOK POOL (valid signal + finite beta), scored, r={sym:ret to t+1 or to last bar},
    y={sym:beta-adj}, closed=set(syms whose last AV bar falls before t+1)). Enters from flat.
    OQ-3/DV-2 (ACCEPTED L557): a held name in `closed` earns r up to its last bar and is closed there; exit cost C x |drifted w| is
    charged in that week and the closure is counted. Its weight leaves the book (leg not re-normalised; the next rebalance tops up, charged)."""
    state = {}; w_d = {}; out = []
    for wk in weeks:
        q = wk['qual']; forced = [s for s in state if s not in q]
        for s in forced: state.pop(s)                              # missing signal/beta -> exit at close t
        if wk['scored']:
            if mode == 'band':
                new = {}
                for s, (S, u) in q.items():
                    p = band_step(state.get(s, 0), u)
                    if p: new[s] = p
                state = new
            else:   # X2: plain quintile, k = n//5, ties by symbol (as dev_run.py)
                o = sorted(q, key=lambda s: (q[s][0], s)); k = len(o) // 5
                state = {s: -1 for s in o[:k]}; state.update({s: 1 for s in o[len(o) - k:]})
        w, flat = target_weights(state)
        if flat: state = {}          # OQ-4/DV-4: band memory cleared when the book is held flat (ACCEPTED L557)
        tw = traded_weight(w, w_d)
        g = leg_return(w, wk['r']) if w else 0.0
        b = leg_return(w, wk['y']) if w else 0.0
        w_d = drift(w, wk['r']) if w else {}
        closed = sorted(s for s in w if s in wk.get('closed', ()))
        cw = float(sum(abs(w_d[s]) for s in closed))               # exit at last bar, at the drifted weight
        for s in closed: w_d.pop(s); state.pop(s, None)
        out.append(dict(dec=wk['dec'], scored=wk['scored'], flat=flat, forced_exits=len(forced), closed_last_bar=len(closed),
                        closed_names=closed, closed_weight=cw,
                        n_long=sum(1 for x in w.values() if x > 0), n_short=sum(1 for x in w.values() if x < 0),
                        traded=tw + cw, gross=g, betaadj=b, net10=g - C10 * (tw + cw), net20=g - C20 * (tw + cw),
                        longs=sorted(s for s, x in w.items() if x > 0), shorts=sorted(s for s, x in w.items() if x < 0)))
    term = float(sum(abs(x) for x in w_d.values()))
    return out, term

def trade_list(names):   # S2: MSTR never appears in any trade list output
    return [s for s in names if s not in RESEARCH_ONLY]

# ---------------- input loading / verification ----------------
class ShaError(Exception): pass
class DataError(Exception): pass
class PreError(Exception): pass

def parse_sums(b, strip=''):
    d = {}
    for line in b.decode().split('\n'):
        if not line.strip(): continue
        h, q = line.strip().split(None, 1); q = q.lstrip('*')
        while q.startswith('./'): q = q[2:]
        if strip and q.startswith(strip): q = q[len(strip):]
        if not re.fullmatch(r'[0-9a-f]{64}', h): raise PreError(f'bad SUMS line {line[:80]!r}')
        d[q] = h
    return d

def read_verified(G, path, want):
    if not (isinstance(want, str) and re.fullmatch(r'[0-9a-f]{64}', want)): raise ShaError(f'{path}: pin is not a full 64-hex sha ({want!r})')
    G.allowed.add(os.path.abspath(path))
    b = open(path, 'rb').read(); h = hashlib.sha256(b).hexdigest()
    if h != want: raise ShaError(f'{path} {h} != {want}')
    return b, h

def first_line(b):
    return b.split(b'\n', 1)[0].decode().rstrip('\r')

def need_header(name, b, want):
    got = first_line(b)
    if got != want: raise PreError(f'{name} header {got!r} != {want!r}')

def preflight(C, G, log):
    """Pre-LOCK: sha of every input (bytes only) + header lines + manifests (SUMS / NEWS_DEV_INDEX: names and shas only).
    Never parses a data row. Used by --dry-check and as stage 1 of the single run."""
    R = C['root']; inp = {}; B = {}
    for k in ('p2sums', 'news_index', 'rsector', 'final100', 'universe_tsv', 's1c_sums', 'price_csv', 'dev_meta', 'price_dev_sums', 'price_top_sums'):
        B[k], inp[k] = read_verified(G, C[k], C[k + '_sha'])
    for k in ('price_csv', 'dev_meta', 'rsector', 'news_index'): need_header(k, B[k], HDR[k])
    if first_line(B['universe_tsv']).split('\t')[0] != 'symbol': raise PreError('UNIVERSE_H3.tsv first column is not symbol')
    s1c = parse_sums(B['s1c_sums'])
    for k, fn in (('final100', 'FINAL_100_H3.txt'), ('universe_tsv', 'UNIVERSE_H3.tsv')):
        if s1c.get(fn) != C[k + '_sha']: raise ShaError(f'stage1c SUMS entry {fn} {s1c.get(fn)} != pin {C[k + "_sha"]}')
    top = parse_sums(B['price_top_sums']); devs = parse_sums(B['price_dev_sums'])
    top_dev = {k: v for k, v in top.items() if k.startswith('dev/')}           # verify the dev entries only
    want_top = {'dev/prices_dev.csv': C['price_csv_sha'], 'dev/DEV_META.csv': C['dev_meta_sha'], 'dev/SHA256SUMS': C['price_dev_sums_sha']}
    if top_dev != want_top: raise ShaError(f'partitioned_prices/SHA256SUMS dev entries {top_dev} != {want_top}')
    if devs != {'prices_dev.csv': C['price_csv_sha'], 'DEV_META.csv': C['dev_meta_sha']}: raise ShaError(f'dev/SHA256SUMS {devs} mismatch')
    inp['coverage'] = []
    for p, h in C['coverage']:
        bb, hh = read_verified(G, p, h); need_header(os.path.basename(p), bb, HDR['coverage']); inp['coverage'].append([p, hh])
    sums = parse_sums(B['p2sums'], strip='partition_2/')
    earn_keys = sorted(k for k in sums if re.fullmatch(r'dev/earnings/[^/]+\.json', k))
    if len(earn_keys) != C['n_universe']: raise PreError(f'dev/earnings entries {len(earn_keys)} != {C["n_universe"]}')
    for k in earn_keys + ['dev/bench/SPY.json']:
        if k not in sums: raise PreError(f'{k} not in partition_2 SUMS')
        read_verified(G, f'{R}/partition_2/{k}', sums[k])
    idx = [l.rstrip('\r').split('\t') for l in B['news_index'].decode().split('\n')[1:] if l.strip()]
    for row in idx:
        if len(row) != 2 or not re.fullmatch(r'raw/2/news/[^/]+/\d{4}-\d{2}\.json', row[0]) or row[0][-12:-5] >= '2025-01':
            raise PreError(f'NEWS_DEV_INDEX bad row {row!r:.120}')
    for p, h in idx: read_verified(G, f'{R}/{p}', h)
    inp['n_news_files_sha_ok'] = len(idx); inp['n_earnings_files_sha_ok'] = len(earn_keys)
    log('preflight', json.dumps(dict(n_news=len(idx), n_earn=len(earn_keys), n_cov=len(C['coverage']))))
    return inp, sums, idx, earn_keys

def universe_check(C, G, sums, idx, earn_keys):
    """F1: universe = FINAL_100_H3.txt (full-sha pinned). Cross-check vs dev/earnings entries and NEWS_DEV_INDEX. Any mismatch = STOP."""
    b, _ = read_verified(G, C['final100'], C['final100_sha'])
    U = [l.strip() for l in b.decode().split('\n') if l.strip()]
    if len(U) != C['n_universe'] or len(set(U)) != len(U) or not all(TICK.match(s) for s in U):
        raise PreError(f'FINAL_100 format: {len(U)} lines, {len(set(U))} unique')
    U = sorted(U); Us = set(U)
    e = {k.split('/')[-1][:-5] for k in earn_keys}
    if e != Us: raise PreError(f'universe x-check: FINAL_100 vs dev/earnings differ {sorted(e ^ Us)}')
    want = {f'raw/2/news/{s}/{m}.json' for s in U for m in MONTHS}; got = [p for p, _ in idx]
    if set(got) != want or len(got) != len(want): raise PreError(f'universe x-check: NEWS_DEV_INDEX != FINAL_100 x 2022-03..2024-12 ({len(got)} rows)')
    return U

def av_daily(b):
    d = json.loads(b); ts = d['Time Series (Daily)']      # 'Meta Data' never read (P-6)
    return {k: float(v['5. adjusted close']) for k, v in ts.items()}

def drop_stale_terminal(df):
    """DV-25 (Victor L561): for EVERY symbol, look at its single FINAL bar only (once, not iterated). If volume <= 1 AND adjusted_close ==
    the previous bar's adjusted_close, drop that final bar; the previous bar becomes the symbol's effective last bar. Returns (df, [[sym, date], ...])."""
    vol = pd.to_numeric(df['volume'], errors='coerce')
    d = df.assign(_v=vol).sort_values(['symbol', 'date'])
    drop_idx, dropped = [], []
    for s, gd in d.groupby('symbol', sort=True):
        if len(gd) < 2: continue
        last, prev = gd.iloc[-1], gd.iloc[-2]
        if last['_v'] <= 1 and last['adjusted_close'] == prev['adjusted_close']:
            drop_idx.append(gd.index[-1]); dropped.append([s, last['date']])
    return df.drop(index=drop_idx), dropped

def load_prices(C, G, U, sess):
    """prices_dev.csv long format -> wide adjusted_close (XNYS sessions <= DEV_END). Any format/universe mismatch = DataError."""
    b, _ = read_verified(G, C['price_csv'], C['price_csv_sha']); need_header('price_csv', b, HDR['price_csv'])
    df = pd.read_csv(io.BytesIO(b), dtype={'symbol': str, 'date': str}, keep_default_na=False, na_values=[''])
    if list(df.columns) != HDR['price_csv'].split(','): raise DataError('prices columns')
    if len(df) != C['expect_price_rows']: raise DataError(f'prices rows {len(df)} != {C["expect_price_rows"]}')
    if set(df.symbol) != set(U): raise DataError(f'universe x-check: prices symbols differ {sorted(set(df.symbol) ^ set(U))[:10]}')
    if not df.date.str.fullmatch(r'\d{4}-\d{2}-\d{2}').all(): raise DataError('prices date format')
    if df.date.min() < DEV_START or df.date.max() > DEV_END: raise DataError(f'prices dates {df.date.min()}..{df.date.max()} outside DEV')
    if df.duplicated(['symbol', 'date']).any(): raise DataError('prices duplicate symbol/date')
    ac = pd.to_numeric(df.adjusted_close, errors='coerce')
    if not (np.isfinite(ac) & (ac > 0)).all(): raise DataError('prices adjusted_close not finite/positive')
    df = df.assign(adjusted_close=ac.astype(float))
    mb, _ = read_verified(G, C['dev_meta'], C['dev_meta_sha']); need_header('dev_meta', mb, HDR['dev_meta'])
    M = pd.read_csv(io.BytesIO(mb), dtype=str).set_index('symbol')
    if set(M.index) != set(U): raise DataError('universe x-check: DEV_META symbols differ')
    g = df.groupby('symbol').date.agg(['min', 'max', 'count'])
    for s in U:
        if (g.loc[s, 'min'], g.loc[s, 'max'], int(g.loc[s, 'count'])) != (M.loc[s, 'first_bar'], M.loc[s, 'last_bar'], int(M.loc[s, 'rows'])):
            raise DataError(f'DEV_META mismatch for {s}')
    off = int((~df.date.isin(set(sess))).sum())
    ss = set(sess); have = df.groupby('symbol').date.agg(set)
    gaps = {s: sum(1 for d in sess if M.loc[s, 'first_bar'] <= d <= M.loc[s, 'last_bar'] and d not in have[s]) for s in U}
    if any(gaps.values()): raise DataError(f'interior XNYS session gaps (closure rule needs terminal ends only): { {k: v for k, v in gaps.items() if v} }')
    # DV-25: DEV_META first/last/rows and the gap check above ran on the file AS WRITTEN (last_bar = the dropped date for dropped symbols;
    # rows = DEV_META rows before dropping). The stale final bar is dropped only now, so everything downstream uses the effective last bar.
    nrows = len(df); df, dropped = drop_stale_terminal(df)
    P = df.pivot(index='date', columns='symbol', values='adjusted_close').reindex(sess)[U]
    return P, dict(rows=nrows, off_calendar_rows=off, stale_terminal_dropped_n=len(dropped), stale_terminal_dropped=dropped,
                   stale_terminal_expected_n=STALE_EXPECT_N, stale_terminal_count_matches_expected=(len(dropped) == STALE_EXPECT_N)), M

def load_coverage(C, G, U):
    frames = []
    for p, h in C['coverage']:
        b, _ = read_verified(G, p, h); need_header(os.path.basename(p), b, HDR['coverage'])
        frames.append(pd.read_csv(io.BytesIO(b), sep='\t', dtype=str, keep_default_na=False))
    cov = pd.concat(frames, ignore_index=True)
    if len(cov) != C['expect_cov_rows']: raise DataError(f'coverage rows {len(cov)} != {C["expect_cov_rows"]}')
    if set(cov.symbol) != set(U): raise DataError(f'universe x-check: coverage symbols differ {sorted(set(cov.symbol) ^ set(U))[:10]}')
    if set(zip(cov.symbol, cov.month)) != {(s, m) for s in U for m in MONTHS}: raise DataError('coverage symbol x month grid != universe x 2022-03..2024-12')
    if (cov.month > '2024-12').any(): raise DataError('coverage month after 2024-12')
    cls = cov.coverage
    if not (cls.eq('ok') | cls.str.startswith('coverage=0') | cls.str.contains('NO_NEWS')).all():
        raise DataError(f'coverage class not in ok / coverage=0 / NO_NEWS*: {sorted(set(cls))[:8]}')
    cov0 = set(zip(cov.symbol[cls.str.startswith('coverage=0')], cov.month[cls.str.startswith('coverage=0')]))
    capped = {}; wre = re.compile(r'^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$')
    for s, cw in zip(cov.symbol, cov.capped_windows):
        cw = cw.strip()
        if cw in ('', '-', '0'): continue
        for part in cw.split(';'):
            if not wre.match(part.strip()): raise DataError(f'capped_windows format {cw!r:.80} (expected YYYY-MM-DD..YYYY-MM-DD[;...] or -/0)')
            a_, b_ = part.strip().split('..')
            capped.setdefault(s, []).append((dt.date.fromisoformat(a_) - dt.timedelta(days=1), dt.date.fromisoformat(b_) + dt.timedelta(days=1)))
    return cov0, capped, dict(rows=len(cov), classes={k: int(v) for k, v in cls.value_counts().items()})

def load_earnings(C, G, U, sums):
    earn = {}; missing = []; rows = 0
    for s in U:
        b, _ = read_verified(G, f'{C["root"]}/partition_2/dev/earnings/{s}.json', sums[f'dev/earnings/{s}.json'])
        d = json.loads(b)
        if not isinstance(d, dict) or set(d) != {'symbol', 'source_class', 'quarterlyEarnings'}: raise DataError(f'earnings {s} keys {sorted(d)[:6]} (split format)')
        if d['symbol'] != s or not isinstance(d['quarterlyEarnings'], list): raise DataError(f'earnings {s} symbol/list')
        ds = set()
        for e in d['quarterlyEarnings']:
            if not isinstance(e, dict) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(e.get('reportedDate', ''))): raise DataError(f'earnings {s} row reportedDate')
            if e['reportedDate'] > DEV_END: raise DataError(f'earnings {s} reportedDate {e["reportedDate"]} after DEV')
            ds.add(e['reportedDate']); rows += 1
        if not ds: missing.append(s)
        earn[s] = sorted(ds)
    if sorted(missing) != sorted(C['expect_earn_missing']): raise DataError(f'earnings MISSING set {missing} != {C["expect_earn_missing"]}')
    return earn, missing, rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--test-mode', action='store_true'); ap.add_argument('--synth-cfg')
    ap.add_argument('--dry-check', action='store_true', help='pre-LOCK checks only: shas, header lines, manifests; no data rows, no LOCK, no output')
    a = ap.parse_args()
    if a.test_mode:
        C = json.load(open(a.synth_cfg)); C['mode'] = 'TEST'
        if not (C['out'].startswith(SYNTH_DIR) and C['lock'].startswith(SYNTH_DIR)):
            sys.stderr.write('CONFIG (exit 6): test lock/out must be under ' + SYNTH_DIR + '\n'); sys.exit(EXIT_CFG)
    else:
        C = dict(REAL)
    missing = [k for k in CFG_KEYS if not C.get(k)]
    if missing or len(C['coverage']) != 7:
        sys.stderr.write(f'CONFIG BLOCKED (exit 6): unset {missing} / coverage files {len(C.get("coverage") or [])}. No lock taken, no data read.\n'); sys.exit(EXIT_CFG)
    calx, usable, nxt, facts = calendar_facts()
    diffs = check_calendar(facts)
    if diffs:
        sys.stderr.write(f'S3 CALENDAR STOP (exit 4): {diffs}\n'); sys.exit(EXIT_CAL)
    if os.path.exists(C['lock']):
        sys.stderr.write(f'LOCK EXISTS (exit 7): {C["lock"]} - one run only\n'); sys.exit(EXIT_LOCK)
    RUNNER_SHA = _sha_file(os.path.abspath(__file__))     # before the guard is installed
    G = Guard([C['out']]); G.install()
    pre_log = []
    try:
        inputs, sums, idx, earn_keys = preflight(C, G, lambda *x: pre_log.append(' '.join(map(str, x))))
        if a.dry_check:
            for p in (C['lock'], C['out']):
                if os.path.exists(p): sys.stderr.write(f'DRY-CHECK: {p} exists\n'); sys.exit(EXIT_LOCK)
            print(json.dumps(dict(dry_check='PASS', mode=C['mode'], calendar=facts, inputs=inputs, env=ENV, path_guard_denials=G.denials,
                                  note='sha + header lines + manifests only; no data row parsed; no LOCK; no output dir'), default=str))
            sys.exit(0)
        U = universe_check(C, G, sums, idx, earn_keys)
    except PermissionError as e:
        sys.stderr.write(f'{e} (exit 3; pre-LOCK)\n'); sys.exit(EXIT_PATH)
    except ShaError as e:
        sys.stderr.write(f'SHA MISMATCH {e} (exit 2; pre-LOCK)\n'); sys.exit(EXIT_SHA)
    except (PreError, KeyError, ValueError, UnicodeDecodeError) as e:
        sys.stderr.write(f'PRE-LOCK FORMAT/UNIVERSE STOP {type(e).__name__} {e} (exit 8)\n'); sys.exit(EXIT_PRE)
    try:
        fd = os.open(C['lock'], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except FileExistsError:
        sys.exit(EXIT_LOCK)
    os.write(fd, json.dumps(dict(created=dt.datetime.now(dt.timezone.utc).isoformat(), runner=os.path.abspath(__file__),
                                  runner_sha=RUNNER_SHA, env=ENV)).encode()); os.close(fd)
    os.mkdir(C['out'])                                # must be new
    LOG = open(f'{C["out"]}/run.log', 'x')
    def log(*x):
        s = ' '.join(str(v) for v in x); LOG.write(s + '\n'); LOG.flush()
    log('H3 DEV run v3', C['mode'], dt.datetime.now(NY).isoformat()); log(DECL_D); log('env', json.dumps(ENV)); log('calendar', json.dumps(facts))
    for l in pre_log: log(l)
    log('universe (FINAL_100_H3.txt)', len(U), ','.join(U)); log('research_only_in_universe', sorted(RESEARCH_ONLY & set(U)))
    try:
        res = compute(C, G, log, calx, usable, nxt, facts, U, sums, idx, inputs)
    except PermissionError as e:
        log('PATH_GUARD', str(e)); LOG.close(); sys.stderr.write(f'{e} (exit 3)\n'); sys.exit(EXIT_PATH)
    except ShaError as e:
        log('SHA MISMATCH', str(e)); LOG.close(); sys.stderr.write(f'SHA MISMATCH {e} (exit 2)\n'); sys.exit(EXIT_SHA)
    except DataError as e:
        log('DATA STOP', str(e)); LOG.close(); sys.stderr.write(f'DATA STOP {e} (exit 9)\n'); sys.exit(EXIT_DATA)
    except Exception as e:   # any other failure after LOCK = incident to Jeremy, no retry (PREREG v2 sec.0)
        log('ABORT', type(e).__name__, str(e)); LOG.close(); sys.stderr.write(f'ABORT {type(e).__name__} {e} (exit 9)\n'); sys.exit(EXIT_DATA)
    res['path_guard_denials'] = G.denials
    with open(f'{C["out"]}/H3_DEV_RAW.json', 'x') as f: json.dump(res, f, indent=1, default=float)
    log('done; raw output to Victor first (S6)'); LOG.close()

def compute(C, G, log, calx, usable, nxt, facts, U, sums, idx, inputs):
    R = C['root']
    # ---- news (raw AV NEWS_SENTIMENT) ----
    cnt = dict(files=0, items_total=0, kept=0, no_entry=0, low_rel=0, unparseable=0, multi_entry=0, after_cutoff=0)
    DEV_CUT = dt.datetime(2024, 12, 31, 16, 0, tzinfo=NY)
    items = {s: [] for s in U}
    for p, h in idx:
        sym = p.split('/')[3]
        bb, _ = read_verified(G, f'{R}/{p}', h); cnt['files'] += 1
        d = json.loads(bb)
        if not isinstance(d, dict) or not isinstance(d.get('feed'), list): raise DataError(f'{p}: no feed list (format A-1)')
        for it in d['feed']:
            cnt['items_total'] += 1
            if not isinstance(it, dict) or 'time_published' not in it or not isinstance(it.get('ticker_sentiment', []), list):
                raise DataError(f'{p}: feed item lacks time_published/ticker_sentiment[] (format A-1)')
            try:
                naive = dt.datetime.strptime(it['time_published'], '%Y%m%dT%H%M%S')
            except Exception: cnt['unparseable'] += 1; continue
            tu = naive.replace(tzinfo=UTC); te = naive.replace(tzinfo=NY)
            if tu > DEV_CUT or te > DEV_CUT: cnt['after_cutoff'] += 1; continue
            ents = [e for e in it.get('ticker_sentiment', []) if isinstance(e, dict) and e.get('ticker') == sym]
            if not ents: cnt['no_entry'] += 1; continue
            if len(ents) > 1: cnt['multi_entry'] += 1
            try:
                rel = float(ents[0]['relevance_score']); s = float(ents[0]['ticker_sentiment_score'])
                if not (np.isfinite(rel) and np.isfinite(s)): raise ValueError
            except Exception: cnt['unparseable'] += 1; continue
            if rel < REL_MIN: cnt['low_rel'] += 1; continue
            cnt['kept'] += 1; items[sym].append((tu.timestamp(), te.timestamp(), s, rel))
    log('news', json.dumps(cnt))
    # ---- coverage (7 TSVs; coverage=0 months, capped windows) ----
    cov0, capped, covinfo = load_coverage(C, G, U); log('coverage', json.dumps(covinfo), 'coverage0', len(cov0), 'capped_symbols', len(capped))
    # ---- prices (long CSV, adjusted_close) + SPY bench ----
    sess = [d for d in calx if d <= DEV_END]; sidx = {d: i for i, d in enumerate(sess)}
    P, pinfo, META = load_prices(C, G, U, sess); log('prices', json.dumps(pinfo))
    log('DV-25 stale terminal bars dropped', pinfo['stale_terminal_dropped_n'], json.dumps(pinfo['stale_terminal_dropped']),
        'expected', STALE_EXPECT_N, 'match' if pinfo['stale_terminal_count_matches_expected'] else 'COUNT DIFFERS (reported only, not a STOP)')
    bspy, _ = read_verified(G, f'{R}/partition_2/dev/bench/SPY.json', sums['dev/bench/SPY.json'])
    try: spy = av_daily(bspy)
    except Exception as e: raise DataError(f'bench SPY format {e}')
    if max(spy) > DEV_END: raise DataError('bench SPY row after 2024-12-31')
    P['SPY'] = pd.Series(spy).reindex(sess)
    if P['SPY'].isna().any(): raise DataError('SPY missing XNYS sessions')
    r = P / P.shift(1) - 1.0
    rm = r['SPY']
    cv = r[U].rolling(BETA_N, min_periods=BETA_N).cov(rm); var = rm.rolling(BETA_N, min_periods=BETA_N).var()
    beta = cv.div(var, axis=0).shift(1)
    # ---- earnings (split format; R-EARN only; S4) ----
    earn, earn_missing, earn_rows = load_earnings(C, G, U, sums)
    log('earnings rows', earn_rows, 'earnings_missing (not imputed; R-EARN only)', earn_missing)
    # ---- sector (R-SECTOR only; full sha F2) ----
    b, _ = read_verified(G, C['rsector'], C['rsector_sha']); need_header('rsector', b, HDR['rsector'])
    sec = pd.read_csv(io.BytesIO(b), sep='\t', dtype=str, keep_default_na=False).set_index('symbol')['Sector'].to_dict()
    inputs = dict(inputs, n_news_files_verified=cnt['files'], prices=pinfo, coverage_info=covinfo, earnings_rows=earn_rows)
    arr = {s: np.array(items[s], float).reshape(-1, 4) for s in U}
    def earn_sessions(s):
        out = set()
        for d in earn[s]:
            j = next((i for i, x in enumerate(sess) if x >= d), None)
            if j is not None: out.update({j - 1, j, j + 1})
        return out
    ES = {s: earn_sessions(s) for s in U}
    Pv = P.values; col = {s: j for j, s in enumerate(P.columns)}
    def week_ret(s, i0, i1):
        """(ret, full, last_i): close t -> close t+1, or to the last valid bar in (t, t+1] if the series ends (OQ-3 closure)."""
        p0 = Pv[i0, col[s]]; seg = Pv[i0 + 1:i1 + 1, col[s]]
        ok = np.isfinite(seg)
        if ok.all(): return seg[-1] / p0 - 1.0, True, i1
        if not ok.any(): return 0.0, False, i0            # no bar after t: closed at close t (its last bar)
        j = int(np.flatnonzero(ok)[-1])
        if not ok[:j + 1].all(): raise DataError(f'{s}: gap inside week after {sess[i0]} (not a terminal series end)')
        return seg[j] / p0 - 1.0, False, i0 + 1 + j
    def weeks_for(reading, W, rearn=False):
        c = 0 if reading == 'UTC' else 1; wks = []
        ex = dict(coverage0=0, capped=0, below_min=0, no_beta_or_price=0, ic_no_return=0, closed_last_bar_in_pool=0, earn=0, earn_missing=0)
        for d in usable:
            i0, i1 = sidx[d], sidx[nxt[d]]
            ws, we = cutoff(sess[i0 - W]), cutoff(d); ms = month_set(ws, we)
            d0, d1 = dt.date.fromisoformat(sess[i0 - W]), dt.date.fromisoformat(d)
            Sv = {}; yv = {}; rv = {}; closed = set(); icset = []
            for s in U:
                if any((s, m) in cov0 for m in ms): ex['coverage0'] += 1; continue
                if any(a_ <= d1 and b_ >= d0 for a_, b_ in capped.get(s, [])): ex['capped'] += 1; continue
                if rearn:
                    if s in earn_missing: ex['earn_missing'] += 1; continue
                    if ES[s] & set(range(i0 - W, i0 + 1)): ex['earn'] += 1; continue
                A = arr[s]; m_ = (A[:, c] > ws) & (A[:, c] <= we)
                if m_.sum() < MIN_ITEMS: ex['below_min'] += 1; continue
                bt = beta.iloc[i0][s]
                if not (np.isfinite(bt) and np.isfinite(Pv[i0, col[s]])): ex['no_beta_or_price'] += 1; continue
                Sv[s] = float(np.average(A[m_, 2], weights=A[m_, 3]))             # BOOK POOL: valid signal + finite beta (L557)
                ret, full, li = week_ret(s, i0, i1)
                spy_r = Pv[li, col['SPY']] / Pv[i0, col['SPY']] - 1.0
                rv[s] = float(ret); yv[s] = float(ret - bt * spy_r)
                if full: icset.append(s)                                           # IC SAMPLE: + valid next-week return (L127, L139)
                else: closed.add(s); ex['ic_no_return'] += 1; ex['closed_last_bar_in_pool'] += 1
            n = len(Sv); scored = n >= MIN_NAMES; q = {}
            if n:
                names = sorted(Sv); rk = stats.rankdata([Sv[s] for s in names])
                q = {s: (Sv[s], (rk[j] - 0.5) / n) for j, s in enumerate(names)}
            ic_ok = scored and len(icset) >= MIN_NAMES
            wks.append(dict(dec=d, nxt=nxt[d], n=n, n_ic=len(icset), scored=scored, qual=q, r=rv, y=yv, closed=closed,
                            ic=(float(stats.spearmanr([Sv[s] for s in icset], [yv[s] for s in icset]).statistic) if ic_ok else None),
                            ic_sec=(sector_ic(icset, Sv, yv, sec) if ic_ok else None)))
        return wks, ex
    out = dict(header=DECL_D, prereg='PREREG_H3_DRAFT_v2.md ecce2bbf', seal='40ddcc9c (S1-S6)', rulings='Victor L557 (51c8ca77), L560 (c37eedb2), L561 (1eb03efe)', env=ENV,
               calendar=facts, inputs=inputs, news_counts=cnt, universe=U, earnings_missing=earn_missing, results={}, weekly={},
               stale_terminal_bars=dict(rule='DV-25: final bar dropped if volume <= 1 and adjusted_close == prior bar (once, all symbols)',
                                        dropped_n=pinfo['stale_terminal_dropped_n'], dropped=pinfo['stale_terminal_dropped'],
                                        expected_n=STALE_EXPECT_N, count_matches_expected=pinfo['stale_terminal_count_matches_expected']))
    for rd in ('UTC', 'ET'):
        for name, W, mode, rearn in (('H3', W_H3, 'band', False), ('X1', W_X1, 'band', False), ('X2', W_H3, 'quintile', False), ('R-EARN', W_H3, 'band', True)):
            wks, ex = weeks_for(rd, W, rearn)
            book, term = run_book(wks, mode)
            out['results'][f'{name}_{rd}'] = summarise(name, rd, wks, book, term, ex)
            out['weekly'][f'{name}_{rd}'] = [dict(dec=w['dec'], nxt=w['nxt'], n=w['n'], n_ic=w['n_ic'], scored=w['scored'], ic=w['ic'], ic_sector=w['ic_sec'],
                                                  **{k: v for k, v in bk.items() if k not in ('longs', 'shorts', 'dec', 'scored', 'closed_names')},
                                                  closed_names=trade_list(bk['closed_names']),
                                                  longs=trade_list(bk['longs']), shorts=trade_list(bk['shorts']),
                                                  research_only_held=sorted(RESEARCH_ONLY & set(bk['longs'] + bk['shorts'])))
                                             for w, bk in zip(wks, book)]
            log(name, rd, json.dumps(out['results'][f'{name}_{rd}'], default=float))
    for name in ('H3', 'X1', 'X2', 'R-EARN'):
        u_, e_ = out['results'][f'{name}_UTC'], out['results'][f'{name}_ET']
        out['results'][f'{name}_A4_materiality'] = dict(delta_mean_ic=(None if u_['mean_ic'] is None or e_['mean_ic'] is None else u_['mean_ic'] - e_['mean_ic']),
                                                        delta_net10=u_['ls_net10_mean'] - e_['ls_net10_mean'])
    g = [out['results'][f'H3_{rd}'] for rd in ('UTC', 'ET')]
    out['DEV_GATE'] = dict(rule='FAIL if under either reading DEV mean IC <= 0 or DEV banded raw L/S mean weekly net at 10 bps <= 0',
                           UTC=g[0]['dev_gate'], ET=g[1]['dev_gate'],
                           H3=('PASS' if all(x['dev_gate'] == 'PASS' for x in g) else 'FAIL'))
    return out
def sector_ic(names, Sv, yv, sec):   # R-SECTOR: sector-demeaned S and target, then Spearman (OQ-9)
    df = pd.DataFrame(dict(S=[Sv[s] for s in names], y=[yv[s] for s in names], sec=[sec.get(s) for s in names]))
    df = df[df.sec.notna() & (df.sec != '')]
    if len(df) < MIN_NAMES: return None
    df['S'] -= df.groupby('sec').S.transform('mean'); df['y'] -= df.groupby('sec').y.transform('mean')
    return float(stats.spearmanr(df.S, df.y).statistic)

def summarise(name, rd, wks, book, term, ex):
    ics = [w['ic'] for w in wks if w['scored'] and w['ic'] is not None]; secs = [w['ic_sec'] for w in wks if w['scored'] and w['ic_sec'] is not None]
    B = pd.DataFrame(book); T = len(B)
    mic = float(np.mean(ics)) if ics else None
    icst = one_sided(ics) if ics else {}
    net = B['net10'].values; netst = one_sided(net)
    gm, tm = float(B['gross'].mean()), float(B['traded'].mean())
    liq = net.copy(); liq[-1] -= C10 * term
    entries = 0; pw = 0; prev = set()
    for bk in book:
        cur = set(bk['longs']) | {'-' + s for s in bk['shorts']}; entries += len(cur - prev); pw += len(cur); prev = cur
    res = dict(variant=name, reading=rd, exploratory=(name != 'H3'), weeks_in_series=T, scored_weeks=len(ics), mean_ic=mic,
               ic_nw_t=icst.get('nw_t'), ic_p_one_sided=icst.get('p_one_sided'), ic_df=icst.get('df'),
               ls_gross_mean=gm, ls_net10_mean=float(B['net10'].mean()), ls_net20_mean=float(B['net20'].mean()),
               ls_net10_nw_t=netst['nw_t'], ls_net10_p_one_sided=netst['p_one_sided'],
               ls_betaadj_gross_mean=float(B['betaadj'].mean()), ls_betaadj_net10_mean=float((B['betaadj'] - C10 * B['traded']).mean()),
               ls_net10_with_liquidation_mean=float(liq.mean()), terminal_liquidation_weight=term,
               mean_traded_weight=tm, mean_one_way_turnover=tm / 2, breakeven_cost_per_side_bps=(gm / tm * 1e4 if tm > 0 else None),
               avg_holding_weeks=(pw / entries if entries else None), flat_weeks=int(B['flat'].sum()), forced_exits=int(B['forced_exits'].sum()),
               closed_last_bar_names=int(B['closed_last_bar'].sum()), closed_last_bar_weeks=int((B['closed_last_bar'] > 0).sum()),
               ic_weeks_skipped_n_ic_lt_40=sum(1 for w in wks if w['scored'] and w['ic'] is None),
               mean_n_long=float(B['n_long'].mean()), mean_n_short=float(B['n_short'].mean()), mean_qualifying=float(np.mean([w['n'] for w in wks])),
               sector_ic_mean=(float(np.mean(secs)) if secs else None), sector_ic_weeks=len(secs), exclusions=ex)
    if name == 'H3':
        res['dev_gate'] = 'PASS' if (mic is not None and mic > 0 and res['ls_net10_mean'] > 0) else 'FAIL'
    return res

if __name__ == '__main__':
    main()
