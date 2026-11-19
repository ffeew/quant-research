import pytest

from quant_research.utils import config


def test_every_trial_config_loads():
    trials = config.list_trials()
    assert "trend_tsmom" in trials
    for name in trials:
        cfg = config.load_trial(name)
        t = cfg["trial"]
        assert t["status"] and t["verdict"]
        assert (config.REPO_ROOT / t["findings"]).is_file()


def test_entry_modules_exist():
    import importlib.util

    for name in config.list_trials():
        entry = config.load_trial(name)["trial"]["entry"]
        if entry:
            assert importlib.util.find_spec(entry) is not None, entry


def test_unknown_trial():
    with pytest.raises(KeyError):
        config.load_trial("no_such_trial")
