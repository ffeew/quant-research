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


def test_v10_excluded_name_with_a_link_stops():
    with pytest.raises(sg.ExcludedLinkError):
        sg.resolve_sic2_groups(
            ["DD"],
            [_link("DD", "800")],
            [_hdr("800", 1, date(2015, 1, 5), "2821")],
            date(2017, 1, 3),
            SESSIONS,
            excluded={"DD"},
        )


def test_v10_excluded_name_without_a_link_is_r1():
    _bad(_one("DD", [], [_hdr("800", 1, date(2015, 1, 5), "2821")], date(2017, 1, 3)), R.NO_CIK_LINK)


def test_v10_tyc_alone_excluded_with_a_link_stops():
    # Both names are on the exclusion list; only TYC (synthetic CIK) has a link, so only TYC is named.
    with pytest.raises(sg.ExcludedLinkError) as ei:
        sg.resolve_sic2_groups(
            ["TYC"],
            [_link("TYC", "810")],
            [_hdr("810", 1, date(2015, 3, 2), "3829")],
            date(2017, 1, 3),
            SESSIONS,
            excluded={"DD", "TYC"},
        )
    assert ei.value.symbols == ("TYC",)
    assert "TYC" in str(ei.value) and "DD" not in str(ei.value)


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


# ------------------------------------------------------------------ regression: previously passing vectors

# Outputs of the vector queries above, recorded from the earlier test revision (before header-scope
# classification and the exclusion set): (case, symbol, session, cik, sic, sic2, reason, accession).
SNAPSHOT = [
    ("V1", "AAA", "2016-06-01", "100", "2834", "28", None, "0000000100-15-000001"),
    ("V1", "AAA", "2015-12-31", "100", "2834", "28", None, "0000000100-15-000001"),
    ("V2", "AAA", "2019-01-02", "100", "2834", "28", None, "0000000100-15-000001"),
    ("V2", "AAB", "2019-01-02", "100", "2834", "28", None, "0000000100-15-000001"),
    ("V3V4", "BBB", "2016-06-01", "200", None, None, "R3_NO_HEADER_BEFORE", None),
    ("V3V4", "BBB", "2017-06-01", "200", None, None, "R3_NO_HEADER_BEFORE", None),
    ("V3V4", "BBB", "2017-06-02", "200", "3571", "35", None, "0000000200-17-000002"),
    ("V3V4_unfiltered_eligible", "BBB", "2017-06-02", "200", "3571", "35", None, "0000000200-17-000002"),
    ("V5", "CCC", "2017-01-03", "300", None, None, "R4_NO_SIC_HEADER_BEFORE", None),
    ("V6", "DDD", "2017-01-03", "400", "0000", None, "R5_INVALID_SIC", "0000000400-16-000001"),
    ("V6", "DDD", "2018-01-02", "400", "0000", None, "R5_INVALID_SIC", "0000000400-16-000001"),
    ("V6", "DDD", "2018-01-03", "400", "3572", "35", None, "0000000400-18-000002"),
    ("V7", "EEE", "2017-01-03", "500", None, None, "R2_CIK_NOT_IN_HEADERS", None),
    ("V7", "FFF", "2017-01-03", None, None, None, "R1_NO_CIK_LINK", None),
    ("V8", "OLD", "2018-06-29", "600", "1311", "13", None, "0000000600-14-000001"),
    ("V8", "NEW", "2018-06-29", None, None, None, "R1_NO_CIK_LINK", None),
    ("V8", "OLD", "2018-07-02", None, None, None, "R1_NO_CIK_LINK", None),
    ("V8", "NEW", "2018-07-02", "600", "1311", "13", None, "0000000600-14-000001"),
    ("rename_new_cik", "NEW", "2018-07-02", "610", None, None, "R3_NO_HEADER_BEFORE", None),
    ("rename_new_cik", "NEW", "2018-07-03", "610", "2911", "29", None, "0000000610-18-000001"),
    ("rename_new_cik_no_headers", "NEW", "2018-07-03", "610", None, None, "R2_CIK_NOT_IN_HEADERS", None),
    ("V9", "TIE", "2016-05-06", "700", "6022", "60", None, "0000000700-16-000002"),
    ("V10_no_link", "DD", "2017-01-03", None, None, None, "R1_NO_CIK_LINK", None),
    ("iv_V1V2", "AAA", "2016-06-01", "100", "2834", "28", None, None),
    ("iv_V1V2", "AAB", "2016-06-01", "100", "2834", "28", None, None),
    ("iv_V1V2", "AAA", "2019-01-02", "100", "2834", "28", None, None),
    ("iv_V1V2", "AAB", "2019-01-02", "100", "2834", "28", None, None),
    ("iv_V4V6", "BBB", "2017-06-01", None, None, None, "NO_INTERVAL", None),
    ("iv_V4V6", "DDD", "2017-06-01", None, None, None, "NO_INTERVAL", None),
    ("iv_V4V6", "BBB", "2017-06-02", "200", "3571", "35", None, None),
    ("iv_V4V6", "DDD", "2017-06-02", None, None, None, "NO_INTERVAL", None),
    ("iv_V4V6", "BBB", "2018-01-02", "200", "3571", "35", None, None),
    ("iv_V4V6", "DDD", "2018-01-02", None, None, None, "NO_INTERVAL", None),
    ("iv_V4V6", "BBB", "2018-01-03", "200", "3571", "35", None, None),
    ("iv_V4V6", "DDD", "2018-01-03", "400", "3572", "35", None, None),
    ("iv_V6", "DDD", "2017-01-03", "400", "0000", None, "R5_INVALID_SIC", None),
    ("iv_V6", "DDD", "2018-01-02", "400", "0000", None, "R5_INVALID_SIC", None),
    ("iv_V6", "DDD", "2018-01-03", "400", "3572", "35", None, None),
    ("iv_V8", "OLD", "2018-06-29", "600", "1311", "13", None, None),
    ("iv_V8", "NEW", "2018-06-29", None, None, None, "NO_INTERVAL", None),
    ("iv_V8", "OLD", "2018-07-02", None, None, None, "NO_INTERVAL", None),
    ("iv_V8", "NEW", "2018-07-02", "600", "1311", "13", None, None),
    ("iv_V9", "TIE", "2016-05-06", "700", "6022", "60", None, None),
]


def _snapshot_now() -> list[tuple[str, str, str, str | None, str | None, str | None, str | None, str | None]]:
    def hdr_cases():
        H2 = [*H100, _hdr("100", 2, date(2018, 3, 5), None)]
        L600b = [_link("OLD", "600", FIRST, date(2018, 7, 2)), _link("NEW", "610", date(2018, 7, 2))]
        H610 = [*H600, _hdr("610", 1, date(2018, 7, 2), "2911")]
        at = time(16, 0, 0)
        H700 = [_hdr("700", 1, date(2016, 5, 5), "6798", at=at), _hdr("700", 2, date(2016, 5, 5), "6022", at=at)]
        return {
            "V1": (["AAA"], [_link("AAA", "100")], H100, [date(2016, 6, 1), FIRST]),
            "V2": (["AAA", "AAB"], [_link("AAA", "100"), _link("AAB", "100")], H2, [date(2019, 1, 2)]),
            "V3V4": (["BBB"], [_link("BBB", "200")], H200, [date(2016, 6, 1), date(2017, 6, 1), date(2017, 6, 2)]),
            "V3V4_unfiltered_eligible": (["BBB"], [_link("BBB", "200")], H200_RAW, [date(2017, 6, 2)]),
            "V5": (["CCC"], [_link("CCC", "300")], [_hdr("300", 1, date(2016, 3, 1), None)], [date(2017, 1, 3)]),
            "V6": (
                ["DDD"],
                [_link("DDD", "400")],
                [_hdr("400", 1, date(2016, 2, 1), "0000"), _hdr("400", 2, date(2018, 1, 2), "3572")],
                [date(2017, 1, 3), date(2018, 1, 2), date(2018, 1, 3)],
            ),
            "V7": (["EEE", "FFF"], [_link("EEE", "500")], H500, [date(2017, 1, 3)]),
            "V8": (["OLD", "NEW"], L600, H600, [date(2018, 6, 29), date(2018, 7, 2)]),
            "rename_new_cik": (["NEW"], L600b, H610, [date(2018, 7, 2), date(2018, 7, 3)]),
            "rename_new_cik_no_headers": (["NEW"], L600b, H600, [date(2018, 7, 3)]),
            "V9": (["TIE"], [_link("TIE", "700")], H700, [date(2016, 5, 6)]),
            "V10_no_link": (["DD"], [], [_hdr("800", 1, date(2015, 1, 5), "2821")], [date(2017, 1, 3)]),
        }

    out = []
    for k, (syms, links, hs, ts) in hdr_cases().items():
        for t in ts:
            r = sg.resolve_sic2_groups(syms, links, hs, t, SESSIONS)
            for sym in syms:
                x = r[sym]
                out.append(
                    (
                        k,
                        sym,
                        t.isoformat(),
                        x.cik,
                        x.sic,
                        x.sic2,
                        x.reason.value if x.reason else None,
                        x.source_accession,
                    )
                )
    iv = _iv
    icases = {
        "iv_V1V2": (
            [iv("AAA", "100", "2834", FIRST, None), iv("AAB", "100", "2834", FIRST, None)],
            ["AAA", "AAB"],
            [date(2016, 6, 1), date(2019, 1, 2)],
        ),
        "iv_V4V6": (
            [iv("BBB", "200", "3571", date(2017, 6, 2), None), iv("DDD", "400", "3572", date(2018, 1, 3), None)],
            ["BBB", "DDD"],
            [date(2017, 6, 1), date(2017, 6, 2), date(2018, 1, 2), date(2018, 1, 3)],
        ),
        "iv_V6": (
            [
                iv("DDD", "400", "0000", date(2016, 2, 2), date(2018, 1, 2)),
                iv("DDD", "400", "3572", date(2018, 1, 3), None),
            ],
            ["DDD"],
            [date(2017, 1, 3), date(2018, 1, 2), date(2018, 1, 3)],
        ),
        "iv_V8": (
            [iv("OLD", "600", "1311", FIRST, date(2018, 6, 29)), iv("NEW", "600", "1311", date(2018, 7, 2), None)],
            ["OLD", "NEW"],
            [date(2018, 6, 29), date(2018, 7, 2)],
        ),
        "iv_V9": ([iv("TIE", "700", "6022", date(2016, 5, 6), None)], ["TIE"], [date(2016, 5, 6)]),
    }
    for k, (ivs, syms, ts) in icases.items():
        for t in ts:
            r = sg.resolve_from_intervals(syms, ivs, t, SESSIONS)
            for sym in syms:
                x = r[sym]
                out.append(
                    (
                        k,
                        sym,
                        t.isoformat(),
                        x.cik,
                        x.sic,
                        x.sic2,
                        x.reason.value if x.reason else None,
                        x.source_accession,
                    )
                )
    return out


def test_previously_passing_vectors_unchanged():
    assert _snapshot_now() == SNAPSHOT


def test_previously_passing_overlap_stop_unchanged():
    links = [_link("GGG", "600", FIRST, date(2018, 7, 3)), _link("GGG", "610", date(2018, 7, 2))]
    with pytest.raises(sg.SicGroupError, match="overlapping"):
        _one("GGG", links, H600, date(2018, 7, 2))


# ------------------------------------------------------------------ exclusion set


def test_exclusion_empty_means_no_check():
    links = [_link("DD", "800")]
    hs = [_hdr("800", 1, date(2015, 1, 5), "2821")]
    a = sg.resolve_sic2_groups(["DD"], links, hs, date(2017, 1, 3), SESSIONS)
    b = sg.resolve_sic2_groups(["DD"], links, hs, date(2017, 1, 3), SESSIONS, excluded=frozenset())
    assert a == b and a["DD"].sic == "2821"


def test_exclusion_active_links_raise_listing_every_offender():
    links = [_link("DD", "800"), _link("TYC", "810"), _link("AAA", "100"), _link("ZZZ", "820", FIRST, date(2016, 1, 4))]
    with pytest.raises(sg.ExcludedLinkError) as ei:
        sg.resolve_sic2_groups(["AAA"], links, H100, date(2017, 1, 3), SESSIONS, excluded={"TYC", "DD", "ZZZ"})
    assert ei.value.symbols == ("DD", "TYC")  # ZZZ's link ended before the session
    assert "DD" in str(ei.value) and "TYC" in str(ei.value)


def test_exclusion_without_link_is_fine():
    out = sg.resolve_sic2_groups(
        ["AAA", "DD"], [_link("AAA", "100")], H100, date(2017, 1, 3), SESSIONS, excluded={"DD"}
    )
    _ok(out["AAA"], "2834")
    _bad(out["DD"], R.NO_CIK_LINK)


def test_exclusion_rejects_bare_string():
    with pytest.raises(sg.SicGroupError, match="bare str"):
        sg.resolve_sic2_groups(["AAA"], [_link("AAA", "100")], H100, date(2017, 1, 3), SESSIONS, excluded="DD")


def test_exclusion_interval_path():
    ivs = [_iv("DD", "800", "2821", FIRST, date(2016, 12, 30)), _iv("AAA", "100", "2834", FIRST, None)]
    out = sg.resolve_from_intervals(["AAA", "DD"], ivs, date(2017, 1, 3), SESSIONS, excluded={"DD"})
    _ok(out["AAA"], "2834")
    _bad(out["DD"], R.NO_INTERVAL)
    with pytest.raises(sg.ExcludedLinkError) as ei:
        sg.resolve_from_intervals(["AAA"], ivs, date(2016, 12, 30), SESSIONS, excluded={"DD", "AAA"})
    assert ei.value.symbols == ("AAA", "DD")
    assert sg.resolve_from_intervals(["DD"], ivs, date(2016, 12, 30), SESSIONS)["DD"].sic == "2821"
