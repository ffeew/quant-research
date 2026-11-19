"""External input locations that used to be hard-coded are required inputs with no default (fail closed)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from quant_research.utils import paths
from quant_research.utils.config import REPO_ROOT

VALIDATE_V2_1 = REPO_ROOT / "src" / "quant_research" / "data" / "earnings_events" / "v2_1" / "validate_v2_1.py"


def test_required_env_rejects_unset_and_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QR_TEST_REQUIRED", raising=False)
    with pytest.raises(paths.MissingInput, match=r"\$QR_TEST_REQUIRED"):
        paths.required_env("QR_TEST_REQUIRED", "a test input")
    monkeypatch.setenv("QR_TEST_REQUIRED", "  ")
    with pytest.raises(paths.MissingInput, match="no default"):
        paths.required_env("QR_TEST_REQUIRED", "a test input")
    monkeypatch.setenv("QR_TEST_REQUIRED", "/some/where")
    assert paths.required_env("QR_TEST_REQUIRED", "a test input") == "/some/where"


@pytest.mark.parametrize("value", [None, ""])
def test_validate_v2_1_fails_closed_without_review_doc(tmp_path: Path, value: str | None) -> None:
    env = {k: v for k, v in os.environ.items() if k != "QR_V2_1_REVIEW_DOC"}
    if value is not None:
        env["QR_V2_1_REVIEW_DOC"] = value
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["QR_DATA_DIR"] = str(tmp_path)
    r = subprocess.run(
        [sys.executable, "-B", str(VALIDATE_V2_1)], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert r.returncode != 0
    assert "MissingInput" in r.stderr and "$QR_V2_1_REVIEW_DOC" in r.stderr, r.stderr[-500:]


def test_validate_v2_1_has_no_review_doc_default() -> None:
    src = VALIDATE_V2_1.read_text()
    assert "prereg_rulings" not in src and "DESK_DIR" not in src


H2C_OTHER_INPUTS = [
    "--purge",
    "/in/PURGE.tsv",
    "--tx_dev_root",
    "/in/tx/TRANSCRIPTS_DEV/",
    "--fye_month_frozen",
    "/in/FYE_MONTH_FROZEN.tsv",
    "--cost_clean",
    "/in/COST_CLEAN.json",
    "--cost_tx_root",
    "/in/cost_tx/TRANSCRIPTS_DEV",
]


def test_h2c_real_run_requires_pull_root() -> None:
    pytest.importorskip("exchange_calendars")
    from quant_research.strategies.sentiment_returns import h2c_dev_run as h

    for argv in (["h2c_dev_run.py"], ["h2c_dev_run.py", "--pull_root", ""], ["h2c_dev_run.py", "--pull_root", "/"]):
        with pytest.raises(h.Stop, match="missing required --pull_root") as e:
            h.load_config(argv)
        assert e.value.code == 10
    s = h.load_config(["h2c_dev_run.py", "--pull_root", "/copy/root/", *H2C_OTHER_INPUTS])
    assert s["PINS"]["COPY_SUMS"][0] == "/copy/root/COPY_SUMS"
    assert s["PINS"]["PRICES_DEV"][0] == "/copy/root/DEV/PRICES_DEV.json"
    assert s["PINS"]["EARNINGS_DEV"][0] == "/copy/root/DEV/EARNINGS_DEV.json"
    assert s["PINS"]["COPY_SUMS"][1] == h.PINS["COPY_SUMS"][1]
    # the module constants carry no real location
    assert all(h.PINS[k][0].startswith(h.PULL_ROOT_PLACEHOLDER) for k in h.PULL_REL)
    assert "PULL_ROOT" not in vars(h)


def test_h2c_real_run_requires_every_desk_input() -> None:
    pytest.importorskip("exchange_calendars")
    from quant_research.strategies.sentiment_returns import h2c_dev_run as h

    full = ["h2c_dev_run.py", "--pull_root", "/copy/root", *H2C_OTHER_INPUTS]
    s = h.load_config(list(full))
    P = s["PINS"]
    assert P["PURGE"][0] == "/in/PURGE.tsv"
    assert P["TX_DEV_SUMS"][0] == "/in/tx/TRANSCRIPTS_DEV/SHA256SUMS" and s["TX_DEV_ROOT"] == "/in/tx/TRANSCRIPTS_DEV"
    assert P["FYE_MONTH_FROZEN"][0] == "/in/FYE_MONTH_FROZEN.tsv"
    assert P["COST_EARNINGS_CLEAN"][0] == "/in/COST_CLEAN.json"
    assert P["COST_TX_SUMS"][0] == "/in/cost_tx/TRANSCRIPTS_DEV/SHA256SUMS"
    assert s["COST_TX_ROOT"] == "/in/cost_tx/TRANSCRIPTS_DEV"
    assert all(P[k][1] == h.PINS[k][1] for k in h.PINS)  # shas untouched
    for i in range(3, len(full), 2):  # drop each input flag in turn, or blank its value
        flag = full[i]
        for argv in (
            full[:i] + full[i + 2 :],
            full[: i + 1] + [""] + full[i + 2 :],
            full[: i + 1] + ["/"] + full[i + 2 :],
        ):
            with pytest.raises(h.Stop, match=f"missing required {flag} ") as e:
                h.load_config(argv)
            assert e.value.code == 10
    for argv in (full + ["--purge", "/x"], full + ["--unknown", "/x"], full + ["--purge"]):
        with pytest.raises(h.Stop, match="bad argv") as e:
            h.load_config(argv)
        assert e.value.code == 10
    # the module constants carry no desk location: every input path is a placeholder until the flags fill it
    for k in ("PURGE", "TX_DEV_SUMS", "FYE_MONTH_FROZEN", "COST_EARNINGS_CLEAN", "COST_TX_SUMS"):
        assert h.PINS[k][0].startswith("<--"), k
    assert h.TX_DEV_ROOT.startswith("<--") and h.COST_TX_ROOT.startswith("<--")
    src = Path(h.__file__).read_text()
    for frag in (
        "h2c_av_pull_20261114",
        "h2c_tx_route_",
        "fiscal_diag_s6b",
        "h2c_cost_clean_",
        "h2c_cost_delta_route_",
    ):
        assert frag not in src, frag


def test_news_prereg_cost_inputs_are_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from quant_research.strategies.news_sentiment import prereg_run as pr

    for name in ("QR_COSTS_INPUTS", "QR_COSTS_INPUTS_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(pr, "_COSTS_SIDE", None)
    with pytest.raises(paths.MissingInput, match=r"\$QR_COSTS_INPUTS "):
        pr.costs_inputs()
    with pytest.raises(paths.MissingInput, match=r"\$QR_COSTS_INPUTS_DIR "):
        pr.costs_inputs_dir()
    with pytest.raises(paths.MissingInput, match=r"\$QR_COSTS_INPUTS_DIR "):
        pr.costs_per_side("XLK")
    monkeypatch.setenv("QR_COSTS_INPUTS_DIR", "")
    with pytest.raises(paths.MissingInput, match="no default"):
        pr.costs_inputs_dir()
    (tmp_path / "per_side_costs.csv").write_text("name,base,base_mktlim\nXLK,1.5,2.5\n")
    monkeypatch.setenv("QR_COSTS_INPUTS_DIR", str(tmp_path))
    monkeypatch.setenv("QR_COSTS_INPUTS", str(tmp_path / "inputs.md"))
    assert pr.costs_inputs() == str(tmp_path / "inputs.md")
    assert pr.costs_per_side("XLK") == (1.5, 2.5)
    src = Path(pr.__file__).read_text()
    assert "/tca/ethan_cost_inputs.md" not in src and '/tca/ethan_inputs"' not in src
    # the check report labels are output text and stay as they were
    assert 'need("ethan_cost_inputs.md",' in src and 'need(f"tca/ethan_inputs/{fn}",' in src
