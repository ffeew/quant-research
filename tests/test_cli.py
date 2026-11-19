import importlib.util
import tomllib

from quant_research import cli
from quant_research.utils import config


def test_list(capsys):
    assert cli.main(["list"]) == 0
    assert "trend_tsmom" in capsys.readouterr().out


def test_datasets_modules_exist():
    with (config.CONFIG_DIR / "datasets.toml").open("rb") as fh:
        ds = tomllib.load(fh)["datasets"]
    assert ds
    for name, d in ds.items():
        assert importlib.util.find_spec(d["module"]) is not None, name


def test_run_without_code_returns_2():
    assert cli.main(["run", "vrp_iron_condor"]) == 2
