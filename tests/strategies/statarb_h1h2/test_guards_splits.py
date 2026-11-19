import hashlib
from datetime import date

import pandas as pd
import pytest

from quant_research.strategies.statarb_h1h2 import guards as g
from quant_research.strategies.statarb_h1h2 import splits as sp


def test_preregistered_boundaries():
    assert (sp.DEV0, sp.DEV1) == (date(2017, 1, 3), date(2021, 12, 31))
    assert sp.EMBARGO1 == date(2022, 3, 29)
    assert sp.HOLDOUT0 == date(2022, 3, 30)
    sp.check_split_invariants()


def test_stage_bounds():
    assert sp.stage_date_bounds("dev") == (sp.DEV1, sp.DEV0, sp.DEV1)
    assert sp.stage_date_bounds("holdout")[1] == sp.HOLDOUT0
    with pytest.raises(SystemExit):
        sp.stage_date_bounds("oos")


def test_pinned_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    good = hashlib.sha256(b"abc").hexdigest()
    assert g.verify_pinned_file("x", f, good) == f
    for path, sha in ((f, "PENDING"), ("PENDING", good), (f, "0" * 64), (tmp_path / "nope", good)):
        with pytest.raises(g.Blocked) as e:
            g.verify_pinned_file("x", path, sha)
        assert e.value.code == 1


def test_sums_line(tmp_path):
    f = tmp_path / "cut.parquet"
    f.write_bytes(b"cut")
    h = g.sha256_file(f)
    sums = tmp_path / "SUMS"
    sums.write_text(f"{h}  {f}\n")
    g.verify_sums_line(sums, g.sha256_file(sums), f, h)
    sums.write_text(f"{'1' * 64}  {f}\n")
    with pytest.raises(g.Blocked):
        g.verify_sums_line(sums, g.sha256_file(sums), f, h)


def test_sums_dir(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "SHA256SUMS").write_text(f"{g.sha256_file(tmp_path / 'a.txt')}  a.txt\n")
    assert list(g.verify_sums_dir(tmp_path, g.sha256_file(tmp_path / "SHA256SUMS"))) == ["a.txt"]
    (tmp_path / "a.txt").write_text("changed")
    with pytest.raises(g.Blocked):
        g.verify_sums_dir(tmp_path, g.sha256_file(tmp_path / "SHA256SUMS"))


def test_acceptance_hash(tmp_path):
    pr = tmp_path / "PREREG.md"
    pr.write_text("synthetic")
    h = g.sha256_file(pr)
    assert g.require_acceptance_hash(h.upper(), pr, h, "dev") == h
    for provided, pin in ((None, h), ("0" * 64, h), (h, "1" * 64), (h, "PENDING")):
        with pytest.raises(g.Blocked):
            g.require_acceptance_hash(provided, pr, pin, "dev")


HDR = b"symbol\tdecision\treasons\tissuer_name\n"


def test_final_list_ok(tmp_path):
    raw = HDR + b"AAA\tKEPT\t\tA\nBBB\tEXCLUDED\tticker reuse\tB\n"
    fl = g.parse_final_list(raw)
    assert fl["kept"] == {"AAA"} and fl["excluded"] == {"BBB": "ticker reuse"}
    p = tmp_path / "fl.tsv"
    p.write_bytes(raw)
    assert g.load_final_list(p, g.sha256_file(p))["sha256"] == g.sha256_file(p)


@pytest.mark.parametrize("raw", [
    HDR.replace(b"\n", b"\r\n") + b"AAA\tKEPT\t\tA\n",      # CR in header
    HDR + b"AAA\tKEPT\t\tA\nAAA\tKEPT\t\tA\n",               # duplicate
    HDR + b"AAA\tMAYBE\t\tA\n",                              # unknown decision
    HDR + b"AAA\tEXCLUDED\t \tA\n",                          # excluded without reason
    HDR + b"AAA\tKEPT\tA\n",                                 # 3 fields
    HDR + b"\xff\xfe\n",                                     # not UTF-8
])
def test_final_list_mismatch_rc18(raw):
    with pytest.raises(g.FinalListMismatch) as e:
        g.parse_final_list(raw)
    assert e.value.code == g.RC_FINAL_LIST_MISMATCH


def test_final_list_pending_vs_mismatch(tmp_path):
    with pytest.raises(g.Blocked) as e:
        g.load_final_list("PENDING", "PENDING")
    assert e.value.code == 1
    with pytest.raises(g.FinalListMismatch):
        g.load_final_list(tmp_path / "absent.tsv", "0" * 64)


def test_require_pins_and_leakage_guard():
    with pytest.raises(g.Blocked, match="b"):
        g.require_pins({"a": "x", "b": "PENDING", "c": None})
    g.assert_no_rows_after(pd.DatetimeIndex(["2021-12-31"]), sp.DEV1, "x")
    with pytest.raises(RuntimeError):
        g.assert_no_rows_after(pd.DatetimeIndex(["2021-12-31", "2022-01-03"]), sp.DEV1, "x")
