"""Typed, pure-function risk helpers for PAPER position sizing.

This module is research and paper-sizing code only. It does no file, network or broker I/O,
reads no environment variables, and holds no desk limit values: every threshold is a required
parameter or config field supplied by the caller. Numbers that appear in docstrings below are
EXAMPLES only, not desk policy.

Weights are fractions of equity keyed by symbol (``{"AAA": 0.10, "BBB": -0.05}``). Long weights
are positive, short weights negative. ``gross = sum(|w|)``, ``net = sum(w)``.

Building blocks
---------------
* Volatility targeting: :func:`portfolio_vol_from_returns`, :func:`portfolio_vol_from_covariance`,
  :func:`scale_to_target_vol` and the convenience wrapper :func:`vol_target_weights`. Scaling is
  capped so gross exposure never exceeds ``VolTargetConfig.gross_cap`` (itself validated to be
  at most 1.0): the module never adds leverage.
* Drawdown: :func:`drawdown_stats` (running peak, drawdown series, current and max drawdown) and a
  hysteresis breaker, :func:`evaluate_drawdown_breaker` / :func:`run_drawdown_breaker`, which
  returns NORMAL, REDUCE or FLAT with an explicit rearm rule.
* Exposure limits: :class:`ExposureLimits` (single-name, gross <= 1.0, net, optional group caps,
  prohibited symbols and asset classes), :func:`apply_exposure_limits` (sizes a book down to the
  limits and zeroes prohibited names) and :func:`pre_trade_check`, which never raises and fails
  closed on bad input.
* Reporting: :func:`build_risk_report` returns a :class:`RiskReport` dataclass (``to_dict()`` for
  rendering elsewhere).

Example (illustrative numbers only)::

    limits = ExposureLimits(single_name_cap=0.10, gross_cap=1.0, net_cap=0.30,
                            prohibited_asset_classes=frozenset({"crypto"}))
    sized = apply_exposure_limits(raw_weights, limits, asset_classes=classes)
    check = pre_trade_check(sized.weights, limits, asset_classes=classes)
    if not check.passed:
        ...  # do not size this book
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

__all__ = [
    "MAX_GROSS",
    "BreakerDecision",
    "BreakerState",
    "DrawdownBreakerConfig",
    "DrawdownStats",
    "ExposureLimits",
    "LimitResult",
    "PreTradeResult",
    "RiskInputError",
    "RiskReport",
    "Violation",
    "VolTargetConfig",
    "VolTargetResult",
    "apply_exposure_limits",
    "build_risk_report",
    "drawdown_stats",
    "evaluate_drawdown_breaker",
    "gross_exposure",
    "net_exposure",
    "portfolio_vol_from_covariance",
    "portfolio_vol_from_returns",
    "pre_trade_check",
    "run_drawdown_breaker",
    "scale_to_target_vol",
    "vol_target_weights",
]

#: Structural no-leverage ceiling. This is not a desk limit; it is the hard invariant of the
#: module (paper sizing never borrows). Desk gross limits are supplied by the caller and must be
#: at or below this value.
MAX_GROSS: float = 1.0

Weights = Mapping[str, float]
FloatArray = npt.NDArray[np.float64]


class RiskInputError(ValueError):
    """Raised by the sizing helpers on invalid input. ``pre_trade_check`` never raises."""


# ----------------------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------------------


def _finite(x: float) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _require_finite(name: str, x: float) -> float:
    if not _finite(x):
        raise RiskInputError(f"{name} must be a finite number, got {x!r}")
    return float(x)


def _require_nonneg(name: str, x: float) -> float:
    v = _require_finite(name, x)
    if v < 0.0:
        raise RiskInputError(f"{name} must be >= 0, got {v!r}")
    return v


def _require_fraction(name: str, x: float, *, allow_zero: bool = True) -> float:
    v = _require_finite(name, x)
    if v > 1.0 or v < 0.0 or (not allow_zero and v == 0.0):
        bound = "[0, 1]" if allow_zero else "(0, 1]"
        raise RiskInputError(f"{name} must be in {bound}, got {v!r}")
    return v


def _validate_weights(weights: Weights) -> dict[str, float]:
    if not isinstance(weights, Mapping):
        raise RiskInputError("weights must be a mapping of symbol -> weight")
    if len(weights) == 0:
        raise RiskInputError("weights are empty")
    out: dict[str, float] = {}
    for sym, w in weights.items():
        if not isinstance(sym, str) or not sym:
            raise RiskInputError(f"invalid symbol {sym!r}")
        out[sym] = _require_finite(f"weight[{sym}]", w)
    return out


def gross_exposure(weights: Weights) -> float:
    """Sum of absolute weights."""
    return float(sum(abs(float(w)) for w in weights.values()))


def net_exposure(weights: Weights) -> float:
    """Sum of signed weights."""
    return float(sum(float(w) for w in weights.values()))


def _scale(weights: Mapping[str, float], k: float) -> dict[str, float]:
    return {s: float(w) * k for s, w in weights.items()}


def _scale_gross_to_cap(weights: Mapping[str, float], cap: float) -> tuple[dict[str, float], bool]:
    """Scale down (never up) so gross <= cap, robust to float round-off."""
    out = dict(weights)
    g = gross_exposure(out)
    if g <= cap:
        return out, False
    k = cap / g
    out = _scale(out, k)
    while gross_exposure(out) > cap:  # float round-off guard; at most a few iterations
        k = math.nextafter(k, 0.0)
        out = _scale(weights, k)
    return out, True


def _scale_net_to_cap(weights: Mapping[str, float], cap: float) -> tuple[dict[str, float], bool]:
    """Scale the whole book down (never up) so |net| <= cap, robust to float round-off."""
    out = dict(weights)
    n = abs(net_exposure(out))
    if n <= cap:
        return out, False
    k = cap / n
    out = _scale(weights, k)
    while abs(net_exposure(out)) > cap:
        k = math.nextafter(k, 0.0)
        out = _scale(weights, k)
    return out, True


# ----------------------------------------------------------------------------------------------
# volatility targeting
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VolTargetConfig:
    """Vol-target parameters. All fields required; no desk defaults.

    Example values (illustrative only): ``target_vol_annual=0.10, lookback=63,
    annualisation_factor=252, gross_cap=1.0``.
    """

    target_vol_annual: float
    lookback: int
    annualisation_factor: float
    gross_cap: float

    def __post_init__(self) -> None:
        tv = _require_finite("target_vol_annual", self.target_vol_annual)
        if tv <= 0.0:
            raise RiskInputError("target_vol_annual must be > 0")
        if not isinstance(self.lookback, int) or isinstance(self.lookback, bool) or self.lookback < 2:
            raise RiskInputError("lookback must be an int >= 2")
        af = _require_finite("annualisation_factor", self.annualisation_factor)
        if af <= 0.0:
            raise RiskInputError("annualisation_factor must be > 0")
        _require_fraction("gross_cap", self.gross_cap, allow_zero=False)


@dataclass(frozen=True)
class VolTargetResult:
    weights: dict[str, float]
    realised_vol_annual: float
    scale: float
    capped_by_gross: bool


def portfolio_vol_from_covariance(
    weights: Weights,
    symbols: Sequence[str],
    covariance: Sequence[Sequence[float]] | FloatArray,
    annualisation_factor: float,
) -> float:
    """Annualised portfolio vol ``sqrt(w' C w * annualisation_factor)``.

    ``covariance`` is the per-period covariance matrix ordered like ``symbols``. Pass
    ``annualisation_factor=1`` if the matrix is already annualised. Every weighted symbol must be
    in ``symbols``; symbols without weight count as zero.
    """
    w = _validate_weights(weights)
    af = _require_finite("annualisation_factor", annualisation_factor)
    if af <= 0.0:
        raise RiskInputError("annualisation_factor must be > 0")
    syms = list(symbols)
    if len(set(syms)) != len(syms) or not syms:
        raise RiskInputError("symbols must be non-empty and unique")
    missing = sorted(set(w) - set(syms))
    if missing:
        raise RiskInputError(f"weights for symbols missing from covariance: {missing}")
    cov: FloatArray = np.asarray(covariance, dtype=np.float64)
    n = len(syms)
    if cov.shape != (n, n):
        raise RiskInputError(f"covariance shape {cov.shape} does not match {n} symbols")
    if not np.all(np.isfinite(cov)):
        raise RiskInputError("covariance contains non-finite values")
    if not np.allclose(cov, cov.T, rtol=1e-9, atol=1e-12):
        raise RiskInputError("covariance is not symmetric")
    if np.any(np.diag(cov) < 0.0):
        raise RiskInputError("covariance has negative variances")
    vec: FloatArray = np.array([w.get(s, 0.0) for s in syms], dtype=np.float64)
    var = float(vec @ cov @ vec)
    if var < -1e-12:
        raise RiskInputError("covariance is not positive semi-definite for these weights")
    vol = math.sqrt(max(var, 0.0) * af)
    if not math.isfinite(vol):
        raise RiskInputError("portfolio vol is not finite")
    return vol


def portfolio_vol_from_returns(
    weights: Weights,
    returns: Mapping[str, Sequence[float]],
    lookback: int,
    annualisation_factor: float,
) -> float:
    """Annualised portfolio vol from aligned per-period asset returns over the last ``lookback`` obs.

    ``returns[symbol]`` is an equally long, time-ordered sequence for every weighted symbol. Any
    NaN/inf in the lookback window is rejected (fail closed) rather than dropped.
    """
    w = _validate_weights(weights)
    if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 2:
        raise RiskInputError("lookback must be an int >= 2")
    missing = sorted(s for s in w if s not in returns)
    if missing:
        raise RiskInputError(f"no returns for weighted symbols: {missing}")
    syms = sorted(w)
    lengths = {len(returns[s]) for s in syms}
    if len(lengths) != 1:
        raise RiskInputError("return series are not aligned (different lengths)")
    length = lengths.pop()
    if length < lookback:
        raise RiskInputError(f"need {lookback} return observations, have {length}")
    mat: FloatArray = np.array([list(returns[s])[-lookback:] for s in syms], dtype=np.float64)
    if not np.all(np.isfinite(mat)):
        raise RiskInputError("returns contain non-finite values in the lookback window")
    cov: FloatArray = np.atleast_2d(np.cov(mat, ddof=1))
    return portfolio_vol_from_covariance(w, syms, cov, annualisation_factor)


def scale_to_target_vol(
    weights: Weights, portfolio_vol_annual: float, target_vol_annual: float, gross_cap: float
) -> VolTargetResult:
    """Scale ``weights`` by ``target / realised`` vol, never letting gross exceed ``gross_cap`` (<= 1).

    A realised vol of zero cannot be targeted and is rejected. If the input book is already
    above ``gross_cap`` it is scaled down to the cap even when the vol ratio says otherwise.
    """
    w = _validate_weights(weights)
    vol = _require_finite("portfolio_vol_annual", portfolio_vol_annual)
    if vol <= 0.0:
        raise RiskInputError("portfolio_vol_annual must be > 0 to vol-target")
    tv = _require_finite("target_vol_annual", target_vol_annual)
    if tv <= 0.0:
        raise RiskInputError("target_vol_annual must be > 0")
    cap = _require_fraction("gross_cap", gross_cap, allow_zero=False)
    k = tv / vol
    scaled = _scale(w, k)
    capped, was_capped = _scale_gross_to_cap(scaled, cap)
    g0 = gross_exposure(w)
    eff = gross_exposure(capped) / g0 if g0 > 0.0 else 0.0
    return VolTargetResult(weights=capped, realised_vol_annual=vol, scale=eff, capped_by_gross=was_capped)


def vol_target_weights(
    weights: Weights, returns: Mapping[str, Sequence[float]], config: VolTargetConfig
) -> VolTargetResult:
    """Estimate realised vol from ``returns`` and scale ``weights`` toward ``config.target_vol_annual``."""
    vol = portfolio_vol_from_returns(weights, returns, config.lookback, config.annualisation_factor)
    return scale_to_target_vol(weights, vol, config.target_vol_annual, config.gross_cap)


# ----------------------------------------------------------------------------------------------
# drawdown and breaker
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DrawdownStats:
    """Drawdowns are positive fractions of the running peak (0.25 means 25% below peak)."""

    running_peak: tuple[float, ...]
    drawdown: tuple[float, ...]
    current_drawdown: float
    max_drawdown: float


def drawdown_stats(equity: Sequence[float]) -> DrawdownStats:
    """Running peak, drawdown series, current and max drawdown of a positive equity curve."""
    if len(equity) == 0:
        raise RiskInputError("equity curve is empty")
    peak = -math.inf
    peaks: list[float] = []
    dds: list[float] = []
    for i, e in enumerate(equity):
        v = _require_finite(f"equity[{i}]", e)
        if v <= 0.0:
            raise RiskInputError(f"equity[{i}] must be > 0, got {v!r}")
        peak = max(peak, v)
        peaks.append(peak)
        dds.append((peak - v) / peak)
    return DrawdownStats(tuple(peaks), tuple(dds), dds[-1], max(dds))


class BreakerState(StrEnum):
    NORMAL = "NORMAL"
    REDUCE = "REDUCE"
    FLAT = "FLAT"


_SEVERITY = {BreakerState.NORMAL: 0, BreakerState.REDUCE: 1, BreakerState.FLAT: 2}


@dataclass(frozen=True)
class DrawdownBreakerConfig:
    """Drawdown breaker thresholds. All fields required; no desk defaults.

    * ``reduce_at``: current drawdown at/above which the breaker signals REDUCE.
    * ``flat_at``: current drawdown at/above which it signals FLAT (must be >= ``reduce_at``).
    * ``reduce_multiplier``: exposure multiplier while in REDUCE, in [0, 1].
    * ``rearm_at``: explicit rearm rule. A tripped breaker (REDUCE or FLAT) stays tripped, and
      never steps down by itself, until current drawdown recovers to at or below ``rearm_at``
      (must be < ``reduce_at``); it then returns to NORMAL. Escalation REDUCE -> FLAT is
      immediate. Between ``rearm_at`` and ``reduce_at`` the previous state is held (hysteresis).

    Example values (illustrative only): ``reduce_at=0.10, flat_at=0.20, reduce_multiplier=0.5,
    rearm_at=0.05``.
    """

    reduce_at: float
    flat_at: float
    reduce_multiplier: float
    rearm_at: float

    def __post_init__(self) -> None:
        r = _require_fraction("reduce_at", self.reduce_at, allow_zero=False)
        f = _require_fraction("flat_at", self.flat_at, allow_zero=False)
        _require_fraction("reduce_multiplier", self.reduce_multiplier)
        a = _require_fraction("rearm_at", self.rearm_at)
        if f < r:
            raise RiskInputError("flat_at must be >= reduce_at")
        if a >= r:
            raise RiskInputError("rearm_at must be < reduce_at")


@dataclass(frozen=True)
class BreakerDecision:
    state: BreakerState
    signal: str  # "none" | "reduce" | "flat"
    exposure_multiplier: float
    rearmed: bool
    reason: str


def _decision(state: BreakerState, cfg: DrawdownBreakerConfig, rearmed: bool, reason: str) -> BreakerDecision:
    mult = {BreakerState.NORMAL: 1.0, BreakerState.REDUCE: float(cfg.reduce_multiplier), BreakerState.FLAT: 0.0}
    sig = {BreakerState.NORMAL: "none", BreakerState.REDUCE: "reduce", BreakerState.FLAT: "flat"}
    return BreakerDecision(state, sig[state], mult[state], rearmed, reason)


def evaluate_drawdown_breaker(
    current_drawdown: float, previous_state: BreakerState | str, config: DrawdownBreakerConfig
) -> BreakerDecision:
    """One breaker step. Fails closed: an invalid drawdown, or a previous state that is not a
    :class:`BreakerState` member (plain strings included), returns FLAT."""
    if not isinstance(previous_state, BreakerState):
        return _decision(BreakerState.FLAT, config, False, f"fail-closed: unknown previous state {previous_state!r}")
    if not _finite(current_drawdown) or not 0.0 <= float(current_drawdown) <= 1.0:
        return _decision(BreakerState.FLAT, config, False, f"fail-closed: invalid drawdown {current_drawdown!r}")
    dd = float(current_drawdown)
    if dd >= config.flat_at:
        return _decision(BreakerState.FLAT, config, False, f"drawdown {dd:.6f} >= flat_at")
    if dd >= config.reduce_at:
        state = previous_state if _SEVERITY[previous_state] > _SEVERITY[BreakerState.REDUCE] else BreakerState.REDUCE
        return _decision(state, config, False, f"drawdown {dd:.6f} >= reduce_at")
    if dd <= config.rearm_at:
        rearmed = previous_state is not BreakerState.NORMAL
        reason = "rearmed: drawdown recovered to <= rearm_at" if rearmed else "normal"
        return _decision(BreakerState.NORMAL, config, rearmed, reason)
    return _decision(previous_state, config, False, "hold: drawdown between rearm_at and reduce_at")


def run_drawdown_breaker(
    equity: Sequence[float],
    config: DrawdownBreakerConfig,
    initial_state: BreakerState = BreakerState.NORMAL,
) -> tuple[BreakerDecision, ...]:
    """Apply the breaker along an equity curve; returns one decision per observation."""
    stats = drawdown_stats(equity)
    state = initial_state
    out: list[BreakerDecision] = []
    for dd in stats.drawdown:
        d = evaluate_drawdown_breaker(dd, state, config)
        out.append(d)
        state = d.state
    return tuple(out)


# ----------------------------------------------------------------------------------------------
# exposure limits
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExposureLimits:
    """Paper-sizing exposure limits. All caps required; no desk defaults.

    * ``single_name_cap``: max ``|w|`` per symbol, in [0, 1].
    * ``gross_cap``: max ``sum(|w|)``, in (0, 1]. Values above 1.0 (leverage) are rejected.
    * ``net_cap``: max ``|sum(w)|``, in [0, ``gross_cap``].
    * ``group_caps``: optional max gross per group (e.g. sector), each in [0, 1].
    * ``prohibited_symbols`` / ``prohibited_asset_classes``: always sized to zero and reported.
      Matching is case-insensitive. When asset classes are prohibited, a symbol with no known
      asset class is treated as prohibited (fail closed).

    Example (illustrative only): ``ExposureLimits(single_name_cap=0.10, gross_cap=1.0,
    net_cap=0.30, prohibited_asset_classes=frozenset({"crypto"}))``.
    """

    single_name_cap: float
    gross_cap: float
    net_cap: float
    group_caps: Mapping[str, float] | None = None
    prohibited_symbols: frozenset[str] = field(default_factory=frozenset)
    prohibited_asset_classes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        _require_fraction("single_name_cap", self.single_name_cap)
        g = _require_fraction("gross_cap", self.gross_cap, allow_zero=False)
        if g > MAX_GROSS:
            raise RiskInputError("gross_cap above 1.0 (leverage) is not allowed")
        n = _require_fraction("net_cap", self.net_cap)
        if n > g:
            raise RiskInputError("net_cap must be <= gross_cap")
        if self.group_caps is not None:
            for grp, cap in self.group_caps.items():
                _require_fraction(f"group_caps[{grp}]", cap)
        named: tuple[tuple[str, object], ...] = (
            ("prohibited_symbols", self.prohibited_symbols),
            ("prohibited_asset_classes", self.prohibited_asset_classes),
        )
        for name, coll in named:
            if not isinstance(coll, (frozenset, set)) or not all(isinstance(x, str) for x in coll):
                raise RiskInputError(f"{name} must be a frozenset of strings")

    def is_prohibited(self, symbol: str, asset_class: str | None) -> str | None:
        """Return the reason a symbol is prohibited, or None."""
        if symbol.upper() in {s.upper() for s in self.prohibited_symbols}:
            return "prohibited symbol"
        if self.prohibited_asset_classes:
            if asset_class is None:
                return "asset class unknown while asset classes are prohibited"
            if asset_class.lower() in {c.lower() for c in self.prohibited_asset_classes}:
                return f"prohibited asset class {asset_class}"
        return None


@dataclass(frozen=True)
class LimitResult:
    weights: dict[str, float]
    zeroed: tuple[tuple[str, str], ...]  # (symbol, reason) for prohibited names set to zero
    adjustments: tuple[str, ...]


def _group_gross(weights: Mapping[str, float], groups: Mapping[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s, w in weights.items():
        g = groups.get(s)
        if g is not None:
            out[g] = out.get(g, 0.0) + abs(w)
    return out


def apply_exposure_limits(
    weights: Weights,
    limits: ExposureLimits,
    *,
    groups: Mapping[str, str] | None = None,
    asset_classes: Mapping[str, str] | None = None,
) -> LimitResult:
    """Size a book down to ``limits``. Only ever reduces ``|w|``; never adds leverage.

    Order: zero prohibited names, clip single names, scale each over-cap group, scale the whole
    book for net, then for gross. Every step only shrinks weights, so earlier caps stay met.
    Raises :class:`RiskInputError` on bad input (including a weighted symbol with no group when
    group caps are configured).
    """
    w = _validate_weights(weights)
    classes = asset_classes or {}
    zeroed: list[tuple[str, str]] = []
    adj: list[str] = []

    for s in sorted(w):
        why = limits.is_prohibited(s, classes.get(s))
        if why is not None:
            if w[s] != 0.0:
                zeroed.append((s, why))
            else:
                zeroed.append((s, why + " (already zero)"))
            w[s] = 0.0

    cap = float(limits.single_name_cap)
    for s in sorted(w):
        if abs(w[s]) > cap:
            adj.append(f"single-name clip {s}: {w[s]:.6f} -> {math.copysign(cap, w[s]):.6f}")
            w[s] = math.copysign(cap, w[s])

    if limits.group_caps:
        if groups is None:
            raise RiskInputError("group_caps configured but no groups mapping given")
        ungrouped = sorted(s for s, x in w.items() if x != 0.0 and s not in groups)
        if ungrouped:
            raise RiskInputError(f"symbols with no group while group caps are configured: {ungrouped}")
        for grp, gcap in sorted(limits.group_caps.items()):
            members = {s: x for s, x in w.items() if groups.get(s) == grp}
            scaled, did = _scale_gross_to_cap(members, float(gcap))
            if did:
                adj.append(f"group cap {grp}: gross {gross_exposure(members):.6f} -> {gross_exposure(scaled):.6f}")
                w.update(scaled)

    n = net_exposure(w)
    w, did_net = _scale_net_to_cap(w, float(limits.net_cap))
    if did_net:
        adj.append(f"net cap: {n:.6f} -> {net_exposure(w):.6f}")

    before = gross_exposure(w)
    w, did = _scale_gross_to_cap(w, float(limits.gross_cap))
    if did:
        adj.append(f"gross cap: {before:.6f} -> {gross_exposure(w):.6f}")

    return LimitResult(weights=w, zeroed=tuple(zeroed), adjustments=tuple(adj))


# ----------------------------------------------------------------------------------------------
# pre-trade check
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    symbol: str | None = None


@dataclass(frozen=True)
class PreTradeResult:
    passed: bool
    violations: tuple[Violation, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(v.code for v in self.violations)


_EPS = 1e-12


def _check(
    weights: Any,
    limits: Any,
    groups: Mapping[str, str] | None,
    asset_classes: Mapping[str, str] | None,
    portfolio_vol_annual: float | None,
) -> list[Violation]:
    v: list[Violation] = []
    if not isinstance(limits, ExposureLimits):
        return [Violation("BAD_LIMITS", f"limits must be ExposureLimits, got {type(limits).__name__}")]
    if not isinstance(weights, Mapping):
        return [Violation("BAD_INPUT", "weights must be a mapping of symbol -> weight")]
    if len(weights) == 0:
        return [Violation("EMPTY", "no weights given")]
    clean: dict[str, float] = {}
    for sym, w in weights.items():
        if not isinstance(sym, str) or not sym:
            v.append(Violation("BAD_SYMBOL", f"invalid symbol {sym!r}"))
        elif not _finite(w):
            v.append(Violation("NON_FINITE_WEIGHT", f"weight {w!r} is not a finite number", sym))
        else:
            clean[sym] = float(w)
    if v:
        return v  # fail closed: do not evaluate limits on a partially valid book

    if portfolio_vol_annual is not None:
        if not _finite(portfolio_vol_annual):
            v.append(Violation("BAD_VOL", f"portfolio vol {portfolio_vol_annual!r} is not finite"))
        elif float(portfolio_vol_annual) < 0.0:
            v.append(Violation("BAD_VOL", f"portfolio vol {portfolio_vol_annual!r} is negative"))

    classes = asset_classes or {}
    for s in sorted(clean):
        why = limits.is_prohibited(s, classes.get(s))
        if why is not None and clean[s] != 0.0:
            v.append(Violation("PROHIBITED", f"{why}; weight {clean[s]:.6f} must be zero", s))

    for s in sorted(clean):
        if abs(clean[s]) > limits.single_name_cap + _EPS:
            v.append(Violation("SINGLE_NAME", f"|w|={abs(clean[s]):.6f} > cap {limits.single_name_cap}", s))

    g = gross_exposure(clean)
    if g > MAX_GROSS + _EPS:
        v.append(Violation("LEVERAGE", f"gross {g:.6f} > 1.0 (no leverage)"))
    if g > limits.gross_cap + _EPS:
        v.append(Violation("GROSS", f"gross {g:.6f} > cap {limits.gross_cap}"))
    n = net_exposure(clean)
    if abs(n) > limits.net_cap + _EPS:
        v.append(Violation("NET", f"|net| {abs(n):.6f} > cap {limits.net_cap}"))

    if limits.group_caps:
        if groups is None:
            v.append(Violation("NO_GROUPS", "group caps configured but no groups mapping given"))
        else:
            for s in sorted(clean):
                if clean[s] != 0.0 and s not in groups:
                    v.append(Violation("UNGROUPED", "no group while group caps are configured", s))
            gg = _group_gross(clean, groups)
            for grp, cap in sorted(limits.group_caps.items()):
                if gg.get(grp, 0.0) > float(cap) + _EPS:
                    v.append(Violation("GROUP", f"group {grp} gross {gg[grp]:.6f} > cap {cap}"))
    return v


def pre_trade_check(
    weights: Weights,
    limits: ExposureLimits,
    *,
    groups: Mapping[str, str] | None = None,
    asset_classes: Mapping[str, str] | None = None,
    portfolio_vol_annual: float | None = None,
) -> PreTradeResult:
    """Check a proposed paper book against ``limits``. Never raises; fails closed.

    Returns ``passed=False`` with typed violations for any breach, and also for bad input:
    empty book, NaN/inf weights, invalid symbols, NaN or negative vol, gross above 1.0, missing
    group mapping when group caps are set, or an unexpected internal error (``INTERNAL_ERROR``).
    """
    try:
        violations = _check(weights, limits, groups, asset_classes, portfolio_vol_annual)
    except Exception as exc:  # fail closed: surfaced as a violation, never swallowed
        violations = [Violation("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")]
    return PreTradeResult(passed=not violations, violations=tuple(violations))


# ----------------------------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskReport:
    """Render-agnostic risk summary. ``to_dict()`` gives plain JSON-friendly values."""

    passed: bool
    gross: float | None
    net: float | None
    long: float | None
    short: float | None
    max_single_name: float | None
    n_positions: int
    group_gross: dict[str, float]
    portfolio_vol_annual: float | None
    current_drawdown: float | None
    max_drawdown: float | None
    breaker_state: str | None
    breaker_signal: str | None
    violations: tuple[Violation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "gross": self.gross,
            "net": self.net,
            "long": self.long,
            "short": self.short,
            "max_single_name": self.max_single_name,
            "n_positions": self.n_positions,
            "group_gross": dict(self.group_gross),
            "portfolio_vol_annual": self.portfolio_vol_annual,
            "current_drawdown": self.current_drawdown,
            "max_drawdown": self.max_drawdown,
            "breaker_state": self.breaker_state,
            "breaker_signal": self.breaker_signal,
            "violations": [{"code": x.code, "symbol": x.symbol, "detail": x.detail} for x in self.violations],
        }


def build_risk_report(
    weights: Weights,
    limits: ExposureLimits,
    *,
    groups: Mapping[str, str] | None = None,
    asset_classes: Mapping[str, str] | None = None,
    portfolio_vol_annual: float | None = None,
    drawdown: DrawdownStats | None = None,
    breaker: BreakerDecision | None = None,
) -> RiskReport:
    """Summarise exposures, vol, drawdown, breaker and violations. Does no I/O.

    ``passed`` is False if the pre-trade check fails or the breaker is not NORMAL. Exposure
    figures are None when the weights themselves are invalid.
    """
    check = pre_trade_check(
        weights, limits, groups=groups, asset_classes=asset_classes, portfolio_vol_annual=portfolio_vol_annual
    )
    clean: dict[str, float] | None
    try:
        clean = _validate_weights(weights)
    except RiskInputError:
        clean = None
    gross: float | None = None
    net: float | None = None
    long_: float | None = None
    short: float | None = None
    mx: float | None = None
    gg: dict[str, float] = {}
    n_pos = 0
    if clean is not None:
        gross, net = gross_exposure(clean), net_exposure(clean)
        long_ = float(sum(x for x in clean.values() if x > 0.0))
        short = float(sum(-x for x in clean.values() if x < 0.0))
        mx = max(abs(x) for x in clean.values())
        n_pos = sum(1 for x in clean.values() if x != 0.0)
        if groups is not None:
            gg = _group_gross(clean, groups)
    breaker_ok = breaker is None or breaker.state is BreakerState.NORMAL
    return RiskReport(
        passed=check.passed and breaker_ok,
        gross=gross,
        net=net,
        long=long_,
        short=short,
        max_single_name=mx,
        n_positions=n_pos,
        group_gross=gg,
        portfolio_vol_annual=portfolio_vol_annual,
        current_drawdown=None if drawdown is None else drawdown.current_drawdown,
        max_drawdown=None if drawdown is None else drawdown.max_drawdown,
        breaker_state=None if breaker is None else breaker.state.value,
        breaker_signal=None if breaker is None else breaker.signal,
        violations=check.violations,
    )
