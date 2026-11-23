"""Shared synthetic vectors V1-V10 for the point-in-time SIC-2 rule, plus shared-CIK and rename rules.

All data are synthetic literals. Sessions are Monday-Friday from 2015-12-31 to 2021-12-31 (a
synthetic calendar; holidays are not removed). Reason codes: R1 no CIK link, R2 CIK has no header
rows, R3 no header before t, R4 no SIC-bearing header before t, R5 invalid SIC.

Header scope is the caller's job: a filing whose header blocks do not match the target CIK is
dropped by the caller before it reaches ``resolve_sic2_groups``. The main vector tests follow that
convention; the ``*_unfiltered`` tests pass such rows through to document what the module does
when the caller does not drop them.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from quant_research.strategies.portfolio_construction import sic_groups as sg

R = sg.IneligibleReason


def _sessions() -> list[date]:
    d, end, out = date(2015, 12, 31), date(2021, 12, 31), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = _sessions()
FIRST = SESSIONS[0]


def _et(d: date, t: time = time(16, 30)) -> datetime:
    return datetime.combine(d, t)


def _hdr(
    cik: str, seq: int, d: date, sic: str | None, *, block: str | None = "own", at: time = time(16, 30)
) -> sg.SicHeader:
    yy = f"{d.year % 100:02d}"
    return sg.SicHeader(
        cik=cik,
        accession=f"{int(cik):010d}-{yy}-{seq:06d}",
        acceptance_et=_et(d, at),
        sic=sic,
        sic_block_cik=cik if block == "own" else block,
    )


def _link(sym: str, cik: str, start: date = FIRST, end: date | None = None) -> sg.CikLink:
    return sg.CikLink(sym, cik, start, end)


def _one(sym: str, links, headers, t: date) -> sg.SicResolution:
    return sg.resolve_sic2_groups([sym], links, headers, t, SESSIONS)[sym]


def _ok(r: sg.SicResolution, sic: str) -> None:
    assert r.reason is None and r.sic == sic and r.sic2 == sic[:2], r


def _bad(r: sg.SicResolution, reason: sg.IneligibleReason) -> None:
    assert r.sic2 is None and r.reason is reason, r


# ------------------------------------------------------------------ V1, V2 (one CIK, share classes)

H100 = [_hdr("100", 1, date(2015, 6, 1), "2834")]


def test_v1_header_before_calendar_valid_from_first_session_after():
    _ok(_one("AAA", [_link("AAA", "100")], H100, date(2016, 6, 1)), "2834")
    _ok(_one("AAA", [_link("AAA", "100")], H100, FIRST), "2834")


def test_v2_share_classes_and_carry_forward_over_no_sic_header():
    headers = [*H100, _hdr("100", 2, date(2018, 3, 5), None)]
    links = [_link("AAA", "100"), _link("AAB", "100")]
    out = sg.resolve_sic2_groups(["AAA", "AAB"], links, headers, date(2019, 1, 2), SESSIONS)
    _ok(out["AAB"], "2834")
    _ok(out["AAA"], "2834")
    assert out["AAA"].source_accession == out["AAB"].source_accession == H100[0].accession


# ------------------------------------------------------------------ V3, V4 (other company's block)

H200_RAW = [
    _hdr("200", 1, date(2016, 1, 5), "9999", block="9000200"),  # SIC printed in another company's block
    _hdr("200", 2, date(2017, 6, 1), "3571"),
]
H200 = [h for h in H200_RAW if h.sic_block_cik == h.cik]  # caller drops non-matching filings


def test_v3_other_company_block_never_governs():
    _bad(_one("BBB", [_link("BBB", "200")], H200, date(2016, 6, 1)), R.NO_HEADER_BEFORE)


def test_v4_strictly_before_t():
    _bad(_one("BBB", [_link("BBB", "200")], H200, date(2017, 6, 1)), R.NO_HEADER_BEFORE)
    _ok(_one("BBB", [_link("BBB", "200")], H200, date(2017, 6, 2)), "3571")


def test_v3_v4_unfiltered_other_block_row_is_not_sic_bearing():
    """Passed through unfiltered, the other-block row never governs (same eligibility, same 3571)."""
    r3 = _one("BBB", [_link("BBB", "200")], H200_RAW, date(2016, 6, 1))
    assert r3.sic2 is None and r3.sic is None
    _ok(_one("BBB", [_link("BBB", "200")], H200_RAW, date(2017, 6, 2)), "3571")


@pytest.mark.xfail(
    strict=True,
    reason="unfiltered other-block row counts as a header without SIC, so the reason is R4, not R3",
)
def test_v3_unfiltered_reason_code():
    _bad(_one("BBB", [_link("BBB", "200")], H200_RAW, date(2016, 6, 1)), R.NO_HEADER_BEFORE)


# ------------------------------------------------------------------ V5, V6


def test_v5_no_sic_bearing_header():
    headers = [_hdr("300", 1, date(2016, 3, 1), None)]
    _bad(_one("CCC", [_link("CCC", "300")], headers, date(2017, 1, 3)), R.NO_SIC_HEADER_BEFORE)


def test_v6_invalid_sic_no_carry_back():
    headers = [_hdr("400", 1, date(2016, 2, 1), "0000"), _hdr("400", 2, date(2018, 1, 2), "3572")]
    links = [_link("DDD", "400")]
    _bad(_one("DDD", links, headers, date(2017, 1, 3)), R.INVALID_SIC)
    _bad(_one("DDD", links, headers, date(2018, 1, 2)), R.INVALID_SIC)
    _ok(_one("DDD", links, headers, date(2018, 1, 3)), "3572")


# ------------------------------------------------------------------ V7

H500_RAW = [
    _hdr("500", 1, date(2016, 4, 1), "2000", block="9000500"),
    _hdr("500", 2, date(2016, 9, 1), "2000", block="9000501"),
]
H500 = [h for h in H500_RAW if h.sic_block_cik == h.cik]  # all dropped by the caller


def test_v7_cik_absent_and_no_link():
    links = [_link("EEE", "500")]
    out = sg.resolve_sic2_groups(["EEE", "FFF"], links, H500, date(2017, 1, 3), SESSIONS)
    _bad(out["EEE"], R.CIK_NOT_IN_HEADERS)
    _bad(out["FFF"], R.NO_CIK_LINK)


@pytest.mark.xfail(
    strict=True,
    reason="unfiltered other-block rows make the CIK present without SIC, so the reason is R4, not R2",
)
def test_v7_unfiltered_reason_code():
    _bad(_one("EEE", [_link("EEE", "500")], H500_RAW, date(2017, 1, 3)), R.CIK_NOT_IN_HEADERS)


# ------------------------------------------------------------------ V8 (rename: own link window only)

H600 = [_hdr("600", 1, date(2014, 3, 3), "1311")]
L600 = [_link("OLD", "600", FIRST, date(2018, 7, 2)), _link("NEW", "600", date(2018, 7, 2))]


def test_v8_rename_own_link_window_only():
    _ok(_one("OLD", L600, H600, date(2018, 6, 29)), "1311")
    _bad(_one("OLD", L600, H600, date(2018, 7, 2)), R.NO_CIK_LINK)
    _ok(_one("NEW", L600, H600, date(2018, 7, 2)), "1311")
    _bad(_one("NEW", L600, H600, date(2018, 6, 29)), R.NO_CIK_LINK)


def test_rename_to_new_cik_carries_nothing_across_ciks():
    links = [_link("OLD", "600", FIRST, date(2018, 7, 2)), _link("NEW", "610", date(2018, 7, 2))]
    _bad(_one("NEW", links, H600, date(2018, 7, 3)), R.CIK_NOT_IN_HEADERS)
    headers = [*H600, _hdr("610", 1, date(2018, 7, 2), "2911")]
    _bad(_one("NEW", links, headers, date(2018, 7, 2)), R.NO_HEADER_BEFORE)
    _ok(_one("NEW", links, headers, date(2018, 7, 3)), "2911")


def test_overlapping_links_for_one_symbol_stop():
    links = [_link("GGG", "600", FIRST, date(2018, 7, 3)), _link("GGG", "610", date(2018, 7, 2))]
    with pytest.raises(sg.SicGroupError, match="overlapping"):
        _one("GGG", links, H600, date(2018, 7, 2))


# ------------------------------------------------------------------ V9 (tie on acceptance datetime)


def test_v9_tie_larger_accession_wins():
    at = time(16, 0, 0)
    headers = [_hdr("700", 1, date(2016, 5, 5), "6798", at=at), _hdr("700", 2, date(2016, 5, 5), "6022", at=at)]
    _ok(_one("TIE", [_link("TIE", "700")], headers, date(2016, 5, 6)), "6022")
    rev = list(reversed(headers))
    _ok(_one("TIE", [_link("TIE", "700")], rev, date(2016, 5, 6)), "6022")


# ------------------------------------------------------------------ V10 (excluded name with a link)


@pytest.mark.xfail(
    strict=True,
    reason="no caller exclusion list in this module: a link for a name that must stay unlinked is not refused",
)
def test_v10_excluded_name_with_a_link_stops():
    with pytest.raises(sg.SicGroupError):
        _one("DD", [_link("DD", "800")], [_hdr("800", 1, date(2015, 1, 5), "2821")], date(2017, 1, 3))


def test_v10_excluded_name_without_a_link_is_r1():
    _bad(_one("DD", [], [_hdr("800", 1, date(2015, 1, 5), "2821")], date(2017, 1, 3)), R.NO_CIK_LINK)


# ------------------------------------------------------------------ same vectors through the interval adapter


def _iv(sym: str, cik: str, sic: str, frm: date, to: date | None) -> sg.SicInterval:
    return sg.SicInterval(sym, cik, sic, frm, to or date(2021, 12, 31), to is None)


def _iv_one(sym: str, ivs, t: date) -> sg.SicResolution:
    return sg.resolve_from_intervals([sym], ivs, t, SESSIONS)[sym]


def test_intervals_v1_v2_share_classes():
    ivs = [_iv("AAA", "100", "2834", FIRST, None), _iv("AAB", "100", "2834", FIRST, None)]
    _ok(_iv_one("AAA", ivs, date(2016, 6, 1)), "2834")
    _ok(_iv_one("AAB", ivs, date(2019, 1, 2)), "2834")


def test_intervals_v4_v6_start_first_session_after_acceptance():
    ivs = [_iv("BBB", "200", "3571", date(2017, 6, 2), None), _iv("DDD", "400", "3572", date(2018, 1, 3), None)]
    _bad(_iv_one("BBB", ivs, date(2017, 6, 1)), R.NO_INTERVAL)
    _ok(_iv_one("BBB", ivs, date(2017, 6, 2)), "3571")
    _bad(_iv_one("DDD", ivs, date(2018, 1, 2)), R.NO_INTERVAL)
    _ok(_iv_one("DDD", ivs, date(2018, 1, 3)), "3572")


def test_intervals_v6_invalid_code_row_is_ineligible():
    ivs = [
        _iv("DDD", "400", "0000", date(2016, 2, 2), date(2018, 1, 2)),
        _iv("DDD", "400", "3572", date(2018, 1, 3), None),
    ]
    _bad(_iv_one("DDD", ivs, date(2017, 1, 3)), R.INVALID_SIC)
    _bad(_iv_one("DDD", ivs, date(2018, 1, 2)), R.INVALID_SIC)
    _ok(_iv_one("DDD", ivs, date(2018, 1, 3)), "3572")


def test_intervals_v8_rename_inclusive_end():
    ivs = [_iv("OLD", "600", "1311", FIRST, date(2018, 6, 29)), _iv("NEW", "600", "1311", date(2018, 7, 2), None)]
    _ok(_iv_one("OLD", ivs, date(2018, 6, 29)), "1311")
    _bad(_iv_one("OLD", ivs, date(2018, 7, 2)), R.NO_INTERVAL)
    _ok(_iv_one("NEW", ivs, date(2018, 7, 2)), "1311")


def test_intervals_v9_tie_winner():
    _ok(_iv_one("TIE", [_iv("TIE", "700", "6022", date(2016, 5, 6), None)], date(2016, 5, 6)), "6022")
