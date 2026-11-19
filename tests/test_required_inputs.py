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


def test_h2c_real_run_requires_pull_root() -> None:
    pytest.importorskip("exchange_calendars")
    from quant_research.strategies.sentiment_returns import h2c_dev_run as h

    for argv in (["h2c_dev_run.py"], ["h2c_dev_run.py", "--pull_root", ""], ["h2c_dev_run.py", "--pull_root", "/"]):
        with pytest.raises(h.Stop, match="missing required --pull_root") as e:
            h.load_config(argv)
        assert e.value.code == 10
    s = h.load_config(["h2c_dev_run.py", "--pull_root", "/copy/root/"])
    assert s["PINS"]["COPY_SUMS"][0] == "/copy/root/COPY_SUMS"
    assert s["PINS"]["PRICES_DEV"][0] == "/copy/root/DEV/PRICES_DEV.json"
    assert s["PINS"]["EARNINGS_DEV"][0] == "/copy/root/DEV/EARNINGS_DEV.json"
    assert s["PINS"]["COPY_SUMS"][1] == h.PINS["COPY_SUMS"][1]
    # the module constants carry no real location
    assert all(h.PINS[k][0].startswith(h.PULL_ROOT_PLACEHOLDER) for k in h.PULL_REL)
    assert "PULL_ROOT" not in vars(h)
