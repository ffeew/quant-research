import datetime as dt

from quant_research.features.fiscal_quarters import Row, map_fiscal_year, month_end, quarter_end

D = dt.date


def _rows(fy_end_month: int, year: int, lag_days: int = 25) -> list[Row]:
    return [
        dict(f=quarter_end(year, fy_end_month, n), r=quarter_end(year, fy_end_month, n) + dt.timedelta(lag_days))
        for n in range(1, 5)
    ]


def test_month_and_quarter_end() -> None:
    assert month_end(2020, 2) == D(2020, 2, 29)
    assert quarter_end(2020, 12, 1) == D(2020, 3, 31)
    assert quarter_end(2020, 9, 1) == D(2019, 12, 31)  # FY ending Sep 2020 starts Oct 2019
    assert quarter_end(2020, 9, 4) == D(2020, 9, 30)


def test_interior_year_maps_all_four() -> None:
    out, why = map_fiscal_year(_rows(6, 2017), 6, 2017, D(2014, 1, 1), D(2020, 12, 31))
    assert why == "" and [r["f"] for n in range(1, 5) if (r := out[n]) is not None] == [
        quarter_end(2017, 6, n) for n in range(1, 5)
    ]


def test_interior_year_with_missing_row_maps_nothing() -> None:
    rows = _rows(12, 2016)[:3]
    out, why = map_fiscal_year(rows, 12, 2016, D(2014, 1, 1), D(2020, 12, 31))
    assert why == "closed_rows_3" and all(v is None for v in out.values())


def test_edge_year_bins_per_quarter_and_checks_lag() -> None:
    rows = _rows(12, 2020)
    rows[3] = dict(rows[3], r=rows[3]["f"] + dt.timedelta(150))  # reported too late
    out, why = map_fiscal_year(rows, 12, 2020, D(2014, 1, 1), D(2020, 12, 31))
    assert out[1] is not None and out[4] is None and "Q4_lag" in why
