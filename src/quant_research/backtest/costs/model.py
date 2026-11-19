"""Typed one-way transaction-cost model: spread, commission, regulatory fees, and impact.

This module is pure: no I/O, no network, and no broker or order placement. Fee rates and
model coefficients are supplied by the caller (see ``CostSchedule`` and ``configs/costs/cost_model.toml``).
Per-contract fee components are supported generically; their presence is not a claim that
any listed instrument is traded.

Fee arithmetic follows cap-before-ceil, per component, with exact ``Fraction`` values and no
pre-rounding of notional or quantity. Impact is unhaircut: no venue or auction reduction is
applied inside this module.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Literal

Side = Literal["buy", "sell"]
Unit = Literal["share", "contract"]
ImpactModel = Literal["sqrt", "linear"]
FeeBasis = Literal["per_dollar_notional", "per_share", "per_contract", "per_order"]
AppliesTo = Literal["buy", "sell", "both"]
SpreadMode = Literal["half_spread", "fraction_of_spread"]

_DEC_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_CENT = Fraction(1, 100)
_BPS = Fraction(10_000)


def exact(value: Fraction | Decimal | int | str | float) -> Fraction:
    """Exact rational from ``str`` / ``Decimal`` / ``int`` / ``Fraction``.

    A binary ``float`` is converted through its shortest round-trip repr
    (for example ``0.01`` becomes ``Decimal("0.01")``), i.e. the decimal
    literal the caller wrote, not the binary value. Pass strings or
    ``Decimal`` when the exact decimal matters. Rejects ``bool``, NaN, Inf,
    and malformed strings.
    """
    if isinstance(value, bool):
        raise TypeError("bool is not accepted as a numeric input")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite input")
        return Fraction(Decimal(repr(value)))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite input")
        return Fraction(value)
    if isinstance(value, str):
        text = value.strip()
        if not _DEC_RE.match(text):
            raise ValueError(f"invalid decimal string: {value!r}")
        return Fraction(Decimal(text))
    raise TypeError(f"unsupported numeric type {type(value)!r}")


def ceil_cent(value: Fraction) -> Fraction:
    """Exact ceiling to $0.01. Exactly-zero raw stays 0; any positive raw is at least $0.01.

    Negative raw values are rejected. The ceiling is applied only after any cap.
    """
    if not isinstance(value, Fraction) or value < 0:
        raise ValueError("raw fee must be a nonnegative Fraction")
    return Fraction(math.ceil(value * 100), 100)


def _sqrt(value: Fraction) -> Fraction:
    """High-precision square root returned as a Fraction."""
    if value < 0:
        raise ValueError("square root of a negative value")
    if value == 0:
        return Fraction(0)
    with localcontext() as ctx:
        ctx.prec = 50
        root = (Decimal(value.numerator) / Decimal(value.denominator)).sqrt()
    return Fraction(root)


def _as_optional(value: Fraction | Decimal | int | str | float | None) -> Fraction | None:
    if value is None:
        return None
    return exact(value)


def adverse_tick_round(price: Fraction, tick: Fraction, *, is_buy: bool) -> Fraction:
    """Round a fill price to ``tick``, always against the trader.

    Buys are rounded up to the next tick (or left unchanged if already on a
    tick); sells are rounded down. ``tick`` must be positive.
    """
    if tick <= 0:
        raise ValueError("tick must be positive")
    steps = price / tick
    if is_buy:
        n = math.ceil(steps)
    else:
        n = math.floor(steps)
    return Fraction(n) * tick


@dataclass(frozen=True)
class RegulatoryComponent:
    """One published regulatory or exchange fee line.

    ``cap`` is applied to the exact raw amount before any cent ceiling.
    ``min_price`` skips the component when the reference price is strictly below it
    (the historical equity TAF exemption for sub-rate prices). ``inactive_from`` /
    ``inactive_to`` inclusive, when set, skip the component on those trade dates.
    """

    name: str
    basis: FeeBasis
    applies_to: AppliesTo
    rate: Fraction
    cap: Fraction | None = None
    min_price: Fraction | None = None
    inactive_from: date | None = None
    inactive_to: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rate", exact(self.rate))
        if self.rate < 0:
            raise ValueError(f"{self.name}: rate must be nonnegative")
        object.__setattr__(self, "cap", _as_optional(self.cap))
        if self.cap is not None and self.cap < 0:
            raise ValueError(f"{self.name}: cap must be nonnegative")
        object.__setattr__(self, "min_price", _as_optional(self.min_price))
        if self.min_price is not None and self.min_price < 0:
            raise ValueError(f"{self.name}: min_price must be nonnegative")
        if (self.inactive_from is None) ^ (self.inactive_to is None):
            raise ValueError(f"{self.name}: inactive_from and inactive_to must be set together")
        if self.inactive_from is not None and self.inactive_to is not None and self.inactive_from > self.inactive_to:
            raise ValueError(f"{self.name}: inactive_from must be on or before inactive_to")


@dataclass(frozen=True)
class CommissionSchedule:
    """Broker commission. Bounds apply to the commission total only, before any cent ceiling."""

    per_share: Fraction = Fraction(0)
    per_contract: Fraction = Fraction(0)
    per_order: Fraction = Fraction(0)
    min_per_order: Fraction | None = None
    max_per_order: Fraction | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_share", exact(self.per_share))
        object.__setattr__(self, "per_contract", exact(self.per_contract))
        object.__setattr__(self, "per_order", exact(self.per_order))
        object.__setattr__(self, "min_per_order", _as_optional(self.min_per_order))
        object.__setattr__(self, "max_per_order", _as_optional(self.max_per_order))
        for label, value in (
            ("per_share", self.per_share),
            ("per_contract", self.per_contract),
            ("per_order", self.per_order),
        ):
            if value < 0:
                raise ValueError(f"commission {label} must be nonnegative")
        if self.min_per_order is not None and self.min_per_order < 0:
            raise ValueError("commission min_per_order must be nonnegative")
        if self.max_per_order is not None and self.max_per_order < 0:
            raise ValueError("commission max_per_order must be nonnegative")
        if (
            self.min_per_order is not None
            and self.max_per_order is not None
            and self.min_per_order > self.max_per_order
        ):
            raise ValueError("commission min_per_order must be <= max_per_order")


@dataclass(frozen=True)
class SpreadSpec:
    """Quoted-spread crossing assumption.

    ``half_spread`` pays ``fraction`` times one half of the quoted spread
    (default ``fraction=1`` is standard marketable crossing).
    ``fraction_of_spread`` pays ``fraction`` of the full quoted spread
    (``fraction=0.5`` is the same as default half-spread). When a tick is
    supplied, the half-spread is floored at ``tick / 2`` and the implied fill
    is adverse-rounded to the tick.
    """

    mode: SpreadMode = "half_spread"
    fraction: Fraction = Fraction(1)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fraction", exact(self.fraction))
        if self.mode not in ("half_spread", "fraction_of_spread"):
            raise ValueError("spread mode must be 'half_spread' or 'fraction_of_spread'")
        if self.fraction < 0:
            raise ValueError("spread fraction must be nonnegative")


@dataclass(frozen=True)
class ImpactSpec:
    """Market-impact coefficient. Impact is unhaircut (no venue reduction).

    Square-root: ``k * sigma * sqrt(participation)`` of notional.
    Linear: ``k * sigma * participation`` of notional.
    ``participation`` is traded quantity divided by ADV in the same unit.
    """

    model: ImpactModel = "sqrt"
    k: Fraction = Fraction(1)

    def __post_init__(self) -> None:
        object.__setattr__(self, "k", exact(self.k))
        if self.model not in ("sqrt", "linear"):
            raise ValueError("impact model must be 'sqrt' or 'linear'")
        if self.k < 0:
            raise ValueError("impact k must be nonnegative")


@dataclass(frozen=True)
class CostSchedule:
    """Complete one-way cost schedule. All rates are caller-supplied."""

    commission: CommissionSchedule = field(default_factory=CommissionSchedule)
    regulatory: tuple[RegulatoryComponent, ...] = ()
    spread: SpreadSpec = field(default_factory=SpreadSpec)
    impact: ImpactSpec = field(default_factory=ImpactSpec)
    ceil_fees_to_cent: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> CostSchedule:
        """Build a schedule from a decoded mapping (for example a parsed TOML table).

        This method performs no I/O. Date fields on regulatory components, if present,
        must be ``datetime.date`` or ISO ``YYYY-MM-DD`` strings.
        """
        raw_comm = data.get("commission", {})
        if not isinstance(raw_comm, Mapping):
            raise TypeError("commission must be a table")
        commission = CommissionSchedule(
            per_share=exact(raw_comm["per_share"]) if "per_share" in raw_comm else Fraction(0),
            per_contract=exact(raw_comm["per_contract"]) if "per_contract" in raw_comm else Fraction(0),
            per_order=exact(raw_comm["per_order"]) if "per_order" in raw_comm else Fraction(0),
            min_per_order=_optional_map_number(raw_comm, "min_per_order"),
            max_per_order=_optional_map_number(raw_comm, "max_per_order"),
        )
        raw_regs = data.get("regulatory", {})
        if not isinstance(raw_regs, Mapping):
            raise TypeError("regulatory must be a table of named components")
        components: list[RegulatoryComponent] = []
        for name, raw in raw_regs.items():
            if not isinstance(raw, Mapping):
                raise TypeError(f"regulatory.{name} must be a table")
            components.append(
                RegulatoryComponent(
                    name=str(raw.get("name", name)),
                    basis=_literal(raw["basis"], ("per_dollar_notional", "per_share", "per_contract", "per_order")),
                    applies_to=_literal(raw["applies_to"], ("buy", "sell", "both")),
                    rate=_map_number(raw, "rate"),
                    cap=_optional_map_number(raw, "cap"),
                    min_price=_optional_map_number(raw, "min_price"),
                    inactive_from=_optional_map_date(raw, "inactive_from"),
                    inactive_to=_optional_map_date(raw, "inactive_to"),
                )
            )
        raw_spread = data.get("spread", {})
        if not isinstance(raw_spread, Mapping):
            raise TypeError("spread must be a table")
        spread = SpreadSpec(
            mode=_literal(raw_spread.get("mode", "half_spread"), ("half_spread", "fraction_of_spread")),
            fraction=exact(raw_spread["fraction"]) if "fraction" in raw_spread else Fraction(1),
        )
        raw_impact = data.get("impact", {})
        if not isinstance(raw_impact, Mapping):
            raise TypeError("impact must be a table")
        impact = ImpactSpec(
            model=_literal(raw_impact.get("model", "sqrt"), ("sqrt", "linear")),
            k=exact(raw_impact["k"]) if "k" in raw_impact else Fraction(1),
        )
        ceil_fees = data.get("ceil_fees_to_cent", True)
        if not isinstance(ceil_fees, bool):
            raise TypeError("ceil_fees_to_cent must be a bool")
        return cls(
            commission=commission,
            regulatory=tuple(components),
            spread=spread,
            impact=impact,
            ceil_fees_to_cent=ceil_fees,
        )


def _map_number(data: Mapping[str, object], key: str) -> Fraction:
    if key not in data or data[key] is None:
        raise KeyError(key)
    value = data[key]
    if isinstance(value, (Fraction, Decimal, int, str, float)) and not isinstance(value, bool):
        return exact(value)
    raise TypeError(f"{key} must be a number")


def _optional_map_number(data: Mapping[str, object], key: str) -> Fraction | None:
    if key not in data or data[key] is None:
        return None
    return _map_number(data, key)


def _optional_map_date(data: Mapping[str, object], key: str) -> date | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"{key} must be a date or ISO date string")


def _literal[T: str](value: object, allowed: tuple[T, ...]) -> T:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"expected one of {allowed}, got {value!r}")
    return value


@dataclass(frozen=True)
class Order:
    """A single one-way order at a reference mid.

    ``multiplier`` scales notional and share-equivalent size for ``unit="contract"``
    (for example 100 for a standard equity option). The default is 1 so that
    contract notionals are explicit. Quantity and price must be positive.
    """

    side: Side
    quantity: Fraction
    price: Fraction
    unit: Unit = "share"
    multiplier: Fraction = Fraction(1)

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if self.unit not in ("share", "contract"):
            raise ValueError("unit must be 'share' or 'contract'")
        object.__setattr__(self, "quantity", exact(self.quantity))
        object.__setattr__(self, "price", exact(self.price))
        object.__setattr__(self, "multiplier", exact(self.multiplier))
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("price and quantity must be positive")
        if self.multiplier <= 0:
            raise ValueError("multiplier must be positive")

    @property
    def is_buy(self) -> bool:
        return self.side == "buy"

    @property
    def notional(self) -> Fraction:
        if self.unit == "contract":
            return self.price * self.quantity * self.multiplier
        return self.price * self.quantity

    @property
    def share_quantity(self) -> Fraction:
        if self.unit == "contract":
            return self.quantity * self.multiplier
        return self.quantity

    @property
    def contract_quantity(self) -> Fraction:
        if self.unit == "contract":
            return self.quantity
        return Fraction(0)


@dataclass(frozen=True)
class MarketState:
    """Observable market inputs for one order. Missing optionals zero that component."""

    adv: Fraction | None = None
    sigma: Fraction | None = None
    spread: Fraction | None = None
    spread_bps: Fraction | None = None
    tick: Fraction | None = None
    trade_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "adv", _as_optional(self.adv))
        object.__setattr__(self, "sigma", _as_optional(self.sigma))
        object.__setattr__(self, "spread", _as_optional(self.spread))
        object.__setattr__(self, "spread_bps", _as_optional(self.spread_bps))
        object.__setattr__(self, "tick", _as_optional(self.tick))
        if self.adv is not None and self.adv < 0:
            raise ValueError("adv must be nonnegative")
        if self.sigma is not None and self.sigma < 0:
            raise ValueError("sigma must be nonnegative")
        if self.spread is not None and self.spread < 0:
            raise ValueError("spread must be nonnegative")
        if self.spread_bps is not None and self.spread_bps < 0:
            raise ValueError("spread_bps must be nonnegative")
        if self.tick is not None and self.tick <= 0:
            raise ValueError("tick must be positive")


@dataclass(frozen=True)
class CostBreakdown:
    """One-way cost in currency (same units as the reference price)."""

    spread: Fraction
    commission: Fraction
    regulatory: Fraction
    impact: Fraction
    total: Fraction
    notional: Fraction
    regulatory_detail: Mapping[str, Fraction]
    notes: tuple[str, ...]

    @property
    def total_bps(self) -> Fraction:
        if self.notional == 0:
            raise ValueError("notional is zero")
        return self.total / self.notional * _BPS

    def component_bps(self, name: Literal["spread", "commission", "regulatory", "impact"]) -> Fraction:
        amounts: dict[str, Fraction] = {
            "spread": self.spread,
            "commission": self.commission,
            "regulatory": self.regulatory,
            "impact": self.impact,
        }
        return amounts[name] / self.notional * _BPS


def example_equity_schedule() -> CostSchedule:
    """Neutral equity example matching the numbers in ``configs/costs/cost_model.toml``.

    Rates are published-example values (SEC Section 31 fee-rate advisory; FINRA TAF
    rate notices; broker CAT pass-through schedules). They are not a recommendation.
    """
    return CostSchedule(
        commission=CommissionSchedule(),
        regulatory=(
            RegulatoryComponent(
                name="sec_section_31",
                basis="per_dollar_notional",
                applies_to="sell",
                rate=exact("0.0000206"),
            ),
            RegulatoryComponent(
                name="finra_taf",
                basis="per_share",
                applies_to="sell",
                rate=exact("0.000195"),
                cap=exact("9.79"),
                min_price=exact("0.000195"),
            ),
            RegulatoryComponent(
                name="cat",
                basis="per_share",
                applies_to="both",
                rate=exact("0.000003"),
            ),
        ),
        spread=SpreadSpec(mode="half_spread", fraction=Fraction(1)),
        impact=ImpactSpec(model="sqrt", k=Fraction(1)),
        ceil_fees_to_cent=True,
    )


def spread_cost(order: Order, market: MarketState, spec: SpreadSpec) -> tuple[Fraction, tuple[str, ...]]:
    """Currency cost of crossing the quoted spread, with optional tick-aware adverse rounding."""
    notes: list[str] = []
    full = _full_spread(order.price, market)
    if full is None:
        notes.append("spread missing: spread cost set to 0")
        return Fraction(0), tuple(notes)
    half = full / 2
    if market.tick is not None:
        half = max(half, market.tick / 2)
        full = half * 2
    if spec.mode == "half_spread":
        paid = spec.fraction * half
    else:
        paid = spec.fraction * full
    if paid < 0:
        raise ValueError("implied spread payment is negative")
    mid = order.price
    units = order.notional / mid
    if market.tick is None:
        return paid * units, tuple(notes)
    if order.is_buy:
        fill = adverse_tick_round(mid + paid, market.tick, is_buy=True)
        slip = fill - mid
    else:
        raw_fill = mid - paid
        if raw_fill < 0:
            raw_fill = Fraction(0)
        fill = adverse_tick_round(raw_fill, market.tick, is_buy=False)
        if fill < 0:
            fill = Fraction(0)
        slip = mid - fill
    return slip * units, tuple(notes)


def _full_spread(mid: Fraction, market: MarketState) -> Fraction | None:
    if market.spread is not None:
        return market.spread
    if market.spread_bps is not None:
        return mid * market.spread_bps / _BPS
    return None


def commission_cost(order: Order, schedule: CommissionSchedule, *, ceil_to_cent: bool) -> Fraction:
    """Broker commission for one order, with per-order min/max applied before any cent ceiling."""
    raw = schedule.per_order
    if order.unit == "share":
        raw += schedule.per_share * order.quantity
    else:
        raw += schedule.per_contract * order.quantity
    if schedule.min_per_order is not None and raw < schedule.min_per_order:
        raw = schedule.min_per_order
    if schedule.max_per_order is not None and raw > schedule.max_per_order:
        raw = schedule.max_per_order
    if ceil_to_cent:
        raw = ceil_cent(raw)
    return raw


def regulatory_fees(
    order: Order,
    components: tuple[RegulatoryComponent, ...],
    *,
    trade_date: date | None,
    ceil_to_cent: bool,
) -> tuple[Fraction, dict[str, Fraction]]:
    """Exact per-component regulatory fees. Caps apply to raw amounts before any cent ceiling."""
    detail: dict[str, Fraction] = {}
    total = Fraction(0)
    for component in components:
        amount = _component_amount(order, component, trade_date=trade_date, ceil_to_cent=ceil_to_cent)
        detail[component.name] = amount
        total += amount
    return total, detail


def _component_amount(
    order: Order,
    component: RegulatoryComponent,
    *,
    trade_date: date | None,
    ceil_to_cent: bool,
) -> Fraction:
    if component.applies_to not in ("both", order.side):
        return Fraction(0)
    if component.inactive_from is not None and component.inactive_to is not None:
        if trade_date is None:
            # A dated waiver cannot be applied without a trade date; charge the fee.
            pass
        elif component.inactive_from <= trade_date <= component.inactive_to:
            return Fraction(0)
    if component.min_price is not None and order.price < component.min_price:
        return Fraction(0)
    if component.basis == "per_dollar_notional":
        raw = component.rate * order.notional
    elif component.basis == "per_share":
        raw = component.rate * order.share_quantity
    elif component.basis == "per_contract":
        raw = component.rate * order.contract_quantity
    else:
        raw = component.rate
    if component.cap is not None and raw > component.cap:
        raw = component.cap
    if ceil_to_cent:
        raw = ceil_cent(raw)
    return raw


def impact_cost(order: Order, market: MarketState, spec: ImpactSpec) -> tuple[Fraction, tuple[str, ...]]:
    """Unhaircut impact in currency. Missing ADV or sigma yields zero impact and a note."""
    notes: list[str] = []
    if market.adv is None or market.adv == 0:
        notes.append("adv missing: impact set to 0")
        return Fraction(0), tuple(notes)
    if market.sigma is None:
        notes.append("sigma missing: impact set to 0")
        return Fraction(0), tuple(notes)
    # Participation uses the same unit as ADV: share quantity for share orders, and
    # share-equivalent size (quantity * multiplier) for contract orders. When ADV is
    # itself in contracts, pass multiplier=1 and a contract-unit ADV.
    traded = order.quantity if order.unit == "share" else order.share_quantity
    participation = traded / market.adv
    if participation < 0:
        raise ValueError("participation is negative")
    if spec.model == "sqrt":
        load = _sqrt(participation)
    else:
        load = participation
    # unhaircut: k * sigma * load * notional
    amount = spec.k * market.sigma * load * order.notional
    return amount, tuple(notes)


def total_cost(order: Order, market: MarketState, schedule: CostSchedule) -> CostBreakdown:
    """Compose spread, commission, regulatory fees, and unhaircut impact into one one-way cost."""
    spread_usd, spread_notes = spread_cost(order, market, schedule.spread)
    commission_usd = commission_cost(order, schedule.commission, ceil_to_cent=schedule.ceil_fees_to_cent)
    reg_usd, detail = regulatory_fees(
        order,
        schedule.regulatory,
        trade_date=market.trade_date,
        ceil_to_cent=schedule.ceil_fees_to_cent,
    )
    impact_usd, impact_notes = impact_cost(order, market, schedule.impact)
    total = spread_usd + commission_usd + reg_usd + impact_usd
    return CostBreakdown(
        spread=spread_usd,
        commission=commission_usd,
        regulatory=reg_usd,
        impact=impact_usd,
        total=total,
        notional=order.notional,
        regulatory_detail=detail,
        notes=spread_notes + impact_notes,
    )
