import numpy as np
import pandas as pd
import pytest

from quant_research.strategies.statarb_h1h2 import events as ev
from quant_research.strategies.statarb_h1h2 import universe as u
from quant_research.strategies.statarb_h1h2.guards import Blocked

from . import synth as S

T = pd.Timestamp


def test_subtract_intervals():
    assert u.subtract_intervals((T("2016-01-01"), T("2017-01-01")), [(T("2016-03-01"), T("2016-04-01"))]) == [
        (T("2016-01-01"), T("2016-03-01")),
        (T("2016-04-01"), T("2017-01-01")),
    ]
    out = u.subtract_intervals((T("2016-01-01"), pd.NaT), [(T("2016-06-01"), pd.NaT)])
    assert out == [(T("2016-01-01"), T("2016-06-01"))]
    assert u.subtract_intervals((T("2016-01-01"), T("2016-02-01")), [(T("2017-01-01"), pd.NaT)]) == [
        (T("2016-01-01"), T("2016-02-01"))
    ]


def test_membership_rules():
    pm = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "XLK", "DDD", "EEE"],
            "start_date_filled": T("2015-01-02"),
            "end_date": [None] * 6,
        }
    )
    ls = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "XLK", "EEE"],
            "ipoDate": ["2000-01-03", "2000-01-03", "2016-06-01", "2000-01-03", "2000-01-03"],
            "delistingDate": ["null", "null", "2017-01-31", "null", "null"],
            "listing_source": "active",
        }
    )
    reused = {"tickers": [{"ticker": "BBB", "original_member_periods": [["2015-01-02", "2016-01-04"]]}]}
    missing = {"tickers": [{"ticker": "EEE"}]}
    fl = {"sha256": "x", "excluded": {"AAA": "identity"}, "kept": set()}
    mem, rec = u.build_membership(pm, ls, reused, missing, final_list=fl)
    assert set(mem.symbol) == {"BBB", "CCC"}
    assert rec["final_list_excluded"] == [{"symbol": "AAA", "reason": "identity"}]
    assert rec["etf_rows_dropped"] == ["XLK"] and rec["no_listing_record"] == ["DDD"]
    assert rec["reused_removed"] == ["BBB"] and rec["missing_gap"][0]["symbol"] == "EEE"
    bbb = mem[mem.symbol == "BBB"].iloc[0]
    assert T(bbb.start_date_filled) == T("2016-01-04")
    ccc = mem[mem.symbol == "CCC"].iloc[0]
    assert (T(ccc.start_date_filled), T(ccc.end_date)) == (T("2016-06-01"), T("2017-02-01"))


def test_receipt_lists_only_rows_dated_on_or_before_dev_end():
    pm = pd.DataFrame(
        {
            "symbol": ["OLD", "CLP", "NEW", "XLK", "MIS", "LAT"],
            "start_date_filled": [T("2016-01-04")] * 2
            + [T("2022-06-01"), T("2023-01-03"), T("2016-01-04")]
            + [T("2022-02-01")],
            "end_date": [None, None, None, None, T("2024-01-02"), None],
            "after_boundary": [False, False, True, False, False, True],
        }
    )
    ls = pd.DataFrame(
        {
            "symbol": ["OLD", "CLP", "LAT"],
            "ipoDate": ["2000-01-03", "2000-01-03", "2000-01-03"],
            "delistingDate": ["2023-05-01", "2017-03-01", "null"],  # OLD's clip is after the DEV end
            "listing_source": "active",
        }
    )
    reused = {"tickers": [{"ticker": "OLD", "original_member_periods": [["2023-06-01", None]]}]}
    mem, rec = u.build_membership(pm, ls, reused, {"tickers": [{"ticker": "MIS"}]})
    assert rec["listing_clipped"] == ["CLP"]  # OLD is clipped only in 2023: not listed
    assert rec["reused_removed"] == [] and rec["no_listing_record"] == [] and rec["etf_rows_dropped"] == []
    assert rec["missing_gap"] == [{"symbol": "MIS", "start": "2016-01-04", "end": None}]  # 2024 end not shown
    assert rec["after_boundary_member_rows"] == []
    flat = str(rec)
    assert "NEW" not in flat and "LAT" not in flat and "2023" not in flat and "2024" not in flat
    assert set(mem.symbol) == {"OLD", "CLP", "LAT"}  # membership itself is unchanged
    _, rec_h = u.build_membership(pm, ls, reused, {"tickers": [{"ticker": "MIS"}]}, receipt_end=T("2026-10-28").date())
    assert rec_h["listing_clipped"] == ["OLD", "CLP"] and rec_h["no_listing_record"] == ["NEW"]


def test_listing_overlap_fails_closed():
    pm = S.membership()
    ls = pd.concat([S.listing(), S.listing().iloc[:1].assign(listing_source="delisted", delistingDate="2010-01-04")])
    with pytest.raises(Blocked, match="AAA"):
        u.build_membership(pm, ls, {"tickers": []}, {"tickers": []})
    _mem, rec = u.build_membership(
        pm, ls, {"tickers": []}, {"tickers": []}, final_list={"kept": {"AAA"}, "excluded": {}}
    )
    assert rec["final_list_kept_covered_overlap"] == ["AAA"]
    u.build_membership(pm, ls, {"tickers": []}, {"tickers": []}, listing_overlap_treatment={"AAA": "x"})


def test_elig_filters():
    bars = S.make_bars()
    mem, _ = u.build_membership(S.membership(), S.listing(), {"tickers": []}, {"tickers": []})
    E = u.build_elig(bars, mem)
    assert not E.iloc[:252].any().any()  # 252-session history
    assert E["AAA"].iloc[300] and not E["XLK"].any()  # ETFs are not members
    bars["PX"].iloc[300:, bars["PX"].columns.get_loc("CCC")] = 4.0
    bars["VOL"].iloc[305, bars["VOL"].columns.get_loc("DDD")] = 0
    bars["R"].iloc[310, bars["R"].columns.get_loc("EEE")] = 0.5
    E2 = u.build_elig(bars, mem)
    assert not E2["CCC"].iloc[300:].any()  # price < $5
    assert not E2["DDD"].iloc[305]  # zero volume
    assert not E2["EEE"].iloc[310:330].any() and E2["EEE"].iloc[331]  # 20-session jump filter


def test_event_windows():
    idx = {"A": np.array([10, 50])}
    # frozen semantics: event in (a - margin, b + margin]
    assert ev.ev_in(idx, "A", 11, 20) and not ev.ev_in(idx, "A", 12, 20)
    assert ev.ev_in(idx, "A", 30, 48) and not ev.ev_in(idx, "A", 30, 47)
    assert ev.ev_in(idx, "A", 48, 49, margin=0) is False and ev.ev_in(idx, "A", 48, 50, margin=0)
    assert not ev.ev_in(idx, "Z", 0, 100)
    assert ev.covered(idx, "A", 60) and not ev.covered(idx, "A", 181) and not ev.covered(idx, "A", 5)


def test_boundary_ambiguous():
    et = "America/New_York"
    assert ev.boundary_ambiguous(None)
    assert ev.boundary_ambiguous(pd.Timestamp("2018-05-01 16:04", tz=et).tz_convert("UTC"))
    assert ev.boundary_ambiguous(pd.Timestamp("2018-05-01 09:25", tz=et))
    assert not ev.boundary_ambiguous(pd.Timestamp("2018-05-01 07:00", tz=et))


def test_earliest_possible_index():
    dates = pd.bdate_range("2018-01-01", periods=30)
    e = pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D"],
            "source": ["sec_8k", "nasdaq_scheduled", "x_fallback", "sec_8k"],
            "timing_quality": ["exact_acceptance_time", "exact_acceptance_time", "exact", "unknown_x"],
            "reaction_session": [dates[10], dates[10], dates[10], dates[12]],
            "first_tradable_session": [None] * 4,
            "announce_date_et": [dates[9], dates[9], dates[9], dates[8]],
        }
    )
    out = ev.earliest_possible_index(e, dates).set_index("symbol")._ix.to_dict()
    assert out == {"A": 10, "C": 5, "D": 8}
