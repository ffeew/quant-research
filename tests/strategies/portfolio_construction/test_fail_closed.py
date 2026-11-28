"""A failed compliance check or a failed solve is a coded stop and no usable targets are written.

All data are synthetic.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib

import cvxpy as cp
import numpy as np
import pytest

from quant_research.strategies.portfolio_construction import construct_inputs as ci
from quant_research.strategies.portfolio_construction import fail_closed as fc
from quant_research.strategies.portfolio_construction import targets_io as tio

CONSTRUCT_SRC = (pathlib.Path(tio.__file__).with_name("construct.py")).read_text()


def _chk(limit: str, status: str, value: object = "1%", thr: object = "<=1%") -> dict[str, object]:
    return dict(limit=limit, threshold=thr, value=value, status=status)


def _doc(*checks: dict[str, object]) -> dict[str, object]:
    return dict(book_type="TEST", tradable=True, targets=[], compliance=list(checks))


def _files(root: pathlib.Path) -> list[str]:
    return sorted(os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs)


def _entries(root: pathlib.Path) -> list[str]:
    return sorted(os.path.join(d, n) for d, ds, fs in os.walk(root) for n in ds + fs)


# ---------------------------------------------------------------- compliance gate


def test_failed_checks_pass_and_info_are_fine():
    assert fc.failed_checks([_chk("a", "PASS"), _chk("b", "INFO")]) == []


def test_failed_checks_lists_every_fail_unknown_status_and_missing_block():
    got = fc.failed_checks([_chk("a", "PASS"), _chk("b", "FAIL"), _chk("c", "WEIRD"), "junk"])
    assert len(got) == 3 and got[0].startswith("b (status 'FAIL'") and got[1].startswith("c (status 'WEIRD'")
    assert fc.failed_checks(None) and fc.failed_checks("PASS")  # missing / malformed block fails closed


def test_compliance_fail_stops_with_code_and_lists_every_failed_check(capsys):
    docs = [
        ("/x/shadow/t.json", _doc(_chk("Max notional per position", "FAIL"), _chk("ok", "PASS"))),
        ("/x/targets/t.json", _doc(_chk("Sector ETF gross cap", "FAIL", "12.00%", "<=10%"), _chk("Gross", "FAIL"))),
    ]
    with pytest.raises(SystemExit) as ei:
        fc.require_compliance_pass(docs)
    assert ei.value.code == fc.EXIT_COMPLIANCE_FAIL != 0
    err = capsys.readouterr().err
    for name in ("Max notional per position", "Sector ETF gross cap", "Gross"):
        assert name in err
    assert "shadow/t.json: Max notional per position" in err
    assert "targets/t.json: Sector ETF gross cap" in err


def test_compliance_pass_returns_quietly():
    fc.require_compliance_pass([("/x/t.json", _doc(_chk("a", "PASS"), _chk("b", "INFO")))])


def test_sector_etf_gross_check_built_like_construct_fails_closed(tmp_path):
    rows = [
        dict(symbol="XLK", sector="ETF", target_weight=0.07, target_shares=5),
        dict(symbol="XLE", sector="ETF", target_weight=0.05, target_shares=4),
    ]
    cap = 0.10
    se = ci.sector_etf_gross(rows)
    doc = _doc(_chk("Sector ETF gross cap", "PASS" if se <= cap + 1e-6 else "FAIL", f"{se * 100:.2f}%"))
    p = str(tmp_path / "targets" / "t.json")
    with pytest.raises(SystemExit) as ei:
        tio.write_checked([(p, doc)])
    assert ei.value.code == fc.EXIT_COMPLIANCE_FAIL


# ---------------------------------------------------------------- nothing usable is written on FAIL


def test_fail_writes_nothing_at_all_no_file_no_temp_no_dir(tmp_path):
    p_tr, p_sh = str(tmp_path / "targets" / "t.json"), str(tmp_path / "shadow" / "t.json")
    docs = [(p_sh, _doc(_chk("a", "PASS"))), (p_tr, _doc(_chk("b", "FAIL")))]  # only the SECOND doc fails
    with pytest.raises(SystemExit) as ei:
        tio.write_checked(docs)
    assert ei.value.code not in (0, None)
    assert _entries(tmp_path) == []  # neither doc written; no temp file; no directory created


def test_fail_leaves_existing_files_untouched(tmp_path):
    d = tmp_path / "targets"
    d.mkdir()
    old = d / "old.json"
    old.write_text("{}")
    with pytest.raises(SystemExit):
        tio.write_checked([(str(d / "new.json"), _doc(_chk("b", "FAIL")))])
    assert _files(tmp_path) == [str(old)] and old.read_text() == "{}"


def test_pass_still_writes_atomically_and_returns_digest(tmp_path):
    p_tr, p_sh = str(tmp_path / "targets" / "t.json"), str(tmp_path / "shadow" / "t.json")
    docs = [(p_sh, _doc(_chk("a", "PASS"))), (p_tr, _doc(_chk("b", "INFO")))]
    out = tio.write_checked(docs)
    assert [(p, doc) for p, doc, _ in out] == docs
    assert sorted(_files(tmp_path)) == sorted([p_sh, p_tr])  # exactly the two files, no .tmp_ leftovers
    for p, doc, digest in out:
        assert json.loads(pathlib.Path(p).read_text())["compliance"] == doc["compliance"]
        assert digest == tio.sha256(p)


def test_pass_does_not_overwrite_an_existing_file(tmp_path):
    p = tmp_path / "t.json"
    p.write_text("{}")
    with pytest.raises(FileExistsError):
        tio.write_checked([(str(p), _doc(_chk("a", "PASS")))])
    assert p.read_text() == "{}" and _files(tmp_path) == [str(p)]


# ---------------------------------------------------------------- solve is a coded stop


def _problem(lo: float, hi: float):
    w = cp.Variable(2)
    return w, cp.Problem(cp.Maximize(w.sum()), [w >= lo, w <= hi])


def test_optimal_solve_returns_values():
    w, prob = _problem(0.0, 1.0)
    val = fc.solve_or_stop(prob, w)
    assert np.allclose(val, [1.0, 1.0], atol=1e-6)


def test_infeasible_solve_is_a_coded_stop(capsys):
    w, prob = _problem(1.0, 0.0)  # lo > hi
    with pytest.raises(SystemExit) as ei:
        fc.solve_or_stop(prob, w)
    assert ei.value.code == fc.EXIT_SOLVE_FAILED != 0
    assert "infeasible" in capsys.readouterr().err


def test_unbounded_solve_is_a_coded_stop():
    w = cp.Variable(2)
    prob = cp.Problem(cp.Maximize(w.sum()), [w >= 0])
    with pytest.raises(SystemExit) as ei:
        fc.solve_or_stop(prob, w)
    assert ei.value.code == fc.EXIT_SOLVE_FAILED


class _Fake:
    def __init__(self, status, value, exc=None):
        self.status, self.value, self._exc = status, value, exc

    def solve(self, solver=None):
        if self._exc:
            raise self._exc


def test_inaccurate_missing_or_nonfinite_solutions_are_stops():
    ok = np.array([0.1, 0.2])
    for status, val in (
        ("optimal_inaccurate", ok),
        ("optimal", None),
        ("optimal", np.array([0.1, float("nan")])),
        ("optimal", np.array([float("inf"), 0.0])),
        ("optimal", np.array([])),
        (None, ok),
    ):
        fake = _Fake(status, val)
        with pytest.raises(SystemExit) as ei:
            fc.solve_or_stop(fake, fake)
        assert ei.value.code == fc.EXIT_SOLVE_FAILED, (status, val)
    fake = _Fake("optimal", ok)
    assert fc.solve_or_stop(fake, fake) is ok


def test_solver_exception_is_a_stop():
    fake = _Fake("optimal", np.array([0.0]), exc=cp.error.SolverError("boom"))
    with pytest.raises(SystemExit) as ei:
        fc.solve_or_stop(fake, fake)
    assert ei.value.code == fc.EXIT_SOLVE_FAILED


def test_stop_codes_are_distinct_and_nonzero():
    assert len({0, fc.EXIT_COMPLIANCE_FAIL, fc.EXIT_SOLVE_FAILED}) == 3


def test_exit_codes_are_literal_3_and_4():
    assert fc.EXIT_COMPLIANCE_FAIL == 3 and fc.EXIT_SOLVE_FAILED == 4
    with pytest.raises(SystemExit) as ei:
        fc.require_compliance_pass([("/out/targets/t.json", _doc(_chk("a", "FAIL")))])
    assert ei.value.code == 3
    w, prob = _problem(1.0, 0.0)
    with pytest.raises(SystemExit) as ei:
        fc.solve_or_stop(prob, w)
    assert ei.value.code == 4


def test_empty_compliance_list_is_malformed_and_stops():
    assert fc.failed_checks([]) == ["compliance block missing or malformed"]
    with pytest.raises(SystemExit) as ei:
        fc.require_compliance_pass([("/out/targets/t.json", _doc())])
    assert ei.value.code == 3


def test_unhashable_status_is_coded_stop_not_typeerror():
    got = fc.failed_checks([dict(limit="a", status=["FAIL"], value=None, threshold=None)])
    assert got and got[0].startswith("a (status ['FAIL']")
    with pytest.raises(SystemExit) as ei:
        fc.require_compliance_pass(
            [("/out/targets/t.json", _doc(dict(limit="a", status={"k": 1}, value=None, threshold=None)))]
        )
    assert ei.value.code == 3


def test_warn_status_stops():
    with pytest.raises(SystemExit) as ei:
        fc.require_compliance_pass([("/out/targets/t.json", _doc(_chk("Gross", "WARN")))])
    assert ei.value.code == 3 and "WARN" in str(ei.value.reasons if hasattr(ei.value, "reasons") else "")
    # also visible in the listed reasons
    assert any("WARN" in r for r in ei.value.reasons)


def test_stop_label_includes_parent_dir(capsys):
    stamp = "targets_20261123T153000SGT.json"
    with pytest.raises(SystemExit):
        fc.require_compliance_pass(
            [
                (f"/out/shadow/{stamp}", _doc(_chk("a", "FAIL"))),
                (f"/out/targets/{stamp}", _doc(_chk("b", "FAIL"))),
            ]
        )
    err = capsys.readouterr().err
    assert f"shadow/{stamp}: a" in err
    assert f"targets/{stamp}: b" in err


def test_write_checked_fail_in_first_doc_writes_nothing(tmp_path):
    p_sh, p_tr = str(tmp_path / "shadow" / "t.json"), str(tmp_path / "targets" / "t.json")
    with pytest.raises(SystemExit) as ei:
        tio.write_checked([(p_sh, _doc(_chk("a", "FAIL"))), (p_tr, _doc(_chk("b", "PASS")))])
    assert ei.value.code == 3
    assert _entries(tmp_path) == []


def test_write_checked_lexists_later_path_writes_nothing_for_earlier(tmp_path):
    p_sh = tmp_path / "shadow" / "t.json"
    p_tr = tmp_path / "targets" / "t.json"
    p_tr.parent.mkdir()
    p_tr.write_text("{}")
    with pytest.raises(FileExistsError):
        tio.write_checked([(str(p_sh), _doc(_chk("a", "PASS"))), (str(p_tr), _doc(_chk("b", "PASS")))])
    assert not p_sh.exists() and not p_sh.parent.exists()
    assert p_tr.read_text() == "{}"


# ---------------------------------------------------------------- construct.py wiring (source level; main is not run)


def test_construct_uses_the_fail_closed_paths_only():
    assert "fc.solve_or_stop(prob, w)" in CONSTRUCT_SRC and "prob.solve(" not in CONSTRUCT_SRC
    assert "tio.write_checked(docs)" in CONSTRUCT_SRC and "write_exclusive(" not in CONSTRUCT_SRC
    calls = [
        n
        for n in ast.walk(ast.parse(CONSTRUCT_SRC))
        if isinstance(n, ast.Attribute) and n.attr in {"write_text", "dump"}
    ]
    assert [c for c in calls if getattr(c.value, "id", "") == "tio"] == []
