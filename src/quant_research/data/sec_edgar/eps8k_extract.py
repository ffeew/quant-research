"""(a) EX-99.1 EPS extractor for 8-K Item 2.02 press releases.

For each 8-K accession: locate EX-99.1 (from Ethan's ex99_url when available, else the EDGAR filing index),
fetch it through sec_http (cached, <= 8 req/s, User-Agent from SEC_USER_AGENT), and extract:
  eps_diluted_reported : GAAP diluted EPS for the quarter (primary); if only an unlabeled per-share figure exists,
                         that figure with eps_basis = 'unlabeled-per-share'; NaN if only non-GAAP is reported
  eps_basis            : 'GAAP' | 'unlabeled-per-share' | 'adjusted' (non-GAAP only) | 'none'
  eps_adjusted         : adjusted/non-GAAP diluted EPS if reported (never substituted for GAAP)
  source_exhibit, parse_confidence ('high'|'medium'|'low'|'none'), parse_notes
Tables are read before prose. Negative numbers in parentheses (incl. split cells "(0.12" ")") and
"loss per share" wording are handled. The quarter column is the 3-month current-period column
(header year order is detected; a first column labelled six/nine/twelve months/year is skipped where possible).
No returns of any kind are computed here.
"""
import re, sys, json
import numpy as np, pandas as pd
from quant_research.data.sec_edgar import common; from quant_research.data.sec_edgar import sec_http; from quant_research.data.sec_edgar import htmltables

NUM = re.compile(r"(\(\s*)?(?:\$\s*)?(\(\s*)?(-|–|—)?\s*\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2,3}|\d+\.\d{2,3})(?![\d%])\s*(\))?")
ADJ = re.compile(r"non[\s-]*gaap|adjusted|\bcore\b|excluding|ex-items|pro[\s-]*forma|operating (?:eps|earnings per)|"
                 r"comparable|underlying|normalized|cash eps|recurring", re.I)
GAAP_EXPL = re.compile(r"(?<!non-)(?<!non )\bgaap\b|reported", re.I)
STATEMENT = re.compile(r"statements? of (?:consolidated )?(?:income|operations|earnings|comprehensive)|"
                       r"income statements?|results of operations", re.I)
EPS_CTX = re.compile(r"per (?:common |ordinary )?share|\beps\b|earnings \(?loss\)? per|per diluted share", re.I)
SHARES_ROW = re.compile(r"weighted|shares (?:used|outstanding)|average (?:number of )?(?:common )?shares|"
                        r"dividend|share count|shares in", re.I)
PARTIAL = re.compile(r"continuing operations|discontinued|extraordinary|before (?:cumulative|accounting)", re.I)
LONGPER = re.compile(r"full[\s-]+(?:fiscal\s+)?year|for\s+(?:the\s+)?(?:fiscal\s+)?year|(?:six|nine|twelve|6|9|12)\s+months\s+ended|(?:fiscal\s+)?years?\s+ended|year[\s-]to[\s-]date|\bytd\b|(?:24|26|36|39|40|52|53)\s+weeks\s+ended", re.I)
SHORTPER = re.compile(r"(?:three|3)\s+months\s+ended|quarters?\s+ended|(?:12|13|14|16|17)\s+weeks\s+ended|\bq[1-4]\b|(?:first|second|third|fourth)\s+quarter", re.I)
GUIDE = re.compile(r"\blow\b.{0,20}\bhigh\b|guidance|outlook|forecast|expect|projected|estimate", re.I)
LABEL_OK = re.compile(r"diluted|basic|per (?:common |ordinary )?share|\beps\b|net (?:income|earnings|loss)|earnings|income|loss|"
                      r"total|attributable|continuing|discontinued|reported|gaap", re.I)
NOTEPS = re.compile(r"shares used|weighted|average (?:number of )?(?:common )?(?:diluted )?shares|shares outstanding|"
                    r"for (?:the )?(?:calculation|computation)|used in|computing|dividends? (?:declared|paid|per)", re.I)


def parse_num(m, text_after=""):
    v = float(m.group(4).replace(",", ""))
    neg = bool(m.group(3)) or ((m.group(1) or m.group(2)) and (m.group(5) or text_after.lstrip().startswith(")")))
    return -v if neg else v


def row_numbers(cells):
    """Numbers in a table row after the label, merging split cells like '(0.12' ')'."""
    joined = " ".join(c for c in cells if c)
    out = []
    for m in NUM.finditer(joined):
        out.append(parse_num(m, joined[m.end():m.end() + 3]))
    return out


def label_of(row):
    lab = []
    for c in row:
        if NUM.search(c) and re.search(r"\d\.\d", c):
            break
        if c and c not in ("$", "(", ")"):
            lab.append(c)
    return " ".join(lab)


def header_info(rows):
    """Return (current_index, notes) using the header rows before the first numeric data row."""
    hdr = []
    for r in rows[:8]:
        if any(re.search(r"\d\.\d{2}", c) for c in r):
            break
        hdr.append(" ".join(r))
    h = " ".join(hdr)
    years = [int(y) for y in re.findall(r"\b(20[0-3]\d|19[89]\d)\b", h)]
    idx, notes = 0, []
    if len(years) >= 2 and years[1] > years[0]:
        idx = 1; notes.append("header years ascending: current column = 2nd")
    ml, ms = LONGPER.search(h), SHORTPER.search(h)
    long_first = bool(ml and (not ms or ml.start() < ms.start()))
    if long_first and ms:
        notes.append("header lists a longer period before the quarter; quarter column = after first pair")
        idx += 2
    elif long_first:
        notes.append("header suggests annual/YTD columns only")
    return idx, notes, long_first and not ms


def table_candidates(blocks):
    cands = []
    ctx_text = []
    for bi, (kind, val) in enumerate(blocks):
        if kind == "text":
            ctx_text = (ctx_text + [val])[-3:]
            continue
        rows = val
        title = " ".join(ctx_text[-2:])[-400:] + " " + " ".join(" ".join(r) for r in rows[:3])[:400]
        t_adj = bool(ADJ.search(title)) and not STATEMENT.search(title)
        t_stmt = bool(STATEMENT.search(title))
        if GUIDE.search(" ".join(" ".join(r) for r in rows[:3])) or (GUIDE.search(" ".join(ctx_text[-1:])[-200:]) and not t_stmt):
            continue  # guidance / outlook tables are never actuals
        cur_idx, hnotes, annual_only = header_info(rows)
        section = ""
        for ri, r in enumerate(rows):
            first_num = next((i for i, c in enumerate(r) if re.search(r"\d\.\d", c)), len(r))
            lab = " ".join(c for c in r[:first_num] if c and c not in ("$", "(", ")"))
            nums = row_numbers(r[first_num:])
            if not nums:
                if lab and len(lab) < 160 and not re.search(r"\d", lab):
                    section = lab
                continue
            # strip numbers that are part of the label (e.g., footnote refs)
            full = (section + " | " + lab) if lab else section
            if NOTEPS.search(lab) or NOTEPS.search(section) or (SHARES_ROW.search(section) and not EPS_CTX.search(lab)):
                continue  # share-count / dividend rows and rows under a share-count section (e.g. DXC)
            if re.search(r"\bsegments?\b|business unit", full, re.I):
                continue  # segment EPS tables (DTE) are not company EPS
            if lab and not LABEL_OK.search(lab):
                continue  # segment / business-line rows (e.g. DTE) are never the company EPS
            if not EPS_CTX.search(full) and not (re.search(r"diluted", lab, re.I) and EPS_CTX.search(section + title)):
                continue
            diluted = bool(re.search(r"diluted", full, re.I))
            basic_only = bool(re.search(r"\bbasic\b", lab, re.I)) and not re.search(r"diluted", lab, re.I)
            if basic_only:
                continue
            if ADJ.search(lab) or (ADJ.search(section) and not GAAP_EXPL.search(lab)):
                basis = "adjusted"
            elif GAAP_EXPL.search(lab) or GAAP_EXPL.search(section):
                basis = "GAAP"
            elif t_adj:
                basis = "adjusted"
            else:
                basis = "GAAP_stmt" if t_stmt else "GAAP_implicit"
            vals = [v for v in nums if abs(v) < 1000]
            if not vals:
                continue
            k = cur_idx if cur_idx < len(vals) else 0
            v = vals[k]
            if re.search(r"\bloss\b", lab, re.I) and not re.search(r"income|earnings", lab, re.I) and v > 0 \
                    and "(" not in " ".join(r):
                pass  # 'net loss per share' rows usually show the loss in parentheses; keep the sign as printed
            cands.append(dict(src="table", block=bi, row=ri, label=full[:200], value=v, diluted=diluted,
                              basis=basis, partial=bool(PARTIAL.search(lab)), annual_only=annual_only,
                              n_vals=len(vals), notes="; ".join(hnotes)))
    return cands


PROSE_PATS = [
    # "$0.37 per diluted share" / "(0.12) per diluted share" / "loss of $0.12 per diluted share"
    re.compile(r"(?P<pre>[^.;]{0,160}?)(?P<num>\(?\$\s?\(?\d+\.\d{2,3}\)?)\s+(?:per\s+diluted\s+(?:common\s+)?share|"
               r"diluted\s+(?:earnings|eps|net income|loss)?\s*per\s+share)", re.I),
    # "diluted EPS of $0.37" / "diluted earnings per share was $0.37" / "earnings per diluted share were $1.05"
    re.compile(r"(?P<pre>[^.;]{0,160}?(?:diluted\s+(?:eps|earnings\s+per\s+(?:common\s+)?share|net income per share|"
               r"(?:net\s+)?(?:loss|earnings)\s+per\s+share)|(?:earnings|income|loss|eps)\s+per\s+diluted\s+share)"
               r"[^$\d.;]{0,40}?)(?P<num>\(?-?\$\s?\(?\d+\.\d{2,3}\)?)", re.I),
]
PROSE_UNLAB = re.compile(r"(?P<pre>[^.;]{0,160}?)(?P<num>\(?\$\s?\(?\d+\.\d{2,3}\)?)\s+per\s+(?:common\s+|ordinary\s+)?share", re.I)


def prose_num(s):
    neg = "(" in s or "-" in s
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if neg else v


def prose_candidates(blocks):
    cands = []
    for bi, (kind, val) in enumerate(blocks[:400]):
        if kind == "table":
            # one-column bullet tables behave like prose
            if all(len([c for c in r if c]) <= 2 for r in val):
                val = " ".join(" ".join(r) for r in val)
            else:
                continue
        for pi, pat in enumerate(PROSE_PATS + [PROSE_UNLAB]):
            for m in pat.finditer(val):
                pre = m.group("pre")
                sent = val[max(0, m.start("num") - 200): m.end() + 60]
                if re.search(r"guidance|expects?|outlook|forecast|range of|to \$\d", sent, re.I):
                    continue
                if re.search(r"dividend", pre[-80:], re.I):
                    continue
                v = prose_num(m.group("num"))
                if re.search(r"\b(?:net\s+)?loss\b", pre[-80:], re.I) and v > 0 and not re.search(r"income|earnings", pre[-40:], re.I):
                    v = -v
                tail = pre[-120:]
                basis = "adjusted" if ADJ.search(tail) else ("GAAP" if GAAP_EXPL.search(tail) else "GAAP_implicit")
                prior = bool(re.search(r"(?:prior|last|previous|year[\s-]ago|same)\s+(?:year|quarter|period)|compared (?:to|with)",
                                       val[max(0, m.start("num") - 60): m.start("num")], re.I))
                cands.append(dict(src="prose", block=bi, row=-1, label=sent[:200], value=v,
                                  diluted=pi < len(PROSE_PATS), basis=basis, partial=bool(PARTIAL.search(tail)),
                                  annual_only=bool(LONGPER.search(tail) and not SHORTPER.search(tail)),
                                  prior=prior, n_vals=1, notes=""))
    return cands


def choose(cands):
    """Pick GAAP diluted (primary), adjusted diluted, unlabeled per share; return dict of outputs."""
    for c in cands:
        c.setdefault("prior", False)
    ok = [c for c in cands if not c["annual_only"] and not c["prior"]]
    gaap = [c for c in ok if c["diluted"] and c["basis"] != "adjusted"]
    adj = [c for c in ok if c["diluted"] and c["basis"] == "adjusted"]
    unl = [c for c in ok if not c["diluted"] and c["basis"] != "adjusted"]
    adj_unl = [c for c in ok if not c["diluted"] and c["basis"] == "adjusted"]

    def rank(c):
        # total (net) diluted EPS before continuing-ops-only rows (XBRL EarningsPerShareDiluted is the total; RTX, FIS)
        return (0 if c["src"] == "table" else 1, 1 if c["partial"] else 0,
                {"GAAP_stmt": 0, "GAAP": 1, "GAAP_implicit": 2}.get(c["basis"], 3), c["block"], c["row"])
    out = dict(eps_diluted_reported=np.nan, eps_basis="none", eps_adjusted=np.nan,
               parse_confidence="none", parse_notes="")
    notes = []
    if adj:
        out["eps_adjusted"] = sorted(adj, key=rank)[0]["value"]
    elif adj_unl:
        out["eps_adjusted"] = sorted(adj_unl, key=rank)[0]["value"]; notes.append("adjusted EPS has no diluted label")
    if gaap:
        g = sorted(gaap, key=rank)
        best = g[0]
        out["eps_diluted_reported"] = best["value"]; out["eps_basis"] = "GAAP"
        agree = [c for c in g[1:] if abs(c["value"] - best["value"]) < 0.005]
        if best["src"] == "table" and best["basis"] in ("GAAP_stmt", "GAAP") and not best["partial"]:
            out["parse_confidence"] = "high" if (agree or best["basis"] == "GAAP_stmt") else "medium"
        else:
            out["parse_confidence"] = "medium" if agree else "low"
        if best["partial"]:
            notes.append("only continuing-ops diluted EPS found")
        if best["basis"] == "GAAP_implicit":
            notes.append("GAAP basis implied (no GAAP/statement label)")
        notes.append(f"picked {best['src']}: {best['label'][:90]}")
        if best.get("notes"):
            notes.append(best["notes"])
    elif unl:
        u = sorted(unl, key=rank)[0]
        out["eps_diluted_reported"] = u["value"]; out["eps_basis"] = "unlabeled-per-share"
        out["parse_confidence"] = "low"; notes.append("FLAG per-share EPS without 'diluted' label: " + u["label"][:90])
    elif not np.isnan(out["eps_adjusted"]):
        out["eps_basis"] = "adjusted"; out["parse_confidence"] = "medium"
        notes.append("FLAG only non-GAAP EPS reported")
    else:
        notes.append("no EPS found")
    out["parse_notes"] = " | ".join(notes)[:500]
    return out


def find_ex99(cik, accession):
    """EX-99.1 URL from the EDGAR filing index (used until Ethan's ex99_url is available)."""
    nod = accession.replace("-", "")
    idx = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{nod}/{accession}-index.htm"
    h = sec_http.get(idx).decode("utf-8", "replace")
    best = None
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]
        href = re.findall(r'href="([^"]+)"', r)
        if len(cells) >= 4 and href:
            typ = cells[3].upper()
            if typ in ("EX-99.1", "EX-99", "EX-99.01", "EX-99.(1)") or (typ.startswith("EX-99") and best is None):
                url = "https://www.sec.gov" + href[0]
                if typ.startswith("EX-99.1") or typ in ("EX-99", "EX-99.01"):
                    return url, typ
                best = (url, typ)
    if best:
        return best
    # no EX-99 exhibit (e.g. PXD): the release is in the 8-K body itself; flagged in source_exhibit type
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)]
        href = re.findall(r'href="([^"]+\.htm[l]?)"', r)
        if len(cells) >= 4 and href and cells[3].upper() == "8-K":
            return "https://www.sec.gov" + href[0], "8-K body (no EX-99)"
    return (None, None)


def extract_one(row):
    rec = dict(accession=row["accession"], cik=row["cik"], ticker=row.get("ticker"),
               acceptance_et=row.get("acceptance_et"), session_date=row.get("session_date"))
    try:
        url = row.get("ex99_url")
        typ = "EX-99.1 (ethan)" if isinstance(url, str) and url else None
        if not typ:
            url, typ = find_ex99(row["cik"], row["accession"])
        if not url:
            rec.update(source_exhibit=None, eps_diluted_reported=np.nan, eps_basis="none", eps_adjusted=np.nan,
                       parse_confidence="none", parse_notes="no EX-99 exhibit in filing index")
            return rec
        url = url.replace("/ix?doc=", "")  # inline-XBRL viewer links -> raw document (PXD)
        blocks = htmltables.parse(sec_http.get(url))
        cands = table_candidates(blocks) + prose_candidates(blocks)
        rec.update(source_exhibit=url, exhibit_type=typ, **choose(cands))
        m = re.search(r"(?:three months|quarter|fourth quarter|third quarter|second quarter|first quarter)\s+ended\s+"
                      r"([A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4})", " ".join(v for k, v in blocks[:30] if k == "text"))
        rec["period_text"] = m.group(1) if m else None
    except Exception as e:  # keep going; record the failure
        rec.update(source_exhibit=None, eps_diluted_reported=np.nan, eps_basis="none", eps_adjusted=np.nan,
                   parse_confidence="none", parse_notes=f"error: {type(e).__name__}: {e}"[:300])
    return rec


def assign_fiscal_period(df, xq):
    """fiscal_period = period_end of the latest XBRL quarter ending within 100 days before acceptance;
    falls back to the 'quarter ended <date>' text. (XBRL is used only to label the period, not the value.)"""
    acc = pd.to_datetime(df.acceptance_et)
    fp = []
    g = {c: d.period_end.sort_values().values for c, d in xq.groupby("cik")}
    for c, a, t in zip(df.cik, acc, df.get("period_text", pd.Series([None] * len(df)))):
        pe = g.get(int(c))
        val = pd.NaT
        if pe is not None and pd.notna(a):
            cand = pe[(pe < np.datetime64(a.normalize())) & (pe >= np.datetime64(a.normalize() - pd.Timedelta(days=100)))]
            if len(cand):
                val = pd.Timestamp(cand[-1])
        if pd.isna(val) and isinstance(t, str):
            try:
                val = pd.Timestamp(t.replace(".", ""))
            except Exception:
                pass
        fp.append(val)
    df["fiscal_period"] = pd.to_datetime(pd.Series(fp, index=df.index))
    return df


def validate(df, xq):
    m = df.merge(xq[["cik", "period_end", "eps_diluted_xbrl", "derivation"]],
                 left_on=["cik", "fiscal_period"], right_on=["cik", "period_end"], how="left")
    m["xbrl_abs_diff"] = (m.eps_diluted_reported - m.eps_diluted_xbrl).abs()
    m["xbrl_match"] = np.where(m.eps_diluted_xbrl.notna() & m.eps_diluted_reported.notna(), m.xbrl_abs_diff <= 0.011, np.nan)
    return m.drop(columns=["period_end"])


COLS = ["accession", "cik", "ticker", "fiscal_period", "eps_diluted_reported", "eps_basis", "eps_adjusted",
        "source_exhibit", "parse_confidence", "parse_notes"]


def run(events: pd.DataFrame, out_name="eps8k"):
    """events: columns accession, cik, ticker, acceptance_et, session_date[, ex99_url]."""
    recs = [extract_one(r) for r in events.to_dict("records")]
    df = pd.DataFrame(recs)
    xq = pd.read_parquet(common.OUT / "xbrl_eps_quarterly.parquet")
    df = assign_fiscal_period(df, xq)
    v = validate(df, xq)
    v.to_parquet(common.OUT / f"{out_name}_with_validation.parquet", index=False)
    v[COLS + ["acceptance_et", "session_date"]].to_parquet(common.OUT / f"{out_name}.parquet", index=False)
    return v
