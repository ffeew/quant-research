"""Out-of-scope header records: dropped count, exact-string CIK compare, duplicate accessions.

All data are synthetic literals.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from quant_research.strategies.portfolio_construction import sic_groups as sg

R = sg.IneligibleReason
SESSIONS = [
    date(2020, 1, 1) + timedelta(days=i) for i in range(400) if (date(2020, 1, 1) + timedelta(days=i)).weekday() < 5
]
T = date(2020, 6, 1)  # a session


def _h(cik: str, n: int, sic: str | None, block: str | None, cik_for_acc: str = "0000000100") -> sg.SicHeader:
    return sg.SicHeader(cik, f"{cik_for_acc}-20-{n:06d}", datetime.combine(date(2020, 2, 3), time(10, 0)), sic, block)


def _link(sym: str, cik: str) -> sg.CikLink:
    return sg.CikLink(sym, cik, SESSIONS[0], None)


def _report(headers, links=None, symbols=("AAA",)):
    links = [_link("AAA", "100")] if links is None else links
    return sg.resolve_sic2_groups_with_report(symbols, links, headers, T, SESSIONS)


def test_dropped_count_returned_with_identities():
    hs = [
        _h("100", 1, "2834", "100"),
        _h("100", 2, "6798", "999"),  # other company's block: out of scope
        _h("100", 3, "3571", "888"),  # out of scope
        _h("200", 1, "2000", "777", cik_for_acc="0000000200"),  # out of scope, other CIK
        _h("100", 4, None, None),  # block unset: in scope (no SIC read)
    ]
    rep = _report(hs)
    assert rep.dropped_count == 3
    assert rep.dropped_out_of_scope == (
        ("100", "0000000100-20-000002"),
        ("100", "0000000100-20-000003"),
        ("200", "0000000200-20-000001"),
    )
    assert rep.resolutions["AAA"].sic == "2834"  # eligible result unchanged by the dropped rows
    assert sg.resolve_sic2_groups(["AAA"], [_link("AAA", "100")], hs, T, SESSIONS) == rep.resolutions


def test_dropped_count_zero_when_all_in_scope():
    rep = _report([_h("100", 1, "2834", "100")])
    assert rep.dropped_count == 0 and rep.dropped_out_of_scope == ()


def test_only_out_of_scope_rows_is_r2_and_counted():
    rep = _report([_h("100", 1, "6798", "999")])
    assert rep.dropped_count == 1
    assert rep.resolutions["AAA"].reason is R.CIK_NOT_IN_HEADERS


def test_cik_compare_is_exact_string_padded_vs_unpadded_do_not_match():
    # header block padded, record CIK unpadded: different strings, so out of scope
    rep = _report([_h("100", 1, "2834", "0000000100")])
    assert rep.dropped_count == 1 and rep.resolutions["AAA"].reason is R.CIK_NOT_IN_HEADERS
    # and the reverse
    rep = _report([_h("0000000100", 1, "2834", "100")], links=[_link("AAA", "0000000100")])
    assert rep.dropped_count == 1 and rep.resolutions["AAA"].reason is R.CIK_NOT_IN_HEADERS
    # identical padded strings match
    rep = _report([_h("0000000100", 1, "2834", "0000000100")], links=[_link("AAA", "0000000100")])
    assert rep.dropped_count == 0 and rep.resolutions["AAA"].sic == "2834"


def test_link_cik_padded_vs_header_cik_unpadded_do_not_match():
    rep = _report([_h("100", 1, "2834", "100")], links=[_link("AAA", "0000000100")])
    assert rep.resolutions["AAA"].reason is R.CIK_NOT_IN_HEADERS and rep.dropped_count == 0


def test_duplicate_out_of_scope_accession_is_refused():
    dup = [_h("100", 7, "6798", "999"), _h("100", 7, "3571", "888")]  # same (cik, accession), both out of scope
    with pytest.raises(sg.SicGroupError, match="appears more than once"):
        _report(dup)
    # same accession under different CIKs is not a duplicate
    ok = [_h("100", 7, "6798", "999"), _h("200", 7, "3571", "888")]
    assert _report(ok).dropped_count == 2


def test_duplicate_accession_in_scope_and_out_of_scope_is_refused():
    with pytest.raises(sg.SicGroupError, match="appears more than once"):
        _report([_h("100", 7, "2834", "100"), _h("100", 7, "6798", "999")])
