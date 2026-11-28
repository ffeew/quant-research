"""Construction inputs (universe file, SIC-2 map, ETF sleeve) on synthetic data only; no data store."""

from __future__ import annotations

import argparse
import ast
import hashlib
import pathlib

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest

from quant_research.strategies.portfolio_construction import construct_inputs as ci
from quant_research.strategies.portfolio_construction import sic_groups as sg
from quant_research.strategies.portfolio_construction.research import riskmodels_wf as rw

PKG = pathlib.Path(ci.__file__).parent
CONSTRUCT_SRC = (PKG / "construct.py").read_text()

MAP_HEADER = "rebalance_date,symbol,sic2,reason\n"


def _map(*rows: str) -> str:
    return MAP_HEADER + "".join(r + "\n" for r in rows)


# ------------------------------------------------------------------ universe file


def test_universe_parse_comments_blanks_order():
    text = "# synthetic universe\nAAA\n\n  BBB  \nCC.B\n# end\nXLK\n"
    assert ci.parse_universe(text) == ("AAA", "BBB", "CC.B", "XLK")


def test_universe_reports_every_problem():
    with pytest.raises(ci.ConstructInputError) as ei:
        ci.parse_universe("AAA\nbad\nAAA\nBTC/USD\n")
    probs = ei.value.problems
    assert len(probs) == 3
    assert (
        any("'bad'" in p for p in probs) and any("duplicate" in p for p in probs) and any("BTC/USD" in p for p in probs)
    )


def test_universe_empty_refused():
    with pytest.raises(ci.ConstructInputError, match="no symbols"):
        ci.parse_universe("# only a comment\n\n")


def test_universe_file_required_and_read(tmp_path):
    with pytest.raises(ci.ConstructInputError, match="cannot read"):
        ci.read_universe_file(str(tmp_path / "missing.txt"))
    f = tmp_path / "u.txt"
    f.write_text("AAA\nBBB\n")
    u = ci.read_universe_file(str(f))
    assert u.symbols == ("AAA", "BBB") and len(u.sha256) == 64


def test_cli_requires_universe_and_sic2_map():
    ap = argparse.ArgumentParser()
    ci.add_construct_input_args(ap)
    with pytest.raises(SystemExit):
        ap.parse_args([])
    with pytest.raises(SystemExit):
        ap.parse_args(["--sic2_map", "m.csv"])
    with pytest.raises(SystemExit):
        ap.parse_args(["--universe", "u.txt"])
    with pytest.raises(SystemExit):
        ap.parse_args(["--universe", "u.txt", "--sic2_map", "m.csv"])  # --sector_etf_gross is required
    a = ap.parse_args(["--universe", "u.txt", "--sic2_map", "m.csv", "--sector_etf_gross", "0.10"])
    assert (a.etf_max_pos, a.etf_sleeve_gross, a.etf_sleeve_net) == (0.095, 0.20, 0.10)
    assert a.sector_etf_gross == 0.10


def test_universe_file_utf8_bom_stripped(tmp_path):
    f = tmp_path / "u.txt"
    raw = b"\xef\xbb\xbfAAA\nBBB\n"
    f.write_bytes(raw)
    u = ci.read_universe_file(str(f))
    assert u.symbols == ("AAA", "BBB")
    assert u.sha256 == hashlib.sha256(raw).hexdigest()  # hash is of the file bytes as read
    with pytest.raises(ci.ConstructInputError, match="invalid symbol"):
        ci.parse_universe("\ufeffAAA\n")  # only the file reader strips it


# ------------------------------------------------------------------ SIC-2 map


def test_sic2_map_selects_asof_rows_blank_is_ineligible():
    text = _map(
        "2021-06-01,AAA,28,",
        "2021-06-02,AAA,36,",
        "2021-06-02,BBB,,NO_INTERVAL",
        "2021-06-02,CCC,28,",
    )
    groups, reasons = ci.parse_sic2_map(text, "2021-06-02")
    assert groups == {"AAA": "36", "BBB": None, "CCC": "28"}
    assert reasons == {"BBB": "NO_INTERVAL"}


def test_sic2_map_column_order_free_but_exact():
    groups, _ = ci.parse_sic2_map("symbol,sic2,reason,rebalance_date\nAAA,13,,2021-06-02\n", "2021-06-02")
    assert groups == {"AAA": "13"}
    with pytest.raises(ci.ConstructInputError, match="header"):
        ci.parse_sic2_map("rebalance_date,symbol,sic2\n2021-06-02,AAA,13\n", "2021-06-02")
    with pytest.raises(ci.ConstructInputError, match="header"):
        ci.parse_sic2_map("rebalance_date,symbol,sic2,reason,extra\n", "2021-06-02")


def test_sic2_map_refusals():
    with pytest.raises(ci.ConstructInputError, match="no rows for the as-of session"):
        ci.parse_sic2_map(_map("2021-06-01,AAA,28,"), "2021-06-02")
    with pytest.raises(ci.ConstructInputError) as ei:
        ci.parse_sic2_map(_map("2021-06-02,AAA,28,", "2021-06-02,AAA,36,", "2021-06-02,BBB,2,"), "2021-06-02")
    assert len(ei.value.problems) == 2
    with pytest.raises(ci.ConstructInputError, match="ISO date"):
        ci.parse_sic2_map(_map("2021-06-02,AAA,28,"), "02/06/2021")


def test_read_sic2_map_file(tmp_path):
    f = tmp_path / "m.csv"
    f.write_text(_map("2021-06-02,AAA,28,"))
    snap = ci.read_sic2_map(str(f), "2021-06-02")
    assert snap.groups == {"AAA": "28"} and snap.asof == "2021-06-02" and len(snap.sha256) == 64


# ------------------------------------------------------------------ groups, ETF sleeve, hedge

UNIV = ["AAA", "BBB", "CCC", "XLK", "XLE", "SPY"]
GROUPS: dict[str, str | None] = {"AAA": "28", "BBB": "36", "CCC": "28"}


def test_groups_split_singles_etfs_hedge():
    g = ci.construction_groups(UNIV, GROUPS, etfs=ci.DECLARED_ETFS, hedge="SPY")
    assert g.sector_index == {"28": (0, 2), "36": (1,)}
    assert g.etf_index == (3, 4)
    assert g.labels == {
        "AAA": "SIC2:28",
        "BBB": "SIC2:36",
        "CCC": "SIC2:28",
        "XLK": "ETF",
        "XLE": "ETF",
        "SPY": "HEDGE",
    }


def test_hedge_excluded_from_sleeve_even_though_declared_etf():
    assert "SPY" in ci.DECLARED_ETFS
    g = ci.construction_groups(UNIV, GROUPS, etfs=ci.DECLARED_ETFS, hedge="SPY")
    assert UNIV.index("SPY") not in g.etf_index
    assert all(UNIV.index("SPY") not in ix for ix in g.sector_index.values())


def test_ungrouped_single_names_rejected_all_listed():
    univ = ["AAA", "DDD", "XLK", "EEE", "FFF", "SPY"]
    groups = {"AAA": "28", "DDD": None, "FFF": None}
    with pytest.raises(sg.SectorGroupError) as ei:
        ci.construction_groups(univ, groups, etfs=ci.DECLARED_ETFS, hedge="SPY", reasons={"DDD": "NO_INTERVAL"})
    off = dict(ei.value.offenders)
    assert list(off) == ["DDD", "EEE", "FFF"]
    assert "NO_INTERVAL" in off["DDD"] and "missing" in off["EEE"] and "ineligible" in off["FFF"]


def test_undeclared_etf_like_symbol_is_a_single_name():
    with pytest.raises(sg.SectorGroupError) as ei:
        ci.construction_groups(["AAA", "XLG", "SPY"], {"AAA": "28"}, etfs=ci.DECLARED_ETFS, hedge="SPY")
    assert [n for n, _ in ei.value.offenders] == ["XLG"]


def test_no_catch_all_label():
    g = ci.construction_groups(UNIV, GROUPS, etfs=ci.DECLARED_ETFS, hedge="SPY")
    assert set(g.labels.values()) <= {"SIC2:28", "SIC2:36", "ETF", "HEDGE"}
    assert "Other" not in g.labels.values()


def test_etf_caps_validated():
    ci.validate_etf_caps(0.095, 0.20, 0.10)
    with pytest.raises(ci.ConstructInputError) as ei:
        ci.validate_etf_caps(0.0, float("inf"), -0.1)
    assert len(ei.value.problems) == 3


def test_apply_etf_position_cap_only_touches_sleeve():
    cap = np.array([0.095, 0.05, 0.095, 0.095, 0.03, 0.095])
    out = ci.apply_etf_position_cap(cap, (3, 4), 0.04)
    assert out.tolist() == [0.095, 0.05, 0.095, 0.04, 0.03, 0.095]
    assert cap[3] == 0.095  # input unchanged


def test_exposure_by_label():
    rows = [
        dict(symbol="AAA", sector="SIC2:28", target_weight=0.05, target_shares=10),
        dict(symbol="CCC", sector="SIC2:28", target_weight=-0.02, target_shares=-3),
        dict(symbol="BBB", sector="SIC2:36", target_weight=0.0, target_shares=0),
        dict(symbol="XLK", sector="ETF", target_weight=0.06, target_shares=4),
        dict(symbol="XLE", sector="ETF", target_weight=-0.03, target_shares=-2),
        dict(symbol="SPY", sector="HEDGE", target_weight=-0.2, target_shares=-9),
    ]
    secs, etf = ci.exposure_by_label(rows)
    assert secs == {"SIC2:28": [pytest.approx(0.07), pytest.approx(0.03)]}
    assert (etf.gross, etf.net, etf.max_abs) == (pytest.approx(0.09), pytest.approx(0.03), pytest.approx(0.06))
    with pytest.raises(ci.ConstructInputError, match="unknown group label"):
        ci.exposure_by_label([dict(symbol="ZZZ", sector="Other", target_weight=0.01, target_shares=1)])


def test_etf_sleeve_caps_bind_in_optimiser():
    """Same constraint form as construct.py: ETFs want large weights; per-ETF and sleeve caps bind."""
    univ = ["AAA", "BBB", "XLK", "XLE", "XLF", "SPY"]
    groups = {"AAA": "28", "BBB": "36"}
    g = ci.construction_groups(univ, groups, etfs=ci.DECLARED_ETFS, hedge="SPY")
    cap = ci.apply_etf_position_cap(np.full(len(univ), 0.095), g.etf_index, 0.08)
    alpha = np.array([0.001, 0.001, 0.05, 0.04, 0.03, 0.0])
    w = cp.Variable(len(univ))
    cons = [cp.abs(w) <= cap, cp.norm1(w) <= 0.58]
    for ix in g.sector_index.values():
        cons += [cp.norm1(w[list(ix)]) <= 0.20, cp.abs(cp.sum(w[list(ix)])) <= 0.10]
    ix_e = list(g.etf_index)
    cons += [cp.norm1(w[ix_e]) <= 0.20, cp.abs(cp.sum(w[ix_e])) <= 0.10]
    cp.Problem(cp.Maximize(alpha @ w), cons).solve(solver="CLARABEL")
    wv = np.asarray(w.value).ravel()
    sleeve = wv[ix_e]
    assert abs(sleeve).sum() <= 0.20 + 1e-6 and abs(sleeve.sum()) <= 0.10 + 1e-6
    assert np.isclose(sleeve.sum(), 0.10, atol=1e-5)  # net cap binds (unconstrained the sleeve would be 0.24 long)
    assert max(abs(sleeve)) <= 0.08 + 1e-6 and np.isclose(wv[2], 0.08, atol=1e-5)  # per-ETF cap binds
    assert abs(wv[univ.index("SPY")]) < 1e-6  # hedge has no alpha and is outside the sleeve


def test_etf_caps_boundary_value_one_is_accepted_and_above_refused():
    ci.validate_etf_caps(1.0, 1.0, 1.0)  # val = 1.0 is inside (0, 1]
    ci.validate_sector_etf_gross(1.0, 1.0)
    for bad in (1.0000001, 0.0):
        with pytest.raises(ci.ConstructInputError):
            ci.validate_etf_caps(bad, 0.2, 0.1)
        with pytest.raises(ci.ConstructInputError):
            ci.validate_sector_etf_gross(bad, 1.0)
    with pytest.raises(ci.ConstructInputError, match="must not exceed"):
        ci.validate_sector_etf_gross(1.0, 0.999999)


def test_sector_etf_gross_validated():
    ci.validate_sector_etf_gross(0.10, 0.20)
    ci.validate_sector_etf_gross(0.20, 0.20)
    with pytest.raises(ci.ConstructInputError, match="must not exceed etf_sleeve_gross"):
        ci.validate_sector_etf_gross(0.25, 0.20)
    for bad in (0.0, -0.1, 1.5, float("nan"), float("inf")):
        with pytest.raises(ci.ConstructInputError, match=r"must be in \(0, 1\]"):
            ci.validate_sector_etf_gross(bad, 0.20)


def test_sector_etf_positions_and_gross():
    univ = ["AAA", "XLK", "QQQ", "SMH", "SPY"]
    assert ci.sector_etf_positions(univ, (1, 2, 3)) == (1, 3)
    rows = [
        dict(symbol="XLK", sector="ETF", target_weight=0.06, target_shares=4),
        dict(symbol="SMH", sector="ETF", target_weight=-0.03, target_shares=-2),
        dict(symbol="XLE", sector="ETF", target_weight=0.05, target_shares=0),
        dict(symbol="QQQ", sector="ETF", target_weight=0.04, target_shares=1),
        dict(symbol="AAA", sector="SIC2:28", target_weight=0.05, target_shares=10),
        dict(symbol="SPY", sector="HEDGE", target_weight=-0.2, target_shares=-9),
    ]
    assert ci.sector_etf_gross(rows) == pytest.approx(0.09)


def test_sector_etf_gross_cap_binds_in_optimiser():
    """Same constraint form as construct.py: sector ETFs want 0.18 gross; the 0.10 sector-ETF cap binds."""
    univ = ["AAA", "BBB", "XLK", "XLE", "XLF", "QQQ", "SPY"]
    g = ci.construction_groups(univ, {"AAA": "28", "BBB": "36"}, etfs=ci.DECLARED_ETFS, hedge="SPY")
    cap = ci.apply_etf_position_cap(np.full(len(univ), 0.095), g.etf_index, 0.06)
    alpha = np.array([0.001, 0.001, 0.05, -0.04, 0.03, 0.02, 0.0])
    ix_e = list(g.etf_index)
    ix_se = list(ci.sector_etf_positions(univ, g.etf_index))
    assert [univ[i] for i in ix_se] == ["XLK", "XLE", "XLF"]

    def solve(sector_etf_gross):
        w = cp.Variable(len(univ))
        cons = [cp.abs(w) <= cap, cp.norm1(w) <= 0.58]
        for ix in g.sector_index.values():
            cons += [cp.norm1(w[list(ix)]) <= 0.20, cp.abs(cp.sum(w[list(ix)])) <= 0.10]
        cons += [cp.norm1(w[ix_e]) <= 0.20, cp.abs(cp.sum(w[ix_e])) <= 0.10]
        if sector_etf_gross is not None:
            cons.append(cp.norm1(w[ix_se]) <= sector_etf_gross)
        cp.Problem(cp.Maximize(alpha @ w), cons).solve(solver="CLARABEL")
        return np.asarray(w.value).ravel()

    free = solve(None)
    assert abs(free[ix_se]).sum() > 0.10 + 1e-3  # without the cap, sector ETFs exceed 0.10
    wv = solve(0.10)
    assert np.isclose(abs(wv[ix_se]).sum(), 0.10, atol=1e-5)  # cap binds
    assert abs(wv[ix_e]).sum() <= 0.20 + 1e-6 and abs(wv[ix_e].sum()) <= 0.10 + 1e-6  # still inside the sleeve
    rows = [
        dict(symbol=s, sector=g.labels[s], target_weight=float(wv[i]), target_shares=1 if abs(wv[i]) > 1e-9 else 0)
        for i, s in enumerate(univ)
    ]
    assert ci.sector_etf_gross(rows) <= 0.10 + 1e-6


def test_construct_source_wires_sector_etf_gross():
    assert "ci.validate_sector_etf_gross(a.sector_etf_gross, a.etf_sleeve_gross)" in CONSTRUCT_SRC
    assert "cp.norm1(w[ix_se]) <= a.sector_etf_gross" in CONSTRUCT_SRC
    assert '"Sector ETF gross cap"' in CONSTRUCT_SRC
    for sentence in (
        "A SIC-2 map covering sessions after 2021-12-31 must be reviewed and accepted before use.",
        "a reviewed ETF-to-SIC-2 look-through is required before",
    ):
        assert sentence in " ".join(CONSTRUCT_SRC.split())
    tree = ast.parse(CONSTRUCT_SRC)
    # statement-level string literals (docstrings; the module's sits after the __future__ import)
    docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    in_code = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and "2021-12-31" in n.value
        and id(n) not in docstrings
    ]
    assert in_code == []  # the map end date appears in docstrings only


# ------------------------------------------------------------------ construct.py wiring (source-level; main is not run)


def test_construct_source_has_no_builtin_universe_or_catch_all():
    assert "Other" not in CONSTRUCT_SRC
    tree = ast.parse(CONSTRUCT_SRC)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "SECTOR" not in names and "DESK_UNIVERSE" not in names
    assert "ci.add_construct_input_args(ap)" in CONSTRUCT_SRC
    assert "ci.construction_groups(univ, SIC2.groups" in CONSTRUCT_SRC
    assert "a.etf_sleeve_gross" in CONSTRUCT_SRC and "a.etf_sleeve_net" in CONSTRUCT_SRC


def test_earnings_gate_etf_set_unchanged():
    """The earnings-gate ETF set keeps the old membership: NON_ALPHA, XL* sector ETFs, SMH, store role=etf."""
    old_xl = {"XLK", "XLC", "XLY", "XLF", "XLV", "XLE", "XLP", "XLI", "XLB", "XLU", "XLRE"}
    assert {s for s in ci.SECTOR_ETFS if s.startswith("XL")} == old_xl
    assert (
        'ETFS = set(NON_ALPHA) | {s_ for s_ in univ if s_ in ci.SECTOR_ETFS and s_.startswith("XL")} | {"SMH"} | etf_roles'
        in CONSTRUCT_SRC
    )
    assert {"SPY", "QQQ", "IWM", "DIA", "EEM", "EFA", "TLT", "HYG", "GLD", "SLV"} == ci.NON_ALPHA_ETFS


# ------------------------------------------------------------------ riskmodels_wf with an explicit universe


def _fake_bars(symbols, start, end, adjustment="all", allow_api=False):
    days = pd.bdate_range("2020-01-01", periods=30)
    rows = []
    for k, s in enumerate(symbols):
        for i, d in enumerate(days):
            rows.append(dict(symbol=s, session_date=d.date(), close=100.0 + k + 0.1 * i, volume=1e6, zero_volume=False))
    return pd.DataFrame(rows)


def test_riskmodels_wf_uses_explicit_universe(monkeypatch):
    from quant_research.data.client import desk_data_client as ddc

    seen = []

    def fake(symbols, *a, **k):
        seen.append(list(symbols))
        return _fake_bars(symbols, *a, **k)

    monkeypatch.setattr(ddc, "get_daily_bars", fake)
    monkeypatch.setattr(rw, "CUTOFF", "2021-01-01")
    fr, dropped = rw.load_closes("store", fields=("c", "v"), universe=["AAA", "BBB", "SPY", "XLK", "BTC/USD"])
    assert seen == [["AAA", "BBB"]]
    assert list(fr["c"].columns) == ["AAA", "BBB"] and dropped == []


def test_riskmodels_wf_store_requires_universe():
    with pytest.raises(SystemExit, match="explicit universe"):
        rw.load_closes("store", universe=None)
    with pytest.raises(SystemExit, match="no alpha names"):
        rw.load_closes("store", universe=["SPY", "XLK"])
