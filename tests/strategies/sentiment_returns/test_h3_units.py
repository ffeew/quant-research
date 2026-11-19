"""Synthetic tests for the H3 library. Plain asserts; runs under pytest or a minimal runner."""
import datetime as dt
import random
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from quant_research.strategies.sentiment_returns.h3 import book, config as cfg, signal, stats, weeks
from quant_research.strategies.sentiment_returns.h3.errors import H3ConfigError

P = cfg.H3Params().with_choices(flat_clears_band_memory=True, drift_renormalise_legs=True,
                                 sector_ic_method="demeaned_spearman", n_universe=50)


def close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-12


def _raises(exc: type[BaseException], fn: Callable[..., object], *a: object, **k: object) -> None:
    try:
        fn(*a, **k)
    except exc:
        return
    raise AssertionError(f"{exc.__name__} not raised")


def test_repo_config_loads_and_leaves_choices_unset() -> None:
    p = cfg.load_h3_params()
    assert p.window_sessions == 20 and p.long_in == 0.80 and p.research_only == ("MSTR",)
    for k in cfg.UNSETTLED:
        assert getattr(p, k) is None
        _raises(H3ConfigError, p.require, k)
    _raises(H3ConfigError, p.with_choices, min_leg=3)
    _raises(H3ConfigError, cfg.params_from_dict, {"bogus": 1})
    _raises(H3ConfigError, cfg.params_from_dict, {"long_in": 0.5})
    _raises(H3ConfigError, cfg.params_from_dict, {"sector_ic_method": "other"})


def test_unset_choice_blocks_book() -> None:
    p = cfg.H3Params()
    wk = dict(dec="w1", qual={}, scored=False, r={}, y={})
    _raises(H3ConfigError, book.run_book, [wk], p)
    _raises(H3ConfigError, book.drift, {"A": 1.0}, {"A": 0.0}, p)


def test_band_step_hand_cases() -> None:
    cases = [(0, .80, 1), (0, .79, 0), (0, .20, -1), (0, .21, 0), (1, .60, 1), (1, .59, 0), (1, .20, -1), (1, .21, 0),
             (-1, .40, -1), (-1, .41, 0), (-1, .80, 1), (-1, .79, 0), (1, .99, 1), (-1, .01, -1)]
    assert all(book.band_step(pos, u, P) == e for pos, u, e in cases)


def test_weights_drift_turnover() -> None:
    L = [f"L{i}" for i in range(5)]
    S = [f"S{i}" for i in range(5)]
    w, flat = book.target_weights({**{s: 1 for s in L}, **{s: -1 for s in S}}, P)
    assert not flat and all(close(w[s], .2) for s in L) and all(close(w[s], -.2) for s in S)
    w4, flat4 = book.target_weights({**{s: 1 for s in L[:4]}, **{s: -1 for s in S}}, P)
    assert flat4 and w4 == {}
    assert close(book.traded_weight(w, {}), 2.0)
    r = {s: 0.0 for s in L + S}
    r["L0"] = 0.10
    wd = book.drift(w, r, P)
    assert close(wd["L0"], 0.22 / 1.02) and close(wd["L1"], 0.2 / 1.02)
    exp = abs(.2 - .22 / 1.02) + 4 * abs(.2 - .2 / 1.02)
    assert close(book.traded_weight(w, wd), exp)
    assert close(book.leg_return(w, r), 0.02)
    wd2 = book.drift(w, r, P.with_choices(drift_renormalise_legs=False))
    assert close(wd2["L0"], 0.22) and close(wd2["S0"], -0.2)


def _wk(dec: str, us: Mapping[str, float], scored: bool = True) -> dict[str, Any]:
    rr = {s: 0.0 for s in us}
    return dict(dec=dec, qual={s: (u, u) for s, u in us.items()}, scored=scored, r=rr, y=rr)


NAMES = [f"N{i:02d}" for i in range(50)]
U1 = {s: (i + .5) / 50 for i, s in enumerate(NAMES)}


def test_run_book_entry_and_band_hold() -> None:
    rows, _ = book.run_book([_wk("w1", U1)], P)
    b = rows[0]
    assert b["n_long"] == 10 and b["n_short"] == 10 and close(b["traded"], 2.0)
    assert close(b["net"], b["gross"] - .002) and close(b["net_sens"], b["gross"] - .004)
    u2 = {s: ((i + 10) % 50 + .5) / 50 for i, s in enumerate(NAMES)}
    rows, _ = book.run_book([_wk("w1", U1), _wk("w2", u2)], P)
    l1, l2 = set(rows[0]["longs"]), set(rows[1]["longs"])
    assert l2 == {s for s in NAMES if u2[s] >= .8} | {s for s in l1 if u2[s] >= .6}


def test_forced_exit_and_unscored_week_holds() -> None:
    q2 = {s: u for s, u in U1.items() if s != "N49"}
    rows, term = book.run_book([_wk("w1", U1), _wk("w2", q2, scored=False)], P)
    assert rows[1]["forced_exits"] == 1 and "N49" not in rows[1]["longs"] and rows[1]["n_long"] == 9
    assert close(term, 2.0)


def test_flat_memory_choice_matters() -> None:
    few = {s: u for s, u in U1.items() if u < .8 or s in ("N40", "N41", "N42", "N43")}
    w3 = {s: .7 for s in ("N40", "N41", "N42", "N43")} | {"N44": .85} | {s: .3 for s in NAMES[:5]}
    seq = [_wk("w1", U1), _wk("w2", few), _wk("w3", w3)]
    a, _ = book.run_book(seq, P)
    b, _ = book.run_book(seq, P.with_choices(flat_clears_band_memory=False))
    assert a[1]["flat"] and b[1]["flat"] and a[1]["forced_exits"] == 6
    assert a[2]["flat"] and not b[2]["flat"] and b[2]["n_long"] == 5 and b[2]["n_short"] == 5


def test_quintile_mode_and_trade_list() -> None:
    rows, _ = book.run_book([_wk("w1", U1)], P.with_choices(flat_clears_band_memory=None), mode="quintile")
    assert rows[0]["n_long"] == 10 and rows[0]["n_short"] == 10
    assert book.trade_list(["AAA", "MSTR", "BBB"], cfg.load_h3_params()) == ["AAA", "BBB"]


def test_decision_dates_and_straddle() -> None:
    d0 = dt.date(2021, 1, 4)
    sess = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(120) if (d0 + dt.timedelta(days=i)).weekday() < 5]
    usable, nxt, straddle = weeks.decision_dates(sess, 5, "2021-01-04", "2021-03-31")
    assert usable and all(dt.date.fromisoformat(d).weekday() == 4 for d in usable)
    assert sess.index(usable[0]) - 5 >= 0 and usable[0] == "2021-01-15"
    assert all(nxt[d] <= "2021-03-31" for d in usable) and straddle == ["2021-03-26"]


def test_cutoff_and_month_padding() -> None:
    c = weeks.cutoff("2021-03-01")
    assert dt.datetime.fromtimestamp(c, weeks.NY).hour == 15
    assert weeks.month_set(weeks.cutoff("2021-03-01"), weeks.cutoff("2021-03-31")) == {"2021-02", "2021-03", "2021-04"}


def test_parse_item_and_window_score() -> None:
    it = dict(time_published="20210301T120000",
              ticker_sentiment=[dict(ticker="AAA", relevance_score="0.9", ticker_sentiment_score="0.3")])
    st, row = signal.parse_item(it, "AAA", .5)
    assert st == "kept" and row is not None and row[0] - row[1] in (-18000.0, -14400.0)
    assert signal.parse_item(it, "BBB", .5)[0] == "no_entry"
    assert signal.parse_item(dict(it, time_published="bad"), "AAA", .5)[0] == "unparseable"
    lo = dict(it, ticker_sentiment=[dict(ticker="AAA", relevance_score="0.2", ticker_sentiment_score="0.3")])
    assert signal.parse_item(lo, "AAA", .5)[0] == "low_rel"
    a = np.array([[1, 1, 0.5, 1.0], [2, 2, -0.5, 3.0], [3, 3, 1.0, 1.0], [9, 9, 9.0, 1.0]])
    ws = signal.window_score(a, "UTC", 0, 3, 3)
    assert ws is not None and close(ws, (0.5 - 1.5 + 1.0) / 5)
    assert signal.window_score(a, "ET", 0, 3, 4) is None


def test_cross_section_ranks_and_min_names() -> None:
    ok, q = signal.cross_section({f"S{i}": float(i) for i in range(40)}, P)
    assert ok and close(q["S0"][1], 0.5 / 40) and close(q["S39"][1], 39.5 / 40)
    assert not signal.cross_section({"A": 1.0}, P)[0]


def test_stats_summary_gate_and_sector_ic() -> None:
    rng = random.Random(7)
    x = [rng.gauss(0.01, 0.02) for _ in range(60)]
    o = stats.one_sided(x, 4)
    assert o["df"] == 59 and 0 <= o["p_one_sided"] <= 1
    assert stats.one_sided([1.0, 1.0, 1.0], 4)["nw_t"] is None
    names = [f"S{i:02d}" for i in range(40)]
    S = {s: rng.random() for s in names}
    sec = {s: ("A" if i % 2 else "B") for i, s in enumerate(names)}
    ic = stats.sector_ic(names, S, S, sec, P)
    assert ic is not None and close(ic, 1.0)
    assert stats.sector_ic(names[:10], S, S, sec, P) is None
    _raises(H3ConfigError, stats.sector_ic, names, S, S, sec, cfg.H3Params())
    rows, term = book.run_book([_wk(f"w{i}", U1) for i in range(4)], P)
    wks = [dict(scored=True, ic=0.05, ic_sec=None) for _ in rows]
    sm = stats.summarise(wks, rows, term, P)
    assert sm["scored_weeks"] == 4 and close(sm["mean_ic"], 0.05) and sm["avg_holding_weeks"] == 4.0
    assert close(sm["breakeven_cost_per_side_bps"], sm["ls_gross_mean"] / sm["mean_traded_weight"] * 1e4)
    assert stats.dev_gate(dict(mean_ic=0.01, ls_net_mean=0.001)) == "PASS"
    assert stats.dev_gate(dict(mean_ic=0.01, ls_net_mean=-0.001)) == "FAIL"
    assert stats.combined_gate({"UTC": dict(mean_ic=.1, ls_net_mean=.1), "ET": dict(mean_ic=-.1, ls_net_mean=.1)}) == "FAIL"
