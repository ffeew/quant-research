"""Tests for PIT SIC-2 grouping. Synthetic records and a synthetic session calendar only."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from quant_research.strategies.portfolio_construction import paper_risk as pr
from quant_research.strategies.portfolio_construction import sic_groups as sg
from quant_research.strategies.portfolio_construction.sic_groups import (
    CikLink,
    IneligibleReason,
    SicGroupError,
    SicHeader,
    SicInterval,
)


def _weekday_sessions(start: date, n_days: int, holidays: frozenset[date] = frozenset()) -> list[date]:
    out = []
    d = start
    for _ in range(n_days):
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def _et(y: int, m: int, d: int, hh: int, mm: int) -> datetime:
    """Naive ET wall-clock acceptance time (the module's input convention)."""
    return datetime.combine(date(y, m, d), time(hh, mm))


# Synthetic calendar: weekdays from Mon 2030-01-07, with Wed 2030-01-16 a synthetic holiday.
HOL = date(2030, 1, 16)
SESS = _weekday_sessions(date(2030, 1, 7), 60, frozenset({HOL}))
CIK = "0000000001"
LINK = CikLink("AAA", CIK, date(2030, 1, 7), None)


def _h(acc_n: int, when: datetime, sic: str | None, cik: str = CIK, block: str | None = None) -> SicHeader:
    return SicHeader(cik, f"{acc_n:010d}-30-000001", when, sic, cik if block is None else block)


def _one(headers, session, links=(LINK,)):
    return sg.resolve_sic2_groups(["AAA"], links, headers, session, SESS)["AAA"]


# ------------------------------------------------------------------ SIC helpers


@pytest.mark.parametrize(
    "sic, ok",
    [
        ("2834", True),
        ("0100", True),
        ("0000", False),
        ("283", False),
        ("28345", False),
        ("28a4", False),
        ("", False),
        (None, False),
        (" 2834", False),
        ("２８３４", False),
    ],
)
def test_valid_sic(sic, ok):
    assert sg.valid_sic(sic) is ok
    assert (sg.sic2_of(sic) is not None) is ok


def test_sic2_boundary():
    assert sg.sic2_of("2899") == "28"
    assert sg.sic2_of("2900") == "29"
    assert sg.sic2_of("0100") == "01"


def test_first_session_after_skips_weekend_and_holiday():
    assert sg.first_session_after(date(2030, 1, 11), SESS) == date(2030, 1, 14)  # Fri -> Mon
    assert sg.first_session_after(date(2030, 1, 15), SESS) == date(2030, 1, 17)  # holiday skipped
    assert sg.first_session_after(SESS[-1], SESS) is None


# ------------------------------------------------------------------ PIT rule


def test_strict_before_acceptance_and_first_session_after():
    # accepted Tue 2030-01-08 after the close: not valid that day, valid from Wed 2030-01-09
    hs = [_h(1, _et(2030, 1, 8, 17, 30), "2834")]
    assert _one(hs, date(2030, 1, 8)).reason is IneligibleReason.NO_HEADER_BEFORE
    r = _one(hs, date(2030, 1, 9))
    assert r.eligible and r.sic2 == "28" and r.source_accession == hs[0].accession


def test_acceptance_before_open_same_day_still_not_valid_that_day():
    hs = [_h(1, _et(2030, 1, 8, 6, 0), "2834")]
    assert not _one(hs, date(2030, 1, 8)).eligible
    assert _one(hs, date(2030, 1, 9)).eligible


def test_acceptance_on_weekend_and_before_holiday():
    hs = [_h(1, _et(2030, 1, 12, 10, 0), "3674")]  # Saturday
    assert _one(hs, date(2030, 1, 14)).sic2 == "36"  # Monday
    hs2 = [_h(2, _et(2030, 1, 15, 20, 0), "3674")]  # Tue evening; Wed is a holiday
    assert not _one(hs2, date(2030, 1, 15)).eligible
    assert _one(hs2, date(2030, 1, 17)).sic2 == "36"


def test_sic_change_takes_over_from_first_session_after():
    hs = [_h(1, _et(2030, 1, 7, 9, 0), "2834"), _h(2, _et(2030, 1, 21, 16, 5), "3674")]
    assert _one(hs, date(2030, 1, 21)).sic2 == "28"
    assert _one(hs, date(2030, 1, 22)).sic2 == "36"


def test_equal_acceptance_tie_larger_accession_wins():
    t = _et(2030, 1, 8, 16, 0)
    hs = [_h(5, t, "2834"), _h(9, t, "3674"), _h(7, t, "1311")]
    r = _one(hs, date(2030, 1, 10))
    assert r.sic == "3674" and r.source_accession == hs[1].accession


def test_later_acceptance_beats_larger_accession():
    hs = [_h(9, _et(2030, 1, 8, 9, 0), "2834"), _h(1, _et(2030, 1, 8, 9, 1), "3674")]
    assert _one(hs, date(2030, 1, 10)).sic == "3674"


def test_duplicate_accession_raises():
    t = _et(2030, 1, 8, 16, 0)
    with pytest.raises(SicGroupError):
        _one([_h(5, t, "2834"), _h(5, t, "3674")], date(2030, 1, 10))


def test_carry_forward_over_headers_without_sic():
    hs = [
        _h(1, _et(2030, 1, 7, 9, 0), "2834"),
        _h(2, _et(2030, 1, 14, 9, 0), None),
        _h(3, _et(2030, 1, 21, 9, 0), ""),
        _h(4, _et(2030, 1, 22, 9, 0), "   "),
    ]
    r = _one(hs, date(2030, 1, 28))
    assert r.eligible and r.sic == "2834" and r.source_accession == hs[0].accession


def test_other_cik_block_sic_ignored():
    # SIC printed in another company's block (e.g. SUBJECT COMPANY) does not count for this CIK
    hs = [_h(1, _et(2030, 1, 7, 9, 0), "2834"), _h(2, _et(2030, 1, 14, 9, 0), "6798", block="0000000099")]
    assert _one(hs, date(2030, 1, 22)).sic == "2834"
    only_other = [_h(2, _et(2030, 1, 14, 9, 0), "6798", block="0000000099")]
    assert _one(only_other, date(2030, 1, 22)).reason is IneligibleReason.NO_SIC_HEADER_BEFORE


def test_other_cik_records_ignored():
    hs = [_h(1, _et(2030, 1, 7, 9, 0), "2834", cik="0000000002")]
    assert _one(hs, date(2030, 1, 22)).reason is IneligibleReason.CIK_NOT_IN_HEADERS


def test_reasons_in_order():
    assert _one([], date(2030, 1, 22), links=()).reason is IneligibleReason.NO_CIK_LINK
    assert _one([], date(2030, 1, 22)).reason is IneligibleReason.CIK_NOT_IN_HEADERS
    late = [_h(1, _et(2030, 1, 25, 9, 0), "2834")]
    assert _one(late, date(2030, 1, 22)).reason is IneligibleReason.NO_HEADER_BEFORE
    nosic = [_h(1, _et(2030, 1, 8, 9, 0), None)]
    assert _one(nosic, date(2030, 1, 22)).reason is IneligibleReason.NO_SIC_HEADER_BEFORE


@pytest.mark.parametrize("bad", ["0000", "283", "28A4", "28345"])
def test_invalid_governing_sic_is_ineligible_no_carry_back(bad):
    hs = [_h(1, _et(2030, 1, 7, 9, 0), "2834"), _h(2, _et(2030, 1, 14, 9, 0), bad)]
    r = _one(hs, date(2030, 1, 22))
    assert r.reason is IneligibleReason.INVALID_SIC and r.sic2 is None and r.sic == bad


def test_link_window_exclusive_end_and_overlap():
    links = (CikLink("AAA", CIK, date(2030, 1, 7), date(2030, 1, 21)),)
    hs = [_h(1, _et(2030, 1, 7, 9, 0), "2834")]
    assert _one(hs, date(2030, 1, 18), links).eligible
    assert _one(hs, date(2030, 1, 21), links).reason is IneligibleReason.NO_CIK_LINK
    overlap = (
        CikLink("AAA", CIK, date(2030, 1, 7), date(2030, 1, 21)),
        CikLink("AAA", "0000000002", date(2030, 1, 20), None),
    )
    with pytest.raises(SicGroupError):
        _one(hs, date(2030, 1, 18), overlap)


def test_shared_cik_two_symbols():
    links = [CikLink("AAA", CIK, date(2030, 1, 7), None), CikLink("AAB", CIK, date(2030, 1, 7), None)]
    hs = [_h(1, _et(2030, 1, 7, 9, 0), "4911")]
    res = sg.resolve_sic2_groups(["AAA", "AAB"], links, hs, date(2030, 1, 10), SESS)
    assert sg.group_map(res) == {"AAA": "49", "AAB": "49"}


@pytest.mark.parametrize(
    "sessions, session",
    [
        ([], date(2030, 1, 8)),
        ([date(2030, 1, 8), date(2030, 1, 8)], date(2030, 1, 8)),
        (SESS, HOL),
        (SESS, date(2030, 1, 12)),
    ],
)
def test_bad_calendar_or_non_session_raises(sessions, session):
    with pytest.raises(SicGroupError):
        sg.resolve_sic2_groups(["AAA"], [LINK], [], session, sessions)


def test_same_accession_at_different_times_raises():
    hs = [_h(5, _et(2030, 1, 8, 9, 0), "2834"), _h(5, _et(2030, 1, 9, 9, 0), "2834")]
    with pytest.raises(SicGroupError):
        _one(hs, date(2030, 1, 22))
    # raised even when neither copy would govern on the session asked about
    with pytest.raises(SicGroupError):
        _one(hs, date(2030, 1, 8))


def test_same_accession_under_two_ciks_is_allowed():
    other = "0000000002"
    hs = [_h(5, _et(2030, 1, 8, 9, 0), "2834"), _h(5, _et(2030, 1, 8, 9, 0), "6798", cik=other)]
    assert _one(hs, date(2030, 1, 22)).sic == "2834"


@pytest.mark.parametrize(
    "cal",
    [
        [],
        [date(2030, 1, 8), date(2030, 1, 7)],
        [date(2030, 1, 7), date(2030, 1, 7), date(2030, 1, 8)],
    ],
)
def test_first_session_after_validates_calendar(cal):
    with pytest.raises(SicGroupError):
        sg.first_session_after(date(2030, 1, 7), cal)


def test_aware_datetime_and_bad_accession_raise():
    aware = SicHeader(CIK, "0000000001-30-000001", datetime(2030, 1, 8, 9, 0, tzinfo=UTC), "2834", CIK)
    with pytest.raises(SicGroupError):
        _one([aware], date(2030, 1, 10))
    with pytest.raises(SicGroupError):
        _one([SicHeader(CIK, "1-2-3", _et(2030, 1, 8, 9, 0), "2834", CIK)], date(2030, 1, 10))


# ------------------------------------------------------------------ interval adapter


def _iv(sym, sic, f, t, open_end=False, cik=CIK):
    return SicInterval(sym, cik, sic, f, t, open_end)


def test_interval_inclusive_end_bound():
    ivs = [_iv("AAA", "2834", date(2030, 1, 7), date(2030, 1, 18))]
    assert sg.resolve_from_intervals(["AAA"], ivs, date(2030, 1, 18), SESS)["AAA"].sic2 == "28"
    r = sg.resolve_from_intervals(["AAA"], ivs, date(2030, 1, 21), SESS)["AAA"]
    assert r.reason is IneligibleReason.NO_INTERVAL and r.sic2 is None


def test_interval_open_end_flag_ignores_placeholder_end():
    placeholder = date(2030, 1, 18)
    ivs = [_iv("AAA", "2834", date(2030, 1, 7), placeholder, open_end=True)]
    assert sg.resolve_from_intervals(["AAA"], ivs, date(2030, 2, 25), SESS)["AAA"].sic2 == "28"
    closed = [_iv("AAA", "2834", date(2030, 1, 7), placeholder, open_end=False)]
    assert not sg.resolve_from_intervals(["AAA"], closed, date(2030, 2, 25), SESS)["AAA"].eligible


def test_interval_contiguous_change_and_before_start():
    ivs = [
        _iv("AAA", "2834", date(2030, 1, 7), date(2030, 1, 18)),
        _iv("AAA", "3674", date(2030, 1, 21), date(2030, 1, 21), True),
    ]
    assert sg.resolve_from_intervals(["AAA"], ivs, date(2030, 1, 21), SESS)["AAA"].sic2 == "36"
    late = [_iv("AAA", "2834", date(2030, 1, 21), date(2030, 1, 21), True)]
    assert not sg.resolve_from_intervals(["AAA"], late, date(2030, 1, 18), SESS)["AAA"].eligible


def test_interval_shared_cik_pair():
    ivs = [
        _iv("AAA", "4911", date(2030, 1, 7), date(2030, 1, 7), True),
        _iv("AAB", "4911", date(2030, 1, 7), date(2030, 1, 7), True),
    ]
    res = sg.resolve_from_intervals(["AAA", "AAB"], ivs, date(2030, 1, 10), SESS)
    assert sg.group_map(res) == {"AAA": "49", "AAB": "49"}
    assert res["AAA"].cik == res["AAB"].cik == CIK


def test_interval_overlap_and_inverted_raise():
    with pytest.raises(SicGroupError):
        sg.resolve_from_intervals(
            ["AAA"],
            [
                _iv("AAA", "2834", date(2030, 1, 7), date(2030, 1, 18)),
                _iv("AAA", "3674", date(2030, 1, 18), date(2030, 1, 25)),
            ],
            date(2030, 1, 10),
            SESS,
        )
    with pytest.raises(SicGroupError):
        sg.resolve_from_intervals(
            ["AAA"], [_iv("AAA", "2834", date(2030, 1, 18), date(2030, 1, 7))], date(2030, 1, 10), SESS
        )


def test_interval_invalid_sic():
    r = sg.resolve_from_intervals(
        ["AAA"], [_iv("AAA", "0000", date(2030, 1, 7), date(2030, 1, 7), True)], date(2030, 1, 10), SESS
    )
    assert r["AAA"].reason is IneligibleReason.INVALID_SIC


# ------------------------------------------------------------------ caps integration (fail closed)

# Example limits for tests only, not policy.
EX = pr.ExposureLimits(single_name_cap=0.5, gross_cap=1.0, net_cap=1.0, group_caps={"28": 0.3, "36": 0.3})


def _groups():
    links = [CikLink(s, f"00000000{i:02d}", date(2030, 1, 7), None) for i, s in enumerate(["AAA", "BBB", "CCC"])]
    hs = [
        SicHeader("0000000000", "0000000001-30-000001", _et(2030, 1, 7, 9, 0), "2834", "0000000000"),
        SicHeader("0000000001", "0000000002-30-000001", _et(2030, 1, 7, 9, 0), "2836", "0000000001"),
        # CCC: no SIC-bearing header -> ineligible
        SicHeader("0000000002", "0000000003-30-000001", _et(2030, 1, 7, 9, 0), None, "0000000002"),
    ]
    return sg.group_map(sg.resolve_sic2_groups(["AAA", "BBB", "CCC"], links, hs, date(2030, 1, 10), SESS))


def test_sic2_group_caps_scale_shared_major_group():
    g = _groups()
    assert g == {"AAA": "28", "BBB": "28", "CCC": None}
    res = pr.apply_exposure_limits({"AAA": 0.3, "BBB": 0.3, "CCC": 0.0}, EX, groups=g)
    assert res.weights["AAA"] + res.weights["BBB"] == pytest.approx(0.3)
    assert pr.pre_trade_check(res.weights, EX, groups=g).passed


def test_ineligible_name_with_weight_is_rejected():
    g = _groups()
    chk = pr.pre_trade_check({"AAA": 0.1, "CCC": 0.05}, EX, groups=g)
    assert not chk.passed and "INELIGIBLE_GROUP" in chk.codes
    assert [v.symbol for v in chk.violations if v.code == "INELIGIBLE_GROUP"] == ["CCC"]
    with pytest.raises(pr.RiskInputError):
        pr.apply_exposure_limits({"AAA": 0.1, "CCC": 0.05}, EX, groups=g)


def test_ineligible_name_at_zero_weight_passes():
    assert pr.pre_trade_check({"AAA": 0.1, "CCC": 0.0}, EX, groups=_groups()).passed


def test_report_group_gross_skips_ineligible():
    rep = pr.build_risk_report({"AAA": 0.1, "BBB": 0.1, "CCC": 0.0}, EX, groups=_groups())
    assert rep.group_gross == {"28": pytest.approx(0.2)} and rep.passed
