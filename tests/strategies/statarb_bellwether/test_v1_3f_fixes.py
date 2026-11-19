"""Synthetic tests for the review fixes to the bellwether runner (B1 look-ahead, B2 ADV cap,
B3 calendar-day borrow). Each test fails on the pre-fix runner and passes on the fixed one.

The runner is loaded with a config built from the pre-cleanup pins, exactly as in the
equivalence test, so no desk path or pin is needed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from .test_config_equivalence import bars, earnings, old_src, pair

__all__ = ["old_src"]  # re-exported pytest fixture


@pytest.fixture(scope="module")
def mod(old_src: str, tmp_path_factory: pytest.TempPathFactory) -> Any:
    tmp: Path = tmp_path_factory.mktemp("fixes")
    _, new = pair(old_src, tmp, {})
    return new


def _h1(mod: Any) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[Any]]:
    B = bars()
    d = pd.DatetimeIndex(B["R"].index)
    stocks = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    E = pd.DataFrame(True, index=d, columns=stocks)
    sub = pd.Series("Semis", index=stocks)
    evidx = mod.make_evidx(mod.earliest_possible_index(earnings(d), B["R"].index))
    W, tr = mod.signal_h1(B, E, sub, evidx, eval_start=mod.DEV0, eval_end=mod.DEV1, last_exit_i=len(d) - 1 - mod.MARGIN)
    return B, W, tr


def test_b1_h1_signal_at_t_first_earns_t1_to_t2(mod: Any) -> None:
    B, W, tr = _h1(mod)
    d = W.index
    nz = np.flatnonzero((W.abs().sum(axis=1) > 0).to_numpy())
    assert len(nz), "fixture must produce an H1 book"
    i = int(nz[0]) - 1
    assert d[i] in tr  # the bar before the first holding is a signal bar
    assert (W.iloc[: i + 1] == 0).all().all()  # nothing held on that signal bar
    deep = dict(B, VOL=B["VOL"] * 1e6)  # keep the ADV cap out of this timing check
    g = mod.apply_costs_and_returns(deep, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")["daily"]
    gross = g["gross"]
    assert gross.loc[d[i + 1]] == 0
    R = deep["R"].iloc[i + 2].reindex(W.columns).fillna(0.0)
    assert np.isclose(gross.loc[d[i + 2]], float((W.iloc[i + 1] * R).sum())) and gross.loc[d[i + 2]] != 0


def _flat(n: int = 30, start: str = "2018-01-01", **cols: float) -> dict[str, pd.DataFrame]:
    d = pd.bdate_range(start, periods=n)
    return {
        "R": pd.DataFrame({"A": cols.get("r", 0.01)}, index=d),
        "PX": pd.DataFrame({"A": 50.0}, index=d),
        "VOL": pd.DataFrame({"A": cols.get("vol", 1e7)}, index=d),
    }


def test_b2_adv_cap_limits_the_trade_and_carries_the_remainder(mod: Any) -> None:
    b = _flat(vol=1e4)  # ADV20 = $500k; 1% = $5k per session
    d = b["R"].index
    W = pd.DataFrame({"A": 0.0}, index=d)
    tgt = 12_000 / float(mod.AUM)
    W.iloc[15:, 0] = tgt  # target $12k: two capped sessions, then the rest
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")
    g = out["daily"]["gross"]
    step = mod.PARTICIPATION_CAP * 50 * 1e4 / mod.AUM
    assert np.isclose(g.loc[d[16]], step * 0.01)  # only the capped slice is held and earns
    assert np.isclose(g.loc[d[17]], 2 * step * 0.01)  # remainder carried to the next session
    assert np.isclose(g.loc[d[18]], tgt * 0.01) and np.isclose(g.loc[d[25]], tgt * 0.01)
    assert out["n_sessions_adv_capped"] == 2
    traded = out["daily"]["tc"].sum() / (3.0 / 1e4)  # fake cost model: 3 bps on each buy
    assert np.isclose(traded, tgt)  # cost on shares actually traded, once


def test_b3_borrow_accrues_calendar_days_over_a_weekend(mod: Any) -> None:
    b = _flat(n=60, r=0.0)
    d = b["R"].index
    W = pd.DataFrame({"A": -0.5}, index=d)
    cfg = mod.build_cost_config("unknown_borrow_required")
    out = mod.apply_costs_and_returns(b, W, cfg, idea="H1")["daily"]["borrow"]
    per_day = 0.5 * cfg.borrow_rate / 360.0
    mon = [t for t in out.index[1:] if t.day_of_week == 0][0]
    assert np.isclose(out.loc[mon], 3 * per_day)  # Fri close -> Mon close accrues 3 days
    assert np.isclose(out.loc[mon + pd.Timedelta(days=1)], per_day)
    span = (out.index[-1] - out.index[0]).days
    assert np.isclose(out.iloc[1:].sum(), span * per_day)  # = rate * span / 360 on the short


def test_b3_terminal_bound_borrow_overlay_accrues_calendar_days(mod: Any) -> None:
    from .test_config_equivalence import FakeClient

    B = bars()
    d = pd.DatetimeIndex(B["R"].index)
    W = pd.DataFrame(0.0, index=d, columns=B["R"].columns)
    W.loc[d[380] :, "CCC"] = -0.01  # short held through its last print (tau = session 399)
    roster = [
        {
            "symbol": "CCC",
            "identity_ok": True,
            "short_terms": {
                "h": str(d[410].date()),
                "alternatives": [{"cash": 5.0, "ratio": 1.0, "acquirer_id": "ACQ", "acquirer_identity_accepted": True}],
            },
        }
    ]
    cfg = mod.build_cost_config("unknown_borrow_required")
    _, ov, rec = mod.h1_terminal_bound(B, W, roster, cfg, client=FakeClient(), path="A")
    assert rec and rec[0]["booking_session"] == str(d[400].date())
    gaps = d.to_series().diff().dt.days.to_numpy()[401:]
    per = -ov.iloc[401:].to_numpy() / gaps  # borrow-only sessions after booking
    assert np.allclose(per, 0.01 * cfg.borrow_rate / 360.0)  # per calendar day, weekends included
    assert (gaps == 3).any()


def _delisting(n: int = 30, vol: float = 1e4) -> dict[str, pd.DataFrame]:
    b = _flat(n=n, vol=vol)  # A: $50, ADV20 $500k at vol 1e4, so 1% = 5e-4 of AUM per session
    b["PX"].iloc[20:, 0] = np.nan  # last print at session 19
    b["VOL"].iloc[20:, 0] = 0.0
    b["R"].iloc[20:, 0] = np.nan
    return b


def test_round2_h1_bound_applies_to_capped_exit_still_held_at_delisting(mod: Any) -> None:
    b = _delisting()
    d = b["R"].index
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:17, 0] = 12_000 / float(mod.AUM)  # entry fills 5k, 5k, 2k; exit from row 17 is capped
    step = 5_000 / float(mod.AUM)
    held = mod.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[15], 12_000 / float(mod.AUM)) and np.isclose(held.iloc[19], 2_000 / float(mod.AUM))
    cfg = mod.build_cost_config("unknown_borrow_required")
    Wa, ov, rec = mod.h1_terminal_bound(b, W, [{"symbol": "A", "identity_ok": True}], cfg)
    assert W["A"].iloc[19] == 0 and step > 0  # target already flat at tau, but 2k is still held
    assert len(rec) == 1 and np.isclose(rec[0]["weight"], 2_000 / float(mod.AUM))
    assert np.isclose(ov.iloc[20], -2_000 / float(mod.AUM)) and np.isclose(ov.sum(), ov.iloc[20])  # -100% of held
    after = mod.held_positions(b, Wa)["A"]
    assert after.iloc[20:].eq(0).all()  # settled at the last close once bound


def test_round2_no_print_name_cannot_trade(mod: Any) -> None:
    b = _flat(vol=1e7)
    d = b["R"].index
    b["PX"].iloc[14:17, 0] = np.nan  # suspended three sessions, prints again after
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[11:13, 0] = 0.1
    held = mod.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[14:17], 0.1).all() and held.iloc[17] == 0


def test_round2_h2_stress_applies_to_held_position(mod: Any) -> None:
    b = _delisting()
    d = b["R"].index
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[17:25, 0] = 12_000 / float(mod.AUM)  # capped entry: 10k held when A stops printing
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 12_000 / float(mod.AUM), "w_etf": 0.0, "entry_i": 17, "exit_i": 25}]
    ov, srec = mod.h2_delisting_stress(b, W, pos)
    assert np.isclose(srec[0]["stress_weight"], 10_000 / float(mod.AUM))
    assert np.isclose(ov.iloc[20], -0.30 * 10_000 / float(mod.AUM)) and np.isclose(ov.sum(), ov.iloc[20])
