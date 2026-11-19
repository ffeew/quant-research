"""Test configuration.

The research data store is private and not in this repo. Tests that need it are skipped
automatically (reported as "needs research data") unless QR_REQUIRE_DATA=1, in which case
missing data is a hard failure. Point QR_DATA_DIR at a data store to run them for real.
"""

import os

import pytest

REQUIRE_DATA = os.environ.get("QR_REQUIRE_DATA") == "1"
_MISSING = (FileNotFoundError, NotADirectoryError)


# End-to-end tests that drive the portfolio constructor against the real bar/earnings store.
# They are marked `data` and only run when QR_DATA_DIR points at an existing data store.
DATA_TESTS = (
    "tests/strategies/portfolio_construction/test_construct_limits02.py::",
    "tests/strategies/portfolio_construction/test_targets_io.py::test_construct_end_to_end_no_overwrite",
    "tests/strategies/portfolio_construction/test_targets_io.py::test_cio_hold_suppresses_tradable_write",
    "tests/strategies/portfolio_construction/test_earnings.py::test_stale_or_missing_calendar_failsafe",
    "tests/strategies/portfolio_construction/test_earnings.py::test_real_calendar_smoke",
    "tests/strategies/portfolio_construction/test_earnings.py::test_missing_pin_fail_closed",
    "tests/strategies/portfolio_construction/test_earnings.py::test_real_named_cases_clear_through_20261106",
)


def _have_data() -> bool:
    d = os.environ.get("QR_DATA_DIR")
    return d is not None and d != "" and os.path.isdir(d)


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="needs research data: set QR_DATA_DIR to a data store")
    for item in items:
        if any(item.nodeid.startswith(p) for p in DATA_TESTS):
            item.add_marker(pytest.mark.data)
            if not _have_data() and not REQUIRE_DATA:
                item.add_marker(skip)


class _DataAwareModule(pytest.Module):
    def _getobj(self):
        try:
            return super()._getobj()
        except _MISSING as exc:
            if REQUIRE_DATA:
                raise
            pytest.skip(f"needs research data (QR_DATA_DIR): {exc}", allow_module_level=True)


def pytest_pycollect_makemodule(module_path, parent):
    if module_path.name.startswith("test_"):
        return _DataAwareModule.from_parent(parent, path=module_path)
    return None


def _skip_if_missing(outcome):
    if REQUIRE_DATA:
        return
    exc = outcome.excinfo
    if exc and issubclass(exc[0], _MISSING):
        outcome.force_exception(pytest.skip.Exception(f"needs research data (QR_DATA_DIR): {exc[1]}"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    _skip_if_missing((yield))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _skip_if_missing((yield))
