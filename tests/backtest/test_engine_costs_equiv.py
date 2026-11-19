"""Byte-identity of engine outputs: v1.1 cost_model path vs the typed-module adapter."""

from __future__ import annotations

import itertools
import math
import pickle
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quant_research.backtest import engine as new_engine
from quant_research.backtest.costs import cost_model as v11
from quant_research.backtest.costs import engine_compat as compat
from tests.backtest import reference_v11_engine as old_engine

PROTO = pickle.HIGHEST_PROTOCOL


def _dump(obj: Any) -> bytes:
    return pickle.dumps(obj, protocol=PROTO)


def _panel(
    *,
    start: str = "2026-09-01",
    end: str = "2026-11-20",
    symbols: list[str] | None = None,
    close0: dict[str, float] | None = None,
    vol: dict[str, float] | None = None,
    on: float = 0.0,
    id_: float = 0.001,
    drop_from: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    symbols = symbols or ["AAA", "BBB", "SPY"]
    idx = pd.bdate_range(start, end)
    close0 = close0 or {"AAA": 50.0, "BBB": 37.13, "SPY": 400.0}
    vol = vol or {"AAA": 2_000_000.0, "BBB": 80_000.0, "SPY": 50_000_000.0}
    close = pd.DataFrame({s: close0[s] for s in symbols}, index=idx, dtype=float)
    # mild deterministic walk so sigma is positive and stable
    for i, _ in enumerate(idx):
        close.iloc[i] = close.iloc[0] * (1.0 + 0.0005 * ((i % 7) - 3))
    vol_raw = pd.DataFrame({s: vol[s] for s in symbols}, index=idx, dtype=float)
    if drop_from:
        for s, day in drop_from.items():
            close.loc[close.index >= day, s] = np.nan
            vol_raw.loc[vol_raw.index >= day, s] = np.nan
    on_df = pd.DataFrame(on, index=idx, columns=symbols, dtype=float)
    id_df = pd.DataFrame(id_, index=idx, columns=symbols, dtype=float)
    if drop_from:
        for s, day in drop_from.items():
            on_df.loc[on_df.index >= day, s] = np.nan
            id_df.loc[id_df.index >= day, s] = np.nan
    ret = (1.0 + on_df) * (1.0 + id_df) - 1.0
    return {"ret": ret, "on": on_df, "id": id_df, "vol_raw": vol_raw, "close_raw": close}


def _rf(panel: dict[str, pd.DataFrame], rate: float = 0.0001) -> pd.Series:
    return pd.Series(rate, index=panel["ret"].index, dtype=float)


def _targets(dates: pd.Index, specs: list[tuple[int, dict[str, float]]]) -> dict[pd.Timestamp, pd.Series]:
    out: dict[pd.Timestamp, pd.Series] = {}
    for i, weights in specs:
        out[dates[i]] = pd.Series(weights, dtype=float)
    return out


def _copy_panel(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {k: v.copy(deep=True) for k, v in panel.items()}


def _run(
    mod: Any, panel: dict[str, pd.DataFrame], targets: dict[pd.Timestamp, pd.Series], rf: pd.Series, **kw: Any
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    result: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None = mod.simulate(
        _copy_panel(panel), targets, rf, **kw
    )
    return result


def _assert_byte_identical(a: tuple[Any, Any, Any] | None, b: tuple[Any, Any, Any] | None) -> None:
    if a is None or b is None:
        assert a is None and b is None
        return
    for name, left, right in zip(("daily", "trades", "delist"), a, b, strict=True):
        lb, rb = _dump(left), _dump(right)
        if lb != rb:
            # Helpful diff on failure without weakening the byte check.
            if isinstance(left, pd.DataFrame) and isinstance(right, pd.DataFrame):
                pytest.fail(f"{name} pickle bytes differ\nLEFT:\n{left}\nRIGHT:\n{right}")
            pytest.fail(f"{name} pickle bytes differ ({len(lb)} vs {len(rb)})")


def test_compat_constants_match_v11() -> None:
    assert compat.BUCKETS == v11.BUCKETS
    assert compat.VENUES == v11.VENUES
    assert compat.SEC_FEE_PER_DOLLAR == v11.SEC_FEE_PER_DOLLAR
    assert compat.TAF_PER_SHARE == v11.TAF_PER_SHARE
    assert compat.TAF_MAX_PER_TRADE == v11.TAF_MAX_PER_TRADE
    assert compat.TAF_HOLIDAY == v11.TAF_HOLIDAY
    assert compat.CAT_PER_SHARE == v11.CAT_PER_SHARE
    assert compat.K_IMPACT_DEFAULT == v11.K_IMPACT_DEFAULT


def test_compat_trade_cost_matches_v11_grid() -> None:
    sides = ("buy", "sell")
    prices = (0.50, 12.34, 37.13, 100.0, 656.71)
    shares = (0.7, 1.0, 15.0, 50.0, 3333.3337, 60_000.0)
    advs = (None, 1e4, 1e5, 5e6, 4.2e7)
    sigs = (None, 0.01, 0.016, 0.05)
    venues = ("continuous", "open", "close")
    dates = (date(2026, 10, 30), date(2027, 2, 1))
    n = 0
    for side, price, sh, adv, sig, venue, d in itertools.product(sides, prices, shares, advs, sigs, venues, dates):
        a = v11.trade_cost(side, price, sh, adv, sig, venue=venue, trade_date=d)
        b: dict[str, Any] = dict(compat.trade_cost(side, price, sh, adv, sig, venue=venue, trade_date=d))
        for k, av in a.items():
            bv = b[k]
            if k == "participation" and isinstance(av, float) and math.isnan(av):
                assert isinstance(bv, float) and math.isnan(bv)
                continue
            if isinstance(av, float):
                assert isinstance(bv, float)
                assert math.isclose(av, bv, rel_tol=0.0, abs_tol=0.0) or av == bv
                assert av == bv, (k, av, bv, side, price, sh, venue, d)
            else:
                assert av == bv, (k, av, bv, side, price, sh, venue, d)
        n += 1
    assert n > 1000


def test_v11_fee_undercharge_preserved() -> None:
    # CAT raw = 0.000003 * 3333.3337 = 0.0100000011 -> v1.1 cents to 0.01 (not 0.02)
    f11 = v11.regulatory_fees_usd("buy", 50.0, 3333.3337, date(2026, 10, 30))
    fc = compat.regulatory_fees_usd("buy", 50.0, 3333.3337, date(2026, 10, 30))
    assert f11 == fc
    assert fc["cat_usd"] == 0.01


def test_taf_cap_and_holiday() -> None:
    cap_n = v11.regulatory_fees_usd("sell", 10.0, 1_000_000, date(2027, 2, 1))
    cap_c = compat.regulatory_fees_usd("sell", 10.0, 1_000_000, date(2027, 2, 1))
    assert cap_n == cap_c
    assert cap_c["taf_usd"] == 9.79
    hol_n = v11.regulatory_fees_usd("sell", 100.0, 100, date(2026, 10, 30))
    hol_c = compat.regulatory_fees_usd("sell", 100.0, 100, date(2026, 10, 30))
    assert hol_n == hol_c
    assert hol_c["taf_usd"] == 0.0


@pytest.mark.parametrize("fill", ["open", "close"])
def test_engine_byte_identical_base_book(fill: str) -> None:
    panel = _panel()
    dates = panel["ret"].index
    targets = _targets(
        dates,
        [
            (15, {"AAA": 0.4, "BBB": 0.3, "SPY": 0.2}),
            (25, {"AAA": 0.2, "BBB": -0.3, "SPY": 0.2}),
            (40, {"AAA": 0.0, "SPY": 0.5}),
        ],
    )
    rf = _rf(panel)
    _assert_byte_identical(
        _run(old_engine, panel, targets, rf, fill=fill, etfs=frozenset({"SPY"})),
        _run(new_engine, panel, targets, rf, fill=fill, etfs=frozenset({"SPY"})),
    )


def test_engine_zero_trading_cost_days_and_no_trade() -> None:
    panel = _panel()
    dates = panel["ret"].index
    # A single entry: later days have cost 0 and only borrow/gross.
    targets = _targets(dates, [(15, {"AAA": -0.5, "BBB": 0.5})])
    rf = _rf(panel, 0.0)
    old = _run(old_engine, panel, targets, rf, fill="open")
    new = _run(new_engine, panel, targets, rf, fill="open")
    _assert_byte_identical(old, new)
    assert old is not None and (old[0]["cost"] == 0).sum() > 0
    # No valid next-session trade -> both return None
    late = {dates[-1]: pd.Series({"AAA": 1.0})}
    assert _run(old_engine, panel, late, rf) is None
    assert _run(new_engine, panel, late, rf) is None


def test_engine_impact_on_and_off() -> None:
    # Impact off: ADV missing / non-positive volume -> adv_shares is None
    panel_off = _panel(vol={"AAA": 0.0, "BBB": 0.0, "SPY": 0.0})
    # Impact on: very large participation on a small name
    panel_on = _panel(vol={"AAA": 500.0, "BBB": 800.0, "SPY": 1_000.0})
    dates = panel_off["ret"].index
    targets = _targets(dates, [(15, {"AAA": 0.8, "BBB": -0.8})])
    rf = _rf(panel_off)
    for panel in (panel_off, panel_on):
        _assert_byte_identical(
            _run(old_engine, panel, targets, rf, fill="open"),
            _run(new_engine, panel, targets, rf, fill="open"),
        )


def test_engine_odd_lots_and_rounding_boundaries() -> None:
    # Prices chosen so book_usd / price is a non-lot share count; 3333.3337 CAT boundary via book/price.
    panel = _panel(
        close0={"AAA": 30.000003, "BBB": 100.0 / 3333.3337, "SPY": 19.99},
        vol={"AAA": 15_000.0, "BBB": 3_000.0, "SPY": 8e6},
    )
    dates = panel["ret"].index
    targets = _targets(
        dates,
        [
            (12, {"AAA": 0.15, "BBB": 1.0, "SPY": -0.15}),
            (20, {"AAA": 0.15, "BBB": 1.0, "SPY": -0.15}),  # zero delta after first (still compared)
            (30, {"AAA": -0.2, "BBB": 0.05, "SPY": 0.4}),
        ],
    )
    rf = _rf(panel)
    for fill, book in itertools.product(("open", "close"), (100_000.0, 12345.67, 50_000.0)):
        _assert_byte_identical(
            _run(old_engine, panel, targets, rf, fill=fill, book_usd=book, etfs=frozenset({"SPY"})),
            _run(new_engine, panel, targets, rf, fill=fill, book_usd=book, etfs=frozenset({"SPY"})),
        )


def test_engine_taf_cap_large_sell() -> None:
    # Large short on a mid-price name with huge book -> TAF cap binds.
    panel = _panel(close0={"AAA": 10.0, "BBB": 10.0, "SPY": 10.0}, vol={"AAA": 2e6, "BBB": 2e6, "SPY": 2e6})
    dates = panel["ret"].index
    targets = _targets(dates, [(15, {"AAA": -1.0})])
    rf = _rf(panel)
    old = _run(old_engine, panel, targets, rf, fill="open", book_usd=10_000_000.0)
    new = _run(new_engine, panel, targets, rf, fill="open", book_usd=10_000_000.0)
    _assert_byte_identical(old, new)
    # date after signal is dates[16]; sell size is 1.0 * 10e6 / ~10 = ~1e6 shares, TAF capped
    assert old is not None and not old[1].empty


def test_engine_holiday_and_post_holiday_dates() -> None:
    # Window covers TAF holiday (2026-10-01..12-31) only. Post-holiday uses a 2027 panel.
    panel_h = _panel(start="2026-09-01", end="2026-11-20")
    panel_n = _panel(start="2027-01-04", end="2027-03-15")
    for panel, fill in itertools.product((panel_h, panel_n), ("open", "close")):
        dates = panel["ret"].index
        targets = _targets(dates, [(15, {"AAA": 0.5, "BBB": -0.5}), (30, {"AAA": -0.5, "BBB": 0.5})])
        rf = _rf(panel)
        _assert_byte_identical(
            _run(old_engine, panel, targets, rf, fill=fill),
            _run(new_engine, panel, targets, rf, fill=fill),
        )


def test_engine_delist_and_missing_bars() -> None:
    panel = _panel(drop_from={"BBB": "2026-10-15"})
    dates = panel["ret"].index
    targets = _targets(dates, [(15, {"AAA": 0.3, "BBB": 0.3, "SPY": 0.3}), (35, {"AAA": 0.5, "SPY": 0.5})])
    rf = _rf(panel)
    _assert_byte_identical(
        _run(old_engine, panel, targets, rf, fill="open", etfs=frozenset({"SPY"})),
        _run(new_engine, panel, targets, rf, fill="open", etfs=frozenset({"SPY"})),
    )


def test_engine_serialized_json_bytes() -> None:
    panel = _panel()
    dates = panel["ret"].index
    targets = _targets(dates, [(18, {"AAA": 0.25, "BBB": 0.25, "SPY": -0.5})])
    rf = _rf(panel)
    old = _run(old_engine, panel, targets, rf, fill="open", etfs=frozenset({"SPY"}))
    new = _run(new_engine, panel, targets, rf, fill="open", etfs=frozenset({"SPY"}))
    assert old is not None and new is not None
    for left, right in zip(old, new, strict=True):
        assert _dump(left) == _dump(right)
        lj = left.to_json(orient="split", double_precision=15, date_format="iso")
        rj = right.to_json(orient="split", double_precision=15, date_format="iso")
        assert lj.encode("utf-8") == rj.encode("utf-8")
        for col in left.columns:
            if pd.api.types.is_numeric_dtype(left[col]) and pd.api.types.is_numeric_dtype(right[col]):
                lv = left[col].to_numpy()
                rv = right[col].to_numpy()
                assert lv.dtype == rv.dtype
                assert lv.tobytes() == rv.tobytes()
