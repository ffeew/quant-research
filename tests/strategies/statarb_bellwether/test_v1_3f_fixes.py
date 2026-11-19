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


def test_round4_one_tradable_print_definition(mod: Any) -> None:
    PX = pd.DataFrame({"A": [10.0, 0.0, np.nan, 11.0, 12.0, -1.0, 13.0, 14.0, 15.0]})
    VOL = pd.DataFrame({"A": [1.0, 1.0, 1.0, 1.0, 0.0, 1.0, np.nan, 1.0, 1.0]})
    FF = pd.DataFrame({"A": [False] * 7 + [True, np.nan]})
    one = {"PX": PX, "VOL": VOL, "FFILL": FF}
    want = [True, False, False, True, False, False, False, False, False]  # close > 0 AND volume > 0, no ffill
    assert mod.tradable_mask(one)["A"].tolist() == want
    assert mod.last_print_index(one, "A") == 3 == mod._trusted_tau(one, "A")
    assert mod.last_print_index(one, "Z") == -1 and mod._trusted_tau(one, "Z") is None
    b = _flat()
    b["PX"].iloc[20:, 0] = 0.0  # a zero price is no print (not only NaN), even with volume
    assert mod._trusted_tau(b, "A") == 19 == mod.last_print_index(b, "A")
    W = pd.DataFrame({"A": 0.0}, index=b["R"].index)
    W.iloc[10:28, 0] = 0.005
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.005, "w_etf": 0.0, "entry_i": 10, "exit_i": 28}]
    assert mod.h2_delisting_receipts(b, W, pos)[0]["last_close_session"] == str(b["R"].index[19].date())


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


def test_round3_h2_receipts_and_stress_follow_the_held_remainder(mod: Any) -> None:
    b = _delisting()  # last print at close 19; 1% ADV = 5k per session
    d = b["R"].index
    k = 1.0 / float(mod.AUM)
    # (a) capped exit: planned exit at 18 (before the last print), 2k still held past it
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:18, 0] = 12_000 * k
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 12_000 * k, "w_etf": 0.0, "entry_i": 12, "exit_i": 18}]
    rec = mod.h2_delisting_receipts(b, W, pos)
    assert len(rec) == 1 and np.isclose(rec[0]["held_weight"], 2_000 * k) and rec[0]["held_past_planned_exit"]
    ov, srec = mod.h2_delisting_stress(b, W, pos)
    assert np.isclose(ov.iloc[20], -0.30 * 2_000 * k) and np.isclose(ov.sum(), ov.iloc[20])
    assert np.isclose(srec[0]["stress_weight"], 2_000 * k)
    # (b) last print at exit_i - 1: the exit is ordered at close 20, which has no print
    W2 = pd.DataFrame({"A": 0.0}, index=d)
    W2.iloc[12:20, 0] = 10_000 * k
    pos2 = [dict(pos[0], w_sym=10_000 * k, exit_i=20)]
    rec2 = mod.h2_delisting_receipts(b, W2, pos2)
    assert len(rec2) == 1 and np.isclose(rec2[0]["held_weight"], 10_000 * k)
    assert np.isclose(mod.h2_delisting_stress(b, W2, pos2)[0].iloc[20], -0.30 * 10_000 * k)
    # (c) fully exited at the last print: nothing held past it, so no receipt and no stress
    W3 = pd.DataFrame({"A": 0.0}, index=d)
    W3.iloc[12:19, 0] = 4_000 * k
    pos3 = [dict(pos[0], w_sym=4_000 * k, exit_i=19)]
    assert mod.h2_delisting_receipts(b, W3, pos3) == [] and mod.h2_delisting_stress(b, W3, pos3)[0].sum() == 0


def test_round3_h1_suspension_gap_check_uses_the_held_position(mod: Any) -> None:
    b = _delisting()  # tau = 19; 1% ADV = 5k per session
    d = b["R"].index
    k = 1.0 / float(mod.AUM)
    b["VOL"].iloc[17, 0] = 0.0  # untrusted session 17 (zero volume) before tau
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:16, 0] = 12_000 * k  # target flat from 16, but the capped exit still holds 7k over 17
    held = mod.held_positions(b, W)["A"]
    assert W["A"].iloc[17] == 0 and np.isclose(held.iloc[17], 7_000 * k)
    roster = [{"symbol": "A", "identity_ok": True}]
    cfg = mod.build_cost_config("unknown_borrow_required")
    with pytest.raises(SystemExit, match="suspension gap"):
        mod.h1_terminal_bound(b, W, roster, cfg)
    W2 = W.copy()
    W2.iloc[12:16, 0] = 4_000 * k  # filled in one session, out by close 16: nothing held over 17
    assert mod.held_positions(b, W2)["A"].iloc[17] == 0
    _, ov, rec = mod.h1_terminal_bound(b, W2, roster, cfg)
    assert rec == [] and ov.sum() == 0


def test_round3_zero_adv_allows_cuts_toward_zero_at_stress_cost_never_grows(mod: Any) -> None:
    b = _flat(vol=1e7)
    d = b["R"].index
    b["PX"].iloc[13:25, 0] = np.nan  # no prints 13-24 (suspended); from fill day 25 the ADV20
    b["VOL"].iloc[13:25, 0] = np.nan  # window has 8 sessions, fewer than 10, so ADV20 is NaN
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[11:25, 0] = 0.1  # held 0.1 from close 11
    W.iloc[25, 0] = 0.04  # cut at close 25 with no ADV: allowed, in full
    W.iloc[26, 0] = 0.08  # grow at close 26 with no ADV: never
    W.iloc[27:, 0] = -0.05  # flip at close 27: cut to 0 only
    held = mod.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[25], 0.1) and np.isclose(held.iloc[26], 0.04)
    assert np.isclose(held.iloc[27], 0.04) and held.iloc[28:].eq(0).all()
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")
    tc = out["daily"]["tc"]
    stress = 2.0 * 4.0  # fake cost model: 4 bp on a sell, doubled
    assert np.isclose(tc.loc[d[26]], 0.06 * stress / 1e4) and np.isclose(tc.loc[d[28]], 0.04 * stress / 1e4)
    assert out["n_forced_cuts_zero_adv"] == 2 and np.isclose(out["forced_cut_notional_usd"], 0.10 * mod.AUM)


def test_round3_settlement_after_the_last_print_is_not_free(mod: Any) -> None:
    b = _delisting()  # last print at close 19 at $50; 1% ADV = 5k per session
    d = b["R"].index
    k = 1.0 / float(mod.AUM)
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:18, 0] = 12_000 * k  # capped exit leaves 2k held past the last print
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")
    assert mod.held_positions(b, W)["A"].iloc[20:22].tolist() == [pytest.approx(2_000 * k), 0.0]
    assert np.isclose(out["daily"]["tc"].loc[d[21]], 2_000 * k * 2.0 * 4.0 / 1e4)
    assert out["n_post_last_print_settlements"] == 1
    assert np.isclose(out["post_last_print_settlement_notional_usd"], 2_000.0)


def test_round4_stress_cost_is_two_times_the_one_way_cost(mod: Any) -> None:
    assert mod.STRESS_ONE_WAY_COST_MULT == 2.0  # pinned, not net_edge's round-trip break-even multiple
    b = _delisting()
    d = b["R"].index
    k = 1.0 / float(mod.AUM)
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:18, 0] = 12_000 * k
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H1")
    assert np.isclose(out["daily"]["tc"].loc[d[21]], 2_000 * k * 8.0 / 1e4)  # 2 x 4 bp one-way sell
    assert out["forced_trade_cost"] == "stress: 2.0 x one-way cost at no ADV"


def _trailing_zero_volume_bars() -> dict[str, pd.DataFrame]:
    b = _flat()  # A last trades at close 24: closes 25-29 remain $50 with zero volume
    b["VOL"].iloc[25:, 0] = 0.0
    b["R"].iloc[25:, 0] = 0.02  # deliberately stale marks, not prints
    return b


def test_round4_trailing_zero_volume_h1_tau_last_print_no_trade_after_bound(mod: Any) -> None:
    b = _trailing_zero_volume_bars()
    d = b["R"].index
    assert (b["PX"]["A"].iloc[25:] == 50.0).all() and len(b["PX"]) - 25 == 5
    assert mod._trusted_tau(b, "A") == 24 == mod.last_print_index(b, "A")
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[10:, 0] = 0.05  # held long through the stale closes
    cfg = mod.build_cost_config("unknown_borrow_required")
    Wa, ov, rec = mod.h1_terminal_bound(b, W, [{"symbol": "A", "identity_ok": True}], cfg)
    assert rec[0]["tau"] == str(d[24].date()) and np.isclose(ov.iloc[25], -0.05) and np.isclose(ov.sum(), -0.05)
    assert Wa["A"].iloc[24] == 0.05 and Wa["A"].iloc[25:].eq(0).all()  # W_adj zeroed from tau+1
    held = mod.held_positions(b, Wa)["A"]
    assert np.isclose(held.iloc[25], 0.05) and held.iloc[26:].eq(0).all()
    after_tau = [(fd, t) for _d, fd, _h, ts, _c in mod._fills(b, Wa) for t in ts if t[0] == "A" and fd > d[24]]
    assert len(after_tau) == 1  # only a forced settlement, never a normal fill on a zero-volume close
    assert after_tau[0][1][5] == mod.FORCED_SETTLEMENT and after_tau[0][1][2] == 50.0
    out = mod.apply_costs_and_returns(b, Wa, cfg, idea="H1")
    assert out["daily"]["gross"].loc[d[25] :].eq(0).all()  # nothing earned after its -100% bound
    assert np.isclose(out["daily"]["tc"].loc[d[26]], 0.05 * 2.0 * 4.0 / 1e4)  # 2 x the 4 bp one-way sell


def test_round4_zero_volume_close_cannot_be_exited_at_one_x(mod: Any) -> None:
    b = _trailing_zero_volume_bars()
    b["VOL"].iloc[:25, 0] = 1e4  # 1% ADV = $5k per session
    d = b["R"].index
    k = 1.0 / float(mod.AUM)
    W = pd.DataFrame({"A": 0.0}, index=d)
    W.iloc[12:24, 0] = 12_000 * k  # capped exit at close 24 leaves $7k past the last real print
    held = mod.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[25], 7_000 * k) and held.iloc[26:].eq(0).all()
    out = mod.apply_costs_and_returns(b, W, mod.build_cost_config("unknown_borrow_required"), idea="H2")
    assert np.isclose(out["daily"]["tc"].loc[d[26]], 7_000 * k * 2.0 * 4.0 / 1e4)  # stress, not 1x
    assert out["n_post_last_print_settlements"] == 1
    assert np.isclose(out["post_last_print_settlement_notional_usd"], 7_000)
    assert out["daily"]["gross"].loc[d[25] :].eq(0).all()
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 12_000 * k, "w_etf": 0.0, "entry_i": 12, "exit_i": 24}]
    rec = mod.h2_delisting_receipts(b, W, pos)
    assert len(rec) == 1 and rec[0]["last_close_session"] == str(d[24].date())
    assert np.isclose(rec[0]["held_weight"], 7_000 * k)
    ov, _ = mod.h2_delisting_stress(b, W, pos)
    assert np.isclose(ov.iloc[25], 7_000 * k * -0.30) and np.isclose(ov.sum(), ov.iloc[25])


def test_round4_weights_off_the_price_index_fail_closed(mod: Any) -> None:
    b = _flat()
    d = b["R"].index
    extra = d.append(pd.DatetimeIndex([d[-1] + pd.Timedelta(days=7)]))
    W = pd.DataFrame({"A": 0.0}, index=extra)
    W.iloc[12:, 0] = 0.1
    cfg = mod.build_cost_config("unknown_borrow_required")
    with pytest.raises(SystemExit, match="not in the price index"):
        mod.apply_costs_and_returns(b, W, cfg, idea="H1")
    with pytest.raises(SystemExit, match="not in the price index"):
        mod.held_positions(b, W)
    with pytest.raises(SystemExit, match="not in the price index"):
        mod.h1_terminal_bound(b, W, [{"symbol": "A", "identity_ok": True}], cfg)
