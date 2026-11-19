"""PEAD-gap long-only trend variant on the survivorship-aware PIT S&P 500 store ($QR_DATA_DIR).
Read-only. No orders. Every number in results.md is produced by run_all.py importing this module.
Prices: bars/daily/total_return (open/high/low/close_adj = Alpaca adjustment=all; verified here that
close_adj is exactly proportional to tr_index_best, so close-to-close = ret_total_best).
Volume: SIP volume_adj (split-adjusted consolidated volume). IEX files are NOT used."""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, math, json
from datetime import date
import numpy as np, pandas as pd, exchange_calendars as xc
sys.path.insert(0, f"{_QR.COSTS_DIR}")
from quant_research.backtest.costs.cost_model import trade_cost  # Tomas v1.1

D = f"{_QR.DATA_DIR}/"
SPLIT = pd.Timestamp("2021-12-31"); OOS0 = pd.Timestamp("2022-01-03")
MAXHOLD = 60; TPR = 2.0; FIRST = 252; CLIP_USD = 10_000.0

# ---------------- data ----------------
tr = pd.read_parquet(D + "bars/daily/total_return/daily_total_return.parquet",
                     columns=["symbol", "session_date", "open_adj", "high_adj", "low_adj", "close_adj",
                              "volume_adj", "volume_raw", "close_raw", "ret_total_best", "tr_index_best"])
tr["session_date"] = pd.to_datetime(tr["session_date"])
cal = pd.DatetimeIndex(sorted(tr.session_date.unique()))
SYMS = sorted(tr.symbol.unique())
def piv(col): return tr.pivot(index="session_date", columns="symbol", values=col).reindex(index=cal, columns=SYMS)
O, H, L, C = (piv(c) for c in ("open_adj", "high_adj", "low_adj", "close_adj"))
V = piv("volume_adj"); Vraw = piv("volume_raw"); Craw = piv("close_raw"); RET = piv("ret_total_best")
uni = pd.read_parquet(D + "universe/universe.parquet").set_index("symbol")
mem = pd.read_parquet(D + "universe/sp500_membership.parquet")
dl = pd.read_parquet(D + "universe/delisting_returns.parquet").set_index("symbol")
ev = pd.read_parquet(D + "earnings/earnings_events.parquet")

# ---------------- indicators (all as of close t) ----------------
prevC = C.shift(1)
TRNG = np.maximum.reduce([(H - L).values, (H - prevC).abs().values, (L - prevC).abs().values])
TRNG = pd.DataFrame(TRNG, index=cal, columns=SYMS)
TRNG[prevC.isna()] = (H - L)[prevC.isna()]
ATR = TRNG.rolling(14).mean()
SMA50 = C.rolling(50).mean(); SMA200 = C.rolling(200).mean()
GAP = O / prevC - 1
VRAT = V / V.shift(1).rolling(20).mean()
ABOVE = (C > SMA50) & (C > SMA200)
SPY_UP = (C["SPY"] > SMA200["SPY"])
SPYRET = RET["SPY"]
ADV_USD = (Vraw * Craw).rolling(20).mean()       # as-traded $ ADV through t (PIT, raw)
ADV_SH = Vraw.rolling(20).mean()
SIG20 = RET.rolling(20).std()
RV21 = SPYRET.rolling(21).std() * math.sqrt(252)  # VIX proxy (VIX not in store)

# ---------------- PIT membership mask [start, end) ----------------
MEMB = pd.DataFrame(False, index=cal, columns=SYMS)
for r in mem.itertuples():
    if r.symbol not in MEMB.columns: continue
    s = pd.Timestamp(r.start_date_filled); e = pd.Timestamp(r.end_date) if r.end_date is not None else pd.Timestamp("2100-01-01")
    MEMB.loc[(cal >= s) & (cal < e), r.symbol] = True

# ---------------- earnings alignment ----------------
xnys = xc.get_calendar("XNYS")
sess_all = xnys.sessions_in_range("2015-12-01", "2027-03-31")
sidx = {d: k for k, d in enumerate(sess_all)}
ev = ev[ev.source != "nasdaq_scheduled"].copy()
ev["fts"] = pd.to_datetime(ev.first_tradable_session)
ev["ad"] = pd.to_datetime(ev.announce_date_et)
def earn_days(mode):
    """Set of (symbol, session) that are 'first session after an earnings timestamp'.
    BMO -> announce day; AMC -> next session; these equal first_tradable_session (verified against XNYS opens).
    DURING_MKT (EDGAR 8-K accepted 09:30-16:00) and UNKNOWN (Nasdaq-only, time not supplied): the press release
    can precede the 8-K / the time is unknown, so the gap can sit on the announce day OR the next session.
    mode='strict': first_tradable_session only. mode='aligned' (primary): strict + announce day for DURING_MKT/UNKNOWN.
    Both are PIT at the close of the gap day (8-K accepted before 16:00 ET, or Nasdaq report date)."""
    out = set()
    for r in ev.itertuples():
        if pd.notna(r.fts): out.add((r.symbol, r.fts))
        if mode == "aligned" and r.timing in ("DURING_MKT", "UNKNOWN") and r.ad in sidx: out.add((r.symbol, r.ad))
    return out
def earn_window_mask(k=2):
    """True if session is within +-k sessions of any event's announce day or first tradable session."""
    M = pd.DataFrame(False, index=cal, columns=SYMS); ci = {d: i for i, d in enumerate(cal)}
    for r in ev.itertuples():
        if r.symbol not in M.columns: continue
        for d in (r.ad, r.fts):
            if pd.isna(d) or d not in ci: continue
            i = ci[d]; M.iloc[max(0, i - k):i + k + 1, M.columns.get_loc(r.symbol)] = True
    return M
def coverage_mask(lookback_days=135):
    """PIT earnings coverage: symbol has >=1 event (knowledge) in the prior `lookback_days` calendar days."""
    M = pd.DataFrame(False, index=cal, columns=SYMS)
    for s, g in ev.groupby("symbol"):
        if s not in M.columns: continue
        d = np.sort(g.ad.dropna().values.astype("datetime64[ns]"))
        c = cal.values.astype("datetime64[ns]")
        p = np.searchsorted(d, c, side="right") - 1
        ok = p >= 0
        last = np.where(ok, d[np.clip(p, 0, None)], np.datetime64("NaT"))
        M[s] = ok & ((c - last) <= np.timedelta64(lookback_days, "D"))
    return M

# ---------------- simulation ----------------
Oa, Ha, La, Ca, ATRa = O.values, H.values, L.values, C.values, ATR.values
ADVa, ADVSa, SIGa, CRa = ADV_USD.values, ADV_SH.values, SIG20.values, Craw.values
col = {s: k for k, s in enumerate(SYMS)}
LASTBAR = {s: int(np.where(~np.isnan(Ca[:, col[s]]))[0].max()) for s in SYMS}
NT = len(cal)

def terminal(s, mode):
    """terminal return applied when bars end before exit. mode: 'table' (delisting_returns, null->0),
    'bankrupt100' (null & last raw close < $5 or failed banks -> -100%)."""
    if s not in dl.index: return 0.0, "no_row"
    r = dl.loc[s]; tv = r.terminal_return
    if pd.notna(tv) and not r.suspect: return float(tv), "matched"
    if mode == "bankrupt100" and (s in ("SIVB", "FRC", "SBNY") or r.last_close_raw < 5): return -1.0, "assumed_-100%"
    return 0.0, "null_as_last_close"

def sim(s, i_sig, atrk=2.0, delist_mode="table"):
    c_ = col[s]; i = i_sig + 1
    if i >= NT: return None
    E = Oa[i, c_]; atr = ATRa[i_sig, c_]
    if not (E > 0 and atr > 0): return None
    Dd = atrk * atr; stop = E - Dd; tp = E + TPR * Dd
    last = min(i + MAXHOLD - 1, NT - 1)
    o, h, l, c = Oa[i:last + 1, c_], Ha[i:last + 1, c_], La[i:last + 1, c_], Ca[i:last + 1, c_]
    valid = ~np.isnan(c)
    gs = (o <= stop); gt = (o >= tp); gs[0] = gt[0] = False
    hs = l <= stop; ht = h >= tp
    anyev = valid & (gs | gt | hs | ht)
    term = 0.0; tflag = ""
    if anyev.any():
        k = int(np.argmax(anyev)); j = i + k
        if gs[k]: X, why, ven = o[k], "stop_gap", "open"
        elif gt[k]: X, why, ven = o[k], "tp_gap", "open"
        elif hs[k]: X, why, ven = stop, "stop", "continuous"     # stop assumed first if both touched
        else: X, why, ven = tp, "tp", "continuous"
    else:
        if last == i + MAXHOLD - 1 and valid[-1]: j = last; why = "time"; ven = "close"
        elif LASTBAR[s] < last: j = LASTBAR[s]; why = "delisted"; ven = "close"
        else: j = last; why = "open_eod"; ven = "close"
        X = Ca[j, c_]
        if why == "delisted":
            term, tflag = terminal(s, delist_mode)
    Xeff = X * (1 + term)
    return dict(sym=s, sig=cal[i_sig], i_sig=i_sig, i=i, j=j, E=E, X=Xeff, X_bar=X, D=Dd, why=why, ven=ven,
                term=term, term_flag=tflag, days=j - i + 1, R_gross=(Xeff - E) / Dd,
                regime="SPY>200" if SPY_UP.iat[i_sig] else "SPY<200")

def costs(t):
    """Tomas v1.1 one-way costs in bps: entry MOO (venue open) at t+1; exit venue per exit type.
    $10k clip at raw price; ADV/sigma lagged to the signal close; bucket-default spread (no quotes in store).
    Also flat 5 bps/side (prior study) for comparability."""
    s, c_, isg = t["sym"], col[t["sym"]], t["i_sig"]
    p = CRa[isg, c_]; adv = ADVSa[isg, c_]; sig = SIGa[isg, c_]
    p = p if p > 0 else 1.0
    sh = CLIP_USD / p; adv = adv if adv > 0 else None; sig = sig if sig > 0 else None
    ce = trade_cost("buy", p, sh, adv, sig, None, venue="open", trade_date=cal[t["i"]].date())
    cx = trade_cost("sell", p, sh, adv, sig, None, venue=t["ven"], trade_date=cal[t["j"]].date())
    t["bucket"] = ce["bucket"]; t["c_in_bps"] = ce["total_bps"]; t["c_out_bps"] = cx["total_bps"]
    t["adv_usd"] = ADVa[isg, c_]
    unit = 1e-4 / t["D"]
    t["cost_R_1x"] = (ce["total_bps"] * t["E"] + cx["total_bps"] * t["X"]) * unit
    t["cost_R_flat5"] = 5 * (t["E"] + t["X"]) * unit
    t["R_1x"] = t["R_gross"] - t["cost_R_1x"]; t["R_2x"] = t["R_gross"] - 2 * t["cost_R_1x"]
    t["R_flat5"] = t["R_gross"] - t["cost_R_flat5"]
    return t

def run_signals(cands, atrk=2.0, delist_mode="table", busy_rule=True):
    """cands: list of (i_sig, sym) sorted by i_sig. One open position per symbol (prior rule)."""
    out = []; busy = {}
    for i, s in cands:
        if busy_rule and busy.get(s, -1) >= i + 1: continue
        t = sim(s, i, atrk, delist_mode)
        if t: out.append(costs(t)); busy[s] = t["j"]
    return out

def candidates(gap_th=0.04, vr_th=1.8, universe="pit", extra_mask=None, syms=None):
    m = (GAP > gap_th) & (VRAT > vr_th) & ABOVE
    if universe == "pit": m &= MEMB
    if syms is not None: m &= pd.DataFrame(np.isin(SYMS, syms)[None, :].repeat(NT, 0), index=cal, columns=SYMS)
    if extra_mask is not None: m &= extra_mask
    m.iloc[:FIRST] = False; m.iloc[-1] = False
    ii, jj = np.where(m.values)
    order = np.lexsort((jj, ii))
    return [(int(ii[k]), SYMS[jj[k]]) for k in order]

def daily_curve(trades, key="R_1x"):
    pnl = np.zeros(NT)
    for t in trades:
        c_ = col[t["sym"]]; i, j = t["i"], t["j"]
        cl = Ca[i:j + 1, c_].copy(); cl[-1] = t["X"]
        ref = np.concatenate([[t["E"]], cl[:-1]])
        d = (cl - ref) / t["D"]; d[np.isnan(d)] = 0.0
        pnl[i:j + 1] += d
        pnl[j] -= (t["R_gross"] - t[key])
    return pd.Series(pnl, index=cal)

# ---------------- stats ----------------
def nw_t(y, X=None, lags=10):
    y = np.asarray(y, float)
    X = np.ones((len(y), 1)) if X is None else np.c_[np.ones(len(y)), X]
    b = np.linalg.lstsq(X, y, rcond=None)[0]; e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X); S = (X * e[:, None]).T @ (X * e[:, None])
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1); G = (X[l:] * e[l:, None]).T @ (X[:-l] * e[:-l, None]); S += w * (G + G.T)
    se = np.sqrt(np.diag(XtXi @ S @ XtXi)); return b, b / se

def trade_stats(tr_, key):
    if not tr_: return dict(n=0)
    R = np.array([t[key] for t in tr_])
    return dict(n=len(R), hit=round(float((R > 0).mean()), 3), exp_R=round(float(R.mean()), 4),
                t_trade=round(float(R.mean() / (R.std(ddof=1) / math.sqrt(len(R)))), 2) if len(R) > 2 else None)

def curve_stats(p):
    p = p.astype(float); sd = p.std(ddof=1)
    sr = p.mean() / sd if sd > 0 else 0.0
    cum = p.cumsum(); dd = (cum - cum.cummax()).min()
    z = (p - p.mean()) / p.std(ddof=0) if sd > 0 else p * 0
    return dict(days=len(p), sharpe=round(sr * math.sqrt(252), 3), sr_d=float(sr), maxDD_R=round(float(dd), 1),
                skew=float((z ** 3).mean()), kurt=float((z ** 4).mean()))
