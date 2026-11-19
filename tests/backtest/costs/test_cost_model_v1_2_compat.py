from __future__ import annotations

"""Equivalence: the typed cost module reproduces the versioned fee and unhaircut impact numbers."""

import math
from datetime import date

import pytest

from quant_research.backtest.costs.cost_model_v1_2 import regulatory_fees_usd as v12_fees
from quant_research.backtest.costs.model import (
    CommissionSchedule,
    CostSchedule,
    ImpactSpec,
    MarketState,
    Order,
    RegulatoryComponent,
    exact,
    impact_cost,
    regulatory_fees,
)


def _order(
    side: str = "buy",
    quantity: str | int = 100,
    price: str | int = 100,
    unit: str = "share",
    multiplier: str | int = 1,
) -> Order:
    return Order(side=side, quantity=exact(quantity), price=exact(price), unit=unit, multiplier=exact(multiplier))  # type: ignore[arg-type]


def _v12_equivalent_schedule(include_taf_holiday: bool) -> CostSchedule:
    taf = RegulatoryComponent(
        name="taf_usd",
        basis="per_share",
        applies_to="sell",
        rate=exact("0.000195"),
        cap=exact("9.79"),
        min_price=exact("0.000195"),
        inactive_from=date(2026, 10, 1) if include_taf_holiday else None,
        inactive_to=date(2026, 12, 31) if include_taf_holiday else None,
    )
    return CostSchedule(
        commission=CommissionSchedule(),
        regulatory=(
            RegulatoryComponent(
                name="sec_usd",
                basis="per_dollar_notional",
                applies_to="sell",
                rate=exact("0.0000206"),
            ),
            taf,
            RegulatoryComponent(name="cat_usd", basis="per_share", applies_to="both", rate=exact("0.000003")),
        ),
        ceil_fees_to_cent=True,
    )


@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize("price,shares", [("50", "100"), ("50", "3333.3337"), ("100.1", "1"), ("0.0001", "1000"), ("50", "60000")])
@pytest.mark.parametrize("trade_date", [date(2026, 10, 30), date(2027, 2, 1)])
def test_regulatory_equivalence_with_v1_2(side: str, price: str, shares: str, trade_date: date) -> None:
    """Migrating a v1.2 regulatory-fee call to the new schedule yields identical component amounts."""
    schedule = _v12_equivalent_schedule(include_taf_holiday=True)
    order = _order(side=side, quantity=shares, price=price)
    new_total, detail = regulatory_fees(
        order, schedule.regulatory, trade_date=trade_date, ceil_to_cent=True
    )
    legacy = v12_fees(side, price, shares, trade_date, True)
    assert detail["sec_usd"] == exact(str(legacy["sec_usd_exact"]))
    assert detail["taf_usd"] == exact(str(legacy["taf_usd_exact"]))
    assert detail["cat_usd"] == exact(str(legacy["cat_usd_exact"]))
    assert new_total == exact(str(legacy["fees_usd_exact"]))
    assert float(new_total) == legacy["fees_usd"]


def test_impact_equivalence_unhaircut_v1_2_formula() -> None:
    """Square-root impact matches the unhaircut v1.2 formula (venue multiplier = 1)."""
    price, shares, adv, sigma, k = 100.0, 50.0, 5_000_000.0, 0.02, 1.0
    expected = k * sigma * math.sqrt(shares / adv) * price * shares
    order = _order(quantity="50", price="100")
    market = MarketState(adv=exact("5000000"), sigma=exact("0.02"))
    got, _ = impact_cost(order, market, ImpactSpec(model="sqrt", k=exact("1")))
    assert abs(float(got) - expected) < 1e-9
