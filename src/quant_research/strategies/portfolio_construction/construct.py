#!/usr/bin/env python3
"""
Portfolio construction model for the CIO desk (Alpaca PAPER).  READ-ONLY w.r.t. the desk:
reads Dmitri's store (data/bars, data/universe, data/earnings) + desk_data_client (rule #5), $QR_DESK_DIR/{positions.json,orders_status.json,performance/history.csv},
writes only $QR_DESK_DIR/portfolio/targets_<date>.json (+ diagnostics).  Places NO orders.

Pipeline
 1. Point-in-time signals rebuilt from daily bars for every date (same definitions as quant.py).
 2. Holdout ("pseudo-OOS") rank-IC of each signal vs forward 5-day returns, sampled every 5 days
    (non-overlapping).  First 60% of dates = in-sample, last 40% = OOS holdout.
 3. Signal weights: w ∝ C_shr^-1 * IC_shr  (IC shrunk to 0 with prior n0, signals with OOS t<1 or IC<=0 get 0),
    blended 50/50 with equal weights (correlation-adjusted C_shr^-1 * 1).  If NO signal passes -> pure equal-weight fallback.
    C_shr = 0.5*C + 0.5*I  (C = time-series correlation of the signals' IC series).
 4. Expected 5d alpha_i = IC_c * sigma_i,5d * z_i  (Grinold).  With a shrunk covariance the unconstrained
    optimum w ∝ Σ^-1 α  ≈ inverse-vol sizing with a correlation adjustment.
 5. Convex optimisation (cvxpy):  max α'w − tc/H·|w−w0|  s.t. ex-ante vol ≤ target, Risk-Manager limits,
    |β'w| ≤ beta_tol, sector caps, earnings blackout.  Then integer-share rounding + post-checks.
 6. Admission gate (FRAMEWORK.md §1): a signal is VALIDATED only if it passes the internal OOS test AND is
    listed in --victor_passed (Victor's PASS / CONDITIONAL PASS in validation/verdicts-log.md).
 7. FALLBACK = SHADOW / DE-RISK ONLY (CIO-confirmed 2026-10-30, default --fallback derisk): with no validated
    signal the full optimised book is written to portfolio/shadow/targets_<date>.json (tradable=false,
    NOT FOR TRADING) and the tradable portfolio/targets_<date>.json may only trim / close / cover existing
    positions and tighten stops: no new names, no increases, no hedge additions.
 8. Optional Garleanu-Pedersen (2013) partial trading (off by default): --gp_ell L = lambda/gamma gives
    a/gamma = (-(1-rho+L*rho) + sqrt((1-rho+L*rho)^2 + 4L(1-rho)^2)) / (2(1-rho))  (GP Prop. 2, scalar case)
    and trade rate tau = a/lambda = (a/gamma)/L; each signal k is scaled by 1/(1+phi_k a/gamma) (GP Prop. 4)
    with phi_k = 1 - 5-day cross-sectional rank autocorrelation of signal k (trailing 120d); then
    w = w0 + tau (w* - w0).  --gp_rate overrides tau.
 9. risk/LIMITS.md alignment (§1, §3, §5), ORDER OF OPERATIONS:
      combine signals -> sleeve weights -> vol-scaling multiplier m (one overlay per sleeve)
      -> panic multiplier -> book optimisation (beta, sector, 6% ex-ante vol CONSTRAINT, position, risk, gross caps
      incl. breaker cap) -> stops -> compliance check.
    * Sleeves: momentum = {MOM_12_1, RS63}, trend = {TREND}, reversal = {REV5}, event = {PEAD}.
    * m_s = min(1, sigma_target_s / sigma_hat_126d,s), sigma_hat from the sleeve's backtest-proxy daily returns
      (unit-gross, dollar-neutral book on the sleeve's z-score, lagged one day; bars from --proxy_src).
      sigma_target_s defaults to the proxy's long-run (full-sample) vol; override with --sigma_target.
      This is the ONLY vol-scaling overlay. The 6% book ex-ante vol cap is an optimiser constraint, not a scaler.
    * Panic (risk/state/panic_flag.json, FAIL-SAFE = ON): momentum and trend sleeves x multiplier (0.5),
      no new / increased shorts in names with a negative momentum or trend z (loser-shorts), net beta >= -0.10.
    * Breakers (risk/state/breaker_state.json, FAIL-SAFE = HALVED/30%): gross cap from the file
      (buffer 1pp below), HALTED -> de-risk only, no new trades.
    * Covariance: Ledoit-Wolf (2004) optimal shrinkage intensity to constant correlation (default, --shrinkage lw);
      fixed 0.5 via --shrinkage fixed --shrink_delta 0.5. Risk-forecast inflation k (--risk_inflation, default 1.25)
      multiplies ex-ante vol in the 6% book vol cap only (walk-forward bias 1.15-1.37 for MV on Dave's bars; MV-LW 1.20).
    * Hard asset exclusion: only US-listed equities/ETFs; crypto pairs can never enter any targets file.
10. LIMITS.md alignment (current header read at run time, v0.3.7 at 02:28 SGT; CIO 01:58 + Risk rulings ~02:13/02:27/02:28; FRAMEWORK v0.6/v0.7):
    * EARNINGS (H7, earnings_gate.py, Dmitri's data/earnings calendar, read-only): a name whose next release falls
      inside the holding horizon (execution session + --earn_horizon_sessions) may not be opened or increased on
      either side; a held position carries exit_by = last session before the release (AMC: the release day) and is
      closed now if exit_by is today. SHORTS are never held through their own release (no exceptions); a held LONG
      may be kept through only with a CIO exception (--earnings_hold_exceptions, 3x stop-gap stress = CIO's).
      DEFAULT POLICY risk_ruling_20261030_0227 (--earnings_policy; Risk decisions-log 2026-10-30 02:27):
      (1) confirmed date -> standard H7, 10-session flag; (2) estimated date (Dmitri's next_earnings sidecar) -> window
      opens 5 sessions before the earliest candidate minus the 10-session flag (15 sessions); shorts closed before the
      window opens, nothing opened/increased inside it; (3) estimated date outside the buffered horizon counts as known
      only if the last 8-K 2.02 is <= 45 days old, else unknown (tradable: no new/increased short; shadow: flagged);
      (4) no date row, or a calendar/sidecar > 1 US session stale (or sha256 mismatch/unreadable) -> FULL FAIL-SAFE
      (treated as reporting inside the window: no opens/adds, existing position closed this session, both books);
      (5) earliest date across the current file applies. --earnings_policy strict = pre-ruling gate (estimated dates
      = unknown). ETFs are exempt. The manual --blackout list stays on top.
    * sigma_target (§5 T12): expanding-window median of the proxy sleeve's 126d realised vol once the proxy has
      >= 3 years (756 days) of history; before that the proxy's full-sample vol. 1x cap (m <= 1) unchanged.
    * PANIC (§3) is FINAL since ~02:27 SGT: a flag file with no provisional marker is BINDING. Responses come from the
      file when panic is on: multiplier_momentum_trend (sleeve factor), momentum_short_notional_multiplier (held
      momentum shorts cut to <= mult x current), new_loser_shorts_allowed (false -> no new/increased short in names with
      a negative momentum/trend z), net_beta_floor (book beta >= floor). Hard-coded 0.5 / 0.5 / false / -0.10 are
      fail-safe defaults only (missing/invalid field, or missing/stale/invalid file -> panic ON). T8 responses
      (beta floor, loser-short ban) are pending validation: applied as written, logged t8_status=pending_validation.
      A file that still says provisional is context only (--panic_provisional context, default; 'apply' forces it).
    * BREAKER (T4, change log v0.3-v0.3.5): RESUMED_DISARMED = 30% gross cap; backstop_equity is read from breaker_state.json as Risk's
      CURRENT EPISODE backstop (reset by Risk on every exit-(ii) lift, which needs Daniel's logged OK) and never
      recomputed; construction never infers a lift or re-arm (HALTED stays de-risk only until Risk's file changes).
      Run equity <= backstop in any non-HALTED state -> treated as HALTED. Unknown state, an invalid backstop, or
      halt_armed=false outside RESUMED_DISARMED -> FAIL-SAFE HALVED 30%.
11. DESK RULE #5 (2026-10-30, FRAMEWORK v0.7): history only from Dmitri's store, live data only through
    $QR_DATA_DIR/lib/desk_data_client.py. Book prices/vols/betas/cov/ADV: store (SIP, adjusted) for complete
    sessions + SIP 5-min intraday bars via the client for today's partial row. data.json is no longer read.
    Sleeve proxy (--proxy_src store_pit): PIT S&P 500 members from the store, Victor's defect names + SNDK excluded,
    PROVISIONAL until Dmitri's fixes land. Shadow book bumped to shadow_fallback_composite_v2; method_version "v2".
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import json, math, argparse, csv, re, datetime as dt
import numpy as np, pandas as pd
import cvxpy as cp
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quant_research.strategies.portfolio_construction.risk_state import read_panic, read_breaker, NYSE_HOLIDAYS, ET, SGT
from quant_research.strategies.portfolio_construction import earnings_gate as eg
from quant_research.strategies.portfolio_construction import targets_io as tio
DDC_LIB = f"{_QR.DATA_DIR}/lib"            # DESK RULE #5: Dmitri's shared client (read-only; never edited here)
if DDC_LIB not in sys.path: sys.path.insert(0, DDC_LIB)
from quant_research.data.client import desk_data_client as ddc
from quant_research.strategies.portfolio_construction.risk_state import limits_version as _limits_version
LIMITS_VERSION = _limits_version() or "unreadable"   # parsed from the risk/LIMITS.md header at run time (v0.3.7 at 02:28 SGT)
METHOD_VERSION = "v2"                          # method_version in every targets doc / log line (FRAMEWORK §8a)

DEFECT_LABEL = "PROVISIONAL - data defects pending Dmitri's fixes"
DATA_ISSUES = f"{_QR.DESK_DIR}/validation/backtests/pead_long_pit/data_issues.json"

# Stable identifiers for downstream consumers (Priya / Performance). Bump the version suffix ONLY on a material
# methodology change (signal set, combination rule, risk model, constraints); log the change in FRAMEWORK.md §8a.
SHADOW_SLEEVE_ID = "shadow_fallback_composite_v2"   # v2 (2026-10-30 ~02:20 SGT): sigma_target rule, earnings gate, rule-#5 data; 02:3x: earnings policy risk_ruling_20261030_0227 + FINAL panic (flagged for CIO: §8a bump candidate)
SHADOW_BOOK_NAME = "Shadow fallback composite v2"
SHADOW_DESCRIPTION = ("Non-tradable tracking book (paper, never executed). Five price signals (MOM_12_1, RS63, TREND, REV5, PEAD) "
    "are equal-weighted in the fallback (any signal with OOS t <= -2 gets weight 0; RS63 on 2026-10-30), grouped into "
    "momentum/trend/reversal/event sleeves, each scaled by its 126d vol multiplier m (<= 1) and the panic factor, then sized "
    "long/short by a mean-variance optimiser on a 120d Ledoit-Wolf constant-correlation covariance with a 6% ex-ante vol cap "
    "(forecast x1.25), |beta| <= 0.01 via an SPY hedge, sector, 9.5% position, 0.95% risk-to-stop and 58% (or breaker) gross "
    "caps, TCA cost model; 2xATR(14) stops. US equities/ETFs only. v2: sigma_target = expanding median of the 126d vol of a "
    "PIT S&P 500 sleeve proxy from Dmitri's SIP store (Victor's defect names + SNDK excluded; PROVISIONAL), LIMITS H7 "
    "earnings gate (default policy risk_ruling_20261030_0227), Risk's panic flag (binding when final; responses from the file), prices/volumes from Dmitri's store "
    "+ SIP intraday via desk_data_client (desk rule #5).")
TRADABLE_IDS = {"DE-RISK ONLY": ("tradable_derisk_only_v1", "Tradable de-risk-only book v1",
                                 "Tradable book while no signal is validated or the breaker is HALTED: may only trim, close or cover existing "
                                 "positions (toward the shadow book, the buffered limits, the breaker gross cap and, if panic, the file's momentum-short cut and net beta floor) and tighten stops."),
                "FULL": ("tradable_validated_composite_v1", "Tradable validated composite v1",
                         "Tradable book on Victor-validated signals, same construction as the shadow composite.")}

ROOT = f"{_QR.DESK_DIR}"
def excluded_asset(sym):
    """HARD EXCLUSION: crypto is ruled out entirely (CIO). Alpaca crypto pairs contain '/'; also deny bare tickers."""
    u = str(sym).upper()
    return "/" in u or u in {"BTCUSD", "ETHUSD", "SOLUSD", "BTC", "ETH", "SOL", "DOGEUSD", "LTCUSD", "AVAXUSD"}
SLEEVE_OF = {"MOM_12_1": "momentum", "RS63": "momentum", "TREND": "trend", "REV5": "reversal", "PEAD": "event"}
PANIC_SLEEVES = {"momentum", "trend"}
# Index / macro ETFs: not in the alpha cross-section. SPY is allowed as a beta hedge only.
NON_ALPHA = {"SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "TLT", "HYG", "GLD", "SLV"}
HEDGE = "SPY"
# Hand-coded GICS sectors (kept from v1; the store has CURRENT GICS only). Sector ETFs map to their sector.
SECTOR = {}
for sec, names in {
    "Tech": "AAPL MSFT NVDA AVGO ORCL CRM AMD ADBE CSCO ACN INTC QCOM TXN IBM NOW INTU MU AMAT LRCX KLAC PANW XLK SMH",
    "Comm": "GOOGL META NFLX DIS T VZ XLC",
    "ConsDisc": "AMZN TSLA HD MCD LOW BKNG SBUX NKE TJX XLY",
    "Fin": "BRK.B JPM V MA BAC WFC GS MS SPGI BLK SCHW C AXP MMC CB PGR XLF",
    "Health": "LLY UNH JNJ ABBV MRK TMO ABT AMGN PFE ISRG ELV CI REGN VRTX BMY MDT GILD SYK XLV",
    "Energy": "XOM CVX COP XLE",
    "Staples": "WMT PG COST KO PEP PM MO XLP",
    "Industrials": "GE CAT RTX HON UNP DE LMT ETN FDX UPS ADP UBER XLI",
    "Materials": "LIN XLB", "Utilities": "NEE XLU", "RealEstate": "PLD XLRE",
    "Index": "SPY QQQ IWM DIA EEM EFA", "Rates": "TLT HYG", "Commod": "GLD SLV"}.items():
    for s in names.split(): SECTOR[s] = sec

# Desk universe (DESK RULE #5, 2026-10-30): the 117 US equities/ETFs of quant.py's list, frozen here (= SECTOR map keys).
# data.json is no longer read. MMC is absent from Dmitri's store (Marsh McLennan trades as MRSH there); it was already
# dropped under data.json (90 bars < 260), so the effective universe is unchanged at 116.
DESK_UNIVERSE = sorted(SECTOR)
HIST_CAL_DAYS = 420                              # same window as quant.py (start = today - 420 calendar days)
DATA_PROVENANCE = {}                             # filled by load() / sleeve_vol_scaling(); written to every targets doc

def load(args):
    """DESK RULE #5. History: Dmitri's SIP store (bars/daily/adjusted) via desk_data_client.get_daily_bars (local parquet
    first; the client calls the API, throttled + cached, only for sessions after the store's coverage end). Today's
    partial row: SIP 5-min bars (adjustment=all, regular hours 09:30-16:00 ET) via desk_data_client.get_intraday_bars
    (end capped by the client at now-16 min: free-plan SIP). No data.json, no direct HTTP.
    --live_source offline_test: no API call; today's row = the last complete bar's open/volume with close = last close
    (zero-return placeholder). TESTS ONLY, never production."""
    cut = pd.Timestamp(args.asof_bar_cutoff)
    end = (cut - pd.Timedelta(days=1)).date(); start = (cut - pd.Timedelta(days=HIST_CAL_DAYS)).date()
    syms = [s for s in DESK_UNIVERSE if not excluded_asset(s)]
    df = ddc.get_daily_bars(syms, start, end, adjustment="all", allow_api=(args.live_source == "client"))
    df = df[pd.to_datetime(df["session_date"]) < cut].copy()
    if "zero_volume" in df.columns: df = df[~df["zero_volume"].fillna(False).astype(bool)]
    df["session_date"] = pd.to_datetime(df["session_date"])
    P = {f: df.pivot(index="session_date", columns="symbol", values=f).sort_index() for f in ("close", "high", "low", "open", "volume")}
    n_ok = P["close"].notna().sum()
    keep = [c for c in P["close"].columns if n_ok[c] >= 260]    # 12-1 momentum + ATR history (as v1); 420 cal. days ~ 288 sessions
    missing = sorted(set(syms) - set(P["close"].columns)); short = sorted(set(P["close"].columns) - set(keep))
    C, Hh, L, O, V = (P[f][keep] for f in ("close", "high", "low", "open", "volume"))
    live_t = cut
    src_counts = df["source"].value_counts().to_dict() if "source" in df.columns else {}
    if args.live_source == "client":
        ib = ddc.get_intraday_bars(keep, f"{cut.date()} 09:30", f"{cut.date()} 16:00", "5Min", adjustment="all")
        if ib is None or ib.empty: raise SystemExit(f"desk_data_client returned no intraday bars for {cut.date()}: fail closed, no targets written")
        tl = ib["timestamp_local"]; ib = ib[(tl.dt.strftime("%H:%M") >= "09:30") & (tl.dt.strftime("%H:%M") < "16:00")]
        g = ib.sort_values("timestamp_utc").groupby("symbol")
        agg = pd.DataFrame(dict(o=g["open"].first(), h=g["high"].max(), l=g["low"].min(), c=g["close"].last(), v=g["volume"].sum(),
                                t=g["timestamp_utc"].last(), n=g.size()))
        live = {s: dict(o=float(r.o), h=float(r.h), l=float(r.l), c=float(r.c), v=float(r.v)) for s, r in agg.iterrows()}
        last = {s: float(r.c) for s, r in agg.iterrows()}
        last_ts = {s: (r.t + pd.Timedelta(minutes=5)).isoformat() for s, r in agg.iterrows()}   # bar END time (UTC)
        live_desc = (f"{cut.date()} partial session: SIP 5-min bars 09:30 ET .. {max(last_ts.values()) if last_ts else None} (bar end, UTC) via "
                     f"desk_data_client.get_intraday_bars (o=first open, h/l=max/min, v=sum, close=last 5-min close; >= 16 min delayed)")
    elif args.live_source == "offline_test":
        live = {s: dict(o=float(C[s].iloc[-1]), h=float(Hh[s].iloc[-1]), l=float(L[s].iloc[-1]), c=float(C[s].iloc[-1]), v=float(V[s].iloc[-1])) for s in keep}
        last = {s: v["c"] for s, v in live.items()}; last_ts = {s: str(C.index[-1].date()) for s in keep}
        live_desc = f"OFFLINE TEST: no live row (placeholder = last complete bar {C.index[-1].date()}); NOT FOR PRODUCTION"
    else:
        raise SystemExit(f"unknown --live_source {args.live_source}")
    DATA_PROVENANCE.update(book_history=dict(source=f"Dmitri's store {_QR.DATA_DIR}/bars/daily/adjusted (SIP, adjustment=all) via desk_data_client.get_daily_bars",
                                             store_version=_store_version(), store_coverage_end=str(ddc.store_coverage("all")),
                                             window=[str(start), str(end)], rows_by_source=src_counts, warnings=list(df.attrs.get("warnings", [])),
                                             universe=f"DESK_UNIVERSE ({len(syms)} symbols, frozen quant.py list)", used=len(keep),
                                             missing_in_store=missing, dropped_short_history=short),
                           live_row=dict(source=args.live_source, description=live_desc, n_symbols=len(live)))
    return C, Hh, L, O, V, last, last_ts, live, live_t

def _store_version():
    try: return open(f"{_QR.DATA_DIR}/VERSION").read().strip()
    except OSError: return None

def signals_panel(C, O, V):
    """Point-in-time signal panels (date x symbol). Definitions mirror quant.py."""
    spy = C[HEDGE]
    vol20 = C.pct_change().rolling(20).std() * math.sqrt(252)
    sig = {}
    sig["MOM_12_1"] = C.shift(21) / C.shift(252) - 1                 # quant.py 'mom'
    sig["RS63"] = (C / C.shift(63) - 1).sub(spy / spy.shift(63) - 1, axis=0)   # quant.py 'rs63'
    sig["TREND"] = C / C.rolling(200).mean() - 1                      # continuous version of above200
    sig["REV5"] = -(C / C.shift(5) - 1)                               # short-term reversal (RSI/oversold idea)
    gap = O / C.shift(1) - 1
    vr = V / V.shift(1).rolling(20).mean()
    ev = gap.where((gap.abs() > 0.04) & (vr > 1.8))                  # quant.py gap/PEAD definition
    sig["PEAD"] = ev.ffill(limit=14).fillna(0.0)                       # sign/size of gap within last 15 sessions
    # desk composite from quant.py (reported only)
    sig["DESK_SCORE"] = (sig["MOM_12_1"] * 100 + sig["RS63"] * 100) / (vol20 * 100).clip(lower=10)
    return sig

def zscore_row(x):
    x = x.astype(float)
    m, s = x.mean(), x.std()
    if not s or np.isnan(s): return x * 0
    return ((x - m) / s).clip(-3, 3)

def ic_study(sig, C, universe, horizon=5, split=0.6):
    fwd = C.shift(-horizon) / C - 1
    out, series = {}, {}
    for k, S in sig.items():
        S = S[universe]
        dates = [t for t in S.index if S.loc[t].notna().sum() > 30 and fwd.loc[t, universe].notna().sum() > 30]
        dates = dates[::horizon]                                       # non-overlapping
        ics = []
        for t in dates:
            a = S.loc[t]; b = fwd.loc[t, universe]
            m = a.notna() & b.notna()
            if a[m].nunique() < 5: continue
            ics.append((t, a[m].rank().corr(b[m].rank())))
        ser = pd.Series(dict(ics)).dropna()
        series[k] = ser
        n = len(ser); cut = int(n * split)
        ins, oos = ser.iloc[:cut], ser.iloc[cut:]
        f = lambda z: (float(z.mean()) if len(z) else float("nan"),
                       float(z.mean() / z.std() * math.sqrt(len(z))) if len(z) > 2 and z.std() > 0 else float("nan"), len(z))
        out[k] = dict(zip(["is_ic", "is_t", "is_n"], f(ins))) | dict(zip(["oos_ic", "oos_t", "oos_n"], f(oos))) | \
                 dict(first=str(ser.index[0].date()) if n else None, oos_start=str(oos.index[0].date()) if len(oos) else None,
                      last=str(ser.index[-1].date()) if n else None)
    return out, series

def signal_weights(stats, series, keys, n0=20, t_min=1.0, blend=0.5, harm_t=-2.0):
    df = pd.DataFrame({k: series[k] for k in keys}).dropna()
    Cs = df.corr().values if len(df) > 5 else np.eye(len(keys))
    Cs = 0.5 * Cs + 0.5 * np.eye(len(keys))
    inv = np.linalg.inv(Cs)
    # signals with significant NEGATIVE OOS evidence (t <= harm_t) are excluded even from the fallback
    harmed = [k for k in keys if stats[k]["oos_n"] > 2 and stats[k]["oos_t"] <= harm_t]
    ones = np.array([0.0 if k in harmed else 1.0 for k in keys])
    eq = np.clip(inv @ ones, 0, None) * ones; eq = eq / eq.sum()
    shr = []
    for k in keys:
        s = stats[k]; ok = (s["oos_n"] > 2) and (s["oos_ic"] > 0) and (s["oos_t"] >= t_min)
        shr.append(s["oos_ic"] * s["oos_n"] / (s["oos_n"] + n0) if ok else 0.0)
    shr = np.array(shr)
    passed = [k for k, v in zip(keys, shr) if v > 0]
    if shr.sum() <= 0:
        w, mode = eq, "FALLBACK equal-weight (correlation-adjusted C_shr^-1·1; equal when IC history is short): no signal passed OOS (IC>0 and t>=%.1f); excluded for OOS t<=%.1f: %s" % (t_min, harm_t, harmed or "none")
    else:
        icw = np.clip(inv @ shr, 0, None); icw = icw / icw.sum()
        w, mode = blend * icw + (1 - blend) * eq, f"{blend:.0%} OOS-IC weights (C_shr^-1·IC_shr) + {1-blend:.0%} equal-weight (C_shr^-1·1)"
    return dict(zip(keys, w)), mode, passed, dict(zip(keys, shr)), pd.DataFrame(Cs, keys, keys)

def signal_decay(sig, universe, lag=5, window=120):
    """phi_k per `lag`-day period: 1 - mean cross-sectional Spearman corr(s_t, s_{t+lag}) over the trailing window."""
    out = {}
    for k, S in sig.items():
        S = S[universe].iloc[-window - lag:]
        ac = []
        for i in range(0, len(S) - lag):
            a, b = S.iloc[i], S.iloc[i + lag]; m = a.notna() & b.notna()
            if m.sum() > 30 and a[m].nunique() > 5 and b[m].nunique() > 5: ac.append(a[m].rank().corr(b[m].rank()))
        out[k] = float(min(1.0, max(0.0, 1 - np.mean(ac)))) if ac else 1.0
    return out

def gp_params(ell, rho=0.0):
    """Garleanu-Pedersen (2013) Prop. 2 under Assumption A (Lambda = lambda*Sigma), scalar case. ell = lambda/gamma."""
    b = (1 - rho) + ell * rho
    a_over_g = (-b + math.sqrt(b * b + 4 * ell * (1 - rho) ** 2)) / (2 * (1 - rho))
    return a_over_g, a_over_g / ell     # (a/gamma, trade rate tau = a/lambda)

def shrunk_cov(R, method="lw", fixed_delta=0.5):
    """Shrinkage to the constant-correlation target F (Ledoit & Wolf 2004, 'Honey, I shrunk...').
    method='lw'   : OPTIMAL intensity delta* = max(0, min(1, kappa/T)), kappa = (pi - rho)/gamma
                    (own implementation of the paper's Appendix B / Ledoit's covCor.m; S with 1/T, demeaned).
    method='fixed': delta = fixed_delta (v2 behaviour: 0.5, sample cov with ddof=1).
    Returns (Sigma, rbar, delta)."""
    if method == "fixed":
        S = R.cov().values; sd = np.sqrt(np.diag(S))
        corr = S / np.outer(sd, sd); n = len(sd)
        rbar = (corr.sum() - n) / (n * (n - 1))
        F = rbar * np.outer(sd, sd); np.fill_diagonal(F, sd ** 2)
        return (1 - fixed_delta) * S + fixed_delta * F, rbar, float(fixed_delta)
    X = R.values.astype(float); T, N = X.shape
    X = X - X.mean(0)
    S = X.T @ X / T
    var = np.diag(S); sd = np.sqrt(var)
    rbar = ((S / np.outer(sd, sd)).sum() - N) / (N * (N - 1))
    F = rbar * np.outer(sd, sd); np.fill_diagonal(F, var)
    Y = X ** 2
    phiMat = Y.T @ Y / T - 2 * (X.T @ X) * S / T + S ** 2          # pi_ij
    phi = phiMat.sum()
    term1 = (X ** 3).T @ X / T
    help_ = X.T @ X / T; hd = np.diag(help_)
    theta = term1 - hd[:, None] * S - help_ * var[None, :] + var[:, None] * S
    np.fill_diagonal(theta, 0)
    rho = np.diag(phiMat).sum() + rbar * ((1 / sd)[:, None] * sd[None, :] * theta).sum()
    gamma = np.linalg.norm(S - F, "fro") ** 2
    d = float(max(0.0, min(1.0, (phi - rho) / gamma / T)))
    return d * F + (1 - d) * S, rbar, d

def load_bars(path, cutoff):
    d = json.load(open(path))
    F = {k: {} for k in "cov"}
    for s_, b in d["bars"].items():
        if excluded_asset(s_): continue
        b = [x for x in b if x["t"][:10] < cutoff]
        if not b: continue
        idx = pd.to_datetime([x["t"][:10] for x in b])
        for k in "cov": F[k][s_] = pd.Series([x[k] for x in b], idx)
    return [pd.DataFrame(F[k]).sort_index() for k in "cov"]

def sigma_target_rule(r, window=126, rule="limits", min_days=756):
    """LIMITS §5 T12: sigma_target = expanding-window median of the sleeve's rolling `window`-day realised vol (annualised)
    once >= min_days of daily history exist; before that the full-sample realised vol. Evaluated at the last date of r
    (the expanding window = all history up to the cutoff). Returns (value, source text)."""
    r = pd.Series(r).dropna()
    lr = float(r.std() * math.sqrt(252)) if len(r) > 20 else float("nan")
    if rule == "limits" and len(r) >= min_days:
        roll = r.rolling(window).std().dropna() * math.sqrt(252)
        return float(roll.median()), f"expanding median of proxy {window}d realised vol ({len(roll)} windows, {len(r)} proxy days >= {min_days}) - LIMITS §5 T12"
    if rule == "limits":
        return lr, f"proxy full-sample vol ({len(r)} proxy days < {min_days}) - LIMITS §5 T12 pre-3y rule"
    return lr, "proxy long-run (full-sample) vol (rule=fullsample, v0.5)"

def defect_names():
    """Victor's data_issues.json members_without_bars_symbols + SNDK (ticker reuse). Fail closed if unreadable."""
    try:
        iss = json.load(open(DATA_ISSUES))
        return set(iss["members_without_bars_symbols"]) | {"SNDK"}
    except Exception as e:  # noqa
        raise SystemExit(f"cannot read Victor's defect list {DATA_ISSUES} ({type(e).__name__}): store_pit proxy needs it; no targets written")

def load_store_pit(cutoff, start="2016-01-01"):
    """PIT S&P 500 proxy panel from Dmitri's store (rule #5): bars/daily/adjusted for every current + former member
    (universe.parquet roles sp500_current / sp500_former_since_2016) minus Victor's defect names and SNDK, via
    desk_data_client.get_daily_bars(allow_api=False); zero_volume rows masked; membership mask from
    universe/sp500_membership.parquet ([start_date_filled, end_date)). SPY added for RS63. No delisting returns applied
    (same as the old proxy). Returns C, O, V, member mask M, info."""
    D = f"{_QR.DATA_DIR}"
    uni = pd.read_parquet(f"{D}/universe/universe.parquet", columns=["symbol", "role"])
    mem = pd.read_parquet(f"{D}/universe/sp500_membership.parquet")
    bad = defect_names()
    stocks = sorted(set(uni.loc[uni["role"].isin(["sp500_current", "sp500_former_since_2016"]), "symbol"]) - bad)
    end = (pd.Timestamp(cutoff) - pd.Timedelta(days=1)).date()
    df = ddc.get_daily_bars(stocks + [HEDGE], start, end, adjustment="all", allow_api=False)
    df = df[pd.to_datetime(df["session_date"]) < pd.Timestamp(cutoff)].copy()
    df.loc[df["zero_volume"].fillna(False).astype(bool), ["open", "close", "volume"]] = np.nan
    df["session_date"] = pd.to_datetime(df["session_date"])
    C, O, V = (df.pivot(index="session_date", columns="symbol", values=f).sort_index() for f in ("close", "open", "volume"))
    idx = C.index; cols = [c for c in C.columns if c != HEDGE]
    M = pd.DataFrame(False, index=idx, columns=cols)
    for r in mem.itertuples():
        if r.symbol not in M.columns: continue
        e = pd.Timestamp(r.end_date) if r.end_date is not None and not pd.isna(r.end_date) else None
        sel = (idx >= pd.Timestamp(r.start_date_filled)) & ((idx < e) if e is not None else True)
        M.loc[sel, r.symbol] = True
    info = dict(source="Dmitri's store bars/daily/adjusted (SIP) via desk_data_client.get_daily_bars(allow_api=False); PIT membership universe/sp500_membership.parquet",
                store_version=_store_version(), span=[str(idx[0].date()), str(idx[-1].date())], n_symbols_loaded=len(cols),
                n_excluded_defects=len(bad), excluded_defects=sorted(bad), excluded_defects_source=DATA_ISSUES + " members_without_bars_symbols + SNDK",
                avg_members_per_day=round(float((M & C[cols].notna()).sum(axis=1).mean()), 1),
                delisting_returns="not applied (as in the previous proxy)", status=DEFECT_LABEL)
    return C, O, V, M, info

def masked_z(X, mask):
    """Vectorised zscore_row over the PIT members only (same formula: mean/std(ddof=1), clip +-3, non-members / NaN -> 0)."""
    X = X.where(mask)
    z = X.sub(X.mean(axis=1), axis=0).div(X.std(axis=1).replace(0, np.nan), axis=0).clip(-3, 3)
    return z.fillna(0.0)

def sleeve_vol_scaling(proxy_src, cutoff, names, sleeve_sw, window=126, sigma_target=None, rule="limits", min_days=756, proxy_path=None):
    """Per-sleeve m = min(1, sigma_target / sigma_hat_126d) from the sleeve's backtest-proxy daily returns.
    sigma_target (LIMITS §5 T12, rule='limits'): expanding median of the rolling 126d realised vol once >= min_days
    (3y) of proxy history, else the proxy's full-sample vol. rule='fullsample' = v0.5 behaviour."""
    pinfo = None
    if proxy_src == "store_pit":       # production (CIO 2026-10-30 ~02:12): PIT S&P 500 from Dmitri's store, defects excluded
        Cp, Op, Vp, Mp, pinfo = load_store_pit(cutoff)
        alpha_names = list(Mp.columns)
        sigp = signals_panel(Cp, Op, Vp)
        R = Cp.pct_change(fill_method=None)
        Mv = Mp & Cp[alpha_names].notna()
        zf = lambda k: masked_z(sigp[k][alpha_names], Mv)
    elif proxy_src == "statarb":       # TESTS / AUDIT ONLY: Dave's deprecated IEX file via an explicit --proxy_path
        if not proxy_path: raise SystemExit("--proxy_src statarb needs an explicit --proxy_path (Dave's file is deprecated; tests/audit only, never production)")
        if not os.path.exists(proxy_path): raise SystemExit(f"sleeve proxy bars not found: {proxy_path}; no targets written")
        Cp, Op, Vp = load_bars(proxy_path, cutoff)
        if HEDGE not in Cp.columns: raise SystemExit(f"proxy source {proxy_src} lacks {HEDGE}")
        keep = [c for c in Cp.columns if c in names or c == HEDGE]
        Cp, Op, Vp = Cp[keep], Op[keep], Vp[keep]
        Cp = Cp.loc[Cp.notna().mean(axis=1) >= 0.5]; Op, Vp = Op.loc[Cp.index], Vp.loc[Cp.index]
        sigp = signals_panel(Cp, Op, Vp)
        R = Cp.pct_change()
        alpha_names = [c for c in Cp.columns if c != HEDGE]
        zf = lambda k: sigp[k][alpha_names].apply(zscore_row, axis=1).fillna(0)
        pinfo = dict(source=f"{proxy_path} (Dave's deprecated IEX bars; TEST/AUDIT ONLY)", status="NOT FOR PRODUCTION")
    else:
        raise SystemExit(f"unknown --proxy_src {proxy_src}")
    DATA_PROVENANCE["sleeve_proxy"] = dict(pinfo, proxy_src=proxy_src)
    out = {}
    for sl in sorted(set(SLEEVE_OF.values())):
        ks = [k for k in SLEEVE_OF if SLEEVE_OF[k] == sl]
        Zs = sum(zf(k) for k in ks) / len(ks)
        W = Zs.sub(Zs.mean(axis=1), axis=0); W = W.div(W.abs().sum(axis=1).replace(0, np.nan), axis=0)
        r = (W.shift(1) * R[alpha_names]).sum(axis=1, min_count=1)
        r = r[W.shift(1).abs().sum(axis=1) > 0].dropna()
        lr = float(r.std() * math.sqrt(252)) if len(r) > 20 else float("nan")
        rv = float(r.iloc[-window:].std() * math.sqrt(252)) if len(r) >= window else float("nan")
        tgt_rule, tsrc = sigma_target_rule(r, window, rule, min_days)
        tgt = (sigma_target or {}).get(sl, tgt_rule)
        if np.isnan(rv) or np.isnan(tgt) or rv <= 0:
            m, note = 1.0, f"insufficient proxy history ({len(r)} days < {window}); m=1 (no scale-up possible anyway)"
        else:
            m, note = min(1.0, tgt / rv), "ok"
        out[sl] = dict(signals=ks, sleeve_signal_weight=round(sum(sleeve_sw.get(k, 0) for k in ks), 4),
                       proxy_src=proxy_src, proxy_status=(pinfo or {}).get("status"), proxy_days=int(len(r)), proxy_start=str(r.index[0].date()) if len(r) else None,
                       proxy_end=str(r.index[-1].date()) if len(r) else None,
                       sigma_hat_126d=round(rv, 4), sigma_target=round(float(tgt), 4),
                       sigma_target_source="CLI --sigma_target" if (sigma_target or {}).get(sl) is not None else tsrc,
                       sigma_full_sample=round(lr, 4), sigma_target_rule_value=round(tgt_rule, 4),
                       t13_alert=bool(tgt and not np.isnan(rv) and rv / tgt > 1.5),
                       ratio_sigma_hat_over_target=round(rv / tgt, 3) if tgt and not np.isnan(rv) else None,
                       m=round(float(m), 4), overlay="sleeve 126d vol scaling (LIMITS.md §5) - the only vol overlay", note=note)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="label written to targets asof (default: asof_bar_cutoff)")
    ap.add_argument("--asof_bar_cutoff", default=None, help="drop bars on/after this date (partial live session). Default: ET date of --now; if before 09:30 ET, the previous NYSE session")
    ap.add_argument("--equity", type=float, default=None, help="default: last row of performance/history.csv")
    ap.add_argument("--vol_target", type=float, default=0.06, help="ex-ante annualised vol cap")
    ap.add_argument("--tc_bps", type=float, default=10.0, help="one-way cost (spread+slippage), bps of notional")
    ap.add_argument("--hold_periods", type=float, default=4.0, help="expected holding in 5d periods (TC amortisation)")
    ap.add_argument("--atr_mult", type=float, default=2.0)
    ap.add_argument("--max_pos", type=float, default=0.095)   # limit 10%, 0.5% buffer for price drift
    ap.add_argument("--max_risk", type=float, default=0.0095) # limit 1%
    ap.add_argument("--max_gross", type=float, default=0.58)  # limit 60%
    ap.add_argument("--beta_tol", type=float, default=0.01, help="optimiser tol; post-rounding check uses 0.02")
    ap.add_argument("--sector_gross", type=float, default=0.20)
    ap.add_argument("--sector_net", type=float, default=0.10)
    ap.add_argument("--min_w", type=float, default=0.01)
    ap.add_argument("--band", type=float, default=0.01, help="no-trade band (weight) for held positions")
    ap.add_argument("--long_only", action="store_true")
    ap.add_argument("--ic_floor", type=float, default=0.02, help="composite IC used in fallback mode")
    ap.add_argument("--blackout", default="AMZN,INTC,XOM,CVX", help="no new/increased risk (earnings per trade_log.md)")
    ap.add_argument("--fallback", choices=["derisk", "full"], default="derisk",
                    help="no validated signal: 'derisk' (CIO policy) = shadow book + de-risk-only tradable file")
    ap.add_argument("--victor_passed", default="", help="comma list of signal keys with Victor PASS/COND PASS (none as of 2026-10-30)")
    ap.add_argument("--gp_ell", type=float, default=None, help="Garleanu-Pedersen lambda/gamma; enables GP aim + partial trading (off by default)")
    ap.add_argument("--gp_rate", type=float, default=None, help="override GP trade rate tau in (0,1]")
    ap.add_argument("--gp_rho", type=float, default=0.0, help="GP per-period discount rate rho")
    ap.add_argument("--outdir", default=f"{ROOT}/portfolio")
    ap.add_argument("--cost_model", choices=["tca", "flat"], default="tca",
                    help="tca = tca/baseline_report.md §5 per-side model: HS + k*sigma*sqrt(Q/ADV) + H (+ borrow on shorts); flat = --tc_bps")
    ap.add_argument("--tca_k", type=float, default=0.75, help="impact coefficient k (baseline_report §5 ASSUMPTION; cost_model.md uses 1.0)")
    ap.add_argument("--tca_clip", type=float, default=0.05, help="typical trade size Q as fraction of equity for the impact term")
    ap.add_argument("--borrow_bps_yr", type=float, default=25.0, help="ETB borrow on short MV, bps/yr (tca/cost_model.md §4 ASSUMPTION; Alpaca paper charges none)")
    ap.add_argument("--shrinkage", choices=["lw", "fixed"], default="lw", help="covariance shrinkage to constant correlation: lw = Ledoit-Wolf 2004 optimal intensity (default); fixed = --shrink_delta")
    ap.add_argument("--shrink_delta", type=float, default=0.5, help="fixed shrinkage intensity when --shrinkage fixed (v2 = 0.5)")
    ap.add_argument("--risk_inflation", type=float, default=1.25, help="risk-forecast inflation k: ex-ante vol in the 6%% cap = k * sqrt(w'Sw). Source: walk-forward bias 1.15-1.37 (MV on Dave's bars), MV-LW 1.20")
    ap.add_argument("--run_ts", default=None, help="override the run timestamp (ISO, SGT) used in file names and the log (tests only)")
    ap.add_argument("--no_latest", action="store_true", help="do not update the non-authoritative latest.json symlinks")
    ap.add_argument("--positions", default=f"{ROOT}/positions.json", help="positions file (list of Alpaca position dicts)")
    ap.add_argument("--equity_source", default=None, help="label for --equity provenance")
    ap.add_argument("--panic_path", default=f"{ROOT}/risk/state/panic_flag.json", help="Risk panic flag (read-only; FAIL-SAFE = panic ON)")
    ap.add_argument("--breaker_path", default=f"{ROOT}/risk/state/breaker_state.json", help="Risk breaker state (read-only; FAIL-SAFE = HALVED 30%%)")
    ap.add_argument("--state_max_age_days", type=int, default=1, help="max age of state files in US trading days")
    ap.add_argument("--now", default=None, help="ISO time for staleness checks (default: now, SGT)")
    ap.add_argument("--proxy_src", choices=["store_pit", "statarb"], default="store_pit", help="sleeve backtest proxy: store_pit = PIT S&P 500 from Dmitri's SIP store, Victor's defect names + SNDK excluded (PROVISIONAL; production); statarb = Dave's deprecated IEX file via --proxy_path (tests/audit only)")
    ap.add_argument("--proxy_path", default=None, help="bars file for --proxy_src statarb (tests/audit only)")
    ap.add_argument("--live_source", choices=["client", "offline_test"], default="client", help="today's partial row: client = SIP intraday via desk_data_client (production); offline_test = no API, placeholder row (tests only)")
    ap.add_argument("--vol_window", type=int, default=126, help="realised-vol window for sleeve m (LIMITS.md §5)")
    ap.add_argument("--sigma_target", default="", help="per-sleeve target vol, e.g. 'momentum=0.10,trend=0.08' (default: proxy long-run vol)")
    ap.add_argument("--sigma_target_rule", choices=["limits", "fullsample"], default="limits", help="limits = LIMITS §5 T12 (expanding median of 126d vol once >= 3y proxy, else full-sample vol); fullsample = v0.5")
    ap.add_argument("--sigma_min_days", type=int, default=756, help="proxy days needed for the expanding-median rule (3y x 252)")
    ap.add_argument("--panic_provisional", choices=["context", "apply"], default="context",
                    help="only for a flag file that still carries a provisional marker: context = report only, §3 responses not applied; apply = apply anyway. A FINAL flag (no marker, since 02:27 SGT) is always binding; fail-safe panic is always applied.")
    ap.add_argument("--earnings_dir", default=f"{ROOT}/data/earnings", help="Dmitri's earnings calendar (read-only)")
    ap.add_argument("--earn_horizon_sessions", type=int, default=6, help="holding horizon after the execution session (5d book + 1 session slack)")
    ap.add_argument("--earnings_hold_exceptions", default="", help="comma list of LONGS with a logged CIO exception to hold through earnings (LIMITS H7); never shorts")
    ap.add_argument("--earn_max_age_days", type=int, default=1, help="calendar freshness (US trading days since fetched_at_utc)")
    ap.add_argument("--earnings_policy", choices=list(eg.POLICIES), default=eg.POLICY_RULING,
                    help="risk_ruling_20261030_0227 (default; Risk decisions-log 02:27) or strict (pre-ruling: estimated dates = unknown)")
    ap.add_argument("--next_earnings_dir", default=eg.NEXT_DIR, help="Dmitri's next_earnings sidecar dir; newest next_earnings_*.parquet is used")
    ap.add_argument("--next_earnings_file", default="", help="explicit sidecar file (tests); overrides the newest-file search")
    a = ap.parse_args()
    # Resolve asof_bar_cutoff (partial/live session date). Post-close / pre-open runs use the prior NYSE session.
    if a.asof_bar_cutoff is None:
        _now = dt.datetime.fromisoformat(a.now) if a.now else dt.datetime.now(SGT)
        if _now.tzinfo is None: _now = _now.replace(tzinfo=SGT)
        _et = _now.astimezone(ET)
        _d = _et.date()
        if _et.time() < dt.time(9, 30):
            _d = _d - dt.timedelta(days=1)
            while _d.weekday() >= 5 or _d in NYSE_HOLIDAYS:  # skip weekends/holidays (same set as risk_state)
                _d = _d - dt.timedelta(days=1)
        elif _d.weekday() >= 5 or _d in NYSE_HOLIDAYS:
            while _d.weekday() >= 5 or _d in NYSE_HOLIDAYS:
                _d = _d - dt.timedelta(days=1)
        a.asof_bar_cutoff = _d.isoformat()
    if a.date is None:
        a.date = str(a.asof_bar_cutoff)
    gp_on = a.gp_ell is not None or a.gp_rate is not None

    if a.equity is None:
        rows = list(csv.DictReader(open(f"{ROOT}/performance/history.csv")))
        a.equity = float(rows[-1]["equity"]); eq_src = f"performance/history.csv {rows[-1]['date_sgt']}"
    else: eq_src = a.equity_source or "CLI"
    E = a.equity
    C, Hh, L, O, V, last, last_ts, live, live_t = load(a)
    # extended frames = complete bars + today's live row (used ONLY for the live signal cross-section)
    Cx, Ox, Vx = C.copy(), O.copy(), V.copy()
    for F in (Cx, Ox, Vx): F.loc[live_t] = np.nan
    for s_, b in live.items():
        if s_ in Cx.columns: Cx.loc[live_t, s_] = last[s_]; Ox.loc[live_t, s_] = b["o"]; Vx.loc[live_t, s_] = b["v"]
    pos = {p["symbol"]: p for p in json.load(open(a.positions))}
    bad_pos = [s_ for s_ in pos if excluded_asset(s_)]
    if bad_pos: raise SystemExit(f"HARD EXCLUSION: excluded (crypto) symbols in positions file: {bad_pos}; refusing to build targets")
    # ---- Risk state files (read-only, FAIL-SAFE) ----
    now = dt.datetime.fromisoformat(a.now) if a.now else None
    if now is not None and now.tzinfo is None: now = now.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    PANIC = read_panic(a.panic_path, now, a.state_max_age_days)
    BRKR = read_breaker(a.breaker_path, now, a.state_max_age_days)
    # LIMITS §3: FINAL flag (no provisional marker) = BINDING; a file still marked provisional = context only; fail-safe always applied.
    # §3 responses come from the file (multiplier, momentum short notional multiplier, new_loser_shorts_allowed, net_beta_floor);
    # hard-coded 0.5 / False / -0.10 are fail-safe defaults only (risk_state.read_panic). T8 responses: t8_status pending_validation.
    panic_prov = bool(PANIC.get("provisional")) and not PANIC["fail_safe"]
    PANIC_ON = bool(PANIC["panic"]) and (PANIC["fail_safe"] or not panic_prov or a.panic_provisional == "apply")
    PANIC.update(provisional_mode=a.panic_provisional, panic_provisional=panic_prov, applied=PANIC_ON,
                 treatment=("FAIL-SAFE panic ON applied (file missing/stale/invalid)" if PANIC["fail_safe"] else
                            (f"PROVISIONAL flag: read and logged; §3 responses {'APPLIED (--panic_provisional apply)' if a.panic_provisional == 'apply' else 'NOT applied (LIMITS §3: context only, not binding)'}" if panic_prov else "binding flag (no provisional marker): applied if ON")))
    # LIMITS §2b: RESUMED_DISARMED re-halts if live equity <= backstop (also checked against this run's equity)
    # LIMITS T4 (v0.3.5 change log): backstop_equity = Risk's current EPISODE backstop (never recomputed, no inferred lift); tighten-only re-check vs run equity
    if BRKR["state"] != "HALTED" and BRKR.get("backstop_equity") and E <= BRKR["backstop_equity"]:
        BRKR = dict(BRKR, state="HALTED", new_trades_allowed=False, reason=f"{BRKR['state_in_file']} and run equity {E} <= episode backstop_equity {BRKR['backstop_equity']}: treated as HALTED (LIMITS §2b / v0.3.2) until Risk updates the file")
    gross_cap = BRKR["gross_cap_pct"] / 100.0
    gross_buf = min(a.max_gross, gross_cap - 0.01)        # 58% at 60% cap; 29% at 30% cap (LIMITS.md §2a buffer)
    halted = not BRKR["new_trades_allowed"]
    global BRK
    BRK = {}   # live protective stop legs from orders_status.json
    for o in json.load(open(f"{ROOT}/orders_status.json")):
        for lg in (o.get("legs") or []):
            if lg.get("stop_price") and lg.get("status") not in ("canceled", "filled", "expired"):
                BRK[lg["symbol"]] = float(lg["stop_price"])

    sig = signals_panel(C, O, V)          # history (complete bars) -> IC study
    sigx = signals_panel(Cx, Ox, Vx)      # live cross-section
    # PEAD on today's partial bar: |gap|>4% and partial-session volume already >= 1.0x 20d avg (proxy for 1.8x full-day)
    g_live = Ox.loc[live_t] / C.iloc[-1] - 1; vr_live = Vx.loc[live_t] / V.iloc[-20:].mean()
    ev_live = g_live.where((g_live.abs() > 0.04) & (vr_live >= 1.0))
    sigx["PEAD"].loc[live_t] = ev_live.combine_first(sigx["PEAD"].loc[live_t])
    alpha_univ = [s for s in C.columns if s not in NON_ALPHA]
    keys = ["MOM_12_1", "RS63", "TREND", "REV5", "PEAD"]
    stats, series = ic_study(sig, C, alpha_univ)
    sw, mode, passed, ic_shr, sigcorr = signal_weights(stats, series, keys)
    vp = [x.strip() for x in a.victor_passed.split(",") if x.strip()]
    validated = [k for k in passed if k in vp]
    fallback_derisk = ((not validated) and a.fallback == "derisk") or halted   # HALTED -> de-risk only regardless
    gp = None
    if gp_on:
        phi = signal_decay({k: sig[k] for k in keys}, alpha_univ)
        a_g, tau = gp_params(a.gp_ell, a.gp_rho) if a.gp_ell is not None else (0.0, 1.0)
        if a.gp_rate is not None: tau = a.gp_rate
        mult = {k: 1.0 / (1.0 + phi[k] * a_g) for k in keys}
        sw0 = dict(sw); tot = sum(sw[k] * mult[k] for k in keys)
        sw = {k: sw[k] * mult[k] / tot for k in keys} if tot > 0 else sw
        gp = dict(ell=a.gp_ell, rho=a.gp_rho, a_over_gamma=round(a_g, 4), trade_rate_tau=round(tau, 4),
                  phi_5d={k: round(v, 3) for k, v in phi.items()}, aim_multiplier={k: round(v, 3) for k, v in mult.items()},
                  signal_weights_before={k: round(v, 4) for k, v in sw0.items()})

    t = C.index[-1]
    Z = pd.DataFrame({k: zscore_row(sigx[k].loc[live_t, alpha_univ]) for k in keys}).fillna(0)
    live_gaps = {s_: round(float(g_live[s_]) * 100, 1) for s_ in ev_live.dropna().index}
    # sleeve weights -> vol-scaling multiplier m (per sleeve) -> panic multiplier (momentum, trend)
    sig_t = {}
    for kv in [x for x in a.sigma_target.split(",") if x.strip()]:
        k_, v_ = kv.split("="); sig_t[k_.strip()] = float(v_)
    VS = sleeve_vol_scaling(a.proxy_src, a.asof_bar_cutoff, set(alpha_univ), sw, a.vol_window, sig_t, a.sigma_target_rule, a.sigma_min_days, a.proxy_path)
    pf = PANIC["multiplier_momentum_trend"] if PANIC_ON else 1.0
    sleeve_mult = {sl: dict(m=v["m"], panic_factor=(pf if sl in PANIC_SLEEVES else 1.0)) for sl, v in VS.items()}
    for sl in sleeve_mult: sleeve_mult[sl]["total"] = round(sleeve_mult[sl]["m"] * sleeve_mult[sl]["panic_factor"], 4)
    comp_base = sum(sw[k] * Z[k] for k in keys)
    mu_b, sd_b = comp_base.mean(), comp_base.std()
    comp_scaled = sum(sw[k] * sleeve_mult[SLEEVE_OF[k]]["total"] * Z[k] for k in keys)
    comp = ((comp_scaled - mu_b) / sd_b).clip(-3, 3) if sd_b else comp_scaled * 0   # m=1, panic off -> identical to v2
    ic_c = sum(sw[k] * ic_shr[k] for k in keys) if passed else a.ic_floor
    ic_c = max(ic_c, a.ic_floor) if passed else a.ic_floor

    # risk model: 120d daily returns, cov shrunk 50% to constant correlation; beta vs SPY (Blume-adjusted)
    univ = alpha_univ + [HEDGE]
    R = C[univ].pct_change().iloc[-120:].dropna(axis=1)
    univ = [s for s in univ if s in R.columns]; alpha_univ = [s for s in alpha_univ if s in univ]
    Sig_d, rbar, shrink_delta = shrunk_cov(R[univ], a.shrinkage, a.shrink_delta)
    Sig_cap = Sig_d * 252 * a.risk_inflation ** 2      # ex-ante covariance used ONLY in the 6% book vol cap
    sd_d = np.sqrt(np.diag(Sig_d))
    beta_raw = (R[univ].apply(lambda x: x.cov(R[HEDGE])) / R[HEDGE].var()).values
    beta = 0.67 * beta_raw + 0.33
    tr = pd.concat([Hh - L, (Hh - C.shift(1)).abs(), (L - C.shift(1)).abs()], axis=1, keys=["a", "b", "c"]).T.groupby(level=1).max().T
    atr = tr[univ].iloc[-14:].mean()
    px = pd.Series({s: last.get(s, C[s].iloc[-1]) for s in univ})
    stop_pct = (a.atr_mult * atr / px).values
    alpha = np.array([ic_c * sd_d[i] * math.sqrt(5) * comp.get(s, 0.0) if s in alpha_univ else 0.0 for i, s in enumerate(univ)])

    w0 = np.array([float(pos[s]["market_value"]) / E if s in pos else 0.0 for s in univ])
    n = len(univ); w = cp.Variable(n)
    cap = np.minimum(a.max_pos, a.max_risk / stop_pct)
    Sig5 = Sig_d * 5; Sig5 = (Sig5 + Sig5.T) / 2
    if not passed:   # fallback: alpha is unvalidated -> charge full round-trip cost up front (no amortisation)
        a.hold_periods = 1.0
    # per-name one-way cost (fraction of notional)
    TCA_BUCKETS = [(1e9, 2.75, 2.0, "L1 mega"), (2e8, 5.0, 4.0, "L2 large"), (5e7, 12.0, 8.0, "L3 mid"), (0, 30.0, 15.0, "L4 small")]  # baseline_report §5
    hs_meas = {}
    try:
        for r_ in csv.DictReader(open(f"{ROOT}/tca/fills_20261030.csv")):
            if r_.get("half_spread_bps") not in (None, ""): hs_meas.setdefault(r_["symbol"], []).append(float(r_["half_spread_bps"]))
    except FileNotFoundError: pass
    hs_meas = {k: float(np.mean(v)) for k, v in hs_meas.items()}
    # Volumes are SIP (Dmitri's store, rule #5): ADV20 from the store; the TCA file's measured SIP ADV20 overrides
    # where present. The old IEX->SIP scaling ratio is no longer needed (fixed at 1.0).
    adv_iex = (C[univ] * V[univ]).iloc[-20:].mean()   # name kept for diff clarity: this is SIP ADV20 now
    adv_sip = {}
    try:
        for r_ in csv.DictReader(open(f"{ROOT}/tca/fills_20261030.csv")):
            if r_.get("adv20_usd") not in (None, ""): adv_sip[r_["symbol"]] = float(r_["adv20_usd"])
    except FileNotFoundError: pass
    ratios = [adv_sip[k] / adv_iex[k] for k in adv_sip if k in adv_iex.index and adv_iex[k] > 0]
    sip_iex_ratio = 1.0   # store volumes are SIP; median TCA/store ratio reported in data_provenance only
    DATA_PROVENANCE["adv"] = dict(source="SIP ADV20 from Dmitri's store (TCA-file ADV20 where measured)", median_tca_over_store_ratio=round(float(np.median(ratios)), 3) if ratios else None, n=len(ratios))
    adv_usd = pd.Series({s: adv_sip.get(s, adv_iex[s] * sip_iex_ratio) for s in univ})
    sig20 = C[univ].pct_change().iloc[-20:].std()
    cost_bps, cost_src = np.zeros(n), {}
    for i, s in enumerate(univ):
        if a.cost_model == "flat":
            cost_bps[i] = a.tc_bps; continue
        hs_def, hcut, bname = next((h, c_, nm) for lo, h, c_, nm in TCA_BUCKETS if adv_usd[s] > lo)
        hs = hs_meas.get(s, hs_def)
        imp = a.tca_k * sig20[s] * math.sqrt(a.tca_clip * E / adv_usd[s]) * 1e4 if adv_usd[s] > 0 else 0.0
        cost_bps[i] = hs + imp + hcut
        cost_src[s] = dict(adv20_usd_m=round(adv_usd[s] / 1e6, 1), adv_source="SIP (TCA file)" if s in adv_sip else "SIP ADV20 (Dmitri's store)", bucket=bname, hs_bps=round(hs, 2), hs_source="measured pilot fill" if s in hs_meas else "bucket default",
                           impact_bps=round(imp, 2), haircut_bps=hcut, per_side_bps=round(cost_bps[i], 2))
    tc_vec = cost_bps / 1e4 / a.hold_periods
    borrow = (a.borrow_bps_yr / 1e4) * (7.0 / 360.0) if a.cost_model == "tca" else 0.0   # per 5-trading-day period (~7 calendar days)
    cons = [cp.abs(w) <= cap, cp.norm1(w) <= gross_buf, cp.abs(beta @ w) <= a.beta_tol,
            cp.quad_form(w, cp.psd_wrap(Sig_cap)) <= a.vol_target ** 2]   # 6% ex-ante vol (x risk_inflation): CONSTRAINT, not a scaler
    loser, mom_short_cut = set(), {}
    if PANIC_ON:   # LIMITS.md §3 responses, values from Risk's file (fail-safe defaults otherwise); only when applied
        mt = [k for k in keys if SLEEVE_OF[k] in PANIC_SLEEVES]          # all momentum/trend signals, whatever today's weight
        mom_k = [k for k in keys if SLEEVE_OF[k] == "momentum"]
        if not PANIC["new_loser_shorts_allowed"]:
            loser = {s_ for s_ in alpha_univ if any(Z.loc[s_, k] < 0 for k in mt)}
            for i_, s_ in enumerate(univ):
                if s_ in loser: cons.append(w[i_] >= min(0.0, w0[i_]))   # no new short / no larger short
        msm = PANIC["momentum_short_notional_multiplier"]
        if msm < 1:   # held momentum shorts (negative z on a momentum-sleeve signal) cut to <= msm x current notional
            for i_, s_ in enumerate(univ):
                if w0[i_] < 0 and s_ in alpha_univ and any(Z.loc[s_, k] < 0 for k in mom_k):
                    cons.append(w[i_] >= msm * w0[i_]); mom_short_cut[s_] = msm
        if PANIC["net_beta_floor"] is not None: cons.append(beta @ w >= PANIC["net_beta_floor"])
    if a.long_only: cons.append(w[[i for i, s in enumerate(univ) if s != HEDGE]] >= 0)
    for sec in set(SECTOR.get(s, "Other") for s in univ):
        ix = [i for i, s in enumerate(univ) if SECTOR.get(s, "Other") == sec and s != HEDGE]
        if ix: cons += [cp.norm1(w[ix]) <= a.sector_gross, cp.abs(cp.sum(w[ix])) <= a.sector_net]
    bl = [s.strip() for s in a.blackout.split(",") if s.strip()]
    for s in bl:   # earnings blackout: may reduce toward 0, may not add risk
        if s in univ:
            i = univ.index(s); cons += [cp.abs(w[i]) <= abs(w0[i])]
            if w0[i] >= 0: cons.append(w[i] >= 0)
            else: cons.append(w[i] <= 0)
    # ---- LIMITS H7 earnings gate (earnings_gate.py; Dmitri's calendar, read-only) ----
    try:
        import pandas as _pd
        _u = _pd.read_parquet(f"{ROOT}/data/universe/universe.parquet", columns=["symbol", "role"])
        etf_roles = set(_u.loc[_u["role"] == "etf", "symbol"])
    except Exception:  # noqa
        etf_roles = set()
    ETFS = set(NON_ALPHA) | {s_ for s_ in univ if SECTOR.get(s_) and s_.startswith("XL")} | {"SMH"} | etf_roles
    now_eg = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    ev_, einfo_ = eg.load_calendar(now_eg, a.earnings_dir, a.earn_max_age_days)
    exc = [x.strip() for x in a.earnings_hold_exceptions.split(",") if x.strip()]
    nx_, ninfo_ = eg.load_next(now_eg, a.next_earnings_dir, a.next_earnings_file or None, a.earn_max_age_days)
    EG, EINFO = eg.gate_policy(univ, now_eg, a.earn_horizon_sessions, ETFS, exc, events=ev_, info=einfo_, nxt=nx_, ninfo=ninfo_, policy=a.earnings_policy)
    exe_s = EINFO["execution_session"]
    for i_, s_ in enumerate(univ):
        g_ = EG[s_]
        if g_["in_window"]:
            # never held through own release: closed now if exit_by is today (shorts always; longs unless CIO exception), else no add
            if eg.close_by_for(g_, np.sign(w0[i_])) <= exe_s and not (w0[i_] > 0 and g_.get("long_exception")):
                cons.append(w[i_] == 0)
            else:
                cons += [w[i_] >= min(0.0, w0[i_]), w[i_] <= max(0.0, w0[i_])]   # no new / no increase either side
    UNK = [s_ for s_ in univ if EG[s_]["unknown"]]
    tradable_is_optimiser = not fallback_derisk   # FULL mode: the optimiser output IS the tradable book
    if tradable_is_optimiser:   # FAIL-SAFE: unknown next date -> no new / increased short in the TRADABLE book
        for i_, s_ in enumerate(univ):
            if s_ in UNK: cons.append(w[i_] >= min(0.0, w0[i_]))
    obj = cp.Maximize(alpha @ w - tc_vec @ cp.abs(w - w0) - borrow * cp.sum(cp.neg(w[[i for i, s in enumerate(univ)]])))
    fixed0 = []
    for it in range(4):   # drop dust positions (< min_w) and re-solve
        prob = cp.Problem(obj, cons + ([w[fixed0] == 0] if fixed0 else []))
        prob.solve(solver="CLARABEL")
        wv = np.array(w.value).ravel()
        new0 = [i for i in range(n) if abs(wv[i]) < a.min_w and abs(w0[i]) < 1e-9 and i not in fixed0]
        if not new0: break
        fixed0 += new0
    w_star = wv.copy()
    if gp_on:   # GP Prop. 2: trade a fraction tau toward the aim (convex combo of w0 and w*)
        wv = w0 + gp["trade_rate_tau"] * (wv - w0)
    # integer shares (round toward zero so caps hold)
    def stop_for(s, tgt, cur):
        sd = a.atr_mult * atr[s]
        stop = round(px[s] - sd if tgt > 0 else px[s] + sd, 2)
        if cur and np.sign(cur) == np.sign(tgt) and s in BRK:   # never loosen a live stop
            stop = round(min(BRK[s], stop) if tgt < 0 else max(BRK[s], stop), 2)
        return stop
    def within_limits(s, q):
        st = stop_for(s, q, q)
        return abs(q) * px[s] <= a.max_pos * E and abs(q) * abs(px[s] - st) <= a.max_risk * E
    shares = {}
    for i, s in enumerate(univ):
        cur = int(float(pos[s]["qty"])) if s in pos else 0
        tgt = int(math.trunc(wv[i] * E / px[s]))
        if abs(wv[i]) < a.min_w / 2 and cur == 0: tgt = 0
        # no-trade band: keep a held position if the change is < band and it still meets the HARD limits
        if cur and tgt and np.sign(tgt) == np.sign(cur) and abs(tgt - cur) * px[s] / E < a.band:
            if within_limits(s, cur): tgt = cur   # band only inside the buffered limits
        shares[s] = tgt
    # post-rounding beta hedge with SPY (whole shares) if it keeps gross within the buffer
    bvec = dict(zip(univ, beta))
    resid = sum(shares[s] * px[s] / E * bvec[s] for s in univ if s != HEDGE)
    h = int(round(-resid * E / px[HEDGE]))
    gross_ex = sum(abs(shares[s]) * px[s] for s in univ if s != HEDGE) / E
    if h and gross_ex + abs(h) * px[HEDGE] / E <= min(gross_buf + 0.015, gross_cap - 0.005):
        shares[HEDGE] = h
    # integer-rounding beta repair (02:3x fix): whole-share truncation of high-priced names can push book beta past
    # the optimiser's |beta| <= beta_tol, and the SPY hedge may not fit under the gross cap. Then REDUCE-ONLY repair:
    # trim the largest beta contributor on the offending side one share at a time (toward zero, never past the current
    # position's sign, never opening/increasing anything) until |beta| <= beta_tol, re-trying the SPY hedge each step.
    rounding_repair = {}
    def _bk(): return sum(shares[s_] * px[s_] / E * bvec[s_] for s_ in univ)
    for _ in range(500):
        b_ = _bk()
        if abs(b_) <= a.beta_tol: break
        resid_x = sum(shares[s_] * px[s_] / E * bvec[s_] for s_ in univ if s_ != HEDGE)
        h2 = int(round(-resid_x * E / px[HEDGE]))
        g2 = sum(abs(shares[s_]) * px[s_] for s_ in univ if s_ != HEDGE) / E
        if g2 + abs(h2) * px[HEDGE] / E <= min(gross_buf + 0.015, gross_cap - 0.005):
            shares[HEDGE] = h2
            if abs(_bk()) <= a.beta_tol: break
        contrib = [s_ for s_ in univ if s_ != HEDGE and shares[s_] and np.sign(shares[s_] * bvec[s_]) == np.sign(b_)]
        if not contrib: break
        s_ = max(contrib, key=lambda x: abs(shares[x] * px[x] * bvec[x]))
        shares[s_] -= int(np.sign(shares[s_])); rounding_repair[s_] = rounding_repair.get(s_, 0) + 1
    bl = [s.strip() for s in a.blackout.split(",") if s.strip()]

    # ---- DE-RISK-ONLY tradable book (fallback policy): only trim / close / cover existing positions ----
    derisk_note = {}
    def derisk(shadow):
        out_sh = {s: 0 for s in univ}
        for s in univ:
            cur = int(float(pos[s]["qty"])) if s in pos else 0
            if not cur: continue
            t_ = shadow.get(s, 0)
            if t_ == 0 or np.sign(t_) != np.sign(cur):
                tgt, why = 0, "close: shadow book is flat/opposite"
            elif abs(t_) < abs(cur):
                tgt, why = t_, "trim toward shadow book"
                if abs(t_ - cur) * px[s] / E < a.band and within_limits(s, cur): tgt, why = cur, f"hold: trim < {a.band:.0%} no-trade band"
            else:
                tgt, why = cur, "hold: shadow wants >= current; increases not allowed in de-risk mode"
            g_ = EG.get(s, {})
            if tgt and g_.get("in_window") and eg.close_by_for(g_, np.sign(tgt)) <= exe_s and not (tgt > 0 and g_.get("long_exception")):
                tgt, why = 0, why + f"; EARNINGS (H7, {g_.get('kind')}): release {g_['next']} {g_['timing']} -> close by {eg.close_by_for(g_, np.sign(tgt))} (today)"
            while tgt and not within_limits(s, tgt):   # enforce buffered hard limits by trimming only
                tgt -= int(np.sign(tgt)); why += "; trimmed to buffered RM limit"
            out_sh[s] = tgt; derisk_note[s] = why
        # breaker gross cap: trim the largest risk-to-stop positions first until gross <= buffer (LIMITS.md §2a)
        def gross_of(d): return sum(abs(q) * px[x] for x, q in d.items()) / E
        while gross_of(out_sh) > gross_buf + 1e-12:
            s_ = max((x for x in out_sh if out_sh[x]), key=lambda x: abs(out_sh[x]) * abs(px[x] - stop_for(x, out_sh[x], out_sh[x])))
            out_sh[s_] -= int(np.sign(out_sh[s_]))
            if "breaker gross trim" not in derisk_note.get(s_, ""): derisk_note[s_] = derisk_note.get(s_, "") + f"; breaker gross trim to <= {gross_buf:.0%}"
        # panic (LIMITS.md §3, file values): momentum-short cut, then net beta floor by reducing only
        if PANIC_ON:
            for s_, msm_ in mom_short_cut.items():
                cur_ = int(float(pos[s_]["qty"])) if s_ in pos else 0
                lim_ = -int(np.floor(abs(cur_) * msm_))
                if out_sh.get(s_, 0) < lim_:
                    out_sh[s_] = lim_; derisk_note[s_] = derisk_note.get(s_, "") + f"; panic momentum-short cut to x{msm_}"
            bmap = dict(zip(univ, beta))
            def nb(d): return sum(bmap[x] * q * px[x] for x, q in d.items()) / E
            floor_ = PANIC["net_beta_floor"] if PANIC["net_beta_floor"] is not None else -np.inf
            while nb(out_sh) < floor_:
                negs = [x for x in out_sh if out_sh[x] and bmap[x] * out_sh[x] < 0]
                if not negs: break
                s_ = min(negs, key=lambda x: bmap[x] * out_sh[x] * px[x])
                out_sh[s_] -= int(np.sign(out_sh[s_]))
                if "panic beta floor" not in derisk_note.get(s_, ""): derisk_note[s_] = derisk_note.get(s_, "") + f"; reduced for panic net-beta floor {floor_}"
        return out_sh

    def build(shares, derisk_mode=False):
        out = []
        for i, s in enumerate(univ):
            cur = int(float(pos[s]["qty"])) if s in pos else 0
            tgt = shares.get(s, 0)
            if tgt == 0 and cur == 0: continue
            side = "long" if tgt > 0 else ("short" if tgt < 0 else "flat")
            stop = None if tgt == 0 else stop_for(s, tgt, cur)
            risk = abs(tgt) * abs(px[s] - stop) if stop is not None else 0.0
            brk = BRK.get(s) if s in pos else None
            why = []
            if derisk_mode and s in derisk_note: why.append("DE-RISK: " + derisk_note[s])
            if s == HEDGE: why.append(f"beta hedge (beta 1.0); no alpha view")
            else:
                why.append(f"composite z {comp.get(s,0):+.2f} (" + ", ".join(f"{k} {Z.loc[s,k]:+.1f}" for k in keys if sw[k] > 0.01) + ")")
                why.append(f"sector {SECTOR.get(s,'?')}, beta {beta[i]:.2f}, vol {sd_d[i]*math.sqrt(252)*100:.0f}%")
                if s in bl: why.append("earnings blackout: no added risk")
                g_ = EG.get(s, {})
                if g_.get("in_window"): why.append(f"EARNINGS {g_['next']} {g_['timing']} ({g_.get('kind')}): no added risk; exit by {eg.close_by_for(g_, np.sign(tgt))} close" + (" (CIO hold exception)" if g_.get("long_exception") and tgt > 0 else ""))
                elif g_.get("unknown") and tgt < 0: why.append("EARNINGS: next release date UNKNOWN (flag)")
                if not derisk_mode:
                    if abs(abs(wv[i]) - cap[i]) < 1e-3: why.append("at position/risk cap")
                    if cur and tgt == cur: why.append(f"held: change < {a.band:.0%} no-trade band")
                    if cur and tgt == 0: why.append("exit: optimiser assigns ~0 weight after cost")
            if s in rounding_repair and not derisk_mode: why.append(f"trimmed {rounding_repair[s]} sh (integer-rounding beta repair, reduce-only)")
            stop_action = None
            if stop is not None and brk is not None and cur and np.sign(cur) == np.sign(tgt):
                stop_action = "keep" if abs(stop - brk) < 0.005 else "tighten"
            elif stop is not None: stop_action = "new"
            out.append(dict(symbol=s, side=side, target_shares=tgt, target_weight=round(tgt * px[s] / E, 4),
                            current_shares=cur, delta_trade=tgt - cur, ref_price=round(float(px[s]), 2),
                            price_ts_utc=last_ts.get(s), atr14=round(float(atr[s]), 2), stop_price=stop, stop_action=stop_action,
                            stop_rule=f"{a.atr_mult}x ATR(14) from ref price" + ("; tighter of that and live broker stop" if s in BRK and cur and tgt and np.sign(cur)==np.sign(tgt) else ""),
                            existing_broker_stop=brk, est_risk_usd=round(float(risk), 2),
                            est_risk_pct_equity=round(float(risk) / E * 100, 3),
                            beta=round(float(beta[i]), 2), sector=SECTOR.get(s, "Other"),
                            next_earnings=EG.get(s, {}).get("next"), earnings_timing=EG.get(s, {}).get("timing"),
                            earnings_status=EG.get(s, {}).get("kind"),
                            exit_by=(eg.close_by_for(EG[s], np.sign(tgt)) if EG.get(s, {}).get("in_window") and tgt and not (tgt > 0 and EG[s].get("long_exception")) else None),
                            rationale="; ".join(why)))
        out.sort(key=lambda r: -abs(r["target_weight"]))
        wf = np.zeros(n)
        for r in out: wf[univ.index(r["symbol"])] = r["target_weight"]
        turn = float(np.abs(wf - w0).sum())
        secs = {}
        for r in out:
            if r["symbol"] == HEDGE or r["target_shares"] == 0: continue
            g = secs.setdefault(r["sector"], [0, 0]); g[0] += abs(r["target_weight"]); g[1] += r["target_weight"]
        checks = []
        def chk(name, thr, val, ok, info=False): checks.append(dict(limit=name, threshold=thr, value=val, status=("PASS" if ok else ("INFO" if info else "FAIL"))))
        live = [r for r in out if r["target_shares"]]
        _z = dict(symbol="(flat book)", target_weight=0.0, est_risk_usd=0.0)
        mx = max(out, key=lambda r: abs(r["target_weight"]), default=_z)
        chk("Max notional per position", "<=10% equity", f"{abs(mx['target_weight'])*100:.2f}% ({mx['symbol']})", abs(mx["target_weight"]) <= 0.10)
        mr = max(out, key=lambda r: r["est_risk_usd"], default=_z)
        chk("Max risk per position (shares x stop dist)", f"<=1% equity (${E*0.01:,.2f})", f"${mr['est_risk_usd']:,.2f} ({mr['symbol']})", mr["est_risk_usd"] <= 0.01 * E)
        dg = diag(wf)
        chk("Gross exposure", "<=60%", f"{dg['gross_pct']}%", dg["gross_pct"] <= 60)
        chk("Book ex-ante vol cap (inflated)", f"k x sqrt(w'Sw) <= {a.vol_target:.0%} (k = risk_inflation {a.risk_inflation}; {a.shrinkage.upper()} cov, delta {shrink_delta:.3f}); optimiser constraint, not a scaler; does not stack with sleeve m",
            f"{dg['ann_vol_inflated_pct']}% (raw {dg['ann_vol_pct']}%)", dg["ann_vol_inflated_pct"] <= a.vol_target * 100 + 0.05)
        chk("No leverage", "gross<=100%, long notional<=equity", f"gross {dg['gross_pct']}%, long {dg['long_pct']}%", dg["gross_pct"] <= 100)
        chk("No options / us_equity only", "US-listed stocks/ETFs only", "universe = DESK_UNIVERSE us_equity stocks/ETFs (Dmitri's store)", True)
        cx = [r["symbol"] for r in out if excluded_asset(r["symbol"])]
        chk("No crypto (hard exclusion, CIO)", "0 crypto symbols in targets", ", ".join(cx) or "none", not cx)
        chk("Stop price on every position", "all non-zero targets", f"{sum(1 for r in live if r['stop_price'])}/{len(live)}", all(r["stop_price"] for r in live))
        if derisk_mode:
            chk("Net beta (desk target)", "|beta|<=0.02 (desk target, not an RM limit; de-risk mode cannot add a hedge)", f"{dg['beta']:+.4f} (current {diag(w0)['beta']:+.4f})", abs(dg["beta"]) <= 0.02, info=True)
        else:
            chk("Net beta (desk target)", "|beta|<=0.02", f"{dg['beta']:+.4f}", abs(dg["beta"]) <= 0.02)
        ms = max(secs.items(), key=lambda kv: kv[1][0]) if secs else ("-", [0, 0])
        chk("Sector gross cap (desk)", f"<={a.sector_gross*100:.0f}% per sector", f"{ms[1][0]*100:.2f}% ({ms[0]})", ms[1][0] <= a.sector_gross + 1e-6)
        chk("Earnings blackout", "no added risk in " + ",".join(bl), ", ".join(f"{r['symbol']} {r['delta_trade']:+d}" for r in out if r["symbol"] in bl) or "none traded", all(abs(r["target_shares"]) <= abs(r["current_shares"]) for r in out if r["symbol"] in bl))
        # ---- LIMITS H7 earnings (policy risk_ruling_20261030_0227 by default) ----
        tradable_book = derisk_mode or tradable_is_optimiser
        thru = [r["symbol"] for r in out if r["target_shares"] and EG.get(r["symbol"], {}).get("in_window") and
                (r["target_shares"] < 0 or not EG[r["symbol"]].get("long_exception")) and (eg.close_by_for(EG[r["symbol"]], np.sign(r["target_shares"])) <= exe_s or not r.get("exit_by"))]
        chk("Earnings H7: no hold through release", f"in-window names (release <= {EINFO['horizon_end_session']}) flat if exit_by <= {exe_s}, else exit_by set; shorts no exceptions",
            ", ".join(thru) or "none", not thru)
        add = [r["symbol"] for r in out if EG.get(r["symbol"], {}).get("in_window") and abs(r["target_shares"]) > abs(r["current_shares"])]
        chk("Earnings H7: no new/added risk into release", "|target| <= |current| for in-window names", ", ".join(add) or "none", not add)
        unk_sh = [r["symbol"] for r in out if r["symbol"] in UNK and r["target_shares"] < min(0, r["current_shares"])]
        if tradable_book:
            chk("Earnings: unknown next date (FAIL-SAFE)", "tradable: no new/increased short where next release unknown", ", ".join(unk_sh) or "none", not unk_sh)
        else:
            chk("Earnings: unknown next date (shadow flag)", "shadow: shorts with unknown next release are FLAGGED (not constrained)", (", ".join(unk_sh) + " (FLAGGED)") if unk_sh else "none", not unk_sh, info=True)
        ni_ = EINFO.get("next_earnings") or {}
        chk("Earnings calendar", f"policy {EINFO.get('policy')}; fresh (<= 1 US session) else " + ("FULL FAIL-SAFE (ruling 4)" if EINFO.get("policy") == eg.POLICY_RULING else "all single stocks unknown"),
            f"main: {EINFO.get('reason')}; fetched {EINFO.get('fetched_at_utc')}; covers to {EINFO.get('coverage_through')}; next_earnings: {ni_.get('reason')} "
            f"({os.path.basename(ni_.get('path') or '-')}, sha256 {str(ni_.get('sha256'))[:12]}.. pinned_ok={ni_.get('sha256_ok')}, fetched {ni_.get('fetched_at_utc')}); horizon {exe_s}..{EINFO['horizon_end_session']}", True, info=True)
        fs_ = sorted(s_ for s_ in univ if str(EG[s_].get("kind", "")).startswith("failsafe"))
        chk("Earnings: full fail-safe names (ruling 4)", "no date row / stale or unusable file -> treated as reporting inside the window", ", ".join(fs_) or "none", True, info=True)
        # ---- LIMITS.md overlays (§1 H8/H9, §3, §5) ----
        ms_ = {sl: v["m"] for sl, v in VS.items()}
        chk("Vol scaling m (LIMITS §5)", "m in [0,1]; exactly one overlay per sleeve (126d sleeve scaler; no SPY regime scaler)",
            ", ".join(f"{sl} m={v:.3f}" for sl, v in ms_.items()), all(0 <= v <= 1 for v in ms_.values()))
        t13 = [f"{sl} {v['ratio_sigma_hat_over_target']}" for sl, v in VS.items() if v.get("t13_alert")]
        chk("Sleeve vol alert (LIMITS §5 T13, Risk's alert)", "sigma_hat_126d / sigma_target <= 1.5 (alert only; m already scales down)", ", ".join(t13) or "none", not t13, info=True)
        chk("Panic factor (LIMITS §3)", f"x{PANIC['multiplier_momentum_trend']} ({PANIC['response_source'].get('multiplier_momentum_trend')}) on momentum+trend when panic APPLIED (FINAL flag ON or fail-safe); provisional-marked file = context only",
            f"panic={'ON' if PANIC['panic'] else 'off'}{' (FAIL-SAFE)' if PANIC['fail_safe'] else ''}{' PROVISIONAL' if panic_prov else ''}, applied={PANIC_ON}; " + ", ".join(f"{sl} x{v['panic_factor']}" for sl, v in sleeve_mult.items()),
            all(v["panic_factor"] == ((PANIC["multiplier_momentum_trend"] if PANIC_ON else 1.0) if sl in PANIC_SLEEVES else 1.0) for sl, v in sleeve_mult.items()))
        ls_ = [r["symbol"] for r in out if r["symbol"] in loser and r["target_shares"] < 0 and r["target_shares"] < min(0, r["current_shares"])]
        nls_on = PANIC_ON and not PANIC["new_loser_shorts_allowed"]
        chk("Panic: no new loser-shorts (T8, pending validation)", f"no new/increased short in names with negative momentum/trend z when panic ON and file new_loser_shorts_allowed=false ({PANIC['response_source'].get('new_loser_shorts_allowed')})",
            (", ".join(ls_) or "none") if nls_on else "not applied (n/a)", not ls_, info=not nls_on)
        flo_ = PANIC["net_beta_floor"] if PANIC_ON else None
        chk("Panic: net beta floor (T8, pending validation)", f">= {flo_} when panic applied ({PANIC['response_source'].get('net_beta_floor')})", f"{dg['beta']:+.4f}",
            flo_ is None or dg["beta"] >= flo_ - 1e-9, info=flo_ is None)
        msc_ = [r["symbol"] for r in out if r["symbol"] in mom_short_cut and r["current_shares"] < 0 and r["target_shares"] < mom_short_cut[r["symbol"]] * r["current_shares"] - 1]
        chk("Panic: momentum short notional cut", f"held momentum shorts <= x{PANIC['momentum_short_notional_multiplier']} of current when panic applied ({PANIC['response_source'].get('momentum_short_notional_multiplier')})",
            (", ".join(msc_) or f"none ({len(mom_short_cut)} held momentum shorts)") if PANIC_ON else "not applied (n/a)", not msc_, info=not PANIC_ON)
        chk("Drawdown breaker gross cap (H8)", f"gross <= {gross_cap*100:.0f}% (state {BRKR['state']}{', FAIL-SAFE' if BRKR['fail_safe'] else ''}; buffer {gross_buf*100:.0f}%; episode backstop_equity {BRKR.get('backstop_equity')} from Risk's file; halt_armed {BRKR.get('halt_armed')})",
            f"{dg['gross_pct']}%", dg["gross_pct"] <= gross_cap * 100 + 1e-9)
        if halted:
            newt = [r["symbol"] for r in out if r["current_shares"] and abs(r["target_shares"]) > abs(r["current_shares"]) or (r["target_shares"] and not r["current_shares"])]
            chk("Drawdown breaker HALT (H9)", "no new trades; de-risk only" + ("" if derisk_mode else " (shadow book: not tradable, informational)"), ", ".join(newt) or "none", not newt, info=not derisk_mode)
        else:
            chk("Drawdown breaker HALT (H9)", "no new trades when HALTED", f"state {BRKR['state']}: new trades allowed", True)
        chk("Risk state files", "valid and <= 1 US trading day old, else fail-safe",
            f"panic: {PANIC['reason']} (as_of {PANIC['as_of_sgt']}); breaker: {BRKR['reason']} (as_of {BRKR['as_of_sgt']})",
            True, info=True)
        if derisk_mode:
            newn = [r["symbol"] for r in out if r["target_shares"] and not r["current_shares"]]
            inc = [r["symbol"] for r in out if r["current_shares"] and (abs(r["target_shares"]) > abs(r["current_shares"]) or (r["target_shares"] and np.sign(r["target_shares"]) != np.sign(r["current_shares"])))]
            loose = [r["symbol"] for r in out if r["existing_broker_stop"] and r["target_shares"] and r["stop_price"] and
                     ((r["target_shares"] > 0 and r["stop_price"] < r["existing_broker_stop"]) or (r["target_shares"] < 0 and r["stop_price"] > r["existing_broker_stop"]))]
            chk("De-risk: no new names", "0 new symbols", ", ".join(newn) or "none", not newn)
            chk("De-risk: no increase / flip", "|target|<=|current|, same sign", ", ".join(inc) or "none", not inc)
            chk("De-risk: stops only tightened", "never looser than live broker stop", ", ".join(loose) or "none loosened", not loose)
        port = dict(target=dg, current=diag(w0), turnover_pct_equity=round(turn * 100, 2),
                    turnover_usd=round(turn * E, 2), est_cost_usd_flat10=round(turn * E * a.tc_bps / 1e4, 2),
                    est_cost_usd_model=round(float(np.abs(wf - w0) @ cost_bps) * E / 1e4, 2), cost_model=a.cost_model,
                    sector_exposure={k: dict(gross_pct=round(v[0]*100, 2), net_pct=round(v[1]*100, 2)) for k, v in secs.items()},
                    solver_status=prob.status)
        return out, port, checks

    def diag(wx):
        return dict(gross_pct=round(np.abs(wx).sum() * 100, 2), net_pct=round(wx.sum() * 100, 2),
                    long_pct=round(wx[wx > 0].sum() * 100, 2), short_pct=round(wx[wx < 0].sum() * 100, 2),
                    beta=round(float(beta @ wx), 4), ann_vol_pct=round(float(math.sqrt(wx @ Sig_d @ wx * 252)) * 100, 2),
                    ann_vol_inflated_pct=round(float(math.sqrt(wx @ Sig_cap @ wx)) * 100, 2),
                    n_names=int((np.abs(wx) > 1e-9).sum()),
                    exp_alpha_5d_bps=round(float(alpha @ wx) * 1e4, 2))

    _bad = defect_names() if a.proxy_src == "store_pit" else set()
    _ov = sorted(set(univ) & _bad)
    DATA_PROV = dict(desk_rule="DESK_RULES.md #5: history from Dmitri's store; live Alpaca data only via data/lib/desk_data_client.py; no data.json, no direct HTTP",
                     **DATA_PROVENANCE,
                     earnings_calendar=f"{a.earnings_dir} (Dmitri; forward dates from Nasdaq scheduled rows; uses announce_date_et, not first_tradable_session)",
                     victor_defects_file=DATA_ISSUES,
                     book_affected_by_data_defects=bool(a.proxy_src == "store_pit"),
                     data_defect_status=(DEFECT_LABEL if a.proxy_src == "store_pit" else None),
                     reason=("sleeve m / sigma_target come from the PIT S&P 500 proxy on Dmitri's store (defect names + SNDK excluded; delisting returns and "
                             "former-member gaps still pending Dmitri's fixes) -> PROVISIONAL. Book prices/vols/betas use the store for the "
                             f"{len(univ)} current desk names only. Desk-universe overlap with Victor's defect symbols: {_ov or 'none'}"
                             + (" (LIN: missing PRE-2018 Praxair history; the book uses <= 420 calendar days, so not affected)" if "LIN" in _ov else "")),
                     provisional_results_referenced={"risk_inflation k=1.25 10y PIT L/S re-check (research/ls_volcap_wf.py)": DEFECT_LABEL,
                                                     "sleeve m / sigma_target (store_pit proxy)": DEFECT_LABEL if a.proxy_src == "store_pit" else "n/a (test proxy)"})
    cur_book = []
    for s, p in pos.items():
        q = float(p["qty"]); cpx = float(p["current_price"]); brk = BRK.get(s)
        cur_book.append(dict(symbol=s, qty=q, price=cpx, mv=float(p["market_value"]), weight_pct=round(float(p["market_value"]) / E * 100, 2),
                             broker_stop=brk, risk_to_stop_usd=round(abs(q) * abs(cpx - brk), 2) if brk else None,
                             composite_z=round(float(comp.get(s, float("nan"))), 2) if s in comp.index else None))
    base = dict(asof=a.date, generated_sgt=dt.datetime.now().strftime("%Y-%m-%d %H:%M SGT (UTC+8)"),
                equity=E, equity_source=eq_src, last_complete_bar=str(t.date()),
                live_signal_row=DATA_PROVENANCE["live_row"]["description"], live_gap_events_pct=live_gaps,
                method_version=METHOD_VERSION, limits_version=LIMITS_VERSION, earnings_gate=a.earnings_policy, t8_status=PANIC.get("t8_status"),
                assumptions=dict(cost_model=a.cost_model, cost_model_source="tca/baseline_report.md §5 (HS + k·σ·√(Q/ADV) + H) + borrow per tca/cost_model.md §4" if a.cost_model == "tca" else "flat",
                                 tca_k=a.tca_k, tca_clip_frac_equity=a.tca_clip, borrow_bps_yr=a.borrow_bps_yr,
                                 per_name_cost_bps={k_: v_ for k_, v_ in cost_src.items() if k_ in pos or k_ in ("SPY",)},
                                 cost_bps_range=[round(float(cost_bps.min()), 2), round(float(np.median(cost_bps)), 2), round(float(cost_bps.max()), 2)],
                                 tc_one_way_bps_flat=a.tc_bps, tc_amortised_over_5d_periods=a.hold_periods, vol_target_ann=a.vol_target,
                                 stop_rule=f"{a.atr_mult}x ATR(14)", cov=("120d daily, Ledoit-Wolf 2004 optimal shrink to constant corr: delta* %.4f (avg corr %.3f)" % (shrink_delta, rbar)) if a.shrinkage == "lw" else ("120d daily, fixed %.2f shrink to constant corr (avg corr %.3f)" % (shrink_delta, rbar)),
                                 shrinkage=dict(method=a.shrinkage, delta=round(shrink_delta, 4), avg_corr=round(float(rbar), 4)),
                                 risk_inflation=dict(k=a.risk_inflation, applies_to="ex-ante covariance in the 6% book vol cap only (Sigma_cap = k^2 * Sigma * 252)",
                                                     source="research/RESULTS_2026-10-30.md walk-forward forecast bias: MV models on Dave's statarb bars 1.15-1.37, MV-LW 1.20 (L120 weekly); volcap check research/out/volcap_*.json (not affected by the data defects). 10y PIT L/S re-check (research/ls_volcap_wf.py, Dmitri's SIP store): " + DEFECT_LABEL,
                                                     ten_year_pit_check_status=DEFECT_LABEL,
                                                     stacking="does NOT stack with the per-sleeve m (separate time-series overlay on alpha; still the single vol overlay)"),
                                 beta="120d daily vs SPY, Blume 0.67*b+0.33", horizon="5 trading days",
                                 composite_ic_used=round(ic_c, 4), buffers=dict(max_pos=a.max_pos, max_risk=a.max_risk, max_gross=a.max_gross),
                                 long_only=a.long_only, excluded_assets="crypto (hard exclusion, CIO 2026-10-30)", blackout=bl, fallback_policy=a.fallback, victor_passed=vp,
                                 garleanu_pedersen=gp if gp_on else "off"),
                risk_overlays=dict(pipeline_order="combine signals -> sleeve weights -> m (sleeve 126d vol scaling) -> panic multiplier -> optimisation (beta, sector, 6% ex-ante vol constraint, position, risk, gross/breaker caps) -> stops -> compliance",
                                   vol_scaling=VS, panic=PANIC, panic_applied=PANIC_ON, panic_provisional=panic_prov, breaker=BRKR, sleeve_multipliers=sleeve_mult,
                                   earnings=dict(policy=EINFO.get("policy"), policy_source="risk/decisions-log.md 2026-10-30 02:27 (Risk ruling: ACCEPTED WITH CONDITIONS)" if EINFO.get("policy") == eg.POLICY_RULING else "pre-ruling strict mode (CLI option)",
                                                 rule=(eg.__doc__.split("--- pre-ruling")[0].strip() if EINFO.get("policy") == eg.POLICY_RULING else "strict: confirmed/main-calendar dates known; estimated or missing -> unknown (tradable no new/increased short; shadow flag); stale -> all unknown"),
                                                 by_kind={k_: sorted(s_ for s_, v in EG.items() if v.get("kind") == k_) for k_ in sorted({v.get("kind") for v in EG.values()})},
                                                 per_name={s_: {k_: v.get(k_) for k_ in ("kind", "next", "timing", "window_open", "close_by_short", "close_by_long", "in_window", "unknown", "last_8k_202", "h7_flag")} for s_, v in EG.items() if v.get("kind") != "etf_exempt"},
                                                 calendar=EINFO, hold_exceptions=exc, n_in_window=sum(1 for v in EG.values() if v["in_window"]),
                                                 unknown_next_date=sorted(UNK), etf_exempt=sorted(s_ for s_ in univ if EG[s_]["kind"] == "etf_exempt"),
                                                 in_window={s_: dict(next=v["next"], timing=v["timing"], kind=v.get("kind"), close_by_short=v.get("close_by_short", v["close_by"]), close_by_long=v.get("close_by_long", v["close_by"])) for s_, v in EG.items() if v["in_window"]}),
                                   gross_cap_pct=gross_cap * 100, gross_buffer_pct=round(gross_buf * 100, 2),
                                   halted_derisk_only=halted, loser_short_ban_names=sorted(loser),
                                   state_files_used=[a.panic_path, a.breaker_path],
                                   fail_safe_fired=dict(panic=PANIC["fail_safe"], breaker=BRKR["fail_safe"]),
                                   ex_ante_vol_cap=f"{a.vol_target:.0%} annualised: optimiser CONSTRAINT on k^2 x 120d {a.shrinkage.upper()}-shrunk covariance (not a scaler)",
                                   risk_inflation=a.risk_inflation, shrinkage_method=a.shrinkage, shrinkage_delta=round(shrink_delta, 4),
                                   overlay_count_note="risk_inflation recalibrates the risk FORECAST inside the cap; it is not a vol-scaling overlay and does not stack with sleeve m (single overlay)",
                                   hrp="off (not adopted)", gp_partial_trading="on" if gp_on else "off"),
                data_provenance=DATA_PROV,
                positions_source=a.positions,
                signal_study=stats, signal_weighting_mode=mode, signals_passing_internal_oos=passed,
                signals_validated=validated, signal_weights={k: round(v, 4) for k, v in sw.items()},
                signal_ic_corr=sigcorr.round(3).to_dict(), current_book=cur_book)
    if gp_on:
        base["gp_aim_vs_trade"] = dict(aim_turnover_pct=round(float(np.abs(w_star - w0).sum()) * 100, 2),
                                       traded_turnover_pct_pre_rounding=round(float(np.abs(wv - w0).sum()) * 100, 2))
    def guard(doc):
        bad = [r["symbol"] for r in doc["targets"] if excluded_asset(r["symbol"])]
        if bad: raise SystemExit(f"HARD EXCLUSION violated, not writing targets: {bad}")
    sfx = "" if not gp_on else "_gp"
    run_dt = dt.datetime.fromisoformat(a.run_ts) if a.run_ts else None
    if run_dt is not None and run_dt.tzinfo is None: run_dt = run_dt.replace(tzinfo=tio.SGT)
    run_dt, stamp = tio.run_stamp(run_dt)
    generated = run_dt.isoformat(timespec="seconds")
    run_id = f"{stamp}{sfx}"
    p_tr = f"{a.outdir}/targets/targets_{stamp}{sfx}.json"
    p_sh = f"{a.outdir}/shadow/targets_{stamp}{sfx}.json"
    # CIO (Jeremy) 2026-11-06: while new_trades_allowed is false (breaker H9 halt OR CIO all-new-trading hold),
    # DO NOT publish/write any tradable targets file — even an empty de-risk book. Shadow-only is allowed.
    suppress_tradable = bool(halted)
    planned = [p_sh] + ([] if suppress_tradable else [p_tr])
    for p_ in planned:   # fail BEFORE writing anything if a planned path is taken
        if os.path.lexists(p_): raise SystemExit(f"refusing to overwrite existing targets file: {p_}")
    ident = dict(generated_sgt=generated, run_id=run_id, shadow_sleeve_id=SHADOW_SLEEVE_ID, shadow_file=p_sh,
                 tradable_suppressed=suppress_tradable,
                 tradable_suppressed_reason=("new_trades_allowed=false in breaker_state.json (H9 halt and/or CIO all-new-trading hold): no tradable targets file written, even empty; shadow-only" if suppress_tradable else None))
    docs = []
    res = None; out = None
    if fallback_derisk:
        sh_out, sh_port, sh_chk = build(shares)
        shadow = dict(base, **ident, sleeve_id=SHADOW_SLEEVE_ID, book_name=SHADOW_BOOK_NAME, description=SHADOW_DESCRIPTION,
                      book_type="SHADOW", tradable=False,
                      label=f"SHADOW BOOK - NOT FOR TRADING. {SHADOW_BOOK_NAME} ({SHADOW_SLEEVE_ID}): fallback composite on UNVALIDATED signals, for tracking only (FRAMEWORK.md §8)."
                            + (" TRADABLE FILE SUPPRESSED: new_trades_allowed=false (CIO hold / H9)." if suppress_tradable else ""),
                      portfolio=sh_port, compliance=sh_chk, targets=sh_out)
        guard(shadow); docs.append((p_sh, shadow))
        if not suppress_tradable:
            dr = derisk(shares)
            out, port, checks = build(dr, derisk_mode=True)
            sid, bname, bdesc = TRADABLE_IDS["DE-RISK ONLY"]
            res = dict(base, **ident, sleeve_id=sid, book_name=bname, description=bdesc, book_type="DE-RISK ONLY", tradable=True,
                       label=("BREAKER HALTED (H9) -> " if halted else "") + "TRADABLE, DE-RISK ONLY: no validated signal (Victor) or breaker halt -> may only trim/close/cover existing positions and tighten stops. "
                             f"Shadow book ({SHADOW_SLEEVE_ID}): {p_sh}",
                       portfolio=port, compliance=checks, targets=out)
            guard(res); docs.append((p_tr, res))
        else:
            # Keep print/summary variables defined; do not build or write a tradable doc.
            out, port, checks = [], {"target": {"gross_pct": 0.0, "net_pct": 0.0, "beta": 0.0, "n_names": 0}, "current": {"gross_pct": 0.0, "net_pct": 0.0, "beta": 0.0, "n_names": 0}, "turnover_pct_equity": 0.0}, []
            res = dict(base, **ident, sleeve_id="tradable_suppressed", book_name="Tradable suppressed (CIO hold / H9)", description="No tradable file",
                       book_type="SUPPRESSED", tradable=False, label="TRADABLE SUPPRESSED: new_trades_allowed=false",
                       portfolio=port, compliance=checks, targets=out)
    else:
        if suppress_tradable:
            raise SystemExit("new_trades_allowed=false: refusing FULL/fallback-full tradable write (CIO hold / H9). Use default --fallback derisk for shadow-only.")
        out, port, checks = build(shares)
        sid, bname, bdesc = TRADABLE_IDS["FULL"] if validated else ("research_full_fallback_v1", "Research full fallback v1", "--fallback full on unvalidated signals: research only, NOT CIO policy.")
        res = dict(base, **ident, sleeve_id=sid, book_name=bname, description=bdesc,
                   book_type="FULL" if validated else "FULL FALLBACK (--fallback full; NOT CIO policy)", tradable=True,
                   portfolio=port, compliance=checks, targets=out)
        guard(res); docs.append((p_tr, res))
    paths = []
    for p_, doc in docs:
        digest = tio.write_exclusive(p_, doc); paths.append(p_)
        tio.append_log(f"{a.outdir}/targets_log.jsonl", tio.log_record(doc, p_, digest, run_id, generated, a.positions))
        if not a.no_latest: tio.update_latest(p_)
    if suppress_tradable:
        tio.append_log(f"{a.outdir}/targets_log.jsonl", tio.correction_record(
            corrects=[dict(run_id=run_id, book="SUPPRESSED", note="no tradable file this run")],
            fields=dict(tradable_suppressed=True, reason=ident["tradable_suppressed_reason"]),
            note="CIO 2026-11-06: no tradable targets published while new_trades_allowed=false (all-new-trading hold / H9). Shadow-only written.",
            author="Hana (Portfolio Construction)", requested_by="Jeremy (CIO)"))
        print("TRADABLE SUPPRESSED: new_trades_allowed=false (CIO all-new-trading hold and/or H9). No targets/*.json written this run.")
    print(json.dumps({k: res[k] for k in ["equity", "equity_source", "book_type", "signal_weighting_mode", "signals_validated", "signal_weights", "portfolio", "compliance"] if k in res}, indent=1, default=float))
    if gp_on: print("GP", json.dumps(gp), json.dumps(base["gp_aim_vs_trade"]))
    print("\nSIGNAL STUDY"); print(pd.DataFrame(stats).T.round(3).to_string())
    print("\nTARGETS (" + res["book_type"] + ")"); print(pd.DataFrame(out)[["symbol","side","current_shares","target_shares","delta_trade","target_weight","stop_price","existing_broker_stop","stop_action","est_risk_usd","beta"]].to_string() if out else "  (no positions / tradable suppressed)")
    print("wrote", paths)

if __name__ == "__main__":
    main()
