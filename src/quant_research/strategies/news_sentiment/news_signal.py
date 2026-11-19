"""News-sentiment prototype on Alpaca/Benzinga news (cf. Ke, Kelly & Xiu 2019), research only.

Scoring (primary): Loughran-McDonald (LM) finance word lists (lexicon/lm_positive.txt, lm_negative.txt;
  2018-vintage master dictionary as bundled in pysentiment2 0.1.1). Article score on headline+summary:
  (P - N) / (P + N), 0 if no hits. Chosen because LM is built for financial text (general lexicons
  mis-score words like 'liability', 'tax', 'cost', 'crude'), and every score is a transparent word count.
Robustness (variant): VADER compound score (general-purpose, rule-based, handles negation/intensifiers).
Article filter: <= 3 tagged symbols (drops market roundups that tag many tickers).
Timing / no look-ahead: trading day d gets every article with created_at in
  [09:30 ET of session d-1, 09:25 ET of session d)   (primary, "prev-open window")
  [16:00 ET of session d-1, 09:25 ET of session d)   (variant, "overnight only")
  Position opened at the OPEN of d, returns open(d)->open(d+1) ("1d") and open(d)->open(d+5) ("5d").
Universe: stock must be a point-in-time S&P 500 member on d (Dmitri's file via ../desk_data.py).
  Old tickers (e.g. FB) are mapped to current file symbols (META) using aliases.csv (from Dmitri's
  corporate_actions name_changes) for news dated before the change.
Tests per day: (i) long-short = EW long all score>0 minus EW short all score<0;
  (ii) decile spread D10-D1 on days with >= 30 scored stocks. Stats: N days, hit rate, mean,
  t-stat clustered by calendar month. Net = Tomas's cost model v1.1 (tca/tca_scripts/cost_model.py):
  round trip at the open by liquidity bucket (lagged 20d $ADV), assuming each leg fully turns over every
  day (r1); r5 = 5-day cohort return net of one round trip per leg, + ETB borrow 25 bp/yr on the short leg; 2x stress too.
Components (kept separate; panels saved to OUT/stock_day_scores.parquet and OUT/sector_day_scores.parquet):
  1 text sentiment (non-analyst articles), 2 analyst rating changes (+1 upgrade / -1 downgrade),
  3 analyst price-target changes (+1 raise / -1 lower) parsed from Benzinga headlines,
  4 sector scores = mean of member stocks' daily component scores (current GICS from universe.parquet; former
    members have no GICS and drop out) mapped to SPDR ETFs; test long top-3 / short bottom-3 ETFs at the open.
  X posts excluded: no history (archive-forward only).
Usage: python news_signal.py [--raw raw raw_alias]
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, json, glob, re, argparse, html
import numpy as np, pandas as pd
sys.path.insert(0, f"{_QR.DESK_DIR}/equity")
from quant_research.data import desk_data as dd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
sys.path.insert(0, f"{_QR.COSTS_DIR}")
from quant_research.backtest.costs import cost_model as tca   # Tomas's plug-in cost model v1.1 (read-only use)
# round-trip cost (bps) per liquidity bucket, $10k clip at $50, venue='open' (we trade at the open)
_ADV = {"L1": 2e9, "L2": 5e8, "L3": 1e8, "L4": 2e7}
RT_BPS = {b: tca.round_trip_cost_bps(50, 200, adv_shares=a / 50, venue="open") for b, a in _ADV.items()}
BORROW_BPS_PER_DAY = tca.BORROW_RATE_ETB_DEFAULT * 1e4 / 360

ap = argparse.ArgumentParser(); ap.add_argument("--raw", nargs="+", default=["raw", "raw_alias"])
ap.add_argument("--max_syms", type=int, default=3); a = ap.parse_args()
POS = set(open("lexicon/lm_positive.txt").read().split()); NEG = set(open("lexicon/lm_negative.txt").read().split())
tok = re.compile(r"[A-Za-z]+")
def lm(text):
    w = [x.upper() for x in tok.findall(text)]
    p = sum(x in POS for x in w); n = sum(x in NEG for x in w)
    return (p - n) / (p + n) if p + n else 0.0
vader = SentimentIntensityAnalyzer()

# analyse only months completed in the PRIMARY raw dir (alias dir only supplements those months)
months_loaded = sorted(fn.split("/")[-1][:7] for fn in glob.glob(f"{a.raw[0]}/*.jsonl"))
# ---- OOS LOCK (Victor, 2026-10-30): months before 2025-06 are the untouched hold-out for
# PREREG_sector_lm_5d.md. They are skipped unless NEWS_OOS_UNLOCK equals the sha256 of the frozen
# pre-registration file AND that hash is recorded in PREREG_sector_lm_5d.sha256 (written only at freeze).
import hashlib, os
SEEN_START = "2025-06"
_pr = "PREREG_sector_lm_5d.md"; _ph = "PREREG_sector_lm_5d.sha256"
_unlock = os.environ.get("NEWS_OOS_UNLOCK", "")
_ok = (os.path.exists(_pr) and os.path.exists(_ph) and _unlock
       and _unlock == hashlib.sha256(open(_pr, "rb").read()).hexdigest() == open(_ph).read().split()[0])
# Sequencing (Victor final ruling X1 / interim #4): even with a valid unlock, this exploratory script (36 cells,
# VADER, analyst cells) may touch hold-out months only AFTER the single gating run (prereg_run.py) is logged.
sys.path.insert(0, f"{_QR.DESK_DIR}/equity"); from quant_research.strategies.news_sentiment import holdout_guard as _hg
if _ok and not _hg.sector_lm_run_logged():
    print("OOS LOCK: valid unlock, but the gating sector-LM run is not logged yet; exploratory cells stay on the seen sample", flush=True)
    _ok = False
if not _ok:
    _held = [m for m in months_loaded if m < SEEN_START]
    months_loaded = [m for m in months_loaded if m >= SEEN_START]
    print(f"OOS LOCK: skipping {len(_held)} hold-out months (< {SEEN_START}); analysing {len(months_loaded)} seen months only", flush=True)
rows = []
for d in a.raw:
    for fn in sorted(glob.glob(f"{d}/*.jsonl")):
        if fn.split("/")[-1][:7] not in months_loaded: continue
        for line in open(fn):
            x = json.loads(line); syms = x.get("symbols") or []
            if not syms or len(syms) > a.max_syms: continue
            rows.append((x["id"], x["created_at"], (x.get("headline") or ""), (x.get("summary") or ""), syms))
art = pd.DataFrame(rows, columns=["id", "created_at", "headline", "summary", "symbols"]).drop_duplicates("id")
art["text"] = (art.headline + ". " + art.summary).map(html.unescape).str.strip()
art["lm"] = art.text.map(lm)
art["vader"] = art.text.map(lambda t: vader.polarity_scores(t)["compound"])
art["ts"] = pd.to_datetime(art.created_at, utc=True)
# ---- analyst component, parsed from Benzinga's structured headlines (kept SEPARATE from text sentiment)
#   "<Broker> Upgrades <Co> to <Rating>[, Raises Price Target to $X]"; "... Maintains <R> on <Co>, Lowers Price Target to $X"
hl = art.headline.map(html.unescape)
art["is_analyst"] = hl.str.contains(r"\b(?:Upgrades|Downgrades|Initiates Coverage|Reinstates|Maintains|Reiterates|Price Target)\b", regex=True)
art["rating_chg"] = np.select([hl.str.contains(r"\bUpgrades\b"), hl.str.contains(r"\bDowngrades\b")], [1.0, -1.0], np.nan)
art["pt_chg"] = np.select([hl.str.contains(r"\bRaises Price Target\b"), hl.str.contains(r"\bLowers Price Target\b")], [1.0, -1.0], np.nan)

# ---- map article timestamps to trading day d --------------------------------------------
cal = dd.calendar(); cal = cal[cal >= "2016-01-01"]
et = lambda days, hhmm: (pd.DatetimeIndex(days) + pd.Timedelta(hhmm)).tz_localize("America/New_York").tz_convert("UTC")
sess = pd.DataFrame({"d": cal, "open_utc": et(cal, "9h30m"), "cut_utc": et(cal, "9h25m"), "close_utc": et(cal, "16h")})
sess["prev_open"] = sess.open_utc.shift(1); sess["prev_close"] = sess.close_utc.shift(1)
art = art.sort_values("ts")
s2 = sess.dropna().sort_values("cut_utc")
m = pd.merge_asof(art, s2[["cut_utc", "d", "prev_open", "prev_close"]], left_on="ts", right_on="cut_utc", direction="forward", allow_exact_matches=False)
m = m.dropna(subset=["d"])
lm_ = set(months_loaded)
m = m[m.d.dt.strftime("%Y-%m").isin(lm_) & m.prev_open.dt.tz_convert("UTC").dt.strftime("%Y-%m").isin(lm_)]
m["in_primary"] = m.ts >= m.prev_open
m["in_overnight"] = m.ts >= m.prev_close
ex = m.explode("symbols").rename(columns={"symbols": "symbol"})
al = pd.read_csv("aliases.csv", parse_dates=["process_date"])
for r in al.itertuples():
    k = (ex.symbol == r.old_symbol) & (ex.d < r.process_date); ex.loc[k, "symbol"] = r.new_symbol
ex = ex[dd.is_member(ex.symbol, ex.d)]
ex = ex[~((ex.symbol == "SNDK") & (ex.d < pd.Timestamp("2017-01-01")))]   # ticker reuse guard (old SanDisk)
ex[["id", "ts", "d", "symbol", "in_primary", "in_overnight", "lm", "vader", "headline"]].sample(min(40, len(ex)), random_state=0).sort_values("ts").to_csv(f"{dd.OUT}/timing_audit_sample.csv", index=False)

# ---- open-to-open returns ----------------------------------------------------------------
pos = {d: i for i, d in enumerate(cal)}
def fwd_open(sym):
    b = dd.bars(sym)
    if b is None: return None
    o = b.open.reindex(cal)
    full = dd.bars_full(sym).reindex(cal)
    adv = (full.close * full.volume).rolling(20, min_periods=10).mean().shift(1)   # lagged 20d $ADV
    bucket = pd.Series(np.select([adv > 1e9, adv > 2e8, adv > 5e7], ["L1", "L2", "L3"], "L4"), index=cal)
    return pd.DataFrame({"r1": o.shift(-1) / o - 1, "r5": o.shift(-5) / o - 1, "rt_bps": bucket.map(RT_BPS)})
need = ex.symbol.unique(); R = {}
for s in need:
    f = fwd_open(s)
    if f is not None: R[s] = f
spy = fwd_open(dd.BENCH)

def daily_tests(sd, score, window, deciles=True):
    sd = sd.copy()
    sd = sd.join(pd.concat({s: R[s] for s in sd.symbol.unique() if s in R}, names=["symbol", "d"]), on=["symbol", "d"])
    out = {}
    for h, hold in (("r1", 1), ("r5", 5)):
        x = sd.dropna(subset=[h])
        # (i) long-short positive vs negative
        g = x.groupby("d")
        L = x[x[score] > 0].groupby("d")[h].mean(); S = x[x[score] < 0].groupby("d")[h].mean()
        ls = (L - S).dropna()
        # cost: full daily turnover of each leg (conservative), round trip spread over the holding period
        cL = x[x[score] > 0].groupby("d").rt_bps.mean(); cS = x[x[score] < 0].groupby("d").rt_bps.mean()
        ls_cost = ((cL + cS) / 1e4 + BORROW_BPS_PER_DAY / 1e4 * hold).reindex(ls.index)   # one round trip per cohort
        # (ii) deciles on days with >= 30 names
        cnt = g[h].transform("size"); y = x[(cnt >= 30) & deciles].copy()
        y["dec"] = y.groupby("d")[score].rank(method="first", pct=True).mul(10).apply(np.ceil).clip(1, 10)
        dm = y.groupby(["d", "dec"])[h].mean().unstack()
        dsp = (dm[10] - dm[1]).dropna() if len(dm) else pd.Series(dtype=float)
        if len(dm):
            cm = y.groupby(["d", "dec"]).rt_bps.mean().unstack()
            d_cost = ((cm[10] + cm[1]) / 1e4 + BORROW_BPS_PER_DAY / 1e4 * hold).reindex(dsp.index)
        else: d_cost = pd.Series(dtype=float)
        mon = lambda s: s.index.to_period("M")
        for name, ser, cost in (("LS_pos_minus_neg", ls, ls_cost), ("D10_minus_D1", dsp, d_cost)):
            if len(ser) < 20: out[f"{name}_{h}"] = dict(n_days=int(len(ser))); continue
            out[f"{name}_{h}"] = dict(n_days=int(len(ser)), n_stock_days=int(len(x if name.startswith("LS") else y)),
                hit_rate=round(float((ser > 0).mean()), 3), mean_gross=round(float(ser.mean()), 6),
                t_month_clustered=round(float(dd.clustered_t(ser.values, mon(ser))), 2),
                mean_cost_per_day=round(float(cost.mean()), 6),
                mean_net_tomas_v1_1=round(float((ser - cost).mean()), 6),
                t_net_month_clustered=round(float(dd.clustered_t((ser - cost).values, mon(ser))), 2),
                mean_net_2x_cost_stress=round(float((ser - 2 * cost).mean()), 6),
                ann_sharpe_gross=round(float(ser.mean() / ser.std() * np.sqrt(252 / (1 if h == "r1" else 5))), 2),
                first=str(ser.index.min().date()), last=str(ser.index.max().date()))
        if h == "r1":   # FF5+Mom daily alpha; open(d)->open(d+1) straddles close-to-close days d and d+1,
            F = dd.ff("daily"); cols = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
            Fd = F[cols].reindex(cal); X = pd.concat([Fd.add_suffix("_d"), Fd.shift(-1).add_suffix("_d1")], axis=1)
            for name, ser in (("LS_pos_minus_neg", ls), ("D10_minus_D1", dsp)):
                if len(ser) >= 24: out[f"FF5Mom_alpha_{name}_r1"] = {k: v for k, v in dd.ff_alpha(ser, X.reindex(ser.index), 5).items() if k != "betas"}
        if len(dm): out[f"decile_means_{h}"] = {int(k): round(float(v), 6) for k, v in dm.mean().items()}
    return out

res = {}; variants = 0
# Component 1: text sentiment on NON-analyst articles (stock level), 2 lexicons x 2 windows
for window, flag in (("prev_open", "in_primary"), ("overnight", "in_overnight")):
    for score in ("lm", "vader"):
        sd = ex[ex[flag] & ~ex.is_analyst].groupby(["symbol", "d"]).agg(lm=("lm", "mean"), vader=("vader", "mean"), n_articles=("id", "size")).reset_index()
        res[f"text_{score}_{window}"] = daily_tests(sd, score, window); variants += 1
        res[f"text_{score}_{window}"]["stock_days"] = int(len(sd))
# Components 2 and 3: analyst rating changes and price-target changes (stock level, prev-open window)
for comp in ("rating_chg", "pt_chg"):
    sd = ex[ex.in_primary & ex[comp].notna()].groupby(["symbol", "d"]).agg(**{comp: (comp, "mean"), "n_articles": ("id", "size")}).reset_index()
    res[f"analyst_{comp}"] = daily_tests(sd, comp, "prev_open", deciles=False); variants += 1
    res[f"analyst_{comp}"]["stock_days"] = int(len(sd))
# Stock-day panel with all components kept separate (for Victor)
P = ex[ex.in_primary]
txt = P[~P.is_analyst].groupby(["symbol", "d"]).agg(text_lm=("lm", "mean"), text_vader=("vader", "mean"), n_text=("id", "size"))
ana = P.groupby(["symbol", "d"]).agg(rating_chg=("rating_chg", "mean"), n_rating=("rating_chg", "count"), pt_chg=("pt_chg", "mean"), n_pt=("pt_chg", "count"))
panel = txt.join(ana, how="outer").reset_index()
panel.loc[panel.n_rating == 0, "rating_chg"] = np.nan; panel.loc[panel.n_pt == 0, "pt_chg"] = np.nan
panel["n_text"] = panel.n_text.fillna(0).astype(int)
panel.to_parquet(f"{dd.OUT}/stock_day_scores.parquet", index=False)
# Component 4: sector level = mean of member stocks' daily scores, mapped to SPDR sector ETFs
SECTOR_ETF = {"Information Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Health Care": "XLV",
              "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Industrials": "XLI", "Utilities": "XLU",
              "Materials": "XLB", "Real Estate": "XLRE", "Communication Services": "XLC"}
u = dd.universe(); gics = dict(zip(u.symbol, u.gics_sector))
panel["sector"] = panel.symbol.map(gics)
sec = panel.dropna(subset=["sector"]).groupby(["sector", "d"]).agg(text_lm=("text_lm", "mean"), rating_chg=("rating_chg", "mean"),
        pt_chg=("pt_chg", "mean"), n_stocks_text=("text_lm", "count"), n_stocks_rating=("rating_chg", "count"), n_stocks_pt=("pt_chg", "count")).reset_index()
sec["etf"] = sec.sector.map(SECTOR_ETF)
sec.to_parquet(f"{dd.OUT}/sector_day_scores.parquet", index=False)
ETF_RT = RT_BPS["L1"]
for comp, ncol, nmin in (("text_lm", "n_stocks_text", 3), ("rating_chg", "n_stocks_rating", 1), ("pt_chg", "n_stocks_pt", 2)):
    z = sec[sec[ncol] >= nmin].copy()
    z = z.join(pd.concat({e: R.get(e, fwd_open(e)) for e in z.etf.unique()}, names=["etf", "d"]), on=["etf", "d"])
    out = {}
    for h, hold in (("r1", 1), ("r5", 5)):
        y = z.dropna(subset=[h, comp]); y = y[y.groupby("d")[comp].transform("size") >= (6 if comp != "rating_chg" else 2)]
        k3 = 3 if comp != "rating_chg" else 1
        y["rk"] = y.groupby("d")[comp].rank(method="first")
        y["n"] = y.groupby("d")[comp].transform("size")
        top = y[y.rk > y.n - k3].groupby("d")[h].mean(); bot = y[y.rk <= k3].groupby("d")[h].mean()
        ser = (top - bot).dropna()
        if comp == "rating_chg": ser = ser[(y.groupby("d")[comp].max() > 0) & (y.groupby("d")[comp].min() < 0)].dropna()  # need an up and a down sector
        cost = 2 * ETF_RT / 1e4 + BORROW_BPS_PER_DAY / 1e4 * hold
        if len(ser) < 20: out[f"top3_minus_bottom3_{h}"] = dict(n_days=int(len(ser))); continue
        out[f"top3_minus_bottom3_{h}"] = dict(n_days=int(len(ser)), hit_rate=round(float((ser > 0).mean()), 3),
            mean_gross=round(float(ser.mean()), 6), t_month_clustered=round(float(dd.clustered_t(ser.values, ser.index.to_period("M"))), 2),
            mean_net_tomas_v1_1=round(float(ser.mean() - cost), 6), first=str(ser.index.min().date()), last=str(ser.index.max().date()))
    res[f"sector_{comp}"] = out; variants += 1
diag = dict(universe_mode=dd.UNIVERSE_MODE, months_loaded=months_loaded, n_months_loaded=len(months_loaded), articles_after_filter=int(len(art)),
            stock_day_article_rows=int(len(ex)), symbols=int(ex.symbol.nunique()),
            lm_nonzero_share=round(float((art.lm != 0).mean()), 3), summary_nonempty_share=round(float((art.summary.str.len() > 0).mean()), 3),
            spec_variants=variants, rt_cost_bps_by_bucket={k: round(v, 2) for k, v in RT_BPS.items()},
            files_used=[dd.MEMBERSHIP, dd.BARS_DIR, f"{_QR.DATA_DIR}/corporate_actions/all_actions.parquet (name_changes -> aliases.csv)", f"{_QR.COSTS_DIR}/cost_model.py"], note="specs: 4 text (LM/VADER x window) + 2 analyst (rating, PT) + 3 sector (text, rating, PT); each x 2 horizons; text: LS + decile, analyst: LS only, sector: top3-bottom3",
            analyst_article_share=round(float(art.is_analyst.mean()), 3), gics_missing_symbols=int(panel[panel.sector.isna()].symbol.nunique()),
            x_posts="excluded: X has no history (archive-forward only)")
json.dump(dict(diag=diag, results=res), open(f"{dd.OUT}/results.json", "w"), indent=1)
print(json.dumps(dict(diag=diag, results=res), indent=1))
