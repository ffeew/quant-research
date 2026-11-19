import numpy as np
import pandas as pd

from quant_research.strategies.statarb_h1h2 import events, signals, universe
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
