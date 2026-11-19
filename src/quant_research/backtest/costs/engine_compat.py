"""Engine-facing cost adapter that reproduces cost_model v1.1 totals.

The typed cost model in ``quant_research.backtest.costs.model`` uses exact
Fraction fee arithmetic, unhaircut impact, and has no bucket defaults, venue
multipliers, or paper buffer. The backtest engine previously called
``cost_model.trade_cost`` (v1.1) and its outputs must not move.

This adapter composes the same one-way components the engine reads
(``total_bps``, ``bucket``, ``participation``, and the v1.1 fee cent-ceiling)
with v1.1 float arithmetic, including the known v1.1 undercharge on some
sub-cent raw fees (``ceil(round(x * 100, 6)) / 100``). It does not change the
typed model's exact path.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TypedDict

# v1.1 published-example rates (same values as cost_model v1.1).
SEC_FEE_PER_DOLLAR = 20.60e-6
TAF_PER_SHARE = 0.000195
TAF_MAX_PER_TRADE = 9.79
TAF_HOLIDAY = (date(2026, 10, 1), date(2026, 12, 31))
CAT_PER_SHARE = 0.000003
K_IMPACT_DEFAULT = 1.0

# (min ADV USD, half_spread_bps, sigma_daily, paper_buffer_bps)
BUCKETS: dict[str, tuple[float, float, float, float]] = {
    "L1 mega (ADV>$1B)": (1e9, 2.75, 0.015, 2.0),
    "L2 large ($200M-1B)": (2e8, 5.0, 0.020, 4.0),
    "L3 mid ($50-200M)": (5e7, 12.0, 0.025, 8.0),
    "L4 small (<$50M)": (0.0, 30.0, 0.035, 15.0),
}
# (half_spread multiplier, impact multiplier) relative to the backtest reference price.
VENUES: dict[str, tuple[float, float]] = {
    "continuous": (1.0, 1.0),
    "close": (0.0, 0.5),
    "open": (0.5, 1.0),
}
MAX_RELIABLE_PARTICIPATION = 0.10


class TradeCostResult(TypedDict):
    side: str
    venue: str
    notional_usd: float
    bucket: str
    participation: float
    fees_bps: float
    half_spread_bps: float
    impact_bps: float
    paper_buffer_bps: float
    total_bps: float
    fees_usd: float
    half_spread_usd: float
    impact_usd: float
    paper_buffer_usd: float
    total_usd: float
    fee_detail: dict[str, float]
    k: float
    sigma_daily: float
    warnings: list[str]


def liq_bucket(adv_usd: float) -> str:
    for name, (lo, *_rest) in BUCKETS.items():
        if adv_usd >= lo:
            return name
    return "L4 small (<$50M)"


def _ceil_cent_v11(x: float) -> float:
    """v1.1 cent ceiling: ceil(round(x * 100, 6)) / 100. Preserved for engine identity."""
    return math.ceil(round(x * 100, 6)) / 100.0 if x > 0 else 0.0


def regulatory_fees_usd(
    side: str,
    price: float,
    shares: float,
    trade_date: date | None = None,
    round_per_trade: bool = True,
) -> dict[str, float]:
    """v1.1 regulatory fees in USD (float path, including the v1.1 cent-ceiling)."""
    if trade_date is None:
        trade_date = date.today()
    notional = abs(price * shares)
    sell = side.lower() in ("sell", "sell_short", "short")
    sec = SEC_FEE_PER_DOLLAR * notional if sell else 0.0
    taf = 0.0
    if sell and not (TAF_HOLIDAY[0] <= trade_date <= TAF_HOLIDAY[1]) and price >= TAF_PER_SHARE:
        taf = min(TAF_PER_SHARE * abs(shares), TAF_MAX_PER_TRADE)
    cat = CAT_PER_SHARE * abs(shares)
    if round_per_trade:
        sec, taf, cat = _ceil_cent_v11(sec), _ceil_cent_v11(taf), _ceil_cent_v11(cat)
    return {"sec_usd": sec, "taf_usd": taf, "cat_usd": cat, "fees_usd": sec + taf + cat}


def trade_cost(
    side: str,
    price: float,
    shares: float,
    adv_shares: float | None = None,
    sigma_daily: float | None = None,
    spread_bps: float | None = None,
    *,
    k: float = K_IMPACT_DEFAULT,
    paper_buffer_bps: float | None = None,
    crossing: bool = True,
    venue: str = "continuous",
    trade_date: date | None = None,
    round_fees_per_trade: bool = True,
) -> TradeCostResult:
    """One-way expected cost, v1.1-identical floats, for the backtest engine."""
    if price <= 0 or shares <= 0:
        raise ValueError("price and shares must be positive")
    notional = price * shares
    warnings: list[str] = []
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
        # Float square-root, matching v1.1 (not the typed model's Decimal sqrt).
        impact_bps = imp_mult * k * sigma_daily * math.sqrt(participation) * 1e4
        if participation > MAX_RELIABLE_PARTICIPATION:
            warnings.append(
                f"participation {participation:.1%} of ADV > {MAX_RELIABLE_PARTICIPATION:.0%}: "
                "impact model unreliable, split the order"
            )
    else:
        impact_bps = 0.0
        warnings.append("adv_shares missing: impact set to 0")
    buffer_bps = buf_def if paper_buffer_bps is None else paper_buffer_bps
    fees = regulatory_fees_usd(side, price, shares, trade_date, round_fees_per_trade)
    fees_bps = fees["fees_usd"] / notional * 1e4
    total_bps = fees_bps + half_spread_bps + impact_bps + buffer_bps

    def to_usd(bps: float) -> float:
        return bps * notional / 1e4

    return {
        "side": side,
        "venue": venue,
        "notional_usd": notional,
        "bucket": bucket,
        "participation": participation,
        "fees_bps": fees_bps,
        "half_spread_bps": half_spread_bps,
        "impact_bps": impact_bps,
        "paper_buffer_bps": buffer_bps,
        "total_bps": total_bps,
        "fees_usd": fees["fees_usd"],
        "half_spread_usd": to_usd(half_spread_bps),
        "impact_usd": to_usd(impact_bps),
        "paper_buffer_usd": to_usd(buffer_bps),
        "total_usd": to_usd(total_bps),
        "fee_detail": fees,
        "k": k,
        "sigma_daily": sigma_daily,
        "warnings": warnings,
    }
