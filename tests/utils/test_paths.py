import importlib
import os

from quant_research.utils import paths


def test_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QR_DATA_DIR", str(tmp_path))
    mod = importlib.reload(paths)
    try:
        assert mod.DATA_DIR == str(tmp_path)
        assert mod.data_path("bars", "x.parquet") == os.path.join(str(tmp_path), "bars", "x.parquet")
    finally:
        monkeypatch.delenv("QR_DATA_DIR")
        importlib.reload(paths)


def test_costs_dir_points_at_package():
    assert os.path.isfile(os.path.join(paths.COSTS_DIR, "cost_model.py"))
