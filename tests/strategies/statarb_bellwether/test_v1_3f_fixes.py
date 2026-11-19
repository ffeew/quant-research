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
    first = d[11]  # held from the first fill with ADV history (fill day d[10])
    assert out.loc[: d[10]].eq(0).all()
    mon = [t for t in out.index if t > first and t.day_of_week == 0][0]
    assert np.isclose(out.loc[mon], 3 * per_day)  # Fri close -> Mon close accrues 3 days
    assert np.isclose(out.loc[mon + pd.Timedelta(days=1)], per_day)
    span = (out.index[-1] - d[10]).days
    assert np.isclose(out.loc[first:].sum(), span * per_day)  # = rate * span / 360 on the short


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
    W.iloc[12:18, 0] = 12_000 / float(mod.AUM)  # entry fills 5k, 5k, 2k; the exit from close 18 is capped
    step = 5_000 / float(mod.AUM)
    held = mod.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[15], 12_000 / float(mod.AUM)) and np.isclose(held.iloc[20], 2_000 / float(mod.AUM))
    cfg = mod.build_cost_config("unknown_borrow_required")
    Wa, ov, rec = mod.h1_terminal_bound(b, W, [{"symbol": "A", "identity_ok": True}], cfg)
    assert W["A"].iloc[19] == 0 and step > 0  # target already flat at tau, but 2k is still held past it
    assert len(rec) == 1 and np.isclose(rec[0]["weight"], 2_000 / float(mod.AUM))
    assert np.isclose(ov.iloc[20], -2_000 / float(mod.AUM)) and np.isclose(ov.sum(), ov.iloc[20])  # -100% of held
    after = mod.held_positions(b, Wa)["A"]
    assert np.isclose(after.iloc[20], 2_000 / float(mod.AUM)) and after.iloc[21:].eq(0).all()  # settled once bound


def test_round2_no_print_name_cannot_trade(mod: Any) -> None:
    b = _flat(vol=1e7)
    d = b["R"].index
    b["PX"].iloc[14:17, 0] = np.nan  # suspended three sessions, prints again after
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[11:14, 0] = 0.1  # exit ordered at close 14, a no-print day
    held = mod.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[14], 0.1)
    assert np.isclose(held.iloc[15:18], 0.1).all()  # closes 14-16 have no print: the exit can't fill
    assert held.iloc[18] == 0  # fills at close 17, the first print after the gap


def test_round2_h2_stress_applies_to_held_position(mod: Any) -> None:
    b = _delisting()
    d = b["R"].index
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[17:25, 0] = 16_000 / float(mod.AUM)  # capped entry at closes 17, 18, 19: 15k held past the last print
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 16_000 / float(mod.AUM), "w_etf": 0.0, "entry_i": 17, "exit_i": 25}]
    ov, srec = mod.h2_delisting_stress(b, W, pos)
    assert np.isclose(srec[0]["stress_weight"], 15_000 / float(mod.AUM))
    assert np.isclose(ov.iloc[20], -0.30 * 15_000 / float(mod.AUM)) and np.isclose(ov.sum(), ov.iloc[20])


def _terminal_short(mod: Any, n: int, h_i: int) -> tuple[pd.DatetimeIndex, pd.Series, Any]:
    from .test_config_equivalence import FakeClient

    b = _delisting(n=n, vol=1e9)
    d = pd.DatetimeIndex(b["R"].index)
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:25, 0] = -0.05
    terms = {
        "h": str(d[h_i].date()),
        "alternatives": [{"cash": 5.0, "ratio": 1.0, "acquirer_id": "ACQ", "acquirer_identity_accepted": True}],
    }
    roster = [{"symbol": "A", "identity_ok": True, "short_terms": terms}]
    cfg = mod.build_cost_config("unknown_borrow_required")
    _, ov, rec = mod.h1_terminal_bound(b, W, roster, cfg, client=FakeClient(), path="A")
    return d, ov, rec


def test_round2_terminal_borrow_three_days_over_a_weekend(mod: Any) -> None:
    d, ov, rec = _terminal_short(mod, 30, 27)
    per_day = 0.05 * 0.10 / 360  # 10%/yr, 360-day basis, per calendar day
    mon = next(j for j in range(21, 28) if d[j].day_of_week == 0)
    assert np.isclose(ov.iloc[mon], -3 * per_day)  # Fri close -> Mon close: 3 calendar days
    assert np.isclose(ov.iloc[mon + 1], -per_day)
    assert rec[0]["borrow_rate"] == 0.10


def test_round2_terminal_borrow_over_a_year_is_about_ten_percent(mod: Any) -> None:
    n = 300
    d0 = pd.bdate_range("2018-01-01", periods=n)
    h_i = int(np.searchsorted(d0.values, (d0[19] + pd.Timedelta(days=365)).to_datetime64()))
    d, ov, _ = _terminal_short(mod, n, h_i)
    borrow = -float(ov.sum()) - 0.05 * (65.0 / 50.0 - 1.0)  # minus the V_max liability
    days = (d[h_i] - d[19]).days  # tau close -> h close
    assert days >= 365 and np.isclose(borrow, 0.05 * 0.10 * days / 360)
    assert 0.10 <= borrow / 0.05 < 0.1025  # ~10% of the short over a year (360-day basis)


def test_round2_adv20_excludes_fill_day_volume(mod: Any) -> None:
    b = _flat(vol=1e4)  # ADV20 = $500k; 1% = $5k per session
    d = b["R"].index
    b["VOL"].iloc[15, 0] = 1e9  # huge volume on the fill day itself must not lift its cap
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[15:, 0] = 0.01
    held = mod.held_positions(b, W)["A"]
    step = 5_000 / float(mod.AUM)
    assert np.isclose(held.iloc[16], step)  # fill at close d[15] uses ADV20 ending d[14]
    assert held.iloc[17] > 2 * step  # the next window (ending d[15]) includes the spike


def test_round2_no_adv_history_means_no_trade(mod: Any) -> None:
    b = _flat(vol=1e7)
    d = b["R"].index
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[2:, 0] = 0.1  # wants to trade before any ADV history exists
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")
    held = mod.held_positions(b, W)["A"]
    assert held.iloc[:11].eq(0).all() and np.isclose(held.iloc[11], 0.1)  # 10 sessions of history first
    assert out["daily"]["tc"].loc[: d[10]].eq(0).all() and out["n_sessions_adv_capped"] == 8  # rows 3-10
    b["VOL"]["A"] = 0.0  # never any volume: no ADV, never filled
    assert mod.held_positions(b, W)["A"].eq(0).all()


# ---- review round 3 (from #10) ----


def test_round3_one_last_print_definition(mod: Any) -> None:
    PX = pd.DataFrame({"A": [10.0, 0.0, np.nan, 11.0, 0.0, -1.0, np.nan]})
    assert [mod.has_print(v) for v in PX["A"]] == [True, False, False, True, False, False, False]
    assert mod.printed_mask(PX)["A"].tolist() == [True, False, False, True, False, False, False]
    assert mod.last_print_index(PX, "A") == 3 and mod.last_print_index(PX, "Z") == -1
    b = _flat()
    b["PX"].iloc[20:, 0] = 0.0  # a zero price is no print (not only NaN), even with volume
    assert mod._trusted_tau(b, "A") == 19 == mod.last_print_index(b["PX"], "A")
    W = pd.DataFrame({"A": 0.0}, index=b["R"].index)
    W.iloc[10:28, 0] = 0.005
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.005, "w_etf": 0.0, "entry_i": 10, "exit_i": 28}]
    assert mod.h2_delisting_receipts(b, pos)[0]["last_close_session"] == str(b["R"].index[19].date())


def test_round3_exit_cost_is_charged_at_the_true_last_print(mod: Any) -> None:
    b = _delisting(vol=1e7)  # last print at close 19, deep enough for no cap
    d = b["R"].index
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:19, 0] = 0.1  # exit ordered at close 19, the last print
    tc = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")["daily"]["tc"]
    assert np.isclose(tc.loc[d[20]], 0.1 * 4.0 / 1e4)  # the exit fills (and pays: fake 4 bp sell) at close 19
    assert np.isclose(tc.sum(), 0.1 * (3.0 + 4.0) / 1e4)
    assert mod.held_positions(b, W)["A"].iloc[20] == 0  # nothing left past the last print


def test_round3_nothing_trades_on_a_no_print_day(mod: Any) -> None:
    b = _flat(vol=1e7)
    d = b["R"].index
    b["PX"].iloc[15, 0] = np.nan  # no print at close 15 only
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[15:, 0] = 0.1  # entry ordered at close 15
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")
    held = mod.held_positions(b, W)["A"]
    assert held.iloc[16] == 0 and np.isclose(held.iloc[17], 0.1)  # fills at close 16, not 15
    assert out["daily"]["tc"].loc[d[16]] == 0 and np.isclose(out["daily"]["tc"].loc[d[17]], 0.1 * 3.0 / 1e4)
    b["PX"].iloc[15, 0] = 0.0  # a zero price is no print either
    assert mod.held_positions(b, W)["A"].iloc[16] == 0
