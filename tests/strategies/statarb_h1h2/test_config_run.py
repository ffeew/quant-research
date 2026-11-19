import json
import re
from pathlib import Path

import pandas as pd
import pytest

from quant_research.strategies.statarb_h1h2 import config as C
from quant_research.strategies.statarb_h1h2 import run
from quant_research.strategies.statarb_h1h2.guards import Blocked

from . import synth as S

PKG = Path(run.__file__).resolve().parent


def test_example_config_is_all_pending_and_refuses(capsys):
    cfg = C.load_config(C.DEFAULT_CONFIG)
    assert cfg.pending() == sorted(C.DEV_INPUTS)
    assert all(p.sha256 == "PENDING" and p.path == "PENDING" for p in cfg.inputs.values())
    assert run.main(["--config", str(C.DEFAULT_CONFIG), "--syntax-check"]) == 0
    assert run.main(["--config", str(C.DEFAULT_CONFIG), "--stage", "dev", "--acceptance-hash", "0" * 64]) == 1
    assert "PENDING" in capsys.readouterr().err


def test_config_validation(tmp_path, monkeypatch):
    bad = tmp_path / "bad.toml"
    bad.write_text('[harness.inputs.prereg]\npath = "x"\nsha256 = "abc"\n')
    with pytest.raises(Blocked):
        C.load_config(bad)
    bad.write_text('[harness.inputs.not_an_input]\npath = "x"\nsha256 = "PENDING"\n')
    with pytest.raises(Blocked):
        C.load_config(bad)
    bad.write_text("[trial]\n")
    with pytest.raises(Blocked):
        C.load_config(bad)
    monkeypatch.setattr(C.qr_paths, "DATA_DIR", str(tmp_path / "store"))
    ok = tmp_path / "ok.toml"
    ok.write_text(
        '[harness]\nout_dir = "${QR_DATA_DIR}/o"\n[harness.inputs.prereg]\npath = "p/PREREG.md"\n'
        f'sha256 = "{"A" * 64}"\n'
    )
    cfg = C.load_config(ok)
    assert cfg.inputs["prereg"] == C.Pin(str(tmp_path / "store" / "p" / "PREREG.md"), "a" * 64)
    assert cfg.out_dir == str(tmp_path / "store" / "o")
    monkeypatch.setenv(C.CONFIG_ENV, str(ok))
    assert C.load_config().source == "ok.toml"


@pytest.fixture()
def synth_cfg(tmp_path):
    files = S.write_inputs(tmp_path / "in")
    return tmp_path, files, S.write_config(tmp_path, files)


def _args(cfg, files, *extra):
    return ["--config", str(cfg), "--stage", "dev", "--acceptance-hash", S.sha(files["prereg"]), *extra]


def test_end_to_end_dry_run_signals(synth_cfg, capsys):
    _root, files, cfg = synth_cfg
    assert run.main(_args(cfg, files, "--dry-run-signals")) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["returns_computed"] is False and res["eval"] == ["2017-01-03", "2021-12-31"]
    assert res["H1"]["n_days_nonzero"] > 0 and res["H2"]["n_days_nonzero"] > 0
    assert res["universe_receipt"]["n_member_rows"] == len(S.STOCKS)


def test_end_to_end_returns_and_out_no_clobber(synth_cfg, capsys):
    root, files, cfg = synth_cfg
    assert run.main(_args(cfg, files, "--out", "res.json")) == 0
    res = json.loads((root / "out" / "res.json").read_text())
    assert res["returns_computed"] is True
    assert {"H1_pathA", "H1_pathB", "H2"} <= set(res)
    assert res["H2"]["borrow_rate_used"] == 0.10 and res["H2"]["required_borrow_gate"] in ("PASS", "FAIL on costs")
    assert res["H2"]["cost_floor"] == res["H1_pathA"]["cost_floor"] == "standard_minimum_plus_half_spread"
    for k in ("n_forced_cuts_zero_adv", "forced_cut_notional_usd", "n_post_last_print_settlements"):
        assert k in res["H2"] and k in res["H1_pathA"]  # forced trades are disclosed in the run output
    with pytest.raises(FileExistsError):
        run.main(_args(cfg, files, "--out", "res.json"))
    assert run.main(_args(cfg, files, "--out", "../escape.json")) == 1


@pytest.mark.parametrize(
    "extra,code",
    [
        (["--stage", "holdout"], 1),
        (["--acceptance-hash", "0" * 64], 1),
        (["--idea", "H1", "--delisting-stress"], 1),
    ],
)
def test_refusals(synth_cfg, extra, code):
    _, files, cfg = synth_cfg
    assert run.main(_args(cfg, files) + extra) == code


def test_pin_mismatch_and_identity_rc18(synth_cfg):
    root, files, cfg = synth_cfg
    S.write_config(root, files, overrides={"earnings_dev_cut": "1" * 64})
    assert run.main(_args(cfg, files, "--dry-run-signals")) == 1
    S.write_config(root, files, overrides={"identity_list": "2" * 64})
    assert run.main(_args(cfg, files, "--dry-run-signals")) == 18
    files["identity_list"].write_bytes(b"symbol\tdecision\r\n")
    S.write_config(root, files)
    assert run.main(_args(cfg, files, "--dry-run-signals")) == 18


def test_tr_cut_with_post_embargo_row_refused(tmp_path):
    extra = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "session_date": [pd.Timestamp("2022-03-30")],
            "close_raw": [50.0],
            "volume_raw": [1e6],
            "ret_total_best": [0.0],
            "tr_index_best": [50.0],
        }
    )
    files = S.write_inputs(tmp_path / "in", tr_extra_rows=extra)
    cfg = S.write_config(tmp_path, files)
    assert run.main(_args(cfg, files, "--dry-run-signals")) == 1


def test_tr_cut_not_in_sums_refused(synth_cfg):
    root, files, cfg = synth_cfg
    files["tr_dev_cut_sums"].write_text(f"{'3' * 64}  {files['tr_dev_cut']}\n")
    S.write_config(root, files)
    assert run.main(_args(cfg, files, "--dry-run-signals")) == 1


def test_package_has_no_hardcoded_paths_or_pins():
    # no absolute-path literals, no sha256-like pins, no API-key handling in the harness
    pat = re.compile(r"[\"']/[A-Za-z_]+/|\b[0-9a-f]{64}\b|API_KEY")
    for f in sorted(PKG.glob("*.py")) + [C.DEFAULT_CONFIG]:
        hits = pat.findall(f.read_text())
        assert not hits, (f.name, hits)
