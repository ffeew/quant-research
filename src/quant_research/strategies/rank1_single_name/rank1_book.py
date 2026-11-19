"""Integrated fabricated-only long/cash study accounting. NO production reader/entry.
Cash transaction and epistemic ledgers separate; semantic questions block production.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_FLOOR, InvalidOperation
from decimal import Decimal as D
from typing import Any, cast

from quant_research.strategies.rank1_single_name.rank1_core import Blocked, Insufficient, clock


@dataclass(frozen=True)
class Bar:
    security: str
    index: int
    open: object
    close: object
    adv20: object
    sigma20: object
    open_tradable: bool
    verified_halt: bool
    synthetic_only: bool = False
    volume: object = None
    sip: bool = False
    close_known_at: object = None
    lag_available_at: object = None
    lag_end_index: object = None
    sigma_estimator_sha256: object = None
    sigma20_closes: object = None


@dataclass(frozen=True)
class Identity:
    issuer: str
    security: str
    start: str
    end: str
    known_at: str
    synthetic_only: bool = False


@dataclass(frozen=True)
class Distribution:
    security: str
    ex_index: int
    pay_index: int
    amount_per_new_share: object
    synthetic_only: bool = False
    known_at: object = None
    entitlement: object = None


@dataclass(frozen=True)
class ExchangeEntitlement:
    security: str
    quantity_per_old_share: object
    ex_index: int
    pay_index: int
    known_at: str
    source_sha256: str
    synthetic_only: bool = False


@dataclass(frozen=True)
class Action:
    issuer: str
    index: int
    time: str
    kind: str  # SPLIT, EXCHANGE, CASH_TERMINAL, BOUND
    ratio: object
    cash_per_old_share: object
    new_security: object
    identity_verified: bool
    time_verified: bool
    public_known_at: str
    fee_bp: object = None  # REJECTED legacy caller field; never used for costing
    cash_in_lieu: object = None
    synthetic_only: bool = False


class Market:
    def __init__(
        self,
        calendar: Any,
        bars: list[Bar],
        identities: list[Identity],
        distributions: list[Distribution],
        actions: list[Action],
        rf: dict[int, Any],
    ) -> None:
        self.cal = calendar
        self.bars: dict[tuple[str, int], Bar] = {}
        self.identities: tuple[Identity, ...] = tuple(identities)
        self.distributions: tuple[Distribution, ...] = tuple(distributions)
        self.actions: tuple[Action, ...] = tuple(actions)
        self.rf = dict(rf)
        for b in bars:
            if b.synthetic_only is not True or not b.security.startswith("SYNTH_"):
                raise Blocked("fabricated market namespace/marker")
            if (b.security, b.index) in self.bars:
                raise Blocked("duplicate bar")
            self.bars[b.security, b.index] = b
        for row in (*self.identities, *self.distributions, *self.actions):
            record = cast(Any, row)
            if record.synthetic_only is not True:
                raise Blocked("fabricated identity/event marker required")
        for a in self.actions:
            if a.identity_verified is not True or a.time_verified is not True:
                raise Blocked("unbounded identity/time defect")
            if a.kind not in {"SPLIT", "EXCHANGE", "CASH_TERMINAL", "BOUND"}:
                raise Blocked("unknown corporate action")
            if not self.cal.sessions[a.index].open <= clock(a.time) <= self.cal.sessions[a.index].close:
                raise Blocked(
                    "event must be normalized to regular effective session; outside-hours mapping supplied first"
                )
            self.identity(a.issuer, clock(a.time) - timedelta(microseconds=1))
            clock(a.public_known_at)
            if a.kind == "CASH_TERMINAL" and a.fee_bp is not None:
                raise Blocked("Q6 caller fee including zero REFUSED")
            if a.kind == "EXCHANGE":
                if not a.new_security or self.identity(a.issuer, clock(a.time)) != a.new_security:
                    raise Blocked("unknown exchange new security/identity")
                if not D(str(a.ratio)).is_finite() or D(str(a.ratio)) <= 0:
                    raise Blocked("invalid exchange quantity")
        for d in self.distributions:
            if d.security not in {r.security for r in self.identities}:
                raise Blocked("unknown distribution security")
            clock(d.known_at)
            if d.pay_index < d.ex_index or D(str(d.amount_per_new_share)) < 0:
                raise Blocked("invalid distribution timing/amount")

    def identity(self, issuer: str, when: Any, known_before: Any = None) -> str:
        rows = [
            r
            for r in self.identities
            if r.issuer == issuer
            and clock(r.start) <= when < clock(r.end)
            and (clock(r.known_at) < known_before if known_before is not None else clock(r.known_at) <= when)
        ]
        if len(rows) != 1:
            raise Blocked("unknown/ambiguous effective identity")
        return rows[0].security

    def bar(self, security: str, t: int) -> Bar:
        if (security, t) not in self.bars:
            raise Blocked("missing required mark; no forward fill")
        return self.bars[security, t]

    def price(self, security: str, t: int, kind: str, known_before: Any = None) -> D:
        b = self.bar(security, t)
        v = getattr(b, kind)
        if kind == "close" and known_before is not None and clock(b.close_known_at) >= known_before:
            raise Blocked("close/revision not known before decision/control cutoff")
        if v is None or not D(str(v)).is_finite() or D(str(v)) <= 0:
            raise Blocked("missing/nonpositive official price; no stale fill")
        if kind == "open" and b.open_tradable is not True:
            raise Blocked("nontradable open is not a fill")
        return D(str(v))

    def lag_inputs(self, security: str, t: int, signed_cost: Any = None) -> tuple[D, D]:
        from statistics import median

        from quant_research.strategies.rank1_single_name.rank1_core import hash_shape

        if signed_cost is None:
            raise Blocked("Q4 sigma adapter/TR-basis contract input missing; signed definition is pinned")
        signed_pin = signed_cost.sigma_estimator_pin()
        b = self.bar(security, t)
        cut = self.cal.cutoff(self.cal.sessions[t])
        if (
            t < 20
            or b.lag_end_index != t - 1
            or clock(b.lag_available_at) >= cut
            or not hash_shape(b.sigma_estimator_sha256)
        ):
            raise Blocked("lagged cost-estimator endpoint/clock/pin missing")
        if b.sigma_estimator_sha256 != signed_pin:
            raise Blocked("Q4 estimator hash does not match signed pinned value")
        dollars = []
        for i in range(t - 20, t):
            old = self.bar(security, i)
            if old.sip is not True or old.volume is None or D(str(old.volume)) < 0:
                raise Blocked("20 complete consolidated SIP volume observations required")
            dollars.append(self.price(security, i, "close", cut) * D(str(old.volume)))
        adv = median(dollars)
        if b.adv20 is None or D(str(b.adv20)) != adv or adv <= 0:
            raise Blocked("provided ADV differs from prior20 SIP median or missing")
        if b.sigma20 is None or not D(str(b.sigma20)).is_finite() or D(str(b.sigma20)) < 0:
            raise Blocked("pinned upstream sigma20 input missing")
        from quant_research.strategies.rank1_single_name.rank1_sigma import canonical_sigma20

        canonical = canonical_sigma20(b.sigma20_closes, t, self.cal, signed_cost.sigma_contract, True)
        if D(str(b.sigma20)) != canonical["sigma20"]:
            raise Blocked("upstream sigma20 differs from signed canonical21-close estimator")
        return adv, canonical["sigma20"]

    def rate(self, t: int) -> D:
        if t not in self.rf:
            raise Blocked("RF missing; no zero fill")
        r = D(str(self.rf[t]))
        if not r.is_finite() or r <= -1:
            raise Blocked("invalid decimal RF")
        return r  # documented source decimal; do not divide again

    def exchange_distribution_per_old_share(
        self, d: Any, a: Any, old_security: Any, new_security: Any, known_before: Any = None
    ) -> tuple[D, bool]:
        """Missing entitlement => zero; malformed/unknown identity/time => BLOCKED."""
        from quant_research.strategies.rank1_single_name.rank1_core import hash_shape

        if d.security not in {old_security, new_security}:
            raise Blocked("unknown entitlement security")
        e = d.entitlement
        if e is None:
            return D(0), True
        if not isinstance(e, ExchangeEntitlement) or e.synthetic_only is not True:
            raise Blocked("explicit entitlement schema/marker required")
        if e.security != d.security or e.security not in {old_security, new_security}:
            raise Blocked("unknown/mismatched entitlement security")
        if e.ex_index != d.ex_index or e.pay_index != d.pay_index or not hash_shape(e.source_sha256):
            raise Blocked("unknown entitlement timing/source")
        try:
            qty = D(str(e.quantity_per_old_share))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise Blocked("unknown entitlement quantity") from exc
        if not qty.is_finite() or qty <= 0:
            raise Blocked("unknown entitlement quantity")
        when = clock(e.known_at)
        if when > clock(a.time) or (known_before is not None and when >= known_before):
            return D(0), True
        return qty * D(str(d.amount_per_new_share)), False

    def distribution_link(self, issuer: str, j: int, old: str, new: str, ratio: Any, known_before: Any = None) -> D:
        exchanges = [a for a in self.actions if a.index == j and a.issuer == issuer and a.kind == "EXCHANGE"]
        if len(exchanges) > 1:
            raise Blocked("ambiguous same-session exchange lineage")
        relevant = [
            d for d in self.distributions if d.ex_index == j and d.security in ({old, new} if exchanges else {new})
        ]
        value = D(0)
        for d in relevant:
            if known_before is not None and clock(d.known_at) >= known_before:
                raise Blocked("distribution/control information not known before t")
            if exchanges:
                part, _ = self.exchange_distribution_per_old_share(d, exchanges[0], old, new, known_before)
                value += part
            else:
                value += ratio * D(str(d.amount_per_new_share))
        return value

    def total_return_levels(self, issuer: str, through: int) -> list[D]:
        from decimal import Decimal as D

        levels = [D(1)]
        for j in range(1, through + 1):
            old = self.identity(issuer, self.cal.sessions[j - 1].close)
            new = self.identity(issuer, self.cal.sessions[j].close)
            ratio = D(1)
            cash = D(0)
            for a in self.actions:
                if a.index == j and a.issuer == issuer:
                    if a.kind not in {"SPLIT", "EXCHANGE"}:
                        raise Blocked("terminal not a benchmark TR continuation")
                    ratio *= D(str(a.ratio))
                    cash += D(str(a.cash_per_old_share))
            div = self.distribution_link(issuer, j, old, new, ratio)
            levels.append(
                levels[-1] * (self.price(new, j, "close") * ratio + cash + div) / self.price(old, j - 1, "close")
            )
        return levels

    def five_return(self, issuer: str, t: int) -> D:
        if t < 6:
            raise Insufficient("five lagged close-to-close returns missing")
        wealth = D(1)
        cut = self.cal.cutoff(self.cal.sessions[t])
        for j in range(t - 5, t):  # close(t-6) to close(t-1), exactly FIVE links
            old = self.identity(issuer, self.cal.sessions[j - 1].close)
            new = self.identity(issuer, self.cal.sessions[j].close)
            prev = self.price(old, j - 1, "close", cut)
            now = self.price(new, j, "close", cut)
            ratio = D(1)
            cash = D(0)
            for a in self.actions:
                if a.index == j and a.issuer == issuer:
                    if a.kind not in {"SPLIT", "EXCHANGE"}:
                        raise Blocked("terminal falls in required control history")
                    if clock(a.public_known_at) >= cut:
                        raise Blocked("corporate-action control information not known before t")
                    ratio *= D(str(a.ratio))
                    cash += D(str(a.cash_per_old_share))
            div = self.distribution_link(issuer, j, old, new, ratio, cut)
            wealth *= (now * ratio + cash + div) / prev
        return wealth - 1


@dataclass
class Position:
    issuer: str
    security: str
    qty: D
    entry: int
    planned: int
    notional: D
    entry_adv: D
    entry_sigma: D
    entry_cost: D
    shadow_qty: D
    entry_spy: D
    distributions: D = D(0)
    shadow_distributions: D = D(0)
    terminal_cash: D = D(0)


@dataclass
class CompletedTrade:
    issuer: str
    entry: int
    exit: int
    notional: D
    gross_matched_excess: D
    all_in_cost_fraction: D
    primary_or_path_net_excess: D
    reason: str


class FixtureBook:
    def __init__(
        self,
        market: Market,
        ir: Any,
        cost: Any,
        config: Any,
        start: int,
        end: int,
        policy: str,
        synthetic_only: bool = False,
    ) -> None:
        if synthetic_only is not True:
            raise Blocked("fabricated study only")
        if policy != "NONCASH_BUFFER_PINNED_RF":
            raise Blocked("Q1 only noncash buffer with pinned daily RF is accepted")
        if not 1 <= start <= end < len(market.cal.sessions):
            raise Blocked("invalid supplied stage/warmup")
        self.m = market
        self.ir = ir
        self.cost = cost
        self.cfg = config
        self.start = start
        self.end = end
        self.cash = D(100000)
        self.shadow_cash = D(100000)
        self.cash_only = D(100000)
        self.penalty = D(0)
        self.positions: dict[str, Position] = {}
        self.cooldowns: dict[str, int] = {}
        self.receivables: list[dict[str, Any]] = []
        self.rows: list[dict[str, Any]] = []
        self.trades: list[CompletedTrade] = []
        self.max_concurrent = 0
        self.last_cash_nav = D(100000)
        self.last_nav = D(100000)
        self.last_shadow_nav = D(100000)
        self.discarded: list[Any] = []
        self.halts: list[Any] = []
        self.claim_conventions_pending = False
        self._started = False
        self._new_penalty = D(0)
        self._rf_applied = False
        self.intraday_terminal_shadow: list[Any] = []
        self.exchange_dividends_zeroed: list[Any] = []
        self.cash_terminal_costs: list[Any] = []

    def _charge(self, c: dict[str, Any]) -> None:
        self.cash -= c["transaction_usd"]
        if self._rf_applied:
            self.penalty += c["buffer_usd"]
        else:
            self._new_penalty += c["buffer_usd"]

    def _close(self, p: Position, t: int, ledger: str, reason: str, terminal: Any = None) -> None:
        day = self.m.cal.sessions[t].day.isoformat()
        bar = self.m.bar(p.security, t)
        if terminal:
            if terminal.identity_verified is not True or terminal.time_verified is not True:
                raise Blocked("unverified terminal identity/time")
            if terminal.kind == "BOUND":
                proceeds = D(0)
                c = self.cost.bounded_terminal(
                    p.notional, p.entry_adv, p.entry_sigma, bar.adv20, day, ledger, True, True
                )
            elif terminal.kind == "CASH_TERMINAL":
                proceeds = p.qty * D(str(terminal.cash_per_old_share))
                if proceeds < 0:
                    raise Blocked("negative legal consideration")
                if proceeds == 0:
                    if terminal.fee_bp is not None:
                        raise Blocked("Q6 caller fee including zero REFUSED")
                    c = self.cost.bounded_terminal(
                        p.notional, p.entry_adv, p.entry_sigma, bar.adv20, day, ledger, True, True
                    )
                else:
                    if terminal.fee_bp is not None:
                        raise Blocked("Q6 caller fee including zero REFUSED")
                    adv, sigma = self.m.lag_inputs(p.security, t, self.cost)
                    c = self.cost.cash_terminal_leg(day, p.qty, terminal.cash_per_old_share, adv, sigma, ledger)
                    self.cash_terminal_costs.append(
                        dict(index=t, issuer=p.issuer, fee_bp=c["fee_bp"], basis="INTERNAL_DATED_SALE_FEE_ON_PROCEEDS")
                    )
            else:
                raise Blocked("not a terminal exit")
        else:
            px = self.m.price(p.security, t, "open")
            proceeds = p.qty * px
            adv, sigma = self.m.lag_inputs(p.security, t, self.cost)
            c = self.cost.leg("sell", day, p.qty, px, adv, sigma, ledger)
        self.cash += proceeds
        self._charge(c)
        intraday = terminal is not None and clock(terminal.time) != self.m.cal.sessions[t].open
        sp = self.m.price("SYNTH_SPY", t, "close" if intraday else "open")
        spy_value = p.shadow_qty * sp
        if intraday:
            self.intraday_terminal_shadow.append(
                dict(
                    index=t,
                    issuer=p.issuer,
                    shadow_pnl_usd=spy_value + p.shadow_distributions - p.notional,
                    reference="SAME_SESSION_OFFICIAL_CLOSE_NO_COST",
                )
            )
        self.shadow_cash += spy_value
        stock_gross = (proceeds + p.distributions + p.terminal_cash) / p.notional - 1
        spy_gross = (spy_value + p.shadow_distributions) / p.notional - 1
        cost = (p.entry_cost + c["transaction_usd"] + c["buffer_usd"]) / p.notional
        gross = stock_gross - spy_gross
        self.trades.append(CompletedTrade(p.issuer, p.entry, t, p.notional, gross, cost, gross - cost, reason))
        del self.positions[p.issuer]
        self.cooldowns[p.issuer] = t + 20

    def _z(self, t: int) -> D:
        if not self.positions:
            return D(0)
        if self.last_nav <= 0:
            raise Blocked("nonpositive prior NAV")
        spy = self.m.five_return("SYNTH_SPY", t)
        z = D(0)
        for p in self.positions.values():
            w = (
                p.qty
                * self.m.price(p.security, t - 1, "close", self.m.cal.cutoff(self.m.cal.sessions[t]))
                / self.last_nav
            )
            z += w * (self.m.five_return(p.issuer, t) - spy)
        return z

    def run(self, candidate_fn: Any, ledger: str = "primary") -> FixtureBook:
        if self._started:
            raise Blocked("single-use study including failed attempts; no hidden reopening")
        self._started = True
        for t in range(self.start, self.end + 1):
            self._new_penalty = D(0)
            self._rf_applied = False
            session = self.m.cal.sessions[t]
            cut = self.m.cal.cutoff(session)
            z = self._z(t)
            # Pay previously recorded receivables; still assets if owner exited earlier.
            for r in self.receivables:
                if r["pay"] == t:
                    if r["book"] == "stock":
                        self.cash += r["amount"]
                    else:
                        self.shadow_cash += r["amount"]
            self.receivables = [r for r in self.receivables if r["pay"] > t]
            prior_positions = dict(self.positions)
            prior_lots = {i: (p.security, p.qty) for i, p in self.positions.items()}
            pending_terminals = []
            intraday_terminals = []
            exchanges = {}
            for a in sorted((a for a in self.m.actions if a.index == t), key=lambda a: clock(a.time)):
                if a.issuer == "SYNTH_SPY":
                    if a.kind != "SPLIT" or clock(a.time) != session.open:
                        raise Blocked("benchmark action requires supplied compatible split semantics")
                    for lot in self.positions.values():
                        cash = lot.shadow_qty * D(str(a.cash_per_old_share))
                        lot.shadow_qty *= D(str(a.ratio))
                        self.shadow_cash += cash
                        lot.shadow_distributions += cash
                    continue
                if a.kind in {"BOUND", "CASH_TERMINAL"} and clock(a.time) != session.open:
                    intraday_terminals.append(a)
                    continue
                p = self.positions.get(a.issuer)
                if p is None:
                    continue
                if a.kind == "EXCHANGE":
                    exchanges[a.issuer] = a
                if a.kind in {"BOUND", "CASH_TERMINAL"}:
                    pending_terminals.append((p, a))
                else:
                    if clock(a.time) != session.open:
                        raise Blocked("intraday split/exchange entitlement order unspecified")
                    qty = p.qty * D(str(a.ratio))
                    cash = p.qty * D(str(a.cash_per_old_share))
                    if qty != qty.to_integral_value():
                        if a.cash_in_lieu is None:
                            raise Blocked("fractional action requires accepted cash-in-lieu")
                        cash += D(str(a.cash_in_lieu))
                        qty = qty.to_integral_value(rounding=ROUND_FLOOR)
                    p.qty = qty
                    self.cash += cash
                    p.terminal_cash += cash
                    if a.kind == "EXCHANGE":
                        if not a.new_security:
                            raise Blocked("exchange security identity missing")
                        p.security = cast(str, a.new_security)
            # Ex-date receivables belong only to prior-close holders, including today's sellers.
            # Explicit supplied PRIOR-CLOSE entitlement is credited before an open terminal exit.
            for d in self.m.distributions:
                if d.ex_index != t:
                    continue
                amount = D(str(d.amount_per_new_share))
                if d.security == "SYNTH_SPY":
                    for p in prior_positions.values():
                        value = p.shadow_qty * amount
                        p.shadow_distributions += value
                        if d.pay_index == t:
                            self.shadow_cash += value
                        else:
                            self.receivables.append(dict(book="shadow", amount=value, pay=d.pay_index))
                else:
                    for issuer, p in prior_positions.items():
                        oldsec, oldqty = prior_lots[issuer]
                        event = exchanges.get(issuer)
                        if event is not None and d.security in {oldsec, event.new_security}:
                            part, zeroed = self.m.exchange_distribution_per_old_share(
                                d, event, oldsec, event.new_security
                            )
                            if zeroed:
                                self.exchange_dividends_zeroed.append(
                                    dict(
                                        index=t,
                                        issuer=issuer,
                                        security=d.security,
                                        reason="NO_AS_KNOWN_EXPLICIT_ENTITLEMENT",
                                    )
                                )
                            value = oldqty * part
                        elif oldsec == d.security:
                            value = oldqty * amount
                        else:
                            continue
                        if issuer not in self.positions:
                            raise Blocked("unknown simultaneous terminal/distribution ownership")
                        p.distributions += value
                        if d.pay_index == t:
                            self.cash += value
                        elif value:
                            self.receivables.append(dict(book="stock", amount=value, pay=d.pay_index))
            for p, a in pending_terminals:
                self._close(p, t, ledger, a.kind, a)
            # Exits free slots BEFORE entries; halts defer EXIT only, never invent an open fill.
            for issuer, p in list(self.positions.items()):
                calendar_exit = self.ir.force_exit(
                    issuer, cut, self.m.cal.sessions[p.planned].open, current_open=session.open
                )
                needed = t >= p.planned or calendar_exit
                if needed:
                    b = self.m.bar(p.security, t)
                    if not b.open_tradable:
                        if b.verified_halt is not True:
                            raise Blocked("unexplained missing exit")
                        self.halts.append((issuer, t))
                        continue
                    self._close(p, t, ledger, "HOLD_OR_IR")
            candidates = tuple(candidate_fn(t))
            if any(c.synthetic_only is not True or not c.issuer.startswith("SYNTH_") for c in candidates):
                raise Blocked("fabricated candidates only")
            if len({c.issuer for c in candidates}) != len(candidates):
                raise Blocked("compiler must choose one action per issuer")
            for c in sorted(candidates, key=lambda c: (-c.score, c.ticker)):
                if c.issuer in self.positions or t <= self.cooldowns.get(c.issuer, -1):
                    continue
                if any(
                    a.index <= t
                    and a.issuer == c.issuer
                    and a.kind in {"BOUND", "CASH_TERMINAL", "EXCHANGE"}
                    and clock(a.public_known_at) < cut
                    for a in self.m.actions
                ):
                    continue
                planned = t + self.cfg.hold
                if planned > self.end:
                    continue  # fixed stage admission, no trailing truncation
                if not self.ir.admit(c.issuer, cut, self.m.cal.sessions[planned].open):
                    continue
                if len(self.positions) >= 5:
                    self.discarded.append((c.issuer, t))
                    continue
                sec = self.m.identity(c.issuer, session.open, cut)
                _bar = self.m.bar(sec, t)
                adv, sigma = self.m.lag_inputs(sec, t, self.cost)
                if c.k >= cut:
                    raise Blocked("candidate not strictly usable at cutoff")
                prev = self.m.price(sec, t - 1, "close", cut)
                qty = (D(5000) / prev).to_integral_value(rounding=ROUND_FLOOR)
                if qty <= 0:
                    raise Blocked("invalid whole-share sizing; no hindsight partial allocation")
                px = self.m.price(sec, t, "open")
                n = qty * px
                if n > adv * D(".01"):
                    raise Blocked("lagged capacity unknown/exceeded")
                cost = self.cost.leg("buy", session.day.isoformat(), qty, px, adv, sigma, ledger)
                if n + cost["transaction_usd"] > self.cash:
                    raise Blocked("capital shortfall; no leverage/resize")
                sp = self.m.price("SYNTH_SPY", t, "open")
                if n > self.shadow_cash:
                    raise Blocked("Q_SHADOW_CAPITAL_SHORTFALL; no implicit comparator leverage")
                self.cash -= n
                self._charge(cost)
                self.shadow_cash -= n
                self.positions[c.issuer] = Position(
                    c.issuer, sec, qty, t, planned, n, adv, sigma, cost["all_in_usd"], n / sp, sp
                )
            self.max_concurrent = max(self.max_concurrent, len(self.positions))
            # Fixed RF on post-open cash ONCE; no weekend credits, no current mark/PIT claim.
            rf = self.m.rate(t)
            self.cash *= 1 + rf
            self.shadow_cash *= 1 + rf
            self.cash_only *= 1 + rf
            self.penalty = self.penalty * (1 + rf) + self._new_penalty
            self._rf_applied = True
            for a in intraday_terminals:
                p = self.positions.get(a.issuer)
                if p is not None:
                    self._close(p, t, ledger, a.kind, a)
            if self.cash < 0 or self.shadow_cash < 0:
                raise Blocked("negative cash")
            stock_value = sum((p.qty * self.m.price(p.security, t, "close") for p in self.positions.values()), D(0))
            shadow_value = sum(
                (p.shadow_qty * self.m.price("SYNTH_SPY", t, "close") for p in self.positions.values()), D(0)
            )
            rec = sum((r["amount"] for r in self.receivables if r["book"] == "stock"), D(0))
            sr = sum((r["amount"] for r in self.receivables if r["book"] == "shadow"), D(0))
            cashnav = self.cash + stock_value + rec
            nav = cashnav - self.penalty
            shadow = self.shadow_cash + shadow_value + sr
            if min(nav, shadow, self.last_nav, self.last_shadow_nav) <= 0:
                raise Insufficient("nonpositive NAV; no infinite return statistic")
            ret = nav / self.last_nav - 1
            shadow_ret = shadow / self.last_shadow_nav - 1
            self.rows.append(
                dict(
                    synthetic_only=True,
                    index=t,
                    day=session.day,
                    nav=nav,
                    cash_nav=cashnav,
                    shadow_nav=shadow,
                    cash_only_nav=self.cash_only,
                    excess=ret - rf,
                    ret=ret,
                    rf=rf,
                    opportunity_pct=ret - shadow_ret,
                    opportunity_usd_over_100k=(nav - self.last_nav - (shadow - self.last_shadow_nav)) / D(100000),
                    z=z,
                    penalty=self.penalty,
                    cash=self.cash,
                    holdings={p.issuer: p.qty * self.m.price(p.security, t, "close") for p in self.positions.values()},
                )
            )
            self.last_cash_nav = cashnav
            self.last_nav = nav
            self.last_shadow_nav = shadow
        if self.positions:
            raise Insufficient("halt/holding crosses fixed stage boundary; no forced final fill")
        return self

    def occupied_blocks(self, lo: int | None = None, hi: int | None = None) -> int:
        lo = self.start if lo is None else lo
        hi = self.end if hi is None else hi
        full = (hi - lo + 1) // 20
        return len({(t.entry - lo) // 20 for t in self.trades if lo <= t.entry <= hi and (t.entry - lo) // 20 < full})
