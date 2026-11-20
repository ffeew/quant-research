import numpy as np
import pandas as pd

from quant_research.strategies.statarb_h1h2 import events, pnl, signals, universe
from quant_research.strategies.statarb_h1h2.splits import DEV0, DEV1, MARGIN, NAME_CAP

from . import synth as S


def _setup(**kw):
    bars = S.make_bars(**kw)
    mem, _ = universe.build_membership(S.membership(), S.listing(), {"tickers": []}, {"tickers": []})
    E = universe.build_elig(bars, mem)
    sub, sec = S.gics()
    ev = S.earnings(bars["R"].index)
    evidx = events.make_evidx(events.earliest_possible_index(ev, bars["R"].index))
    last = len(bars["R"].index) - 1 - MARGIN
    return bars, E, sub, sec, ev, evidx, last


def test_h1_followers_long_when_leaders_led():
    bars, E, sub, _, _, evidx, last = _setup()
    W, tr = signals.signal_h1(bars, E, sub, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    assert tr
    row = W.iloc[350]  # inside the injected leader-gap window
    assert (row[S.LEADERS] < 0).all() and (row[["CCC", "DDD", "EEE", "FFF"]] > 0).all()
    assert np.isclose(row["AAA"], -NAME_CAP)  # name cap trims, does not reallocate
    assert W.abs().max().max() <= NAME_CAP + 1e-12
    assert (W.loc[: pd.Timestamp("2016-11-01")] == 0).all().all()  # nothing before the eval warm-up


class _ZeroCost:
    def one_way_bps(self, side, px, shares, adv_shares, *, symbol, is_etf, cfg):
        return 0.0

    def borrow_usd(self, short_mv_usd, days, cfg):
        return 0.0


def test_h1_signal_at_t_first_earns_t1_to_t2():
    bars, E, sub, _, _, evidx, last = _setup()
    W, tr = signals.signal_h1(bars, E, sub, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    d = W.index
    i = int(np.flatnonzero((W.abs().sum(axis=1) > 0).to_numpy())[0]) - 1  # bar before the first holding
    assert d[i] in tr  # ... is a signal bar: the tranche formed at close t is first held at t+1
    assert (W.iloc[: i + 1] == 0).all().all()  # nothing held on (or before) that signal bar
    for t in tr[1:]:  # every later tranche changes the book one session after its signal bar
        k = d.get_loc(t)
        if k + 1 < len(d):
            assert (W.iloc[k] == W.iloc[k - 1]).all()
    deep = dict(bars, VOL=bars["VOL"] * 1e6)  # keep the ADV cap out of this timing check
    g = pnl.apply_costs_and_returns(
        deep, W, pnl.build_cost_config("unknown_borrow_required"), idea="H1", costs=_ZeroCost()
    )["daily"]["gross"]
    assert g.loc[d[i + 1]] == 0
    R = bars["R"].iloc[i + 2].reindex(W.columns).fillna(0.0)
    assert np.isclose(g.loc[d[i + 2]], float((W.iloc[i + 1] * R).sum()))
    assert g.loc[d[i + 2]] != 0


def test_h1_flips_sign_and_respects_threshold():
    bars, E, sub, _, _, evidx, last = _setup(h1_gap=-0.004)
    W, _ = signals.signal_h1(bars, E, sub, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    row = W.iloc[350]
    assert (row[S.LEADERS] > 0).all() and (row[["CCC", "DDD", "EEE", "FFF"]] < 0).all()
    W2, _ = signals.signal_h1(bars, E, sub, evidx, z_thr=1e6, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    assert (W2 == 0).all().all()


def test_h1_min_group_and_exit_bound():
    bars, E, sub, _, _, evidx, last = _setup()
    W, _ = signals.signal_h1(bars, E, sub, evidx, min_grp=7, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    assert (W == 0).all().all()
    W2, _ = signals.signal_h1(bars, E, sub, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=0)
    assert (W2 == 0).all().all()


def test_h2_peer_readthrough():
    bars, E, sub, sec, ev, evidx, last = _setup()
    W, pos = signals.signal_h2(bars, E, sub, sec, ev, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    assert {p["sym"] for p in pos} == {"CCC", "DDD", "EEE", "FFF"}
    p = pos[0]
    assert p["N"] > 1.5 and p["w_sym"] == 0.005 and p["etf"] == "XLK" and p["w_etf"] < 0
    assert p["entry_i"] == 331 and p["exit_i"] == 371
    d = W.index
    assert (W["CCC"].iloc[331:371] == 0.005).all() and W["CCC"].iloc[330] == 0 and W["CCC"].iloc[371] == 0
    assert np.isclose(W["XLK"].iloc[340], sum(q["w_etf"] for q in pos))
    assert d[p["entry_i"]] > d[330]  # fill after the reaction session


def test_h2_no_trigger_without_shock_or_with_boundary_time():
    bars, E, sub, sec, ev, evidx, last = _setup(h2_shock_i=None)
    _, pos = signals.signal_h2(bars, E, sub, sec, ev, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    assert pos == [] or all(abs(p["N"]) >= 1.5 for p in pos)
    bars, E, sub, sec, ev, evidx, last = _setup()
    ev2 = ev.copy()
    ev2["knowledge_time_utc"] = pd.to_datetime(ev2["reaction_session"]).dt.tz_localize(
        "America/New_York"
    ) + pd.Timedelta(hours=16)
    _, pos2 = signals.signal_h2(bars, E, sub, sec, ev2, evidx, eval_start=DEV0, eval_end=DEV1, last_exit_i=last)
    assert pos2 == []


def test_h2_unit_and_max_positions():
    bars, E, sub, sec, ev, evidx, last = _setup()
    _, pos = signals.signal_h2(
        bars, E, sub, sec, ev, evidx, unit=0.004, NMAX=2, eval_start=DEV0, eval_end=DEV1, last_exit_i=last
    )
    assert len(pos) == 2 and all(p["w_sym"] == 0.004 for p in pos)
    assert [p["sym"] for p in pos] == ["CCC", "DDD"]  # ties broken by symbol


def test_h2_hedge_stays_beta_neutral_when_name_cap_binds():
    d = pd.bdate_range("2018-01-01", periods=30)
    betas = {"CCC": 1.2, "DDD": 0.8, "EEE": 1.5}
    pos = [
        {"sym": s, "etf": "XLK", "w_sym": 0.3, "w_etf": -b * 0.3, "entry_i": 5 + k, "exit_i": 20, "N": 2.0}
        for k, (s, b) in enumerate(betas.items())
    ]
    W = signals.h2_book(pos, d)
    assert np.isclose(W[list(betas)].abs().max().max(), NAME_CAP)  # the cap binds on every name
    book_beta = sum(W[s] * b for s, b in betas.items()) + W["XLK"]
    assert np.allclose(book_beta, 0.0, atol=1e-12)  # hedge re-solved after the cap
    assert W["XLK"].abs().max() > NAME_CAP  # the hedge leg itself is not trimmed
    assert (W.iloc[:5] == 0).all().all() and (W.iloc[20:] == 0).all().all()
