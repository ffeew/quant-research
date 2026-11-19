#!/usr/bin/env python3
"""Plug-in per-trade cost model for backtests (US equities/ETFs, Alpaca).  v1.1

Owner: Tomas (Execution & TCA). Spec, sources and assumptions: $QR_DESK_DIR/tca/cost_model.md
Pure functions: no network, no broker calls, no orders.

one-way cost_bps = fees + half_spread*venue_mult + impact*venue_mult + paper_buffer
  fees        : commission $0 (Alpaca); SEC Sec.31 + FINRA TAF on sells (TAF $0 for trades 1 Oct-31 Dec 2026); CAT both sides
  half-spread : spread_bps / 2 (crossing); bucket default if no quote
  impact      : k * sigma_daily * sqrt(shares / adv_shares) * 1e4   (square-root law; k=1.0 conservative default)
  venue       : 'continuous' | 'close' (MOC/LOC, Alpaca tif='cls') | 'open' (MOO/LOO, Alpaca tif='opg')
  buffer      : paper->live optimism, bucket default (assumption)
holding cost: borrow_cost() = short market value x annual rate x days/360 (ETB S&P 500 default 25 bps/yr, assumption)

Usage:
    import sys; sys.path.insert(0, "src/quant_research/backtest/costs")
    from cost_model import trade_cost, round_trip_cost_bps, borrow_cost, annual_cost_drag, net_edge, impact_grid
    c = trade_cost("sell", price=100, shares=50, adv_shares=5e6, sigma_daily=0.02, spread_bps=2.0)
    c["total_bps"], c["total_usd"], c["warnings"]
    borrow_cost(short_mv_usd=50_000, days=30)["usd"]
    annual_cost_drag(per_rebalance_turnover=0.5, rebalances_per_year=12, one_way_cost_bps=6.0, short_frac_of_gross=0.5)
"""
from __future__ import annotations
import math
from datetime import date

# Regulatory fee constants. Verified 30 Oct 2026. Re-check them when the SEC or FINRA announce changes.
SEC_FEE_PER_DOLLAR = 20.60e-6          # $20.60 per $1M of covered sales, effective 4 Apr 2026 (SEC fee rate advisory FY2026)
TAF_PER_SHARE = 0.000195               # FINRA TAF, covered equity sales, 2026 rate; 2027-28 unchanged (SR-FINRA-2026-020)
TAF_MAX_PER_TRADE = 9.79
TAF_HOLIDAY = (date(2026, 10, 1), date(2026, 12, 31))   # TAF set to $0 for these trade dates (SR-FINRA-2026-021)
CAT_PER_SHARE = 0.000003               # Alpaca pass-through CAT fee, NMS equities, buys and sells (Alpaca fee schedule, Oct 2026)

# Literature-based assumption: k = 1.0 is conservative. Implied large-cap range is 0.3-0.65 (Almgren et al. 2005 Table 3);
# Toth et al. (2011) give "Y of order unity"; tca.py uses a 0.5-1.0 band.
K_IMPACT_DEFAULT = 1.0

# Default parameters by liquidity bucket (ADV in USD). Bucket edges match tca.py liq_bucket().
# These are DESK ASSUMPTIONS, not measured values. Replace them with measured per-name spread/sigma when available.
BUCKETS = {
    #  name                         min ADV$   half_spread_bps  sigma_daily  paper_buffer_bps
    # v1.1: aligned with baseline_report.md section 5 (01:12 SGT). L1 half-spread 2.75 = pilot mean (DATA, n=5, one
    # midday session); all other values are ASSUMPTIONS. Buffer = baseline_report "H haircut" (paper residual measured 0.40 bps).
    "L1 mega (ADV>$1B)":           (1e9,       2.75,            0.015,       2.0),
    "L2 large ($200M-1B)":         (2e8,       5.0,             0.020,       4.0),
    "L3 mid ($50-200M)":           (5e7,       12.0,            0.025,       8.0),
    "L4 small (<$50M)":            (0.0,       30.0,            0.035,       15.0),
}
# Venue multipliers on (half_spread, impact) RELATIVE TO THE BACKTEST'S REFERENCE PRICE. ASSUMPTIONS:
#  continuous: reference = arrival NBBO mid -> pay full half-spread and full impact.
#  close     : reference = official closing auction print; a MOC fill IS that print -> no spread vs reference.
#              Impact halved: Bogousslavsky & Muravyev (2023, JFM) find auction price impact lower than in
#              continuous trading. The 0.5 factor is our assumption, not their estimate.
#  open      : reference = official opening print; same logic, but we keep 0.5x half-spread as a conservative
#              allowance for noisier opening prints (unverified assumption).
VENUES = {"continuous": (1.0, 1.0), "close": (0.0, 0.5), "open": (0.5, 1.0)}
# Annual stock-borrow assumption for easy-to-borrow S&P 500 shorts. D'Avolio (2002, JFE): general-collateral loans
# averaged 17 bps p.a. and the value-weighted fee was 0.25% p.a. Alpaca charges $0 borrow on ETB shares
# (fee schedule, Oct 2026), so 25 bps is a conservative backtest assumption.
BORROW_RATE_ETB_DEFAULT = 0.0025
MAX_RELIABLE_PARTICIPATION = 0.10   # impact fits are unreliable beyond ~10% of ADV (FIM range <=13%; Almgren: "a few %")


def liq_bucket(adv_usd: float) -> str:
    for name, (lo, *_rest) in BUCKETS.items():
        if adv_usd >= lo:
            return name
    return "L4 small (<$50M)"


def _ceil_cent(x: float) -> float:
    return math.ceil(round(x * 100, 6)) / 100.0 if x > 0 else 0.0


def regulatory_fees_usd(side: str, price: float, shares: float, trade_date: date | None = None,
                        round_per_trade: bool = True) -> dict:
    """Return the SEC, TAF and CAT fees in USD for one fill/order. Sells pay SEC and TAF; both sides pay CAT."""
    trade_date = trade_date or date.today()
    notional = abs(price * shares)
    sell = side.lower() in ("sell", "sell_short", "short")
    sec = SEC_FEE_PER_DOLLAR * notional if sell else 0.0
    taf = 0.0
    if sell and not (TAF_HOLIDAY[0] <= trade_date <= TAF_HOLIDAY[1]) and price >= TAF_PER_SHARE:
        taf = min(TAF_PER_SHARE * abs(shares), TAF_MAX_PER_TRADE)
    cat = CAT_PER_SHARE * abs(shares)
    if round_per_trade:  # Alpaca rounds fees up to the cent; rounding per trade is the conservative choice
        sec, taf, cat = _ceil_cent(sec), _ceil_cent(taf), _ceil_cent(cat)
    return {"sec_usd": sec, "taf_usd": taf, "cat_usd": cat, "fees_usd": sec + taf + cat}


def trade_cost(side: str, price: float, shares: float, adv_shares: float | None = None,
               sigma_daily: float | None = None, spread_bps: float | None = None, *,
               k: float = K_IMPACT_DEFAULT, paper_buffer_bps: float | None = None,
               crossing: bool = True, venue: str = "continuous", trade_date: date | None = None,
               round_fees_per_trade: bool = True) -> dict:
    """One-way expected cost of a single order.

    side        'buy' or 'sell'
    price       reference price (arrival mid), in $
    shares      order size, in shares (positive)
    adv_shares  average daily volume in shares (20d). If None, impact is set to 0 and a warning is added.
    sigma_daily daily return volatility as a decimal (0.02 = 2%). None -> bucket default
    spread_bps  quoted bid-ask spread in bps of mid (full spread). None -> 2 x bucket half-spread default
    k           square-root impact coefficient (default 1.0, conservative)
    paper_buffer_bps  extra bps for paper->live optimism. None -> bucket default
    crossing    True for marketable orders (pay half-spread). False for passive fills (half-spread = 0; track fill rate!)
    venue       'continuous' (vs arrival mid) | 'close' (MOC/LOC vs official close) | 'open' (MOO/LOO vs official open)
    Returns a dict with bps (relative to notional) and USD for each component, plus total_bps and total_usd.
    """
    if price <= 0 or shares <= 0:
        raise ValueError("price and shares must be positive")
    notional = price * shares
    warnings = []
    adv_usd = adv_shares * price if adv_shares else 0.0
    bucket = liq_bucket(adv_usd) if adv_shares else "L4 small (<$50M)"
    _, hs_def, sig_def, buf_def = BUCKETS[bucket]
    if sigma_daily is None:
        sigma_daily = sig_def
        warnings.append(f"sigma_daily defaulted to {sig_def} ({bucket})")
    half_spread_bps = (spread_bps / 2.0) if spread_bps is not None else hs_def
    if spread_bps is None:
        warnings.append(f"half-spread defaulted to {hs_def} bps ({bucket})")
    if venue not in VENUES:
        raise ValueError(f"venue must be one of {list(VENUES)}")
    hs_mult, imp_mult = VENUES[venue]
    half_spread_bps *= hs_mult
    if not crossing:
        half_spread_bps = 0.0
    participation = shares / adv_shares if adv_shares else float("nan")
    if adv_shares:
        impact_bps = imp_mult * k * sigma_daily * math.sqrt(participation) * 1e4
        if participation > MAX_RELIABLE_PARTICIPATION:
            warnings.append(f"participation {participation:.1%} of ADV > {MAX_RELIABLE_PARTICIPATION:.0%}: impact model unreliable, split the order")
    else:
        impact_bps = 0.0
        warnings.append("adv_shares missing: impact set to 0")
    buffer_bps = buf_def if paper_buffer_bps is None else paper_buffer_bps
    fees = regulatory_fees_usd(side, price, shares, trade_date, round_fees_per_trade)
    fees_bps = fees["fees_usd"] / notional * 1e4
    total_bps = fees_bps + half_spread_bps + impact_bps + buffer_bps
    to_usd = lambda b: b * notional / 1e4
    return {
        "side": side, "venue": venue, "notional_usd": notional, "bucket": bucket, "participation": participation,
        "fees_bps": fees_bps, "half_spread_bps": half_spread_bps, "impact_bps": impact_bps,
        "paper_buffer_bps": buffer_bps, "total_bps": total_bps,
        "fees_usd": fees["fees_usd"], "half_spread_usd": to_usd(half_spread_bps),
        "impact_usd": to_usd(impact_bps), "paper_buffer_usd": to_usd(buffer_bps),
        "total_usd": to_usd(total_bps), "fee_detail": fees, "k": k, "sigma_daily": sigma_daily,
        "warnings": warnings,
    }


def round_trip_cost_bps(price, shares, adv_shares=None, sigma_daily=None, spread_bps=None, **kw) -> float:
    """Entry plus exit cost in bps of notional. Buy then sell (long). For a short, the costs are the same:
    SEC/TAF are paid on the sell leg either way. Borrow fees are NOT included."""
    b = trade_cost("buy", price, shares, adv_shares, sigma_daily, spread_bps, **kw)
    s = trade_cost("sell", price, shares, adv_shares, sigma_daily, spread_bps, **kw)
    return b["total_bps"] + s["total_bps"]


def net_edge(gross_edge_bps_per_trade: float, rt_cost_bps: float, stress_mult: float = 2.0) -> dict:
    """Per-round-trip break-even check (see cost_model.md section d)."""
    net = gross_edge_bps_per_trade - rt_cost_bps
    net_stress = gross_edge_bps_per_trade - stress_mult * rt_cost_bps
    ratio = rt_cost_bps / gross_edge_bps_per_trade if gross_edge_bps_per_trade > 0 else float("inf")
    if net <= 0:
        flag = "FAIL: edge vanishes after base costs"
    elif net_stress <= 0 or ratio > 0.5:
        flag = "WARN: cost-fragile (fails at stressed costs or costs >50% of gross)"
    else:
        flag = "PASS"
    return {"gross_bps": gross_edge_bps_per_trade, "rt_cost_bps": rt_cost_bps, "net_bps": net,
            "net_stress_bps": net_stress, "cost_to_gross": ratio, "flag": flag}


def annual_net(gross_ann_return: float, annual_turnover: float, one_way_cost_bps: float) -> dict:
    """Portfolio level. annual_turnover = sum over the year of |delta weight| (one-way, as a fraction of book per year).
    cost drag = annual_turnover * one_way_cost. Break-even one-way cost = gross / turnover."""
    drag = annual_turnover * one_way_cost_bps / 1e4
    be = (gross_ann_return / annual_turnover * 1e4) if annual_turnover > 0 else float("inf")
    return {"gross": gross_ann_return, "cost_drag": drag, "net": gross_ann_return - drag,
            "breakeven_one_way_cost_bps": be}


def borrow_cost(short_mv_usd: float, days: float = 365, annual_rate: float = BORROW_RATE_ETB_DEFAULT,
                round_lot: bool = False, price: float | None = None, shares: float | None = None) -> dict:
    """Stock-borrow cost of holding a short for `days` calendar days (360-day convention, accrues weekends).
    annual_rate defaults to 25 bps (ETB assumption). For HTB names pass the quoted rate.
    round_lot=True mimics Alpaca HTB billing: shares rounded up to 100 and collateral = ceil(price*1.02).
    Alpaca paper does NOT charge borrow fees, so this cost must be added in the backtest."""
    mv = short_mv_usd
    if round_lot and price and shares:
        mv = math.ceil(abs(shares) / 100) * 100 * math.ceil(price * 1.02)
    usd = abs(mv) * annual_rate * days / 360.0
    return {"usd": usd, "bps_of_short_mv": (usd / abs(short_mv_usd) * 1e4) if short_mv_usd else 0.0,
            "annual_rate": annual_rate, "days": days}


def annual_cost_drag(per_rebalance_turnover: float, rebalances_per_year: float, one_way_cost_bps: float,
                     short_frac_of_gross: float = 0.5, borrow_rate: float = BORROW_RATE_ETB_DEFAULT,
                     gross_leverage: float = 1.0) -> dict:
    """Annual cost drag of a rebalanced (long-short) book.
    per_rebalance_turnover = traded notional per rebalance / gross book (one-way; buys + sells both counted)
    annual_turnover T      = per_rebalance_turnover * rebalances_per_year
    trading drag (of gross)= T * one_way_cost_bps / 1e4
    borrow drag (of gross) = short_frac_of_gross * borrow_rate        (0.5 for a dollar-neutral book)
    of equity              = (trading + borrow) * gross_leverage       (gross_leverage = gross / equity)"""
    T = per_rebalance_turnover * rebalances_per_year
    trading = T * one_way_cost_bps / 1e4
    borrow = short_frac_of_gross * borrow_rate
    return {"annual_turnover": T, "trading_drag_gross": trading, "borrow_drag_gross": borrow,
            "total_drag_gross": trading + borrow, "total_drag_equity": (trading + borrow) * gross_leverage}


def impact_grid(participations=(1e-5, 1e-4, 1e-3, 0.01, 0.05, 0.10), k: float = K_IMPACT_DEFAULT) -> dict:
    """One-way half-spread + impact (bps) by bucket (default sigma/spread) and participation Q/ADV. Excludes fees/buffer."""
    out = {}
    for name, (_lo, hs, sig, _buf) in BUCKETS.items():
        out[name] = {p: hs + k * sig * math.sqrt(p) * 1e4 for p in participations}
    return out


def _self_test():
    d_hol, d_norm = date(2026, 10, 30), date(2027, 1, 15)
    # 1) Fees: $10,000 sell of 100 sh at $100. SEC = 0.206 -> $0.21; TAF on holiday = 0; CAT = 0.0003 -> $0.01
    f = regulatory_fees_usd("sell", 100.0, 100, d_hol)
    assert f["sec_usd"] == 0.21 and f["taf_usd"] == 0.0 and f["cat_usd"] == 0.01, f
    f2 = regulatory_fees_usd("sell", 100.0, 100, d_norm)
    assert abs(f2["taf_usd"] - 0.02) < 1e-9, f2            # 100*0.000195 = 0.0195 -> $0.02
    f3 = regulatory_fees_usd("sell", 10.0, 1_000_000, d_norm, round_per_trade=False)
    assert abs(f3["taf_usd"] - TAF_MAX_PER_TRADE) < 1e-9   # cap binds
    fb = regulatory_fees_usd("buy", 100.0, 100, d_hol)
    assert fb["sec_usd"] == 0 and fb["taf_usd"] == 0 and fb["cat_usd"] == 0.01
    # 2) Impact: sigma 2%, Q/ADV = 1% -> k*0.02*0.1*1e4 = 20 bps at k=1
    c = trade_cost("buy", 50.0, 50_000, adv_shares=5_000_000, sigma_daily=0.02, spread_bps=4.0,
                   paper_buffer_bps=0.0, trade_date=d_hol)
    assert abs(c["impact_bps"] - 20.0) < 1e-9 and abs(c["half_spread_bps"] - 2.0) < 1e-12, c
    # 3) Tiny desk-sized order in a mega-cap: impact is negligible, so spread + buffer dominate
    c = trade_cost("sell", 200.0, 50, adv_shares=30_000_000, sigma_daily=0.015, spread_bps=1.0, trade_date=d_hol)
    assert c["bucket"].startswith("L1") and c["impact_bps"] < 0.2 and c["total_bps"] < 3.0, c
    # 4) Passive fill pays no half-spread
    assert trade_cost("buy", 20.0, 100, 1e6, 0.03, 10.0, crossing=False)["half_spread_bps"] == 0.0
    # 5) Over-participation warning
    assert any("unreliable" in w for w in trade_cost("buy", 10.0, 200_000, 1e6, 0.03, 10.0)["warnings"])
    # 6) Break-even logic
    assert net_edge(10, 12)["flag"].startswith("FAIL")
    assert net_edge(10, 6)["flag"].startswith("WARN")
    assert net_edge(10, 3)["flag"] == "PASS"
    a = annual_net(0.08, 10.0, 5.0)   # 8% gross, 10x one-way turnover, 5 bps -> 0.5% drag
    assert abs(a["cost_drag"] - 0.005) < 1e-12 and abs(a["breakeven_one_way_cost_bps"] - 80) < 1e-9
    # 7) Venues: MOC has no spread vs the close print and half the impact
    cc = trade_cost("buy", 50.0, 50_000, 5_000_000, 0.02, 4.0, paper_buffer_bps=0.0, venue="close", trade_date=d_hol)
    assert cc["half_spread_bps"] == 0.0 and abs(cc["impact_bps"] - 10.0) < 1e-9, cc
    co = trade_cost("buy", 50.0, 50_000, 5_000_000, 0.02, 4.0, paper_buffer_bps=0.0, venue="open", trade_date=d_hol)
    assert abs(co["half_spread_bps"] - 1.0) < 1e-12 and abs(co["impact_bps"] - 20.0) < 1e-9, co
    # 8) Borrow: $100k short for 360 days at 25 bps = $250; Alpaca HTB-style round lot
    assert abs(borrow_cost(100_000, 360)["usd"] - 250.0) < 1e-9
    b = borrow_cost(205.0, 1, 0.025, round_lot=True, price=205.0, shares=1)   # 100 sh x ceil(209.1)=210 -> $21,000
    assert abs(b["usd"] - 21_000 * 0.025 / 360) < 1e-9
    # 9) Annual drag formula: monthly 50% per rebalance, 6 bps one-way, dollar-neutral, 25 bps borrow
    m = annual_cost_drag(0.5, 12, 6.0)
    assert abs(m["annual_turnover"] - 6) < 1e-12 and abs(m["trading_drag_gross"] - 0.0036) < 1e-12
    assert abs(m["borrow_drag_gross"] - 0.00125) < 1e-12
    # Print the default round-trip table at $10k notional (desk clip)
    print("Self-test passed (v1.1). Default round trip at $10k notional (trade date 2026-10-30, TAF holiday):")
    print(f"{'bucket':24s} {'ADV$':>8s} {'RT bps':>7s} {'RT $':>6s}  (fees / spread / impact / buffer, one-way sell)")
    for name, adv_usd in [("L1", 2e9), ("L2", 5e8), ("L3", 1e8), ("L4", 2e7)]:
        px = 50.0; sh = 10_000 / px; adv_sh = adv_usd / px
        rt = round_trip_cost_bps(px, sh, adv_sh, trade_date=d_hol)
        s = trade_cost("sell", px, sh, adv_sh, trade_date=d_hol)
        print(f"{s['bucket']:24s} {adv_usd/1e6:7.0f}M {rt:7.2f} {rt*10_000/1e4:6.2f}  "
              f"({s['fees_bps']:.2f} / {s['half_spread_bps']:.2f} / {s['impact_bps']:.2f} / {s['paper_buffer_bps']:.2f})")
    print("\nHalf-spread + impact (bps, one-way, k=1, bucket default sigma/spread) by participation Q/ADV:")
    g = impact_grid()
    ps = list(next(iter(g.values())).keys())
    print(f"{'bucket':24s} " + " ".join(f"{p:>8.3%}" for p in ps))
    for name, row in g.items():
        print(f"{name:24s} " + " ".join(f"{v:8.2f}" for v in row.values()))
    print("\nIllustrative annual drag (formula demo, hypothetical turnover inputs; NOT strategy results):")
    for lbl, tau, n, c in [("monthly, 50%/rebal, 6 bps", 0.5, 12, 6.0), ("daily, 10%/rebal, 6 bps", 0.10, 252, 6.0),
                           ("daily, 10%/rebal, 3 bps (MOC)", 0.10, 252, 3.0)]:
        r = annual_cost_drag(tau, n, c)
        print(f"  {lbl:32s} T={r['annual_turnover']:6.1f}x  trading={r['trading_drag_gross']:.2%}  "
              f"borrow={r['borrow_drag_gross']:.3%}  total={r['total_drag_gross']:.2%} of gross")


if __name__ == "__main__":
    _self_test()
