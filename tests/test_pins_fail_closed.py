"""Runners that only record a desk pin refuse to run on a PENDING or missing pin, before any work."""

from __future__ import annotations

import runpy
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from quant_research.utils import pins

H = "ab" * 32


@pytest.fixture
def pin_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    pins.reload()
    yield monkeypatch
    monkeypatch.delenv(pins.PINS_ENV, raising=False)
    pins.reload()


def _set(monkeypatch: pytest.MonkeyPatch, path: Path | None) -> None:
    if path is None:
        monkeypatch.delenv(pins.PINS_ENV, raising=False)
    else:
        monkeypatch.setenv(pins.PINS_ENV, str(path))
    pins.reload()


def _write(tmp: Path, tables: dict[str, dict[str, str]]) -> Path:
    f = tmp / "pins.toml"
    f.write_text("".join(f'["{ns}"]\n' + "".join(f'"{k}" = "{v}"\n' for k, v in t.items()) for ns, t in tables.items()))
    return f


def test_require_pins_refuses_pending_missing_file_and_missing_key(pin_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ns, keys = "strategies.trend_tsmom.run_v2", ("meta.data_build.prereg_tr_sha256", "meta.cost_model.prereg_sha256")
    _set(pin_env, None)  # no $QR_DESK_PINS: the public file, all PENDING
    with pytest.raises(pins.PinPending, match="PENDING or missing"):
        pins.require_pins(ns, *keys)
    _set(pin_env, tmp_path / "absent.toml")
    with pytest.raises(pins.PinPending):
        pins.require_pins(ns, *keys)
    _set(pin_env, _write(tmp_path, {ns: {keys[0]: H}}))  # one key set, one missing
    with pytest.raises(pins.PinPending, match=keys[1]):
        pins.require_pins(ns, *keys)
    _set(pin_env, _write(tmp_path, {ns: dict.fromkeys(keys, H)}))
    assert pins.require_pins(ns, *keys) == dict.fromkeys(keys, H)


def test_trend_v2_run_refuses_before_any_work(
    pin_env: pytest.MonkeyPatch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _set(pin_env, None)
    with pytest.raises(pins.PinPending):
        runpy.run_module("quant_research.strategies.trend_tsmom.run_v2", run_name="__main__")
    assert not (tmp_path / "outputs_v2").exists()  # refused before creating any output
    ns = "strategies.trend_tsmom.run_v2"
    _set(pin_env, _write(tmp_path, {ns: {"meta.data_build.prereg_tr_sha256": H, "meta.cost_model.prereg_sha256": H}}))
    with pytest.raises(FileNotFoundError):  # with real pins it gets past the gate (then needs data)
        runpy.run_module("quant_research.strategies.trend_tsmom.run_v2", run_name="__main__")


def test_oos_runner_refuses_before_parsing(pin_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch) -> None:
    from quant_research.strategies.sentiment_returns import oos_runner

    _set(pin_env, None)
    monkeypatch.setattr(sys, "argv", ["oos_runner", "--mode", "oos", "--config", "/nonexistent.json"])
    with pytest.raises(pins.PinPending, match=r"O\.prereg"):
        oos_runner.main()


def test_build_v2_refuses_before_any_work(pin_env: pytest.MonkeyPatch) -> None:
    _set(pin_env, None)
    cwd = Path.cwd()
    with pytest.raises(pins.PinPending, match="VALIDATION_PIT"):
        runpy.run_module("quant_research.data.earnings_events.v2.build_v2", run_name="__main__")
    assert Path.cwd() == cwd  # refused before its chdir


def test_sec_edgar_builders_refuse_on_pending_release_hash(pin_env: pytest.MonkeyPatch) -> None:
    from quant_research.data.sec_edgar import sue_build, xbrl_eps

    _set(pin_env, None)
    with pytest.raises(pins.PinPending, match="RELEASE_TOP_HASH"):
        xbrl_eps.build(save=False)
    with pytest.raises(pins.PinPending, match="RELEASE_TOP_HASH"):
        sue_build.main()


def test_h3_dev_runner_real_mode_treats_pending_as_unset(
    pin_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from quant_research.strategies.sentiment_returns import h3_dev_runner as h3

    monkeypatch.setattr(sys, "argv", ["h3_dev_runner", "--dry-check"])
    with pytest.raises(SystemExit) as e:
        h3.main()
    assert e.value.code == h3.EXIT_CFG
    err = capsys.readouterr().err
    assert "CONFIG BLOCKED" in err and "p2sums_sha" in err and "coverage sha" in err
