"""Tests for the paper-sizing risk module. Synthetic data only; every number here is an EXAMPLE."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from quant_research.strategies.portfolio_construction import paper_risk as pr
from quant_research.strategies.portfolio_construction.paper_risk import (
    BreakerState,
    DrawdownBreakerConfig,
    ExposureLimits,
    RiskInputError,
    VolTargetConfig,
)

# Example limits for tests only, not desk policy.
EX_LIMITS = ExposureLimits(single_name_cap=0.10, gross_cap=1.0, net_cap=0.30)
EX_BREAKER = DrawdownBreakerConfig(reduce_at=0.10, flat_at=0.20, reduce_multiplier=0.5, rearm_at=0.05)


def _synthetic_returns(n_assets: int, n_obs: int, daily_vol: float, seed: int) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    mat = rng.normal(0.0, daily_vol, size=(n_assets, n_obs))
    return {f"S{i:02d}": [float(x) for x in mat[i]] for i in range(n_assets)}


def _random_book(rng: random.Random, n: int, scale: float) -> dict[str, float]:
    return {f"S{i:02d}": rng.uniform(-scale, scale) for i in range(n)}


# ------------------------------------------------------------------ exposures


def test_gross_net():
    w = {"A": 0.2, "B": -0.1, "C": 0.0}
    assert pr.gross_exposure(w) == pytest.approx(0.3)
    assert pr.net_exposure(w) == pytest.approx(0.1)


# ------------------------------------------------------------------ vol targeting


def test_vol_from_covariance_matches_closed_form():
    cov = [[0.04, 0.0], [0.0, 0.01]]
    vol = pr.portfolio_vol_from_covariance({"A": 0.5, "B": 0.5}, ["A", "B"], cov, 1.0)
    assert vol == pytest.approx(math.sqrt(0.25 * 0.04 + 0.25 * 0.01))


def test_vol_from_covariance_annualises():
    cov = [[1e-4]]
    assert pr.portfolio_vol_from_covariance({"A": 1.0}, ["A"], cov, 252.0) == pytest.approx(0.01 * math.sqrt(252))


@pytest.mark.parametrize(
    "cov",
    [
        [[0.04, 0.01], [0.0, 0.01]],  # asymmetric
        [[float("nan"), 0.0], [0.0, 0.01]],  # NaN
        [[-0.01, 0.0], [0.0, 0.01]],  # negative variance
        [[0.04]],  # wrong shape
    ],
)
def test_vol_from_covariance_rejects_bad_matrix(cov):
    with pytest.raises(RiskInputError):
        pr.portfolio_vol_from_covariance({"A": 0.5, "B": 0.5}, ["A", "B"], cov, 1.0)


def test_vol_from_covariance_missing_symbol():
    with pytest.raises(RiskInputError):
        pr.portfolio_vol_from_covariance({"A": 0.5, "Z": 0.5}, ["A", "B"], [[0.04, 0], [0, 0.01]], 1.0)


def test_vol_from_returns_recovers_synthetic_vol():
    daily = 0.01
    rets = _synthetic_returns(1, 5000, daily, seed=1)
    vol = pr.portfolio_vol_from_returns({"S00": 1.0}, rets, lookback=5000, annualisation_factor=252.0)
    assert vol == pytest.approx(daily * math.sqrt(252), rel=0.05)


def test_vol_from_returns_uses_only_lookback_window():
    calm = [0.0001 * ((-1) ** i) for i in range(100)]
    wild = [0.05 * ((-1) ** i) for i in range(20)]
    rets = {"A": wild + calm}
    v_short = pr.portfolio_vol_from_returns({"A": 1.0}, rets, lookback=50, annualisation_factor=1.0)
    v_long = pr.portfolio_vol_from_returns({"A": 1.0}, rets, lookback=120, annualisation_factor=1.0)
    assert v_short < 0.001 < v_long


@pytest.mark.parametrize(
    "rets, lookback",
    [
        ({"A": [0.01, float("nan"), 0.02, -0.01]}, 4),  # NaN in window
        ({"A": [0.01, 0.02]}, 5),  # too short
        ({"A": [0.01, 0.02, 0.03], "B": [0.01, 0.02]}, 2),  # misaligned
        ({"B": [0.01, 0.02, 0.03]}, 2),  # missing symbol
        ({"A": [0.01, 0.02, 0.03]}, 1),  # lookback < 2
    ],
)
def test_vol_from_returns_fails_closed(rets, lookback):
    w = {"A": 0.5, "B": 0.5} if "B" in rets and "A" in rets else {"A": 1.0}
    with pytest.raises(RiskInputError):
        pr.portfolio_vol_from_returns(w, rets, lookback=lookback, annualisation_factor=252.0)


def test_scale_down_to_target():
    res = pr.scale_to_target_vol({"A": 0.5, "B": 0.5}, 0.20, 0.10, gross_cap=1.0)
    assert res.weights == pytest.approx({"A": 0.25, "B": 0.25})
    assert res.scale == pytest.approx(0.5)
    assert not res.capped_by_gross


def test_scale_up_is_capped_at_gross_one_no_leverage():
    res = pr.scale_to_target_vol({"A": 0.3, "B": -0.2}, 0.02, 0.10, gross_cap=1.0)
    assert res.capped_by_gross
    assert pr.gross_exposure(res.weights) <= 1.0
    assert pr.gross_exposure(res.weights) == pytest.approx(1.0)
    assert res.weights["A"] / res.weights["B"] == pytest.approx(0.3 / -0.2)


def test_scale_respects_lower_gross_cap():
    res = pr.scale_to_target_vol({"A": 0.3}, 0.01, 0.50, gross_cap=0.6)
    assert pr.gross_exposure(res.weights) <= 0.6


def test_scale_already_levered_book_is_brought_under_one():
    res = pr.scale_to_target_vol({"A": 0.9, "B": -0.9}, 0.10, 0.10, gross_cap=1.0)
    assert pr.gross_exposure(res.weights) <= 1.0


@pytest.mark.parametrize("vol", [0.0, -0.1, float("nan"), float("inf")])
def test_scale_rejects_bad_vol(vol):
    with pytest.raises(RiskInputError):
        pr.scale_to_target_vol({"A": 0.5}, vol, 0.10, gross_cap=1.0)


@pytest.mark.parametrize("cap", [1.5, 0.0, -0.2, float("nan")])
def test_scale_rejects_bad_gross_cap(cap):
    with pytest.raises(RiskInputError):
        pr.scale_to_target_vol({"A": 0.5}, 0.2, 0.10, gross_cap=cap)


def test_vol_target_end_to_end_on_synthetic_data():
    rets = _synthetic_returns(4, 2000, 0.02, seed=7)
    w = dict.fromkeys(rets, 0.1)
    cfg = VolTargetConfig(target_vol_annual=0.05, lookback=1000, annualisation_factor=252.0, gross_cap=1.0)
    res = pr.vol_target_weights(w, rets, cfg)
    after = pr.portfolio_vol_from_returns(res.weights, rets, 1000, 252.0)
    assert after == pytest.approx(0.05, rel=1e-9)
    assert pr.gross_exposure(res.weights) <= 1.0


def test_vol_target_low_vol_hits_gross_cap():
    rets = _synthetic_returns(3, 500, 0.0005, seed=3)
    cfg = VolTargetConfig(target_vol_annual=0.50, lookback=250, annualisation_factor=252.0, gross_cap=1.0)
    res = pr.vol_target_weights(dict.fromkeys(rets, 0.2), rets, cfg)
    assert res.capped_by_gross and pr.gross_exposure(res.weights) <= 1.0


@pytest.mark.parametrize(
    "kw",
    [
        dict(target_vol_annual=0.0, lookback=20, annualisation_factor=252.0, gross_cap=1.0),
        dict(target_vol_annual=0.1, lookback=1, annualisation_factor=252.0, gross_cap=1.0),
        dict(target_vol_annual=0.1, lookback=20, annualisation_factor=0.0, gross_cap=1.0),
        dict(target_vol_annual=0.1, lookback=20, annualisation_factor=252.0, gross_cap=1.01),
        dict(target_vol_annual=float("nan"), lookback=20, annualisation_factor=252.0, gross_cap=1.0),
    ],
)
def test_vol_config_validation(kw):
    with pytest.raises(RiskInputError):
        VolTargetConfig(**kw)


# ------------------------------------------------------------------ drawdown


def test_drawdown_stats():
    st = pr.drawdown_stats([100.0, 110.0, 99.0, 121.0, 108.9])
    assert st.running_peak == (100.0, 110.0, 110.0, 121.0, 121.0)
    assert st.drawdown[2] == pytest.approx(0.1)
    assert st.current_drawdown == pytest.approx(0.1)
    assert st.max_drawdown == pytest.approx(0.1)
    assert st.drawdown[0] == 0.0 and st.drawdown[3] == 0.0


def test_drawdown_monotone_up_is_zero():
    st = pr.drawdown_stats([1.0, 2.0, 3.0])
    assert st.max_drawdown == 0.0 and st.current_drawdown == 0.0


@pytest.mark.parametrize("eq", [[], [100.0, float("nan")], [100.0, 0.0], [100.0, -5.0], [float("inf")]])
def test_drawdown_fails_closed(eq):
    with pytest.raises(RiskInputError):
        pr.drawdown_stats(eq)


# ------------------------------------------------------------------ breaker


def test_breaker_trip_reduce_then_flat():
    d = pr.evaluate_drawdown_breaker(0.12, BreakerState.NORMAL, EX_BREAKER)
    assert d.state is BreakerState.REDUCE and d.signal == "reduce" and d.exposure_multiplier == 0.5
    d = pr.evaluate_drawdown_breaker(0.25, d.state, EX_BREAKER)
    assert d.state is BreakerState.FLAT and d.signal == "flat" and d.exposure_multiplier == 0.0


def test_breaker_hysteresis_holds_until_rearm():
    # FLAT does not step down to REDUCE or NORMAL while drawdown is above rearm_at
    for dd in (0.15, 0.10, 0.07):
        assert pr.evaluate_drawdown_breaker(dd, BreakerState.FLAT, EX_BREAKER).state is BreakerState.FLAT
    assert pr.evaluate_drawdown_breaker(0.07, BreakerState.REDUCE, EX_BREAKER).state is BreakerState.REDUCE
    assert pr.evaluate_drawdown_breaker(0.07, BreakerState.NORMAL, EX_BREAKER).state is BreakerState.NORMAL


def test_breaker_rearm():
    d = pr.evaluate_drawdown_breaker(0.05, BreakerState.FLAT, EX_BREAKER)
    assert d.state is BreakerState.NORMAL and d.rearmed and d.exposure_multiplier == 1.0
    d2 = pr.evaluate_drawdown_breaker(0.0, BreakerState.NORMAL, EX_BREAKER)
    assert d2.state is BreakerState.NORMAL and not d2.rearmed


@pytest.mark.parametrize("dd", [float("nan"), -0.01, 1.5, float("inf")])
def test_breaker_fails_closed_on_bad_drawdown(dd):
    d = pr.evaluate_drawdown_breaker(dd, BreakerState.NORMAL, EX_BREAKER)
    assert d.state is BreakerState.FLAT and d.exposure_multiplier == 0.0 and "fail-closed" in d.reason


def test_breaker_fails_closed_on_unknown_state():
    d = pr.evaluate_drawdown_breaker(0.0, "NORMAL", EX_BREAKER)
    assert d.state is BreakerState.FLAT


def test_run_breaker_along_curve_trips_and_rearms():
    eq = [100, 95, 89, 85, 79, 85, 92, 96, 101]
    states = [d.state for d in pr.run_drawdown_breaker([float(x) for x in eq], EX_BREAKER)]
    assert states == [
        BreakerState.NORMAL,  # 0%
        BreakerState.NORMAL,  # 5% <= rearm, still normal
        BreakerState.REDUCE,  # 11%
        BreakerState.REDUCE,  # 15%
        BreakerState.FLAT,  # 21%
        BreakerState.FLAT,  # 15% held
        BreakerState.FLAT,  # 8% held
        BreakerState.NORMAL,  # 4% rearm
        BreakerState.NORMAL,  # new peak
    ]


@pytest.mark.parametrize(
    "kw",
    [
        dict(reduce_at=0.2, flat_at=0.1, reduce_multiplier=0.5, rearm_at=0.05),  # flat < reduce
        dict(reduce_at=0.1, flat_at=0.2, reduce_multiplier=0.5, rearm_at=0.1),  # rearm not below reduce
        dict(reduce_at=0.1, flat_at=0.2, reduce_multiplier=1.5, rearm_at=0.05),  # multiplier > 1
        dict(reduce_at=0.0, flat_at=0.2, reduce_multiplier=0.5, rearm_at=0.0),  # zero threshold
        dict(reduce_at=float("nan"), flat_at=0.2, reduce_multiplier=0.5, rearm_at=0.05),
    ],
)
def test_breaker_config_validation(kw):
    with pytest.raises(RiskInputError):
        DrawdownBreakerConfig(**kw)


# ------------------------------------------------------------------ exposure limits


@pytest.mark.parametrize(
    "kw",
    [
        dict(single_name_cap=0.1, gross_cap=1.2, net_cap=0.3),  # leverage
        dict(single_name_cap=0.1, gross_cap=0.0, net_cap=0.0),
        dict(single_name_cap=0.1, gross_cap=0.5, net_cap=0.6),  # net > gross
        dict(single_name_cap=-0.1, gross_cap=1.0, net_cap=0.3),
        dict(single_name_cap=0.1, gross_cap=float("nan"), net_cap=0.3),
        dict(single_name_cap=0.1, gross_cap=1.0, net_cap=0.3, group_caps={"tech": 1.5}),
        dict(single_name_cap=0.1, gross_cap=1.0, net_cap=0.3, prohibited_symbols="BTCUSD"),
    ],
)
def test_limits_validation(kw):
    with pytest.raises(RiskInputError):
        ExposureLimits(**kw)


def test_prohibited_symbol_zeroed_and_reported():
    lim = ExposureLimits(single_name_cap=0.5, gross_cap=1.0, net_cap=1.0, prohibited_symbols=frozenset({"bad"}))
    res = pr.apply_exposure_limits({"BAD": 0.2, "OK": 0.2}, lim)
    assert res.weights["BAD"] == 0.0 and res.weights["OK"] == pytest.approx(0.2)
    assert res.zeroed and res.zeroed[0][0] == "BAD"


def test_prohibited_asset_class_and_unknown_class_fail_closed():
    lim = ExposureLimits(
        single_name_cap=0.5, gross_cap=1.0, net_cap=1.0, prohibited_asset_classes=frozenset({"crypto"})
    )
    w = {"COIN1": 0.2, "EQ": 0.2, "MYSTERY": 0.1}
    res = pr.apply_exposure_limits(w, lim, asset_classes={"COIN1": "Crypto", "EQ": "equity"})
    assert res.weights == {"COIN1": 0.0, "EQ": pytest.approx(0.2), "MYSTERY": 0.0}
    assert {s for s, _ in res.zeroed} == {"COIN1", "MYSTERY"}
    chk = pr.pre_trade_check(w, lim, asset_classes={"COIN1": "Crypto", "EQ": "equity"})
    assert not chk.passed and chk.codes.count("PROHIBITED") == 2


def test_single_name_clip_preserves_sign():
    res = pr.apply_exposure_limits({"A": 0.3, "B": -0.25, "C": 0.05}, EX_LIMITS)
    assert res.weights["A"] == pytest.approx(0.10) and res.weights["B"] == pytest.approx(-0.10)
    assert res.weights["C"] == pytest.approx(0.05)


def test_net_cap_scales_book():
    lim = ExposureLimits(single_name_cap=1.0, gross_cap=1.0, net_cap=0.2)
    res = pr.apply_exposure_limits({"A": 0.5, "B": 0.1}, lim)
    assert abs(pr.net_exposure(res.weights)) <= 0.2 + 1e-15
    assert pr.net_exposure(res.weights) == pytest.approx(0.2)


def test_group_cap():
    lim = ExposureLimits(single_name_cap=1.0, gross_cap=1.0, net_cap=1.0, group_caps={"tech": 0.3})
    groups = {"A": "tech", "B": "tech", "C": "energy"}
    res = pr.apply_exposure_limits({"A": 0.3, "B": 0.3, "C": 0.2}, lim, groups=groups)
    assert res.weights["A"] + res.weights["B"] == pytest.approx(0.3)
    assert res.weights["C"] == pytest.approx(0.2)
    assert pr.pre_trade_check(res.weights, lim, groups=groups).passed


def test_group_cap_needs_mapping():
    lim = ExposureLimits(single_name_cap=1.0, gross_cap=1.0, net_cap=1.0, group_caps={"tech": 0.3})
    with pytest.raises(RiskInputError):
        pr.apply_exposure_limits({"A": 0.1}, lim)
    with pytest.raises(RiskInputError):
        pr.apply_exposure_limits({"A": 0.1, "Z": 0.1}, lim, groups={"A": "tech"})
    chk = pr.pre_trade_check({"A": 0.1, "Z": 0.1}, lim, groups={"A": "tech"})
    assert not chk.passed and "UNGROUPED" in chk.codes
    assert "NO_GROUPS" in pr.pre_trade_check({"A": 0.1}, lim).codes


def test_apply_limits_rejects_bad_weights():
    for bad in ({}, {"A": float("nan")}, {"": 0.1}):
        with pytest.raises(RiskInputError):
            pr.apply_exposure_limits(bad, EX_LIMITS)


def test_apply_limits_output_passes_pre_trade_check():
    rng = random.Random(11)
    lim = ExposureLimits(single_name_cap=0.08, gross_cap=0.9, net_cap=0.1)
    for _ in range(50):
        w = _random_book(rng, 30, 0.3)
        res = pr.apply_exposure_limits(w, lim)
        assert pr.pre_trade_check(res.weights, lim).passed


def test_no_leverage_invariant_property():
    """Gross never exceeds 1.0 after any sizing function, on randomised synthetic books."""
    rng = random.Random(2026)
    lim = ExposureLimits(single_name_cap=1.0, gross_cap=1.0, net_cap=1.0)
    for _ in range(200):
        w = _random_book(rng, rng.randint(1, 40), rng.uniform(0.01, 3.0))
        assert pr.gross_exposure(pr.apply_exposure_limits(w, lim).weights) <= 1.0
        vol = rng.uniform(1e-4, 1.0)
        tgt = rng.uniform(1e-3, 2.0)
        assert pr.gross_exposure(pr.scale_to_target_vol(w, vol, tgt, 1.0).weights) <= 1.0


# ------------------------------------------------------------------ pre-trade check


def test_pre_trade_pass():
    chk = pr.pre_trade_check({"A": 0.1, "B": -0.1, "C": 0.05}, EX_LIMITS, portfolio_vol_annual=0.08)
    assert chk.passed and chk.violations == ()


def test_pre_trade_reports_each_breach():
    w = {f"S{i}": 0.12 for i in range(10)}  # gross 1.2, net 1.2, every name over 0.10
    chk = pr.pre_trade_check(w, EX_LIMITS)
    assert not chk.passed
    assert {"LEVERAGE", "GROSS", "NET", "SINGLE_NAME"} <= set(chk.codes)
    assert chk.codes.count("SINGLE_NAME") == 10


@pytest.mark.parametrize(
    "weights, code",
    [
        ({}, "EMPTY"),
        ({"A": float("nan")}, "NON_FINITE_WEIGHT"),
        ({"A": float("inf")}, "NON_FINITE_WEIGHT"),
        ({"A": "0.1"}, "NON_FINITE_WEIGHT"),
        ({"A": None}, "NON_FINITE_WEIGHT"),
        ({"": 0.1}, "BAD_SYMBOL"),
        ([("A", 0.1)], "BAD_INPUT"),
        (None, "BAD_INPUT"),
    ],
)
def test_pre_trade_fails_closed_on_bad_weights(weights, code):
    chk = pr.pre_trade_check(weights, EX_LIMITS)
    assert not chk.passed and code in chk.codes


@pytest.mark.parametrize("vol", [float("nan"), -0.01, float("inf")])
def test_pre_trade_fails_closed_on_bad_vol(vol):
    chk = pr.pre_trade_check({"A": 0.05}, EX_LIMITS, portfolio_vol_annual=vol)
    assert not chk.passed and "BAD_VOL" in chk.codes


def test_pre_trade_bad_limits_object():
    chk = pr.pre_trade_check({"A": 0.05}, {"gross_cap": 1.0})
    assert not chk.passed and chk.codes == ("BAD_LIMITS",)


def test_pre_trade_internal_error_is_surfaced_not_raised():
    class Boom(dict):  # a mapping whose iteration explodes
        def items(self):
            raise RuntimeError("boom")

    chk = pr.pre_trade_check(Boom(A=0.1), EX_LIMITS)
    assert not chk.passed and chk.codes == ("INTERNAL_ERROR",)


def test_pre_trade_gross_above_one_always_fails_even_with_loose_caps():
    lim = ExposureLimits(single_name_cap=1.0, gross_cap=1.0, net_cap=1.0)
    chk = pr.pre_trade_check({"A": 0.6, "B": -0.6}, lim)
    assert not chk.passed and "LEVERAGE" in chk.codes


# ------------------------------------------------------------------ report


def test_report_summary():
    dd = pr.drawdown_stats([100.0, 90.0])
    br = pr.evaluate_drawdown_breaker(dd.current_drawdown, BreakerState.NORMAL, EX_BREAKER)
    rep = pr.build_risk_report(
        {"A": 0.1, "B": -0.05, "C": 0.0},
        EX_LIMITS,
        groups={"A": "x", "B": "y", "C": "x"},
        portfolio_vol_annual=0.07,
        drawdown=dd,
        breaker=br,
    )
    d = rep.to_dict()
    assert d["gross"] == pytest.approx(0.15) and d["net"] == pytest.approx(0.05)
    assert d["long"] == pytest.approx(0.1) and d["short"] == pytest.approx(0.05)
    assert d["n_positions"] == 2 and d["group_gross"] == {"x": pytest.approx(0.1), "y": pytest.approx(0.05)}
    assert d["current_drawdown"] == pytest.approx(0.1) and d["breaker_state"] == "REDUCE"
    assert d["passed"] is False  # breaker tripped
    assert d["violations"] == []


def test_report_with_invalid_weights_fails_closed():
    rep = pr.build_risk_report({"A": float("nan")}, EX_LIMITS)
    assert rep.passed is False and rep.gross is None and rep.violations


def test_module_has_no_io_or_network_imports():
    import inspect

    src = inspect.getsource(pr)
    for banned in ("import os", "import socket", "import requests", "urllib", "open(", "subprocess", "os.environ"):
        assert banned not in src
