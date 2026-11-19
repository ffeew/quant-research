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
    W.iloc[5:10, 0] = 0.1  # filled at close d[5]; this is the fill session, not a signal bar
    out = pnl.apply_costs_and_returns(
        b, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=ZeroCost()
    )
    g = out["daily"]["gross"]
    assert g.loc[d[5]] == 0  # nothing is earned on the fill session itself
    assert np.isclose(g.loc[d[6]], 0.1 * b["R"]["A"].iloc[6])  # first return: close d[5] -> d[6]
    assert np.isclose(g.sum(), 5 * 0.1 * 0.01) and (out["daily"]["net"] == g).all()


def test_costs_and_borrow_reduce_net():
    b = _bars()
    W = pd.DataFrame(0.0, index=b["R"].index, columns=["A", "B"])
    W.iloc[5:10, 1] = -0.1
    cfg = pnl.build_cost_config("unknown_borrow_required")
    out = pnl.apply_costs_and_returns(b, W, cfg, idea="H2", costs=FlatCost())
    d = out["daily"]
    assert np.isclose(d["tc"].sum(), 2 * 0.1 * 10 / 1e4)
    assert (d["borrow"] == 0).all()
    shared = pnl.apply_costs_and_returns(b, W, cfg, idea="H2")["daily"]
    held_days = sum((d.index[k] - d.index[k - 1]).days for k in range(6, 11))  # held over rows 6..10
    assert held_days == 7  # includes one weekend
    assert np.isclose(shared["borrow"].sum(), held_days * 0.1 * AUM * 0.10 / 360 / AUM)
    assert (shared["net"] <= shared["gross"]).all()


def test_borrow_accrues_calendar_days_over_weekend_and_year():
    d = pd.bdate_range("2018-01-01", "2019-01-01")
    one = {k: pd.DataFrame({"B": v}, index=d) for k, v in {"R": 0.0, "PX": 20.0, "VOL": 1e9}.items()}
    W = pd.DataFrame({"B": -0.1}, index=d)
    cfg = pnl.build_cost_config("unknown_borrow_required")
    br = pnl.apply_costs_and_returns(one, W, cfg, idea="H2")["daily"]["borrow"]
    per_day = 0.1 * 0.10 / 360
    mon = d[(d.day_of_week == 0) & (d > d[2])][0]
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
    W.iloc[5:10, 0] = 0.1
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
    assert (Wa["A"].iloc[19:] == 0).all() and np.isclose(ov.iloc[20], -0.05) and ov.sum() == ov.iloc[20]
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
    rec = pnl.h2_delisting_receipts(b, pos)
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
    W.iloc[12:17, 0] = 0.0012  # entry fills 5e-4, 5e-4, 2e-4; the exit from row 17 is capped too
    held = pnl.held_positions(b, W)
    assert np.isclose(held["A"].iloc[15], 0.0012) and np.isclose(held["A"].iloc[19], 0.0002)
    roster = [{"symbol": "A", "identity_ok": True}]
    Wa, ov, rec = pnl.h1_terminal_bound(b, W, roster, pnl.build_cost_config("unknown_borrow_required"))
    assert W["A"].iloc[19] == 0  # target already flat at tau, but 2e-4 is still held
    assert len(rec) == 1 and np.isclose(rec[0]["weight"], 0.0002) and rec[0]["target_weight"] == 0
    assert np.isclose(ov.iloc[20], -0.0002) and np.isclose(ov.sum(), -0.0002)  # -100% of what is held
    after = pnl.held_positions(b, Wa)["A"]
    assert np.isclose(after.iloc[19], 0.0002) and after.iloc[20:].eq(0).all()  # settled once bound
    out = pnl.apply_costs_and_returns(b, Wa, pnl.build_cost_config("unknown_borrow_required"), idea="H1")
    assert out["daily"]["gross"].iloc[19:].eq(0).all()  # no return earned past the last print


def test_no_print_name_cannot_trade_and_stays_held():
    b = _bars()
    d = b["R"].index
    b["PX"].iloc[14:17, 0] = np.nan  # suspended for three sessions, then prints again
    W = pd.DataFrame(0.0, index=d, columns=["A", "B"])
    W.iloc[11:13, 0] = 0.1
    held = pnl.held_positions(b, W)["A"]
    assert np.isclose(held.iloc[13], 0.1)
    assert np.isclose(held.iloc[14:17], 0.1).all()  # no print: the exit can't fill
    assert held.iloc[17] == 0  # exits once it prints again


def test_h2_delisting_stress_applies_to_held_position():
    b = _thin_terminal_bars()
    d = b["R"].index
    W = pd.DataFrame(0.0, index=d, columns=["A", "XLK"])
    W.iloc[17:25, 0] = 0.0012  # capped entry: 5e-4 then 1e-3 held when A stops printing at 19
    pos = [{"sym": "A", "etf": "XLK", "w_sym": 0.0012, "w_etf": 0.0, "entry_i": 17, "exit_i": 25, "N": 2.0}]
    ov, srec = pnl.h2_delisting_stress(b, W, pos)
    assert np.isclose(srec[0]["stress_weight"], 0.001)
    assert np.isclose(ov.iloc[20], 0.001 * -0.30) and np.isclose(ov.sum(), ov.iloc[20])
