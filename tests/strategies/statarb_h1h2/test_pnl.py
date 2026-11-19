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
    assert np.isclose(shared["borrow"].sum(), 5 * 0.1 * AUM * 0.10 / 360 / AUM)
    assert (shared["net"] <= shared["gross"]).all()


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
