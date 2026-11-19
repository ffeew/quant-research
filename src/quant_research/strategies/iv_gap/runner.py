"""IV-gap v2 runner (FROZEN CANDIDATE; Ethan desk; built 2026-11-13 SGT).

Spec: PREREG_IV_GAP_v2_DRAFT_r3.md sha 333bccad2e2823a44c88aeb0839ee2fe55a548e4a6dcc97d9d2c8695cc072b46.
Stdlib only. Run (ONE run, after Victor confirmation + LOCK only):
  env -u ALPHAVANTAGE_API_KEY $QR_DATA_DIR/.venv/bin/python -I -B runner.py <NEW_RUN_DIR>
Reads ONLY through Dmitri's sealed reader ivgap_av_reader_v2.api (W1d). No mapping, no direct file reads of
chains/underlyings, no greeks, no IV levels or per-date rows in outputs (reader_calls.tsv date list excepted).
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import csv
import hashlib
import io
import json
import math
import os
import random
import socket
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.dont_write_bytecode = True

# ---------------------------------------------------------------- pins
PREREG_PATH = f"{_QR.DESK_DIR}/research/original/iv_gap_prereg_v2r3_20261113/PREREG_IV_GAP_v2_DRAFT_r3.md"
PREREG_SHA256 = "333bccad2e2823a44c88aeb0839ee2fe55a548e4a6dcc97d9d2c8695cc072b46"  # gitleaks:allow (sha256 digest, not a secret)
W1D_CP_DIR = f"{_QR.DESK_DIR}/validation/dmitri/ivgap_v2_reader_w1e_r2_20261113"
W1D_CP_SUMS_SHA256 = "8559e211f39e6b4483668e3eec1d927f63466027debbd870616989255db7c172"  # gitleaks:allow (sha256 digest, not a secret)
W1D_CP_ROWS = 74
W1_ROOT = f"{_QR.SCRATCH_DIR}/scratch/ivgap_v2_reader_20261113_w1e_r2"
W1_SCRATCH_SUMS_REL = f"{_QR.DESK_DIR}/validation/dmitri/ivgap_v2_reader_w1e_r2_relsums_20261113/W1e_SHA256SUMS_REL"
W1_SCRATCH_SUMS_SHA256 = "1adbaa7387e8a9d330816dacd5c835948ed82d16c7943fac211e848df50b2681"  # gitleaks:allow (sha256 digest, not a secret)
W1_SCRATCH_ROWS = 71
API_REL = "ivgap_av_reader_v2/api.py"
API_SHA256 = "d501f4893cad8649f30f940827308c11c9b4fa7c4142eb27d7eef0615a004dbd"  # gitleaks:allow (sha256 digest, not a secret)
DEV_DATES_SHA256 = "21c8c9bd8881b0bfba8578361735e682b526ea12ee62ca6048d874f6d30a0a54"  # gitleaks:allow (sha256 digest, not a secret)
DEV_DATES_COUNT = 2118
EXPECTED_PINS = {
    "W1_ROOT": W1_ROOT,
    "SPY_DEV": [f"{_QR.SCRATCH_DIR}/scratch/open10_dev_reader_20261110_r8/partitions/SPY_DEV.json",
                "bb7c12e9b0558708867eaa5384f137cfcaecde3ad1d7be109a2ca8a2ae906d59"],
    "OPT_INDEX": [f"{_QR.SCRATCH_DIR}/scratch/open10_dev_reader_20261110_r8/partitions/options/OPTIONS_DEV_INDEX.json",
                  "51af99ac149ae17d96d64f6d0e15031c70259faf1f5400a62a0f0a84cd012248"],
    "QQQ_SRC": [f"{_QR.DATA_DIR}/alphavantage/equity/qqq_daily_adjusted_full_20261110/QQQ.json",
                "b3ba7a7fe12c3e010efeeb27abd38d29c54b50af03bb103f664b18c0414fec30"],
    "BARRED": ["b14e6908e830ffe0935abace7bc8cb973fc467b4a67793904e71afeac78a9aad",
               "9b24db2cade471f53572ecc02465bb09de24694d92d4078a05fa0a4b9df5db0b"],
    "DESK_CLIENT_SHA256_NEVER_OPENED": "64c83245e840cee84413aea8802d46de20de9ccdc45997330b1cce3294bcdc82",
    "VENDORED": {
        "open10_dev_reader/__init__.py": "07ef3d79514329bfc6b758de159b3d7f34604daef4ed57888bd0fa1945898e0e",
        "open10_dev_reader/constants.py": "c06befa8040fd1a7b28504615ffe595e307640509969cefa5b15a2c7a3dca50d",
        "open10_dev_reader/errors.py": "dabb20dfae8c414491f1ceb8fe6317f75cd036db656814ad256007ae91b320cf",
        "open10_dev_reader/r7_dev_read.py": "b53bbc633da9cc561aa501ad315fd643580d3a8bd1b9507fc0175f35b1f11941",
        "open10_dev_reader/r7_pins.py": "3be1ace004f3fd7c6c7abbef523eb60ed7cf04606c975c552d62433dc2943c1f",
        "open10_dev_reader/reader.py": "da134f0917abaf3c967be0f5bb0959d3842db6819c6aeedf20c459658e5503f6",
        "bin/qqq_source_dev.py": "a241f63daf0bd00809c15230e4a9fc0be3be75c554a327787ff5c57d84704be2",
    },
    "DEV_BOUND": "2016-06-01",
    "CHANGEOVER": "2011-03-23",
}

# ---------------------------------------------------------------- frozen parameters (prereg section refs)
SYMBOLS = ("SPY", "QQQ")                       # s1
HOLDOUT = date(2016, 6, 1)                     # s1, s2.1, s6 STOP-d
DEV_FIRST_MONTH = (2009, 1)                    # s1
DEV_LAST_MONTH = (2016, 5)                     # s1
SEED_FMT = "20261113:{SYM}:{YYYY_MM}"          # s3 Sampling
N_PARITY = 5                                   # s3
MIN_PARITY_PAIRS = 3                           # s3
DF_LO, DF_HI = 0.95, 1.01                      # s3: DF in (0.95, 1.01]
FS_LO, FS_HI = 0.90, 1.10                      # s3: F/S in [0.90, 1.10]
IV_LO, IV_HI, IV_XTOL, IV_MAXIT = 1e-4, 5.0, 1e-8, 200  # s3 Black-76 Brent
FLAG_T, DROP_T = 0.05, 0.10                    # s2.5 A1: strict '>'
KILL_T = 0.10                                  # s7 A2: usable iff drop_rate <= 0.10; kill iff > 0.10
N_MIN = 20                                     # s3 / s7 OQ-6
MNY_EDGES = (-0.30, -0.15, -0.075, -0.025, 0.025, 0.075, 0.15, 0.30)  # s3
MNY_MAX = 0.30
DTE_EDGES = (3, 8, 22, 46, 91, 181, 366)       # s3 [3,..,366)
DTE_MIN, DTE_MAX = 3, 365
MARK_TOL = 0.005                               # s4a (iv)
PARITY_TOL = 0.01                              # s4b
RULE6_BUDGET_S = 35 * 60                       # s6 in-run STOP (rule 6)
EXCLUSIONS = ("crossed", "zero_bid", "dte_lt_3", "dte_gt_365", "mny_out", "parity_fail",
              "below_intrinsic", "av_iv_missing", "iv_fail")   # s3 order
DAY_EXCL = ("no_date", "no_underlying")        # s3, s1
N_LEDGER = (("F1", 1), ("F1b", 1), ("F1c", 1), ("F2", 0), ("F3", 1))  # s8
REQUIRED_COLS = ("date", "expiration", "strike", "type", "bid", "ask", "mark", "implied_volatility")
OUTPUT_FILES = ("gap_stats.csv", "coverage.csv", "sanity_bidask.csv", "parity_violations.csv",
                "reader_calls.tsv", "run.log", "SHA256SUMS")
SGT = timezone(timedelta(hours=8))


class RunStop(Exception):
    """In-run STOP (prereg s6): end the run, no retry, report to Victor."""


# ---------------------------------------------------------------- pin checks
def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def check_sums_file(root, rel_sums, expected_rows, expected_sha=None):
    p = os.path.join(root, rel_sums)
    raw = open(p, "rb").read()
    if expected_sha is not None and hashlib.sha256(raw).hexdigest() != expected_sha:
        raise RunStop("PIN_MISMATCH sums sha %s" % p)
    rows = [ln for ln in raw.decode("ascii").splitlines() if ln.strip()]
    if len(rows) != expected_rows:
        raise RunStop("PIN_MISMATCH sums rows %s: %d != %d" % (p, len(rows), expected_rows))
    for ln in rows:
        want, rel = ln.split("  ", 1)
        if rel.startswith("/") or ".." in rel.split("/"):
            raise RunStop("PIN_MISMATCH bad sums path %s" % rel)
        if sha256_file(os.path.join(root, rel)) != want:
            raise RunStop("PIN_MISMATCH %s" % rel)
    return len(rows)


def normalise_pins(p):
    return json.loads(json.dumps(p, sort_keys=True))


def verify_pins_static():
    if sha256_file(PREREG_PATH) != PREREG_SHA256:
        raise RunStop("PIN_MISMATCH prereg")
    n1 = check_sums_file(W1D_CP_DIR, "COPY_SHA256SUMS", W1D_CP_ROWS, W1D_CP_SUMS_SHA256)
    n2 = check_sums_file(W1_ROOT, W1_SCRATCH_SUMS_REL, W1_SCRATCH_ROWS, W1_SCRATCH_SUMS_SHA256)
    a = open(os.path.join(W1_ROOT, API_REL), "rb").read()
    b = open(os.path.join(W1D_CP_DIR, API_REL), "rb").read()
    if a != b or hashlib.sha256(a).hexdigest() != API_SHA256:
        raise RunStop("PIN_MISMATCH api.py scratch vs copy")
    return n1, n2


def import_reader():
    """README step 3: import from the scratch W1 root only."""
    if sys.path[:1] != [W1_ROOT]:
        sys.path.insert(0, W1_ROOT)
    import ivgap_av_reader_v2.api as api  # noqa: E402
    return api


def verify_reader_pins(api):
    got = normalise_pins(api.pins())
    if got != normalise_pins(EXPECTED_PINS):
        raise RunStop("PIN_MISMATCH reader pins()")
    return hashlib.sha256(json.dumps(got, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------- math
def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def black76(F, K, T, DF, sigma, cp):
    if sigma <= 0 or T <= 0:
        raise ValueError("sigma and T must be > 0")
    sd = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if cp == "C":
        return DF * (F * norm_cdf(d1) - K * norm_cdf(d2))
    return DF * (K * norm_cdf(-d2) - F * norm_cdf(-d1))


def brent(f, a, b, xtol=IV_XTOL, maxiter=IV_MAXIT):
    """Brent's method (Brent 1973 zeroin). Returns root or None (no bracket / no convergence)."""
    fa, fb = f(a), f(b)
    if fa == 0:
        return a
    if fb == 0:
        return b
    if fa * fb > 0:
        return None
    c, fc = a, fa
    d = e = b - a
    for _ in range(maxiter):
        if fb * fc > 0:
            c, fc = a, fa
            d = e = b - a
        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        tol1 = 2.0 * 2.220446049250313e-16 * abs(b) + 0.5 * xtol
        xm = 0.5 * (c - b)
        if abs(xm) <= tol1 or fb == 0:
            return b
        if abs(e) >= tol1 and abs(fa) > abs(fb):
            s = fb / fa
            if a == c:
                p, q = 2.0 * xm * s, 1.0 - s
            else:
                q, r = fa / fc, fb / fc
                p = s * (2.0 * xm * q * (q - r) - (b - a) * (r - 1.0))
                q = (q - 1.0) * (r - 1.0) * (s - 1.0)
            if p > 0:
                q = -q
            p = abs(p)
            if 2.0 * p < min(3.0 * xm * q - abs(tol1 * q), abs(e * q)):
                e, d = d, p / q
            else:
                d = e = xm
        else:
            d = e = xm
        a, fa = b, fb
        b += d if abs(d) > tol1 else math.copysign(tol1, xm)
        fb = f(b)
    return None


def implied_vol_b76(price, F, K, T, DF, cp):
    try:
        return brent(lambda s: black76(F, K, T, DF, s, cp) - price, IV_LO, IV_HI)
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def nearest_strikes(strikes, S, n=N_PARITY):
    """n strikes nearest S; tie on distance broken by lower strike (disclosed, FREEZE_NOTE A-4)."""
    return sorted(sorted(set(strikes)), key=lambda k: (abs(k - S), k))[:n]


def ols(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return slope, my - slope * mx


def parity_fit(pairs, S):
    """pairs: {K: (C_mid, P_mid)} of strikes with BOTH legs valid (bid>0, ask>=bid).
    Returns (F, DF) or None (= parity_fail). OLS (C-P) on K: slope=-DF, intercept=DF*F. No clamping."""
    ks = nearest_strikes(list(pairs), S)
    if len(ks) < MIN_PARITY_PAIRS:
        return None
    fit = ols(ks, [pairs[k][0] - pairs[k][1] for k in ks])
    if fit is None:
        return None
    DF = -fit[0]
    if not (DF_LO < DF <= DF_HI):
        return None
    F = fit[1] / DF
    if not (FS_LO <= F / S <= FS_HI):
        return None
    return F, DF


# ---------------------------------------------------------------- sampling
def dev_months():
    y, m = DEV_FIRST_MONTH
    out = []
    while (y, m) <= DEV_LAST_MONTH:
        out.append("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def sample_dates(symbol, dev_dates):
    """1 date per symbol-month, uniform without replacement: random.Random(seed).sample(sorted, 1)."""
    by_month = {}
    for d in dev_dates:
        if date.fromisoformat(d) >= HOLDOUT:
            raise RunStop("HOLDOUT date listed by reader: %s" % d)
        by_month.setdefault(d[:7], []).append(d)
    picks, no_date = {}, []
    for ym in dev_months():
        cands = sorted(by_month.get(ym, []))
        if not cands:
            no_date.append(ym)
            continue
        rng = random.Random(SEED_FMT.format(SYM=symbol, YYYY_MM=ym))
        picks[ym] = rng.sample(cands, 1)[0]
    return picks, no_date


# ---------------------------------------------------------------- buckets / rules
def bucket(x, edges, closed_last):
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        last = i == len(edges) - 2
        if lo <= x < hi or (last and closed_last and x == hi):
            return "[%g,%g%s" % (lo, hi, "]" if (last and closed_last) else ")")
    return None


def mny_bucket(m):
    return bucket(m, MNY_EDGES, True)


def dte_bucket(dte):
    return bucket(dte, DTE_EDGES, False)


def is_flag(gap):
    return abs(gap) > FLAG_T


def is_drop(gap):
    return abs(gap) > DROP_T


def cell_reported(n):
    return n >= N_MIN


def cell_usable(n, drop_rate):
    """s7 A2: usable as cross-check iff reported (n>=20) and drop rate <= 10%. Not written to outputs."""
    return cell_reported(n) and drop_rate <= KILL_T


def symbol_year_killed(drop_rate):
    """s7 A2 kill: symbol-year drop rate over all kept legs > 10%. Not written to outputs."""
    return drop_rate > KILL_T


def n_ledger(completed):
    return sum(v for k, v in N_LEDGER if k != "F3") + (1 if completed else 0)


def _f(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("none", "null", "nan"):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def leg_type(t):
    t = str(t).strip().lower()
    return {"call": "C", "put": "P", "c": "C", "p": "P"}.get(t)


# ---------------------------------------------------------------- per-day processing
def process_day(rows, S, trade_date):
    """Returns dict: kept legs [(type, mny_bucket, dte_bucket, gap)], exclusion counts, seen,
    sanity counts, parity-violation tallies, non_cp count. No IV levels leave this function."""
    td = date.fromisoformat(trade_date)
    excl = {k: 0 for k in EXCLUSIONS}
    san = {"seen": 0, "bid0": 0, "ask_lt_bid": 0, "mark_outside": 0, "mark_mid_gt": 0, "mark_null": 0}
    viol = {}
    kept = []
    non_cp = 0
    legs = []
    for r in rows:
        if r.get("date") != trade_date:
            raise RunStop("reader returned row for other date")
        if date.fromisoformat(r["date"]) >= HOLDOUT:
            raise RunStop("HOLDOUT row returned")
        cp = leg_type(r.get("type"))
        if cp is None:                       # straddle / non-C-P rows: excluded before s3 (FREEZE_NOTE A-2)
            non_cp += 1
            continue
        bid, ask, mark = _f(r.get("bid")), _f(r.get("ask")), _f(r.get("mark"))
        K = _f(r.get("strike"))
        exp = date.fromisoformat(str(r.get("expiration")).strip()[:10])
        legs.append({"cp": cp, "K": K, "bid": bid, "ask": ask, "mark": mark, "exp": exp,
                     "dte": (exp - td).days, "aviv": _f(r.get("implied_volatility"))})
        # s4a sanity over every C/P contract seen
        san["seen"] += 1
        if bid is not None and bid == 0:
            san["bid0"] += 1
        if bid is not None and ask is not None and ask < bid:
            san["ask_lt_bid"] += 1
        if mark is None:
            san["mark_null"] += 1
        elif bid is not None and ask is not None:
            if mark < bid or mark > ask:
                san["mark_outside"] += 1
            if abs(mark - (bid + ask) / 2.0) > MARK_TOL:
                san["mark_mid_gt"] += 1
    by_exp = {}
    for lg in legs:
        by_exp.setdefault(lg["exp"], []).append(lg)
    for exp in sorted(by_exp):
        group = by_exp[exp]
        valid = {}
        for lg in group:
            if lg["bid"] is not None and lg["ask"] is not None and lg["bid"] > 0 and lg["ask"] >= lg["bid"]:
                valid.setdefault(lg["K"], {})[lg["cp"]] = lg
        pairs = {k: ((v["C"]["bid"] + v["C"]["ask"]) / 2.0, (v["P"]["bid"] + v["P"]["ask"]) / 2.0)
                 for k, v in valid.items() if "C" in v and "P" in v}
        fit = parity_fit(pairs, S)
        T = None
        for lg in group:
            bid, ask, dte = lg["bid"], lg["ask"], lg["dte"]
            if bid is None or ask is None or ask < bid:
                excl["crossed"] += 1; continue
            if bid <= 0:
                excl["zero_bid"] += 1; continue
            if dte < DTE_MIN:
                excl["dte_lt_3"] += 1; continue
            if dte > DTE_MAX:
                excl["dte_gt_365"] += 1; continue
            if fit is None:                  # mny_out not evaluable without F (FREEZE_NOTE A-3)
                excl["parity_fail"] += 1; continue
            F, DF = fit
            m = math.log(lg["K"] / F)
            if abs(m) > MNY_MAX:
                excl["mny_out"] += 1; continue
            mid = (bid + ask) / 2.0
            intr = DF * (max(F - lg["K"], 0.0) if lg["cp"] == "C" else max(lg["K"] - F, 0.0))
            if mid < intr:
                excl["below_intrinsic"] += 1; continue
            if lg["aviv"] is None or lg["aviv"] <= 0:
                excl["av_iv_missing"] += 1; continue
            T = dte / 365.0
            iv = implied_vol_b76(mid, F, lg["K"], T, DF, lg["cp"])
            if iv is None:
                excl["iv_fail"] += 1; continue
            kept.append((lg["cp"], mny_bucket(m), dte_bucket(dte), lg["aviv"] - iv))
        # s4b parity violations on expiries that passed the fit
        if fit is not None:
            F, DF = fit
            dte = (exp - td).days
            db = dte_bucket(dte)
            if db is not None:
                for k, v in valid.items():
                    if "C" in v and "P" in v:
                        c, p = v["C"], v["P"]
                        fwd = DF * (F - k)
                        bad = (c["bid"] - p["ask"] > fwd + PARITY_TOL) or (c["ask"] - p["bid"] < fwd - PARITY_TOL)
                        t = viol.setdefault(db, [0, 0])
                        t[0] += 1
                        t[1] += 1 if bad else 0
    return {"kept": kept, "excl": excl, "seen": san["seen"], "san": san, "viol": viol, "non_cp": non_cp}


# ---------------------------------------------------------------- aggregation
def _stats(gaps):
    n = len(gaps)
    if not cell_reported(n):
        return [n, "", "", "", ""]
    return [n, "%.6f" % statistics.median(gaps), "%.6f" % (sum(abs(g) for g in gaps) / n),
            "%.6f" % (sum(1 for g in gaps if is_flag(g)) / n), "%.6f" % (sum(1 for g in gaps if is_drop(g)) / n)]


def aggregate(results):
    """results: {(sym, year): {"kept": [...], "excl": {...}, "seen": int, "days": int, "no_date": int,
    "no_underlying": int, "san": {...}, "viol": {...}, "non_cp": int}}"""
    gap_rows, cov_rows, san_rows, viol_rows = [], [], [], []
    for (sym, yr) in sorted(results):
        R = results[(sym, yr)]
        cells = {}
        for cp, mb, db, g in R["kept"]:
            for t in (cp, "ALL"):
                cells.setdefault((t, mb, db), []).append(g)
        for (t, mb, db) in sorted(cells):
            gap_rows.append(["cell", sym, yr, t, mb, db] + _stats(cells[(t, mb, db)]))
        allg = [g for _, _, _, g in R["kept"]]
        n = len(allg)
        fr = ("%.6f" % (sum(1 for g in allg if is_flag(g)) / n)) if n else ""
        dr = ("%.6f" % (sum(1 for g in allg if is_drop(g)) / n)) if n else ""
        gap_rows.append(["symbol_year", sym, yr, "ALL", "ALL", "ALL", n, "", "", fr, dr])
        cov = (("%.6f" % (n / R["seen"])) if R["seen"] else "")
        cov_rows.append([sym, yr, R["days"], R["no_date"], R["no_underlying"], R["seen"], n, cov]
                        + [R["excl"][k] for k in EXCLUSIONS] + [fr, dr])
        s = R["san"]
        den = s["seen"]
        row = [sym, yr, den]
        for k in ("bid0", "ask_lt_bid", "mark_outside", "mark_mid_gt", "mark_null"):
            row += [s[k], ("%.6f" % (s[k] / den)) if den else ""]
        san_rows.append(row)
        for db in sorted(R["viol"]):
            tested, v = R["viol"][db]
            viol_rows.append([sym, yr, db, tested, v, ("%.6f" % (v / tested)) if tested else ""])
    san_rows.sort(key=lambda r: (r[0], 0 if r[1] == 2009 else 1, r[1]))   # s4a: 2009 first
    return gap_rows, cov_rows, san_rows, viol_rows


GAP_HDR = ["level", "symbol", "year", "type", "moneyness_bucket", "dte_bucket", "n", "median_gap",
           "mean_abs_gap", "flag_rate", "drop_rate"]
COV_HDR = ["symbol", "year", "sampled_days", "no_date", "no_underlying", "contracts_seen", "contracts_kept",
           "coverage_kept_over_seen"] + ["excl_" + k for k in EXCLUSIONS] + ["flag_rate", "drop_rate"]
SAN_HDR = ["symbol", "year", "contracts_seen", "bid_eq_0", "frac_bid_eq_0", "ask_lt_bid", "frac_ask_lt_bid",
           "mark_outside_bid_ask", "frac_mark_outside_bid_ask", "abs_mark_minus_mid_gt_0.005",
           "frac_abs_mark_minus_mid_gt_0.005", "mark_null", "frac_mark_null"]
VIOL_HDR = ["symbol", "year", "dte_bucket", "pairs_tested", "violations", "rate"]


def _csv(rows, hdr, delim=","):
    b = io.StringIO()
    w = csv.writer(b, delimiter=delim, lineterminator="\n")
    w.writerow(hdr)
    w.writerows(rows)
    return b.getvalue()


# ---------------------------------------------------------------- run
def prepare_run_dir(run_dir):
    run_dir = os.path.abspath(run_dir)
    if os.path.lexists(run_dir):
        raise RunStop("REFUSE_OVERWRITE: %s exists" % run_dir)
    os.mkdir(run_dir, 0o755)
    return run_dir


def write_new(run_dir, name, text):
    if name not in OUTPUT_FILES:
        raise RunStop("output %s not in prereg s5 list" % name)
    p = os.path.join(run_dir, name)
    with open(p, "x", encoding="utf-8") as fh:    # 'x' = refuse overwrite
        fh.write(text)


def guard_env():
    if "ALPHAVANTAGE_API_KEY" in os.environ:
        raise RunStop("KEY_IN_ENV (run with env -u ALPHAVANTAGE_API_KEY)")


def block_network():
    def _no(*a, **k):
        raise RunStop("NETWORK_ATTEMPT")
    socket.socket = _no            # type: ignore
    socket.create_connection = _no  # type: ignore
    socket.getaddrinfo = _no        # type: ignore


def run(run_dir, reader, provenance=None, clock=time.monotonic, budget_s=RULE6_BUDGET_S):
    """Core run. `reader` exposes list_dev_dates/read_option_chain/read_underlying_spot (+pins)."""
    t0 = clock()
    run_dir = prepare_run_dir(run_dir)
    log = ["start_sgt\t%s" % datetime.now(SGT).isoformat(timespec="seconds")]
    for k, v in (provenance or {}).items():
        log.append("%s\t%s" % (k, v))
    calls = []
    results = {}
    total_non_cp = 0
    for sym in SYMBOLS:
        dev = list(reader.list_dev_dates(sym))
        picks, no_date = sample_dates(sym, dev)
        calls.append([sym, "ALL", "list_dev_dates", len(dev)])
        for ym in no_date:
            R = results.setdefault((sym, int(ym[:4])), _blank())
            R["no_date"] += 1
        for ym in sorted(picks):
            if clock() - t0 > budget_s:
                raise RunStop("RULE6_BUDGET exceeded; split per rule 6(d)")
            d = picks[ym]
            if date.fromisoformat(d) >= HOLDOUT:
                raise RunStop("HOLDOUT date sampled %s" % d)
            R = results.setdefault((sym, int(ym[:4])), _blank())
            spot = list(reader.read_underlying_spot(sym, d, d))
            calls.append([sym, d, "read_underlying_spot", len(spot)])
            for s in spot:
                if date.fromisoformat(s["date"]) >= HOLDOUT:
                    raise RunStop("HOLDOUT spot row")
            S = None
            for s in spot:
                if s["date"] == d:
                    S = _f(s["close"])
            if S is None or S <= 0:
                R["no_underlying"] += 1
                continue
            chain = list(reader.read_option_chain(sym, d, d))
            calls.append([sym, d, "read_option_chain", len(chain)])
            if chain:
                missing = [c for c in REQUIRED_COLS if c not in chain[0]]
                if missing:
                    raise RunStop("SCHEMA: chain rows lack %s" % ",".join(missing))
            out = process_day(chain, S, d)
            R["days"] += 1
            R["kept"].extend(out["kept"])
            R["seen"] += out["seen"]
            total_non_cp += out["non_cp"]
            for k in EXCLUSIONS:
                R["excl"][k] += out["excl"][k]
            for k in R["san"]:
                R["san"][k] += out["san"][k]
            for db, (a, b) in out["viol"].items():
                t = R["viol"].setdefault(db, [0, 0])
                t[0] += a
                t[1] += b
    gap_rows, cov_rows, san_rows, viol_rows = aggregate(results)
    rsha = (provenance or {}).get("reader_api_sha256", "")
    write_new(run_dir, "gap_stats.csv", _csv(gap_rows, GAP_HDR))
    write_new(run_dir, "coverage.csv", _csv(cov_rows, COV_HDR))
    write_new(run_dir, "sanity_bidask.csv", _csv(san_rows, SAN_HDR))
    write_new(run_dir, "parity_violations.csv", _csv(viol_rows, VIOL_HDR))
    write_new(run_dir, "reader_calls.tsv",
              _csv([[c[0], c[1], c[2], rsha] for c in calls], ["symbol", "date", "call", "reader_sha256"], "\t"))
    log.append("non_call_put_rows_excluded\t%d" % total_non_cp)
    log.append("n_ledger_total\t%d" % n_ledger(True))
    log.append("end_sgt\t%s" % datetime.now(SGT).isoformat(timespec="seconds"))
    write_new(run_dir, "run.log", "\n".join(log) + "\n")
    names = [n for n in OUTPUT_FILES if n != "SHA256SUMS"]
    sums = "".join("%s  %s\n" % (sha256_file(os.path.join(run_dir, n)), n) for n in names)
    write_new(run_dir, "SHA256SUMS", sums)
    for n in OUTPUT_FILES:
        os.chmod(os.path.join(run_dir, n), 0o444)
    os.chmod(run_dir, 0o555)
    return run_dir


def _blank():
    return {"kept": [], "excl": {k: 0 for k in EXCLUSIONS}, "seen": 0, "days": 0, "no_date": 0,
            "no_underlying": 0, "san": {"seen": 0, "bid0": 0, "ask_lt_bid": 0, "mark_outside": 0,
                                        "mark_mid_gt": 0, "mark_null": 0}, "viol": {}, "non_cp": 0}


def main(argv):
    if len(argv) != 2:
        print("usage: runner.py <NEW_RUN_DIR>", file=sys.stderr)
        return 2
    guard_env()
    block_network()
    n1, n2 = verify_pins_static()
    api = import_reader()
    pins_sha = verify_reader_pins(api)
    for s in SYMBOLS:
        dd = api.list_dev_dates(s)
        if len(dd) != DEV_DATES_COUNT:
            raise RunStop("DEV dates count %s" % s)
    prov = {"prereg_sha256": PREREG_SHA256, "runner_sha256": sha256_file(os.path.abspath(__file__)),
            "reader_api_sha256": API_SHA256, "w1d_cp_sums_sha256": W1D_CP_SUMS_SHA256,
            "w1d_cp_ok": n1, "w1_scratch_ok": n2, "reader_pins_json_sha256": pins_sha,
            "python": sys.version.split()[0], "executable": sys.executable,
            "flags_isolated": sys.flags.isolated, "flags_dont_write_bytecode": sys.flags.dont_write_bytecode}
    out = run(argv[1], api, prov)
    print("RUN_DONE %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
