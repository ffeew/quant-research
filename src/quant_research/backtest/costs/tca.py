#!/usr/bin/env python3
"""Baseline TCA for the Alpaca PAPER account. READ-ONLY (GET only).
Usage: python3 tca.py [--out $QR_DESK_DIR/tca] [--k-low 0.5 --k-high 1.0]
Env: ALPACA_API_KEY_ID, ALPACA_API_SECRET_KEY (never printed).
Outputs: fills_YYYYMMDD.csv (per order), tca_raw.json (inputs/aggregates for the report).
"""
from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import os, sys, json, math, argparse, statistics as st
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests

TRADE = "https://paper-api.alpaca.markets"   # PAPER ONLY
DATA = "https://data.alpaca.markets"
assert "paper-api" in TRADE and "://api.alpaca" not in TRADE
# All wall-clock conversions go through the IANA tz database (handles US DST automatically).
# Never use fixed offsets (-4/-5/+8) for market time.
UTC = timezone.utc
ET = ZoneInfo("America/New_York")
SGT = ZoneInfo("Asia/Singapore")

def headers():
    k, s = os.environ.get("ALPACA_API_KEY_ID"), os.environ.get("ALPACA_API_SECRET_KEY")
    if not k or not s:
        sys.exit("ERROR: ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY env vars missing - cannot query Alpaca.")
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}

H = None
def get(url, **params):
    import time
    for attempt in range(6):   # back off on 429 (key is shared with other desk processes)
        r = requests.get(url, headers=H, params=params, timeout=30)   # GET only
        if r.status_code != 429: break
        time.sleep(min(60, 2 ** attempt * 2))
    if r.status_code != 200:
        return {"_error": r.status_code, "_msg": r.text[:200]}
    return r.json()

def ts(s):
    """Parse an Alpaca RFC3339 timestamp (e.g. '2026-10-29T16:51:45.626331422Z') into a tz-aware UTC datetime.
    Nanoseconds are truncated to microseconds. Naive timestamps are rejected (never guess a zone)."""
    if not s: return None
    s = s.replace("Z", "+00:00")
    if "." in s:  # trim nanoseconds
        head, rest = s.split(".", 1)
        i = 0
        while i < len(rest) and rest[i].isdigit(): i += 1
        frac, tz = rest[:i], rest[i:]
        s = f"{head}.{frac[:6]}{tz}"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        raise ValueError(f"naive timestamp {s!r}: refusing to guess its zone")
    return d.astimezone(UTC)

def et(d): return d.astimezone(ET) if d else None
def et_date(d): return d.astimezone(ET).date()
def et_str(d): return d.astimezone(ET).strftime("%Y-%m-%d %H:%M:%S %Z") if d else ""   # %Z -> EDT/EST

def iso(d): return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
def sgt(d): return d.astimezone(SGT).strftime("%Y-%m-%d %H:%M:%S SGT") if d else ""

def all_orders():
    out, until = [], None
    while True:
        p = dict(status="all", limit=500, direction="desc", nested="true")
        if until: p["until"] = until
        page = get(TRADE + "/v2/orders", **p)
        if isinstance(page, dict): raise RuntimeError(page)
        out += page
        if len(page) < 500: break
        until = page[-1]["submitted_at"]
    seen, uniq = set(), []
    for o in out:
        if o["id"] not in seen: seen.add(o["id"]); uniq.append(o)
    return uniq

def all_fills():
    out, tok = [], None
    while True:
        p = dict(page_size=100, direction="desc")
        if tok: p["page_token"] = tok
        page = get(TRADE + "/v2/account/activities/FILL", **p)
        if isinstance(page, dict): raise RuntimeError(page)
        out += page
        if len(page) < 100: break
        tok = page[-1]["id"]
    return out

def flatten(orders):
    res = []
    for o in orders:
        res.append(o)
        for l in o.get("legs") or []: res.append(l)
    return res

def quotes_window(sym, t0, pre=60, post=2):
    """Return (quotes, feed). Try SIP (NBBO), fall back to IEX (IEX-only BBO, not NBBO)."""
    for feed in ("sip", "iex"):
        q = get(f"{DATA}/v2/stocks/{sym}/quotes", start=iso(t0 - timedelta(seconds=pre)),
                end=iso(t0 + timedelta(seconds=post)), feed=feed, limit=10000)
        if "_error" not in q and q.get("quotes"):
            return q["quotes"], feed, None
        err = q.get("_msg") if "_error" in q else "no quotes"
    return [], None, err

def arrival_quote(sym, t0):
    qs, feed, err = quotes_window(sym, t0)
    prior = [q for q in qs if ts(q["t"]) <= t0 and q["bp"] > 0 and q["ap"] > 0 and q["ap"] >= q["bp"]]
    if not prior:
        return None, feed, err or "no valid quote at/before submitted_at"
    q = prior[-1]
    return dict(bid=q["bp"], ask=q["ap"], mid=(q["bp"] + q["ap"]) / 2, qt=q["t"], bsz=q["bs"], asz=q["as"]), feed, None

def last_trade_before(sym, t0):
    for feed in ("sip", "iex"):
        r = get(f"{DATA}/v2/stocks/{sym}/trades", start=iso(t0 - timedelta(seconds=60)), end=iso(t0), feed=feed, limit=10000)
        if "_error" not in r and r.get("trades"):
            return r["trades"][-1]["p"], feed
    return None, None

def minute_bar(sym, t0):
    m = t0.replace(second=0, microsecond=0)
    for feed in ("sip", "iex"):
        r = get(f"{DATA}/v2/stocks/{sym}/bars", timeframe="1Min", start=iso(m), end=iso(m + timedelta(minutes=1)), feed=feed)
        if "_error" not in r and r.get("bars"):
            return r["bars"][0], feed
    return None, None

def daily_stats(sym, t0, n=20):
    d0 = et_date(t0)                                   # trading date in New York
    end = (d0 - timedelta(days=1)).strftime("%Y-%m-%d")
    start = (d0 - timedelta(days=60)).strftime("%Y-%m-%d")
    for feed in ("sip", "iex"):
        r = get(f"{DATA}/v2/stocks/{sym}/bars", timeframe="1Day", start=start, end=end, feed=feed, adjustment="all", limit=1000)
        if "_error" not in r and r.get("bars"):
            b = [x for x in r["bars"] if et_date(ts(x["t"])) < d0][-(n + 1):]
            if len(b) < n + 1: continue
            vols = [x["v"] for x in b[1:]]
            rets = [math.log(b[i]["c"] / b[i - 1]["c"]) for i in range(1, len(b))]
            adv = st.mean(vols)
            return dict(adv_sh=adv, adv_usd=st.mean([x["v"] * x["vw"] for x in b[1:]]),
                        sigma_d=st.stdev(rets), feed=feed, ndays=len(vols), last=b[-1]["t"][:10])
    return None

def tod_bucket(t):
    e = t.astimezone(ET)  # zoneinfo: EDT/EST chosen automatically per date
    mins = e.hour * 60 + e.minute
    if mins < 570: return "pre-market"
    if mins < 600: return "open 09:30-10:00 ET"
    if mins < 690: return "morning 10:00-11:30 ET"
    if mins < 840: return "midday 11:30-14:00 ET"
    if mins < 930: return "afternoon 14:00-15:30 ET"
    if mins < 960: return "close 15:30-16:00 ET"
    return "after-hours"

def liq_bucket(adv_usd):
    if adv_usd is None: return "unknown"
    if adv_usd >= 1e9: return "L1 mega (ADV>$1B)"
    if adv_usd >= 2e8: return "L2 large ($200M-1B)"
    if adv_usd >= 5e7: return "L3 mid ($50-200M)"
    return "L4 small (<$50M)"

def main():
    global H
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=f"{_QR.DESK_DIR}/tca")
    ap.add_argument("--k-low", type=float, default=0.5)
    ap.add_argument("--k-high", type=float, default=1.0)
    a = ap.parse_args()
    H = headers()
    os.makedirs(a.out, exist_ok=True)
    acct = get(TRADE + "/v2/account")
    positions = get(TRADE + "/v2/positions")
    orders = flatten(all_orders())
    fills = all_fills()
    by_order = {}
    for f in fills: by_order.setdefault(f["order_id"], []).append(f)
    rows, gaps = [], []
    for o in orders:
        sub = ts(o["submitted_at"]); fq = float(o["filled_qty"] or 0); q = float(o["qty"] or 0)
        row = dict(order_id=o["id"], symbol=o["symbol"], asset_class=o["asset_class"], side=o["side"],
                   type=o["type"], order_class=o["order_class"], tif=o["time_in_force"], status=o["status"],
                   qty=q, filled_qty=fq, fill_rate=(fq / q if q else None),
                   submitted_sgt=sgt(sub), filled_sgt=sgt(ts(o["filled_at"])),
                   limit_price=o["limit_price"], stop_price=o["stop_price"],
                   is_parent=bool(o.get("legs")), tod_bucket=tod_bucket(sub) if sub else "")
        fl = by_order.get(o["id"], [])
        row["n_fill_prints"] = len(fl)
        if fq > 0 and o["asset_class"] == "us_equity":
            px = float(o["filled_avg_price"])
            vwap_act = sum(float(x["qty"]) * float(x["price"]) for x in fl) / sum(float(x["qty"]) for x in fl) if fl else None
            first = min((ts(x["transaction_time"]) for x in fl), default=None)
            row.update(fill_px=px, fill_vwap_activities=vwap_act, notional=px * fq,
                       secs_to_first_fill=(first - sub).total_seconds() if first else None,
                       secs_to_complete=(ts(o["filled_at"]) - sub).total_seconds() if o["filled_at"] else None)
            sgn = 1 if o["side"] == "buy" else -1
            aq, feed, err = arrival_quote(o["symbol"], sub)
            lt, ltfeed = last_trade_before(o["symbol"], sub)
            mb, mbfeed = minute_bar(o["symbol"], sub)
            row.update(quote_feed=feed or "", last_trade_px=lt, last_trade_feed=ltfeed or "")
            if aq:
                row.update(arr_bid=aq["bid"], arr_ask=aq["ask"], arr_mid=aq["mid"], arr_quote_time_sgt=sgt(ts(aq["qt"])),
                           arr_bid_sz=aq["bsz"], arr_ask_sz=aq["asz"],
                           quoted_spread_bps=(aq["ask"] - aq["bid"]) / aq["mid"] * 1e4,
                           half_spread_bps=(aq["ask"] - aq["bid"]) / aq["mid"] * 1e4 / 2,
                           slippage_bps=sgn * (px - aq["mid"]) / aq["mid"] * 1e4,
                           effective_spread_bps=2 * sgn * (px - aq["mid"]) / aq["mid"] * 1e4,
                           arrival_source=f"NBBO mid ({feed})" if feed == "sip" else f"IEX BBO mid (NOT NBBO)")
            else:
                gaps.append(f"{o['symbol']} {o['id'][:8]}: no arrival quote ({err})")
                row["arrival_source"] = "MISSING quote"
            if lt:
                row["slippage_vs_last_trade_bps"] = sgn * (px - lt) / lt * 1e4
            if mb:
                row.update(bar1m_open=mb["o"], bar1m_vwap=mb["vw"], bar1m_feed=mbfeed,
                           slippage_vs_1m_vwap_bps=sgn * (px - mb["vw"]) / mb["vw"] * 1e4)
            ds = daily_stats(o["symbol"], sub)
            if ds:
                part = fq / ds["adv_sh"]
                row.update(adv20_sh=ds["adv_sh"], adv20_usd=ds["adv_usd"], adv_feed=ds["feed"], sigma_daily=ds["sigma_d"],
                           participation_pct_adv=part * 100,
                           impact_bps_k_low=a.k_low * ds["sigma_d"] * math.sqrt(part) * 1e4,
                           impact_bps_k_high=a.k_high * ds["sigma_d"] * math.sqrt(part) * 1e4,
                           liq_bucket=liq_bucket(ds["adv_usd"]))
                if ds["feed"] != "sip": gaps.append(f"{o['symbol']}: ADV from IEX-only volume (understates consolidated ADV)")
            else:
                gaps.append(f"{o['symbol']}: no daily bars for ADV/vol")
        elif fq > 0:
            gaps.append(f"{o['symbol']}: non-equity asset_class {o['asset_class']} not handled by this script version")
        rows.append(row)
    # CSV
    import csv
    cols = []
    for r in rows:
        for k in r:
            if k not in cols: cols.append(k)
    day = datetime.now(SGT).strftime("%Y%m%d")
    path = os.path.join(a.out, f"fills_{day}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
    # Aggregates
    filled = [r for r in rows if r.get("fill_px")]
    def agg(key):
        g = {}
        for r in filled: g.setdefault(r.get(key), []).append(r)
        out = {}
        for k, rs in g.items():
            def m(f, w=False):
                v = [(r[f], r["notional"]) for r in rs if r.get(f) is not None]
                if not v: return None
                return sum(x * n for x, n in v) / sum(n for _, n in v) if w else st.mean(x for x, _ in v)
            out[k] = dict(n=len(rs), notional=sum(r["notional"] for r in rs), slip_mean=m("slippage_bps"),
                          slip_wavg=m("slippage_bps", True), half_spread=m("half_spread_bps"),
                          slip_last=m("slippage_vs_last_trade_bps"), slip_vwap=m("slippage_vs_1m_vwap_bps"),
                          part=m("participation_pct_adv"), imp_lo=m("impact_bps_k_low"), imp_hi=m("impact_bps_k_high"))
        return out
    status_counts = {}
    for r in rows: status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    raw = dict(generated_sgt=datetime.now(SGT).strftime("%Y-%m-%d %H:%M SGT"),
               account={k: acct.get(k) for k in ("account_number", "status", "equity", "cash", "buying_power", "trading_blocked")},
               positions=[{k: p.get(k) for k in ("symbol", "qty", "avg_entry_price", "market_value")} for p in positions] if isinstance(positions, list) else positions,
               n_orders=len(rows), n_parents=sum(1 for r in rows if r["is_parent"] or r["order_class"] == "simple"),
               n_fill_activities=len(fills), status_counts=status_counts, rows=rows, gaps=sorted(set(gaps)),
               by_symbol=agg("symbol"), by_side=agg("side"), by_type=agg("type"), by_tod=agg("tod_bucket"),
               by_liq=agg("liq_bucket"), csv=path)
    vals = [r["slippage_bps"] for r in filled if r.get("slippage_bps") is not None]
    if vals:
        raw["overall"] = dict(slip_mean=st.mean(vals), slip_median=st.median(vals),
                              slip_wavg=sum(r["slippage_bps"] * r["notional"] for r in filled if r.get("slippage_bps") is not None) / sum(r["notional"] for r in filled if r.get("slippage_bps") is not None),
                              half_spread_mean=st.mean(r["half_spread_bps"] for r in filled if r.get("half_spread_bps") is not None))
    json.dump(raw, open(os.path.join(a.out, "tca_raw.json"), "w"), indent=1, default=str)
    print("wrote", path, "orders", len(rows), "filled", len(filled), "fill activities", len(fills))
    print(json.dumps(raw.get("overall"), indent=1)); print("gaps:", *raw["gaps"], sep="\n  ")

if __name__ == "__main__":
    main()
