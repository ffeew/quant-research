from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
# Metadata-only validation (Jeremy ruling B, 10 Nov 23:41... see README). Fields touched: news -> 'feed' (list length),
# item 'url', item 'time_published'; transcripts -> 'symbol', 'quarter', 'transcript' (entry count, total len of 'content'
# as a character count only). Never reads/prints sentiment, relevance, text or prices.
import json, os, hashlib, collections
D = f'{_QR.DATA_DIR}/av_sentiment_20261110'
rows = [l.rstrip('\n').split('\t') for l in open(D + '/CALLS.log', encoding='utf-8')]
ok = [r for r in rows if len(r) >= 12 and r[9] == 'OK']
outc = collections.Counter(r[9] for r in rows if len(r) >= 10)
miss = [r for r in rows if len(r) >= 10 and r[9] in ('MISSING', 'NOT_ATTEMPTED')]
capr = [r for r in rows if len(r) >= 10 and r[9].startswith('SPLIT_CAP_REACHED')]
calls = sum(1 for r in rows if len(r) >= 4 and r[3] != '-')
# duplicate sha across accepted files
shas = collections.defaultdict(list)
for r in ok: shas[r[8]].append(r[11])
dupsha = {k: v for k, v in shas.items() if len(v) > 1}
small = [(r[11], r[7]) for r in ok if int(r[7]) < 1024]
news = collections.defaultdict(dict)   # (sym, ym) -> {tag: path}
tr = {}
for r in ok:
    p = r[11]
    if '/raw/news/' in p:
        sym = p.split('/')[-2]; fn = os.path.basename(p)[:-5]; parts = fn.split('.')
        news[(sym, parts[0])]['M' if len(parts) == 1 else parts[1]] = p
    elif '/raw/transcripts/' in p:
        tr[(p.split('/')[-2], os.path.basename(p)[:-5])] = p
def meta(p):
    j = json.load(open(p, 'rb'))
    f = j.get('feed') if isinstance(j, dict) else None
    if not isinstance(f, list): return None
    return [(it.get('url'), it.get('time_published')) for it in f if isinstance(it, dict)]
nt = open(D + '/validation_news.tsv', 'x')
nt.write('symbol\tmonth\tfiles_used\titems_raw\titems_dedup\tdup_urls\ttime_min\ttime_max\ttruncated_windows\tnofeed_files\n')
persym = collections.defaultdict(lambda: [0, 0, 0, 0, None, None, 0, 0])
for (sym, ym), tags in sorted(news.items()):
    use = []
    for h in ('h1', 'h2'):
        w = [tags[h + x] for x in ('w1', 'w2') if h + x in tags]
        if w: use += w
        elif h in tags: use.append(tags[h])
    if not use: use = [tags['M']] if 'M' in tags else []
    items, trunc, nofeed = [], 0, 0
    for p in use:
        m = meta(p)
        if m is None: nofeed += 1; continue
        if len(m) >= 1000: trunc += 1
        items += m
    urls = [u for u, _ in items if u]; dd = len(set(urls)); dup = len(urls) - dd
    ts = [t for _, t in items if t]
    tmin, tmax = (min(ts), max(ts)) if ts else ('-', '-')
    nt.write('\t'.join(map(str, [sym, ym, len(use), len(items), dd, dup, tmin, tmax, trunc, nofeed])) + '\n')
    s = persym[sym]; s[0] += 1; s[1] += dd; s[2] += trunc; s[3] += (dd == 0)
    s[4] = tmin if s[4] is None or (tmin != '-' and tmin < s[4]) else s[4]
    s[5] = tmax if s[5] is None or (tmax != '-' and tmax > s[5]) else s[5]
    s[6] += nofeed; s[7] += dup
nt.close()
tt = open(D + '/validation_transcripts.tsv', 'x')
tt.write('symbol\tquarter\tholdout\tentries\tcontent_chars\tsymbol_match\tquarter_match\n')
trsym = collections.defaultdict(lambda: [0, 0, 0, 0])
for (sym, q), p in sorted(tr.items()):
    j = json.load(open(p, 'rb')); t = j.get('transcript') if isinstance(j, dict) else None
    n = len(t) if isinstance(t, list) else 0
    ch = sum(len(e.get('content') or '') for e in t if isinstance(e, dict)) if isinstance(t, list) else 0
    sm, qm = j.get('symbol') == sym if isinstance(j, dict) else False, j.get('quarter') == q if isinstance(j, dict) else False
    tt.write('\t'.join(map(str, [sym, q, 'holdout' if q >= '2016Q1' else 'pre', n, ch, sm, qm])) + '\n')
    s = trsym[sym]; s[0] += 1; s[1] += (n > 0); s[2] += (n == 0); s[3] += (n > 0 and not (sm and qm))
tt.close()
o = ['# VALIDATION (metadata only)', '', 'Request attempts: %d. Outcomes: %s' % (calls, dict(outc)), '',
     'MISSING / NOT_ATTEMPTED rows: %d' % len(miss)] + ['- ' + r[5] + ' ' + r[9] for r in miss] + [
     '', 'SPLIT_CAP_REACHED rows (still truncated or refused): %d' % len(capr)] + ['- ' + r[5] + ' ' + r[9] for r in capr] + [
     '', 'Accepted files under 1 KB: %d' % len(small)] + ['- %s (%s B)' % x for x in small[:200]] + [
     '', 'Duplicate sha256 across accepted files: %d groups' % len(dupsha)] + ['- %s: %s' % (k[:16], ', '.join(os.path.basename(os.path.dirname(x)) + '/' + os.path.basename(x) for x in v[:6])) for k, v in list(dupsha.items())[:200]] + [
     '', '## News per symbol', '', '| symbol | months | items (dedup) | truncated windows | zero-item months | no-feed files | dup URLs | time_published min | max |', '|---|---|---|---|---|---|---|---|---|']
for sym, s in sorted(persym.items()): o.append('| %s | %d | %d | %d | %d | %d | %d | %s | %s |' % (sym, s[0], s[1], s[2], s[3], s[6], s[7], s[4], s[5]))
o += ['', '## Transcripts per symbol', '', '| symbol | quarters OK | non-empty | empty | symbol/quarter mismatch |', '|---|---|---|---|---|']
for sym, s in sorted(trsym.items()): o.append('| %s | %d | %d | %d | %d |' % (sym, *s))
o += ['', 'Per-month and per-quarter detail: validation_news.tsv, validation_transcripts.tsv.']
open(D + '/VALIDATION.md', 'x').write('\n'.join(o) + '\n')
print('validation written', len(news), 'news months', len(tr), 'transcript files', 'dupsha', len(dupsha), 'small', len(small))
