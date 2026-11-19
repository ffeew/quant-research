from __future__ import annotations

import tomllib
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from quant_research.backtest.costs.model import (
    CommissionSchedule,
    CostSchedule,
    ImpactSpec,
    MarketState,
    Order,
    RegulatoryComponent,
    SpreadSpec,
    adverse_tick_round,
    ceil_cent,
    commission_cost,
    example_equity_schedule,
    exact,
    impact_cost,
    regulatory_fees,
    spread_cost,
    total_cost,
)

CONFIG_PATH = Path(__file__).resolve().parents[3] / "configs" / "costs" / "cost_model.toml"


def _order(
    side: str = "buy",
    quantity: str | int = 100,
    price: str | int = 100,
    unit: str = "share",
    multiplier: str | int = 1,
) -> Order:
    return Order(side=side, quantity=exact(quantity), price=exact(price), unit=unit, multiplier=exact(multiplier))  # type: ignore[arg-type]


def test_exact_and_reject() -> None:
    assert exact("0.01") == Fraction(1, 100)
    assert exact(Decimal("0.01")) == Fraction(1, 100)
    assert exact(0.01) == Fraction(1, 100)
    assert exact(2) == Fraction(2)
    for bad in (float("nan"), float("inf"), True, "NaN", "Infinity", "1,0", "", "abc", Decimal("NaN"), None, "0x10"):
        with pytest.raises((TypeError, ValueError)):
            exact(bad)  # type: ignore[arg-type]


def test_ceil_cent_edges() -> None:
    assert ceil_cent(exact("0")) == Fraction(0)
    assert ceil_cent(exact("0.01")) == exact("0.01")
    assert ceil_cent(exact("0.010000001")) == exact("0.02")
    assert ceil_cent(exact("0.0100000000000000000000000000000000000000000001")) == exact("0.02")
    assert ceil_cent(exact("1e-30")) == exact("0.01")
    assert ceil_cent(exact("0.29999999")) == exact("0.30")
    assert ceil_cent(exact("0.30")) == exact("0.30")
    assert ceil_cent(exact("0.30000001")) == exact("0.31")
    with pytest.raises(ValueError):
        ceil_cent(exact("-0.01"))


def test_zero_components() -> None:
    order = _order()
    market = MarketState()
    schedule = CostSchedule()
    breakdown = total_cost(order, market, schedule)
    assert breakdown.spread == 0
    assert breakdown.commission == 0
    assert breakdown.regulatory == 0
    assert breakdown.impact == 0
    assert breakdown.total == 0
    assert "spread missing" in " ".join(breakdown.notes)
    assert "adv missing" in " ".join(breakdown.notes)


def test_spread_half_and_fraction_agree() -> None:
    order = _order(price=100, quantity=50)
    market = MarketState(spread=exact("0.04"))  # 4 cents wide; half-spread 0.02
    half = spread_cost(order, market, SpreadSpec(mode="half_spread", fraction=exact(1)))[0]
    frac = spread_cost(order, market, SpreadSpec(mode="fraction_of_spread", fraction=exact("0.5")))[0]
    assert half == frac == exact("0.02") * 50


def test_spread_bps() -> None:
    order = _order(price=50, quantity=10)
    market = MarketState(spread_bps=exact("4"))  # 4 bps of mid = 0.02 full spread
    paid, _ = spread_cost(order, market, SpreadSpec())
    assert paid == exact("0.01") * 10


def test_spread_tick_floor_and_adverse_round() -> None:
    # mid 10, quoted spread 0 (would be zero), tick 0.01 -> half floored at 0.005
    # buy fill mid+0.005 adverse-rounds to 10.01
    order = _order(side="buy", price="10", quantity=100)
    market = MarketState(spread=exact("0"), tick=exact("0.01"))
    paid, _ = spread_cost(order, market, SpreadSpec())
    assert paid == exact("0.01") * 100
    sell = _order(side="sell", price="10", quantity=100)
    sold, _ = spread_cost(sell, market, SpreadSpec())
    assert sold == exact("0.01") * 100
    # already on a tick and paid width is exactly 1 tick: no extra step
    market2 = MarketState(spread=exact("0.02"), tick=exact("0.01"))
    assert spread_cost(order, market2, SpreadSpec())[0] == exact("0.01") * 100


def test_adverse_tick_round() -> None:
    tick = exact("0.05")
    assert adverse_tick_round(exact("1.00"), tick, is_buy=True) == exact("1.00")
    assert adverse_tick_round(exact("1.01"), tick, is_buy=True) == exact("1.05")
    assert adverse_tick_round(exact("1.01"), tick, is_buy=False) == exact("1.00")
    with pytest.raises(ValueError):
        adverse_tick_round(exact("1"), exact("0"), is_buy=True)


def test_commission_per_share_min_max_and_ceil() -> None:
    order = _order(quantity=10, price=20)
    raw = CommissionSchedule(per_share=exact("0.005"), per_order=exact("0"))
    # 0.05 exactly, no min
    assert commission_cost(order, raw, ceil_to_cent=True) == exact("0.05")
    # min binds
    floored = CommissionSchedule(per_share=exact("0.005"), min_per_order=exact("1.00"))
    assert commission_cost(order, floored, ceil_to_cent=True) == exact("1.00")
    # max binds before ceil: 10 * 0.5 = 5, cap 1.001 -> 1.001 then ceil 1.01
    capped = CommissionSchedule(per_share=exact("0.5"), max_per_order=exact("1.001"))
    assert commission_cost(order, capped, ceil_to_cent=True) == exact("1.01")
    # cap-before-ceil: raw 1.001 without max would ceil to 1.01 anyway; show a sub-cent cap
    tiny = CommissionSchedule(per_share=exact("0.0012"), max_per_order=exact("0.010000001"))
    # raw = 0.012, cap 0.010000001, then ceil -> 0.02
    assert commission_cost(order, tiny, ceil_to_cent=True) == exact("0.02")
    # zero quantity is rejected at Order construction
    with pytest.raises(ValueError):
        _order(quantity=0)


def test_commission_per_contract() -> None:
    order = _order(side="buy", quantity=4, price="1.50", unit="contract", multiplier=100)
    sched = CommissionSchedule(per_contract=exact("0.65"), min_per_order=exact("1.00"))
    # 4 * 0.65 = 2.60, min does not bind
    assert commission_cost(order, sched, ceil_to_cent=True) == exact("2.60")


def test_regulatory_cap_before_ceil() -> None:
    # TAF: 0.000195 * 60000 = 11.70 raw, cap 9.79, no further ceil change
    order = _order(side="sell", quantity=60_000, price=50)
    cap = exact("9.79")
    component = RegulatoryComponent(
        name="finra_taf",
        basis="per_share",
        applies_to="sell",
        rate=exact("0.000195"),
        cap=cap,
    )
    total, detail = regulatory_fees(order, (component,), trade_date=date(2027, 2, 1), ceil_to_cent=True)
    assert detail["finra_taf"] == cap
    assert total == cap
    # buy is not charged
    buy, buy_detail = regulatory_fees(
        _order(side="buy", quantity=60_000, price=50),
        (component,),
        trade_date=date(2027, 2, 1),
        ceil_to_cent=True,
    )
    assert buy == 0 and buy_detail["finra_taf"] == 0


def test_regulatory_cent_undercharge_case() -> None:
    # CAT raw = 0.000003 * 3333.3337 = 0.0100000011 -> ceil to 0.02
    order = _order(side="buy", quantity="3333.3337", price="50")
    component = RegulatoryComponent(name="cat", basis="per_share", applies_to="both", rate=exact("0.000003"))
    total, detail = regulatory_fees(order, (component,), trade_date=None, ceil_to_cent=True)
    assert detail["cat"] == exact("0.02")
    assert total == exact("0.02")


def test_options_per_contract_fees_generic() -> None:
    # Generic per-contract lines (example OCC / ORF-style rates). Not a trading claim.
    order = _order(side="sell", quantity=3, price="2.50", unit="contract", multiplier=100)
    occ = RegulatoryComponent(name="occ_clearing", basis="per_contract", applies_to="both", rate=exact("0.02"))
    orf = RegulatoryComponent(name="orf", basis="per_contract", applies_to="both", rate=exact("0.01"))
    total, detail = regulatory_fees(order, (occ, orf), trade_date=None, ceil_to_cent=True)
    assert detail["occ_clearing"] == exact("0.06")
    assert detail["orf"] == exact("0.03")
    assert total == exact("0.09")
    # notional uses the multiplier
    assert order.notional == exact("2.50") * 3 * 100


def test_impact_sqrt_and_linear() -> None:
    order = _order(quantity=100, price=10)
    market = MarketState(adv=exact(10_000), sigma=exact("0.02"))
    sqrt_usd, notes = impact_cost(order, market, ImpactSpec(model="sqrt", k=exact(1)))
    # participation 0.01, sqrt=0.1, k*sigma*load*notional = 1*0.02*0.1*1000 = 2
    assert notes == ()
    assert abs(float(sqrt_usd) - 2.0) < 1e-12
    linear, _ = impact_cost(order, market, ImpactSpec(model="linear", k=exact(1)))
    # 1*0.02*0.01*1000 = 0.2
    assert linear == exact("0.2")
    missing, miss_notes = impact_cost(order, MarketState(sigma=exact("0.02")), ImpactSpec())
    assert missing == 0 and "adv missing" in miss_notes[0]


def test_impact_unhaircut_no_venue_reduction() -> None:
    # Doubling k doubles impact; there is no hidden 0.5 venue haircut.
    order = _order(quantity=100, price=10)
    market = MarketState(adv=exact(10_000), sigma=exact("0.02"))
    one, _ = impact_cost(order, market, ImpactSpec(model="linear", k=exact(1)))
    two, _ = impact_cost(order, market, ImpactSpec(model="linear", k=exact(2)))
    assert two == 2 * one


def test_composed_total() -> None:
    order = _order(side="sell", quantity=100, price=100)
    market = MarketState(
        adv=exact(1_000_000),
        sigma=exact("0.02"),
        spread=exact("0.02"),
        tick=exact("0.01"),
        trade_date=date(2027, 2, 1),
    )
    breakdown = total_cost(order, market, example_equity_schedule())
    assert breakdown.total == breakdown.spread + breakdown.commission + breakdown.regulatory + breakdown.impact
    assert breakdown.total > 0
    assert breakdown.total_bps > 0
    assert breakdown.commission == 0
    # half-spread 0.01, already on a tick
    assert breakdown.spread == exact("0.01") * 100


def test_monotonicity_size_spread_vol() -> None:
    schedule = example_equity_schedule()
    base_market = MarketState(adv=exact(1_000_000), sigma=exact("0.02"), spread=exact("0.02"), trade_date=date(2027, 2, 1))

    def sell(qty: int, spread: str, sigma: str) -> Fraction:
        order = _order(side="sell", quantity=qty, price=50)
        market = MarketState(adv=exact(1_000_000), sigma=exact(sigma), spread=exact(spread), trade_date=date(2027, 2, 1))
        return total_cost(order, market, schedule).total

    quantities = [1, 2, 10, 100, 1_000, 10_000, 80_000]
    totals = [sell(q, "0.02", "0.02") for q in quantities]
    assert all(totals[i] <= totals[i + 1] for i in range(len(totals) - 1)), totals

    spreads = ["0", "0.01", "0.02", "0.05", "0.10"]
    stotals = [sell(100, s, "0.02") for s in spreads]
    assert all(stotals[i] <= stotals[i + 1] for i in range(len(stotals) - 1)), stotals

    sigmas = ["0", "0.01", "0.02", "0.05", "0.10"]
    vtotals = [sell(100, "0.02", s) for s in sigmas]
    assert all(vtotals[i] <= vtotals[i + 1] for i in range(len(vtotals) - 1)), vtotals
    # unused base_market keeps the default shape documented
    assert base_market.spread == exact("0.02")


def test_config_matches_example_schedule() -> None:
    data = tomllib.loads(CONFIG_PATH.read_text())
    from_file = CostSchedule.from_mapping(data)
    example = example_equity_schedule()
    assert from_file.ceil_fees_to_cent is True
    assert from_file.commission == example.commission
    assert from_file.spread == example.spread
    assert from_file.impact == example.impact
    assert len(from_file.regulatory) == len(example.regulatory)
    for a, b in zip(from_file.regulatory, example.regulatory, strict=True):
        assert a.name == b.name
        assert a.basis == b.basis
        assert a.applies_to == b.applies_to
        assert a.rate == b.rate
        assert a.cap == b.cap
        assert a.min_price == b.min_price
