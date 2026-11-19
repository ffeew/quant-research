import numpy as np
import pandas as pd
import pytest

from quant_research.strategies.statarb_h1h2 import pnl
from quant_research.strategies.statarb_h1h2.guards import Blocked
from quant_research.strategies.statarb_h1h2.splits import AUM


class ZeroCost:
    def one_way_bps(self, side, px, shares, adv_shares, *, symbol, is_etf, cfg):
        return 0.0

    def borrow_usd(self, short_mv_usd, days, cfg):
        return 0.0


class FlatCost(ZeroCost):
    def one_way_bps(self, side, px, shares, adv_shares, *, symbol, is_etf, cfg):
        return 10.0


def _bars(n=30):
    d = pd.bdate_range("2018-01-01", periods=n)
    R = pd.DataFrame({"A": 0.01, "B": -0.005}, index=d)
    PX = pd.DataFrame({"A": 50.0, "B": 20.0}, index=d)
    VOL = pd.DataFrame({"A": 1e7, "B": 1e7}, index=d)
    return {"R": R, "PX": PX, "VOL": VOL}


def test_weight_row_earns_next_close_to_close_zero_cost():
    b = _bars()
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[12:17, 0] = 0.1  # filled at close d[12] (after ADV history); the fill session, not a signal bar
    out = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=ZeroCost()
    )
    g = out["daily"]["gross"]
    assert g.loc[d[12]] == 0  # nothing is earned on the fill session itself
    assert np.isclose(g.loc[d[13]], 0.1 * b["R"]["A"].iloc[13])  # first return: close d[12] -> d[13]
    assert np.isclose(g.sum(), 5 * 0.1 * 0.01) and (out["daily"]["net"] == g).all()


def test_costs_and_borrow_reduce_net():
    b = _bars()
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A", "B"])
    W.iloc[12:17, 1] = -0.1
    cfg = pnl.build_cost_config("unknown_borrow_required")
    out = pnl.apply_costs_and_returns(b, W, cfg, idea="H2", costs=FlatCost())
    d = out["daily"]
    assert np.isclose(d["tc"].sum(), 2 * 0.1 * 10 / 1e4)
    assert (d["borrow"] == 0).all()
    shared = pnl.apply_costs_and_returns(b, W, cfg, idea="H2")["daily"]
    held_days = sum((d.index[k] - d.index[k - 1]).days for k in range(13, 18))  # held over rows 13..17
    assert held_days == 7  # includes one weekend
    assert np.isclose(shared["borrow"].sum(), held_days * 0.1 * AUM * 0.10 / 360 / AUM)
    assert (shared["net"] <= shared["gross"]).all()


def test_borrow_accrues_calendar_days_over_weekend_and_year():
    d = pd.bdate_range("2017-11-01", "2019-01-01")  # ADV history before the year measured
    one = {k: pd.DataFrame({"B": v}, index=d) for k, v in {"R": 0.0, "PX": 20.0, "VOL": 1e9}.items()}
    W = pd.DataFrame({"B": -0.1}, index=d)
    cfg = pnl.build_cost_config("unknown_borrow_required")
    br = pnl.apply_costs_and_returns(one, W, cfg, idea="H2")["daily"]["borrow"]
    per_day = 0.1 * 0.10 / 360
    mon = d[(d.day_of_week == 0) & (d > "2018-01-01")][0]
    assert np.isclose(br.loc[mon], 3 * per_day)  # Friday close -> Monday close: 3 days
    assert np.isclose(br.loc[mon + pd.Timedelta(days=1)], per_day)
    yr = br.loc["2018-01-02":"2019-01-01"].sum() / 0.1  # one full calendar year held short
    assert np.isclose(yr, 0.10 * 365 / 360) and yr >= 0.10  # required 10%/yr, not ~7% (252/360)


def test_adv_cap_fills_over_several_sessions():
    b = _bars()
    d = b["R"].index
    b["VOL"]["A"] = 1e4  # ADV20 = 50 * 1e4 = $500k; 1% = $5k = 5e-4 of AUM per session
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[15:, 0] = 0.0012  # target $12k: needs 3 sessions at the cap
    out = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=ZeroCost()
    )
    g = out["daily"]["gross"]
    step = pnl.PARTICIPATION_CAP * 50 * 1e4 / AUM
    assert np.isclose(g.loc[d[16]], step * 0.01)  # first session: only the capped slice is held
    assert np.isclose(g.loc[d[17]], 2 * step * 0.01)  # remainder carried and filled next session
    assert np.isclose(g.loc[d[18]], 0.0012 * 0.01) and np.isclose(g.loc[d[25]], 0.0012 * 0.01)
    assert out["n_sessions_adv_capped"] == 2  # third session fills the 0.0002 remainder uncapped
    tc = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=FlatCost()
    )
    assert np.isclose(tc["daily"]["tc"].sum(), 0.0012 * 10 / 1e4)  # cost only on shares actually traded


def test_standard_cost_floor():
    cfg = pnl.build_cost_config("unknown_borrow_required")
    fl = pnl.FlooredCostModel(ZeroCost())
    kw = {"symbol": "A", "is_etf": False, "cfg": cfg}
    # ADV $2B (L1): 5 + 2.75; $100M (L3): 10 + 12; unknown ADV -> small: 20 + 30
    assert np.isclose(fl.one_way_bps("buy", 100.0, 10.0, 2e7, **kw), 5.0 + 2.75)
    assert np.isclose(fl.one_way_bps("buy", 100.0, 10.0, 1e6, **kw), 10.0 + 12.0)
    assert np.isclose(fl.one_way_bps("buy", 100.0, 10.0, None, **kw), 20.0 + 30.0)
    assert np.isclose(fl.one_way_bps("buy", 100.0, 10.0, 2e7, symbol="XLK", is_etf=True, cfg=cfg), 2.0 + 2.75)
    assert fl.one_way_bps("buy", 100.0, 0.0, 2e7, **kw) == 0.0
    assert pnl.FlooredCostModel(FlatCost()).one_way_bps("buy", 100.0, 10.0, 2e7, **kw) == 10.0  # higher model kept
    b = _bars()
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A", "B"])
    W.iloc[12:17, 0] = 0.1
    out = pnl.apply_costs_and_returns(b, W, cfg, idea="H1", costs=fl)
    assert out["cost_floor"] == pnl.FlooredCostModel.floor_label and out["daily"]["tc"].sum() > 0


def test_pass_bar_borrow_floor():
    with pytest.raises(RuntimeError):
        pnl.apply_costs_and_returns(_bars(), pd.DataFrame(), pnl.CostConfig("x", 0.01, True), idea="H1")
    with pytest.raises(SystemExit):
        pnl.build_cost_config("nope")


def test_sharpe():
    assert np.isnan(pnl.sharpe_ann(pd.Series([0.01] * 5)))
    s = pd.Series([0.01, -0.005, 0.02, 0.0])
    assert np.isclose(pnl.sharpe_ann(s), s.mean() / s.std() * np.sqrt(252))


def _terminal_bars():
    b = _bars()
    b["PX"].iloc[20:, 0] = np.nan
    b["VOL"].iloc[20:, 0] = 0
    b["R"].iloc[20:, 0] = np.nan
    return b


def test_h1_terminal_long():
    b = _terminal_bars()
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A"])
    W.iloc[10:25, 0] = 0.05
    roster = [{"symbol": "A", "identity_ok": True}]
    Wa, ov, rec = pnl.h1_terminal_bound(b, W, roster, pnl.build_cost_config("unknown_borrow_required"))
    assert Wa["A"].iloc[19] == 0.05 and (Wa["A"].iloc[20:] == 0).all()  # flat from tau+1: no exit fill at tau
    assert np.isclose(ov.iloc[20], -0.05) and ov.sum() == ov.iloc[20]
    assert rec[0]["tau"] == str(b["R"].index[19].date())
    with pytest.raises(Blocked):
        pnl.h1_terminal_bound(b, W, [{"symbol": "A", "identity_ok": False}], pnl.CostConfig())
    with pytest.raises(ValueError):
        pnl.h1_terminal_bound(b, W, roster, pnl.CostConfig(), path="C")


class Closes:
    def sessions(self, start, end):
        return pd.bdate_range(start, end)

    def accepted_acquirer_closes(self, acquirer_id, start, end):
        return pd.Series(30.0, index=pd.bdate_range(start, end))


def test_h1_terminal_short_vmax():
    b = _terminal_bars()
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A"])
    W.iloc[10:25, 0] = -0.05
    h = str(b["R"].index[27].date())
    terms = {
        "h": h,
        "alternatives": [{"cash": 25.0, "ratio": 1.0, "acquirer_id": "ACQ", "acquirer_identity_accepted": True}],
    }
    roster = [{"symbol": "A", "identity_ok": True, "short_terms": terms}]
    cfg = pnl.build_cost_config("unknown_borrow_required")
    _, ov, rec = pnl.h1_terminal_bound(b, W, roster, cfg, client=Closes(), costs=ZeroCost())
    assert rec[0]["V_max"] == 55.0 and np.isclose(ov.iloc[20], -0.05 * (55.0 / 50.0 - 1))
    with pytest.raises(Blocked):
        pnl.h1_terminal_bound(b, W, roster, cfg, client=None)
    bad = [{"symbol": "A", "identity_ok": True, "short_terms": dict(terms, unfiled_proration=True)}]
    with pytest.raises(Blocked):
        pnl.h1_terminal_bound(b, W, bad, cfg, client=Closes())


def test_h2_delisting_base_and_stress():
    b = _terminal_bars()
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A", "XLK"])
    W.iloc[10:28, 0] = 0.005
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.005, "w_etf": -0.004, "entry_i": 10, "exit_i": 28, "N": 2.0}]
    rec = pnl.h2_delisting_receipts(b, W, pos)
    assert len(rec) == 1 and rec[0]["last_close_session"] == str(b["R"].index[19].date())
    ov, _srec = pnl.h2_delisting_stress(b, W, pos)
    assert np.isclose(ov.iloc[20], 0.005 * -0.30) and ov.sum() == ov.iloc[20]
    ov2, srec2 = pnl.h2_delisting_stress(b, W, pos, supplied_delist_returns={"A": -0.1})
    assert ov2.sum() == 0 and srec2[0]["stress"].startswith("not applied")
    short = [dict(pos[0], w_sym=-0.005)]
    ov3, _ = pnl.h2_delisting_stress(b, -W, short)
    assert ov3.sum() == 0  # 0% for shorts


def _thin_terminal_bars():
    b = _terminal_bars()  # A's last print is session 19
    b["VOL"].loc[b["VOL"].index[:20], "A"] = 1e4  # ADV20 = $500k; 1% = $5k = 5e-4 of AUM per session
    return b


def test_h1_terminal_bound_applies_to_capped_exit_still_held_at_delisting():
    b = _thin_terminal_bars()
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A"])
    W.iloc[12:18, 0] = 0.0012  # entry fills 5e-4, 5e-4, 2e-4; the exit from close 18 is capped too
    held = pnl.held_positions(b, W)
    assert np.isclose(held["A"].iloc[15], 0.0012) and np.isclose(held["A"].iloc[20], 0.0002)
    roster = [{"symbol": "A", "identity_ok": True}]
    Wa, ov, rec = pnl.h1_terminal_bound(b, W, roster, pnl.build_cost_config("unknown_borrow_required"))
    assert W["A"].iloc[19] == 0  # target already flat at tau, but 2e-4 is still held past it
    assert len(rec) == 1 and np.isclose(rec[0]["weight"], 0.0002) and rec[0]["target_weight"] == 0
    assert np.isclose(ov.iloc[20], -0.0002) and np.isclose(ov.sum(), -0.0002)  # -100% of what is held
    after = pnl.held_positions(b, Wa)["A"]
    assert np.isclose(after.iloc[20], 0.0002) and after.iloc[21:].eq(0).all()  # settled once bound
    out = pnl.apply_costs_and_returns(b, Wa, pnl.build_cost_config("unknown_borrow_required"), idea="H1")
    assert out["daily"]["gross"].iloc[19:].eq(0).all()  # no return earned past the last print


def test_no_print_name_cannot_trade_and_stays_held():
    b = _bars()
    d = b["R"].index
    b["PX"].iloc[14:17, 0] = np.nan  # suspended for three sessions, then prints again
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[11:14, 0] = 0.1  # exit ordered at close 14, a no-print day
    held = pnl.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[14], 0.1)
    assert np.isclose(held.iloc[15:18], 0.1).all()  # closes 14-16 have no print: the exit can't fill
    assert held.iloc[18] == 0  # fills at close 17, the first print after the gap


def test_h2_delisting_stress_applies_to_held_position():
    b = _thin_terminal_bars()
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A", "XLK"])
    W.iloc[17:25, 0] = 0.0016  # capped entry at closes 17, 18, 19: 1.5e-3 held past the last print (19)
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.0016, "w_etf": 0.0, "entry_i": 17, "exit_i": 25, "N": 2.0}]
    ov, srec = pnl.h2_delisting_stress(b, W, pos)
    assert np.isclose(srec[0]["stress_weight"], 0.0015)
    assert np.isclose(ov.iloc[20], 0.0015 * -0.30) and np.isclose(ov.sum(), ov.iloc[20])


def _terminal_short(n, h_i):
    b = _bars(n)
    b["PX"].iloc[20:, 0] = np.nan
    b["VOL"].iloc[20:, 0] = 0
    b["R"].iloc[20:, 0] = np.nan
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A"])
    W.iloc[10:25, 0] = -0.05
    terms = {
        "h": str(d[h_i].date()),
        "alternatives": [{"cash": 25.0, "ratio": 1.0, "acquirer_id": "ACQ", "acquirer_identity_accepted": True}],
    }
    roster = [{"symbol": "A", "identity_ok": True, "short_terms": terms}]
    _, ov, rec = pnl.h1_terminal_bound(b, W, roster, pnl.build_cost_config("unknown_borrow_required"), client=Closes())
    return d, ov, rec


def test_h1_terminal_borrow_accrues_three_days_over_a_weekend():
    d, ov, rec = _terminal_short(30, 27)
    per_day = 0.05 * AUM * 0.10 / 360 / AUM  # shared model: 10%/yr, 360-day basis, per calendar day
    mon = next(j for j in range(21, 28) if d[j].day_of_week == 0)
    assert np.isclose(ov.iloc[mon], -3 * per_day)  # Fri close -> Mon close: 3 calendar days
    assert np.isclose(ov.iloc[mon + 1], -per_day)
    assert rec[0]["borrow_rate"] == 0.10


def test_h1_terminal_borrow_over_a_year_is_about_ten_percent():
    n = 300
    d0 = pd.bdate_range("2018-01-01", periods=n)
    h_i = int(np.searchsorted(d0.values, (d0[19] + pd.Timedelta(days=365)).to_datetime64()))
    d, ov, _ = _terminal_short(n, h_i)
    liability = 0.05 * (55.0 / 50.0 - 1.0)
    borrow = -ov.sum() - liability
    days = (d[h_i] - d[19]).days  # tau close -> h close
    assert days >= 365
    assert np.isclose(borrow, 0.05 * 0.10 * days / 360)
    assert 0.10 <= borrow / 0.05 < 0.1025  # ~10% of the short over a year (360-day basis)


def test_adv20_excludes_fill_day_volume():
    b = _bars()
    d = b["R"].index
    b["VOL"]["A"] = 1e4  # ADV20 = $500k; 1% = 5e-4 of AUM
    b["VOL"].iloc[15, 0] = 1e9  # huge volume on the fill day itself must not lift its cap
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[15:, 0] = 0.01
    held = pnl.held_positions(b, W)["A"]
    step = pnl.PARTICIPATION_CAP * 50 * 1e4 / AUM
    assert np.isclose(held.iloc[16], step)  # fill at close d[15] uses ADV20 ending d[14]
    assert held.iloc[17] > 2 * step  # the next fill's window (ending d[15]) includes the spike


def test_no_adv_history_means_no_trade():
    b = _bars()
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[2:, 0] = 0.1  # wants to trade before any ADV history exists
    out = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=FlatCost()
    )
    held = pnl.held_positions(b, W)["A"]
    assert held.iloc[:11].eq(0).all() and np.isclose(held.iloc[11], 0.1)  # 10 sessions of history first
    assert out["daily"]["gross"].loc[: d[10]].eq(0).all() and out["n_sessions_adv_capped"] == 8  # rows 3-10 blocked
    b["VOL"]["B"] = 0.0  # B never trades volume: no ADV, never filled
    W.iloc[2:, 1] = -0.1
    assert pnl.held_positions(b, W)["B"].eq(0).all()


def test_one_last_print_definition():
    PX = pd.DataFrame({"A": [10.0, 0.0, np.nan, 11.0, 0.0, -1.0, np.nan]})
    assert [pnl.has_print(v) for v in PX["A"]] == [True, False, False, True, False, False, False]
    assert pnl.printed_mask(PX)["A"].tolist() == [True, False, False, True, False, False, False]
    assert pnl.last_print_index(PX, "A") == 3 and pnl.last_print_index(PX, "Z") == -1
    b = _bars()
    b["PX"].iloc[20:, 0] = 0.0  # a zero price is no print (not only NaN): same last print everywhere
    b["VOL"].iloc[20:, 0] = 0
    assert pnl.trusted_tau(b, "A") == 19 == pnl.last_print_index(b["PX"], "A")
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A", "B"])
    W.iloc[10:28, 0] = 0.005
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.005, "w_etf": 0.0, "entry_i": 10, "exit_i": 28, "N": 2.0}]
    assert pnl.h2_delisting_receipts(b, W, pos)[0]["last_close_session"] == str(b["R"].index[19].date())


def test_exit_cost_is_charged_at_the_true_last_print():
    b = _terminal_bars()  # A's last print is close 19
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[12:19, 0] = 0.1  # exit ordered at close 19, the last print
    out = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=FlatCost()
    )
    tc = out["daily"]["tc"]
    assert np.isclose(tc.loc[d[20]], 0.1 * 10 / 1e4)  # the exit fills (and pays) at close 19
    assert np.isclose(tc.sum(), 2 * 0.1 * 10 / 1e4)
    assert pnl.held_positions(b, W)["A"].iloc[20] == 0  # nothing is left past the last print


def test_nothing_trades_on_a_no_print_day():
    b = _bars()
    d = b["R"].index
    b["PX"].iloc[15, 0] = np.nan  # no print at close 15 only
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[15:, 0] = 0.1  # entry ordered at close 15
    out = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=FlatCost()
    )
    held = pnl.held_positions(b, W)["A"]
    assert held.iloc[16] == 0 and np.isclose(held.iloc[17], 0.1)  # fills at close 16, not 15
    assert out["daily"]["tc"].loc[d[16]] == 0 and np.isclose(out["daily"]["tc"].loc[d[17]], 0.1 * 10 / 1e4)
    b["PX"].iloc[15, 0] = 0.0  # a zero price is no print either
    assert pnl.held_positions(b, W)["A"].iloc[16] == 0


def test_h2_receipts_and_stress_follow_the_held_remainder():
    b = _thin_terminal_bars()  # A's last print is close 19; 1% ADV = 5e-4 of AUM per session
    d = b["R"].index
    # (a) capped exit: planned exit at 18 (before the last print), 2e-4 still held past it
    W = pd.DataFrame(0.0, index=d, columns=["A", "XLK"])
    W.iloc[12:18, 0] = 0.0012
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.0012, "w_etf": 0.0, "entry_i": 12, "exit_i": 18, "N": 2.0}]
    rec = pnl.h2_delisting_receipts(b, W, pos)
    assert len(rec) == 1 and np.isclose(rec[0]["held_weight"], 0.0002) and rec[0]["held_past_planned_exit"]
    ov, srec = pnl.h2_delisting_stress(b, W, pos)
    assert np.isclose(ov.iloc[20], 0.0002 * -0.30) and np.isclose(ov.sum(), ov.iloc[20])
    assert np.isclose(srec[0]["stress_weight"], 0.0002)
    # (b) last print at exit_i - 1: the exit is ordered at close 20, which has no print
    W2 = pd.DataFrame(0.0, index=d, columns=["A", "XLK"])
    W2.iloc[12:20, 0] = 0.001
    pos2 = [dict(pos[0], w_sym=0.001, exit_i=20)]
    rec2 = pnl.h2_delisting_receipts(b, W2, pos2)
    assert len(rec2) == 1 and np.isclose(rec2[0]["held_weight"], 0.001)
    ov2, _ = pnl.h2_delisting_stress(b, W2, pos2)
    assert np.isclose(ov2.iloc[20], 0.001 * -0.30)
    # (c) fully exited at the last print: nothing held past it, so no receipt and no stress
    W3 = pd.DataFrame(0.0, index=d, columns=["A", "XLK"])
    W3.iloc[12:19, 0] = 0.0004
    pos3 = [dict(pos[0], w_sym=0.0004, exit_i=19)]
    assert pnl.h2_delisting_receipts(b, W3, pos3) == [] and pnl.h2_delisting_stress(b, W3, pos3)[0].sum() == 0
