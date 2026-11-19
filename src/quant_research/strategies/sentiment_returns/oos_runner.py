from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
# oos_runner.py - single sealed H1b OOS run (prereg v5 4b045f05..., sealed L293; Jeremy/Victor conditions L297).
# Reuses dev_run.py (copied byte-for-byte, sha pinned) by executing its source with a DECLARED, exact-match list of
# textual edits (EDITS below; each must match exactly once). The SAME transformed source runs in both modes:
#   --mode dev_rehearsal : DEV window/data (parity proof vs DEV_FREEZE 177f5e97). Refuses any HOLDOUT/raw path or news >= 2025-01.
#   --mode oos           : H1b only, both readings (A3), decisions 2025-01-01..2026-10-31. One run; no retries.
# No network. No trading. Output = raw stats for Victor (he rules PASS/FAIL, L297 (d)).
# v2 (Victor C2): interpreter environment pinned via oos_config.json 'env_pin'; verified right after the config is parsed, before any
#   other input is read and before the lock/output folder exist (exit 5 on mismatch). Observed values logged in RUNNER_LOG + *_RAW.json.
import os, sys, re, json, hashlib, argparse, builtins, datetime as dt, traceback

STAGE = os.path.dirname(os.path.abspath(__file__))
DEV_RUN_SHA = '80f4bb71485d2e20741f76a5a2197d64cdb05afeaf7f4d11ba7ac565d462329f'   # = DEV MANIFEST entry
NEWS_RE = re.compile(r'/news/([^/]+)/(\d{4}-\d{2})\.json$')

def sha_file(p):
    h = hashlib.sha256()
    with builtins.open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def die(msg, code=3):
    sys.stderr.write('ABORT: ' + msg + '\n'); sys.exit(code)

ENV_KEYS = ('executable', 'realpath_sha256', 'python', 'pandas', 'numpy', 'exchange_calendars')
def observe_env():
    import platform, pandas, numpy, exchange_calendars
    rp = os.path.realpath(sys.executable)
    return dict(executable=sys.executable, realpath=rp, realpath_sha256=sha_file(rp), python=platform.python_version(),
                pandas=pandas.__version__, numpy=numpy.__version__, exchange_calendars=exchange_calendars.__version__,
                isolated=sys.flags.isolated, dont_write_bytecode=sys.flags.dont_write_bytecode)

def verify_env(pin):
    # v2 / C2: every pinned key must be present and equal; any mismatch -> exit 5 (nothing created yet).
    env = observe_env()
    if not isinstance(pin, dict): die('env_pin missing from config', 5)
    bad = [(k, pin.get(k), env[k]) for k in ENV_KEYS if pin.get(k) != env[k]]
    if pin.get('realpath') is not None and pin['realpath'] != env['realpath']: bad.append(('realpath', pin['realpath'], env['realpath']))
    if bad: die('env pin mismatch (before lock): ' + '; '.join(f'{k}: pinned {w!r} observed {o!r}' for k, w, o in bad), 5)
    return env

# ---------------- declared edits to dev_run.py (old, new); each old must occur exactly once ----------------
EDITS = [
 (f"OUT = '{_QR.DESK_DIR}/research/original/sentiment_returns_dev_20261111'", "OUT = _CFG['out_dir']"),
 ("daily = pd.read_csv(f'{RET}/daily_dev.csv');", "daily = _load_daily();"),
 ("assert len(daily) == 49317 and len(earn) == 5279", "assert len(daily) == _CFG['expected_daily_rows'] and len(earn) == 5279"),
 ("assert daily['date'].max() <= '2024-12-31'", "assert daily['date'].max() <= _CFG['last_return_date']"),
 ("sess = [d.strftime('%Y-%m-%d') for d in cal.sessions_in_range('2021-03-01', '2024-12-31')]",
  "sess = [d.strftime('%Y-%m-%d') for d in cal.sessions_in_range('2021-03-01', _CFG['last_return_date'])]"),
 ("cov_news = cov_news[cov_news['month'] <= '2024-12']",
  "cov_news = cov_news[(cov_news['month'] <= _CFG['news_months'][-1]) & (cov_news['month'] >= _CFG['news_months'][0])]"),
 ("months = [f'{y}-{m:02d}' for y in (2022, 2023, 2024) for m in range(1, 13) if f'{y}-{m:02d}' >= '2022-03']",
  "months = list(_CFG['news_months'])"),
 ("assert months[-1] == '2024-12' and len(months) == 34", "assert months == _CFG['news_months'] and len(months) == _CFG['n_news_months']"),
 ("DEV_CUTOFF = dt.datetime(2024, 12, 31, 16, 0, tzinfo=NY)", "DEV_CUTOFF = dt.datetime(*_CFG['item_cutoff_ymd'], 16, 0, tzinfo=NY)"),
 ("        assert mth <= '2024-12'", "        assert mth <= _CFG['news_months'][-1]"),
 ("assert len(capped) == 0 and len(tsvcap) == 0", "assert set(capped) == {k[:2] for k in tsvcap}"),
 ("dec = [d for d in sess if '2022-03-01' <= d <= '2024-12-31']", "dec = [d for d in sess if _CFG['dec_start'] <= d <= _CFG['dec_end']]"),
 ("if p['nxt'] is None or p['nxt'] > '2024-12-31':", "if p['nxt'] is None or p['nxt'] > _CFG['last_return_date']:"),
 ("assert p['nxt'] <= '2024-12-31'", "assert p['nxt'] <= _CFG['last_return_date']"),
 # prereg v5 s3: capped_incomplete excludes a symbol only from windows overlapping a LISTED capped weekly window
 # ("Rest of that month usable"). dev_run's month-level test was never exercised in DEV (0 capped months).
 ("if any((sym, m) in capped for m in ms): ex['obs_capped'] += 1; continue",
  "if _capped_hit(sym, p['ws'], p['we']): ex['obs_capped'] += 1; continue"),
]
TRUNCATE_AT = "results = {}\n"   # stop before dev_run's own H1a/H1b driver loop and json dump

def transformed_source(src):
    for old, new in EDITS:
        if src.count(old) != 1: die(f'edit anchor count != 1: {old!r}')
        src = src.replace(old, new)
    i = src.find(TRUNCATE_AT)
    if i < 0 or src.count(TRUNCATE_AT) != 1: die('truncate anchor')
    return src[:i]

# ---------------- pass bars (prereg v5 s5, A1-A5; Victor seal note on Holm step-down) ----------------
def holm_h1b(p_h1b, p_h1a=1.0, alpha=0.05):
    # s5 / A5: family N = 2 {H1a, H1b}, one-sided, Holm at 0.05 within each reading. A2 + seal record: H1a failed DEV,
    # keeps its Holm slot with p := 1. Step-down (Victor, seal L293): smallest p tested at alpha/2 = 0.025; the larger at
    # 0.05 only if the smaller is rejected. Ties (p_h1b == 1) -> H1b ordered first; it is not rejected either way.
    fam = sorted([('H1b', p_h1b), ('H1a', p_h1a)], key=lambda x: (x[1], x[0] != 'H1b'))
    m = len(fam); rejected = {}; stop = False; adj = {}; run_max = 0.0
    for i, (h, p) in enumerate(fam):
        thr = alpha / (m - i); run_max = max(run_max, min(1.0, (m - i) * p)); adj[h] = run_max
        rej = (not stop) and p < thr
        if not rej: stop = True
        rejected[h] = dict(p=p, threshold=thr, rejected=bool(rej), holm_adj_p=adj[h])
    return rejected

def evaluate_h1b(oos, dev):
    # s5 PASS, required under BOTH readings (A3), each vs its own frozen DEV stats:
    out = {}
    for rd in ('UTC', 'ET'):
        o, d = oos[rd], dev[rd]; hb = holm_h1b(o['p_one_sided'])['H1b']
        c = {
         'i_dev_mean_ic_gt_0 (s5(i), A2)': d['mean_ic'] > 0,
         'ii_holm_adjusted_p_lt_0.05 (s5(ii), A5; equiv. raw p < 0.025 step 1)': hb['rejected'] and hb['holm_adj_p'] < 0.05,
         'iii_oos_mean_ic_gt_0 (s5(iii))': o['mean_ic'] > 0,
         'iii_oos_mean_ic_ge_50pct_dev (s5(iii))': o['mean_ic'] >= 0.5 * d['mean_ic'],
         'iv_ls_net10_raw_gt_0 (s5(iv), A1a k=floor(n/5), s4A raw returns, 10 bps/side)': o['ls_net10_raw_mean'] > 0,
        }
        out[rd] = dict(criteria={k: bool(v) for k, v in c.items()}, holm=hb, all_met=bool(all(c.values())),
                       dev_mean_ic=d['mean_ic'], oos_mean_ic=o['mean_ic'], half_dev_mean_ic=0.5 * d['mean_ic'])
    out['PASS_both_readings (A3 conjunctive gate)'] = bool(out['UTC']['all_met'] and out['ET']['all_met'])
    out['note'] = 'Runner-computed against v5 s5 bars; Victor rules PASS/FAIL (L297 (d)). A pass is evidence only (L297 (e)).'
    return out

def a4_materiality(u, e):
    # s2 A4 (reported, not a gate): sign flip, |dIC| >= max(50% |UTC IC|, 0.01), or one-sided p crossing 0.05.
    thr = max(0.5 * abs(u['mean_ic']), 0.01); d = abs(u['mean_ic'] - e['mean_ic'])
    sf = (u['mean_ic'] > 0) != (e['mean_ic'] > 0); pc = (u['p_one_sided'] < 0.05) != (e['p_one_sided'] < 0.05)
    return dict(abs_dIC=d, threshold=thr, sign_flip=bool(sf), p_cross_0_05=bool(pc), material=bool(sf or d >= thr or pc))

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', required=True, choices=['dev_rehearsal', 'oos'])
    ap.add_argument('--config', required=True)
    ap.add_argument('--release', default=None)
    ap.add_argument('--out', default=None, help='dev_rehearsal only: override out dir (tests); refused in oos mode')
    a = ap.parse_args()
    cfg_sha = sha_file(a.config); C = json.load(builtins.open(a.config))
    ENV = verify_env(C.get('env_pin'))   # v2 / C2: before any other input is read and before lock/out creation
    M = dict(C['modes'][a.mode]); P = C['frozen_params']; I = C['inputs']
    if a.mode == 'oos':
        if a.out: die('--out not allowed in oos mode')
        if not a.release: die('oos mode needs --release release_input.json')
    elif a.out:
        M['out_dir'] = a.out; M['lock_file'] = a.out.rstrip('/') + '.LOCK'
    # window sanity / partition guards (B1, B8; brief: rehearsal never touches 2025+)
    if a.mode == 'dev_rehearsal':
        if M['dec_end'] > '2024-12-31' or M['last_return_date'] > '2024-12-31' or max(M['news_months']) > '2024-12':
            die('dev_rehearsal refuses a window/news month >= 2025-01')
        if M.get('holdout_daily'): die('dev_rehearsal refuses holdout inputs')
    else:
        if M['dec_start'] < '2025-01-01': die('oos decisions must be >= 2025-01-01 (B8)')
    hyps = M['hypotheses']
    if a.mode == 'oos' and hyps != ['H1b']: die('L297 (c): oos mode runs H1b only')

    # ---- input sha verification BEFORE lock/output creation (abort on mismatch; no retries) ----
    PRE = [('env (verified vs env_pin before lock):', json.dumps(ENV, sort_keys=True))]
    me = sha_file(os.path.abspath(__file__)); PRE.append(('oos_runner.py sha', me))
    devrun = os.path.join(STAGE, 'dev_run.py')
    if sha_file(devrun) != DEV_RUN_SHA: die('dev_run.py sha mismatch')
    rel = None; rel_sha = None
    if a.mode == 'oos':
        rel_sha = sha_file(a.release); rel = json.load(builtins.open(a.release)); PRE.append(('release_input.json sha', rel_sha))
        hs = rel.get('holdout_sums_sha256', '')
        if not re.fullmatch(r'[0-9a-f]{64}', hs): die('release_input.holdout_sums_sha256 missing/placeholder')
        if rel.get('oos_config_sha256') != cfg_sha: die('config sha != release_input.oos_config_sha256')
        if rel.get('oos_runner_sha256') != me: die('runner sha != release_input.oos_runner_sha256')
    if sha_file(I['dev_freeze']) != I['dev_freeze_sha256']: die('DEV_FREEZE sha mismatch')
    if sha_file(I['dev_manifest']) != I['dev_manifest_sha256']: die('DEV MANIFEST sha mismatch')
    def check_sums(sums_path, want, files):
        if sha_file(sums_path) != want: die(f'SUMS sha mismatch: {sums_path}')
        tab = {}
        for line in builtins.open(sums_path):
            h, p = line.strip().split(None, 1); tab[p.lstrip('*').lstrip('./')] = h
        d = os.path.dirname(sums_path)
        for f in files:
            if sha_file(os.path.join(d, f)) != tab[f]: die(f'file sha mismatch: {f}')
        return tab
    check_sums(I['dev_sums'], I['dev_sums_sha256'], ['daily_dev.csv', 'earnings_dev.csv'])
    check_sums(I['news_sums'], I['news_sums_sha256'], ['coverage_news.tsv'])   # per-news-file shas checked by dev_run loop
    if a.mode == 'oos':
        check_sums(M['holdout_sums'], rel['holdout_sums_sha256'], ['daily_holdout.csv'])
    PRE.append(('input shas OK (verified before lock/out creation)',))

    # ---- one-run guard + lock (L297 (c)) ----
    out = M['out_dir']
    if os.path.exists(M['lock_file']): die(f"lock file exists: {M['lock_file']} (one run only)", 4)
    if os.path.exists(out): die(f'output folder exists: {out} (one run only)', 4)
    fd = os.open(M['lock_file'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    os.write(fd, f"{a.mode} started {dt.datetime.now().astimezone().isoformat()} config_sha {cfg_sha}\n".encode()); os.close(fd)
    os.mkdir(out)
    RL = builtins.open(f'{out}/RUNNER_LOG.txt', 'w')
    def rlog(*x):
        s = ' '.join(str(v) for v in x); print(s); RL.write(s + '\n'); RL.flush()
    for x in PRE: rlog(*x)
    rlog('mode', a.mode, 'config', a.config, cfg_sha, 'python', sys.version.split()[0], 'flags', sys.flags.isolated, sys.flags.dont_write_bytecode)

    # ---- guarded open (no raw/, no holdout via open, news months only inside the mode window) ----
    allowed_months = set(M['news_months'])
    def g_open(path, *ar, **kw):
        ap_ = os.path.abspath(str(path))
        if '/av_returns_events_20261111/raw' in ap_ or '/partitioned/holdout' in ap_: die(f'guard: refused {ap_}')
        m = NEWS_RE.search(ap_)
        if m and m.group(2) not in allowed_months: die(f'guard: refused news month {ap_}')
        if a.mode == 'dev_rehearsal' and m and m.group(2) >= '2025-01': die(f'guard: refused {ap_}')
        return builtins.open(path, *ar, **kw)

    import pandas as pd
    def _load_daily():
        d0 = pd.read_csv(I['dev_daily'])
        if a.mode == 'oos':   # B2: HOLDOUT rows may use DEV closes (beta warm-up, first return)
            d1 = pd.read_csv(M['holdout_daily'])
            if list(d1.columns) != list(d0.columns) or d1['date'].min() < '2025-01-01': die('holdout daily schema/date')
            d0 = pd.concat([d0, d1], ignore_index=True)
        return d0
    caps = {}
    if M.get('capped_from_tsv'):
        import csv
        for row in csv.DictReader(builtins.open(I['coverage_news_tsv']), delimiter='\t'):
            if row['month'] in allowed_months and row['capped_windows'] not in ('-', ''):
                for w in row['capped_windows'].split(','):
                    s, e = w.split('..'); caps.setdefault(row['symbol'], []).append((dt.date.fromisoformat(s), dt.date.fromisoformat(s[:8] + e)))
    from zoneinfo import ZoneInfo
    NYz = ZoneInfo('America/New_York')
    def _capped_hit(sym, ws, we):
        # s3 window overlap; padded +-1 day on nominal dates, same conservative padding as DEV note 4 (month test).
        a0 = dt.datetime.fromtimestamp(ws, NYz).date() - dt.timedelta(days=1)
        b0 = dt.datetime.fromtimestamp(we, NYz).date() + dt.timedelta(days=1)
        return any(s <= b0 and a0 <= e for s, e in caps.get(sym, []))

    src = transformed_source(builtins.open(devrun).read())
    ns = {'__name__': 'dev_run_reused', 'open': g_open, '_CFG': M, '_load_daily': _load_daily, '_capped_hit': _capped_hit}
    rlog('exec transformed dev_run.py (', len(EDITS), 'edits ) out', out)
    exec(compile(src, devrun, 'exec'), ns)
    rlog('capped (file keys):', sorted(ns['capped']), 'tsv windows:', {k: [(str(s), str(e)) for s, e in v] for k, v in caps.items()})
    res = {}
    for h in hyps:
        for rd in ('UTC', 'ET'):
            r_ = ns['run'](h, rd); r_.pop('A2_DEV', None); r_['mean_ic_gt_0'] = bool(r_['mean_ic'] > 0)
            res[f'{h}_{rd}'] = r_; rlog(h, rd, json.dumps(r_, default=float))
    F = json.load(builtins.open(I['dev_freeze']))['results']
    ev = {}
    for h in hyps:
        dev = {rd: F[f'{h}_{rd}'] for rd in ('UTC', 'ET')}; oo = {rd: res[f'{h}_{rd}'] for rd in ('UTC', 'ET')}
        ev[h] = dict(A4_materiality=a4_materiality(oo['UTC'], oo['ET']))
        if h == 'H1b': ev[h]['pass_bars'] = evaluate_h1b(oo, dev)
    O = dict(mode=a.mode, prereg='PREREG_DRAFT_v5.md 4b045f05da541175624946865ab695ed2f2c2fc1484554c065d940a2ec284c91',
             conditions='L297: one H1b OOS sitting; no reruns; Victor rules', oos_runner_sha256=me, dev_run_sha256=DEV_RUN_SHA,
             oos_config_sha256=cfg_sha, env=ENV, env_pin=C['env_pin'], release_input_sha256=rel_sha, release_input=rel, window=M,
             news_counts=ns['cnt'], results=res, evaluation=ev,
             H1a='DEV FAIL (A2): p := 1 in Holm; not run OOS' if a.mode == 'oos' else 'rehearsed on DEV',
             caveats=['not verified point-in-time (s7)', 'survivorship: positive results are an upper bound (s7)',
                      'timestamp zone unconfirmed; both readings gate (A3)'],
             finished=dt.datetime.now().astimezone().isoformat())
    name = 'OOS_RAW.json' if a.mode == 'oos' else 'REHEARSAL_RAW.json'
    json.dump(O, builtins.open(f'{out}/{name}', 'w'), indent=1, default=float)
    rlog('wrote', name)
    for f in sorted(os.listdir(out)): os.chmod(f'{out}/{f}', 0o444)

if __name__ == '__main__':
    main()
