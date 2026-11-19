"""U-CAL trading calendar: build + pinned check, on synthetic calendars only (tmp_path)."""

import datetime as dt
import hashlib

import pandas as pd
import pytest

from quant_research.data.pipelines import trading_calendar as tc

D = dt.date
S = {"dev_start": D(2007, 1, 1), "holdout_start": D(2016, 6, 1), "sha256": "", "sha256_env": "QR_UCAL_SHA256_TEST"}
# synthetic sessions: a few weekdays at each end of the window, with a gap standing in for a holiday
SESSIONS = [
    D(2007, 1, 3),
    D(2007, 1, 4),
    D(2007, 1, 5),
    D(2012, 6, 14),
    D(2012, 6, 15),
    D(2015, 12, 24),
    D(2015, 12, 28),
    D(2016, 5, 27),
    D(2016, 5, 31),
]


@pytest.fixture
def cal(tmp_path):
    p = tmp_path / "ucal.csv"
    sha = tc.write_calendar(SESSIONS, p)
    return p, sha


def test_config_entry_loads():
    s = tc.load_settings()
    assert s["dev_start"] == D(2007, 1, 1) and s["holdout_start"] == D(2016, 6, 1)
    assert not str(s["calendar"]).startswith("/") and not str(s["bars"]).startswith("/")


def test_written_sha_matches_file(cal):
    p, sha = cal
    assert sha == hashlib.sha256(p.read_bytes()).hexdigest()
    assert tc.load_calendar(p, sha, S) == SESSIONS


@pytest.mark.parametrize("good", [["2007-01-03"], ["2012-06-15", D(2012, 6, 14)], ["2016-05-31"]])
def test_valid_dates_pass(cal, good):
    p, sha = cal
    assert tc.check_dev_dates(good, p, sha, S) == len(good)


@pytest.mark.parametrize(
    "bad",
    [
        "2012-06-16",  # Saturday
        "2015-12-25",  # holiday gap
        "2012-06-13",
    ],
)  # weekday not in the calendar
def test_non_session_rejected(cal, bad):
    p, sha = cal
    with pytest.raises(ValueError, match="not a DEV trading session"):
        tc.check_dev_dates(["2007-01-03", bad], p, sha, S)


@pytest.mark.parametrize("bad", ["2016-06-01", D(2016, 6, 1), "2019-03-15"])
def test_holdout_boundary_and_later_rejected(cal, bad):
    p, sha = cal
    with pytest.raises(ValueError, match="holdout"):
        tc.check_dev_dates([bad], p, sha, S)


def test_before_window_rejected(cal):
    p, sha = cal
    with pytest.raises(ValueError, match="window start"):
        tc.check_dev_dates(["2006-12-29"], p, sha, S)


def test_range_crossing_holdout_rejected(cal):
    p, sha = cal
    with pytest.raises(ValueError, match="holdout"):
        tc.require_full_session_range("2016-05-02", "2016-06-01", p, sha, S)
    assert tc.require_full_session_range("2016-05-01", "2016-05-31", p, sha, S) == [D(2016, 5, 27), D(2016, 5, 31)]


@pytest.mark.parametrize(
    "bad",
    ["", "2010-13-01", "not-a-date", "20100104", "2010-1-04", None, 20100104, dt.datetime(2012, 6, 15, tzinfo=dt.UTC)],
)
def test_unparseable_rejected(cal, bad):
    p, sha = cal
    with pytest.raises(ValueError):
        tc.check_dev_dates([bad], p, sha, S)


def test_tampered_file_rejected(cal, tmp_path):
    p, sha = cal
    t = tmp_path / "tampered.csv"
    t.write_bytes(p.read_bytes().replace(b"2015-12-24\n", b"2015-12-24\n2015-12-25\n"))
    with pytest.raises(ValueError, match="sha256 mismatch"):
        tc.load_calendar(t, sha, S)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        tc.check_dev_dates(["2015-12-25"], t, sha, S)


def test_pin_from_env_and_fail_closed(cal, monkeypatch):
    p, sha = cal
    monkeypatch.delenv("QR_UCAL_SHA256_TEST", raising=False)
    with pytest.raises(ValueError, match="no valid calendar sha256 pin"):
        tc.check_dev_dates(["2007-01-03"], p, None, S)
    monkeypatch.setenv("QR_UCAL_SHA256_TEST", sha)
    assert tc.check_dev_dates(["2007-01-03"], p, None, S) == 1


def test_build_from_synthetic_bars(tmp_path):
    days = pd.bdate_range("2006-12-20", "2016-06-10").date
    days = [d for d in days if d not in (D(2007, 1, 1), D(2015, 12, 25))]  # synthetic holidays
    bars = pd.DataFrame(
        {
            "symbol": "SPY",
            "session_date": days + days[:5],  # duplicates must collapse
            "close": 1.0,
        }
    )
    bp = tmp_path / "SPY.parquet"
    bars.to_parquet(bp, index=False)
    out, n, sha = tc.build(bp, tmp_path / "cal" / "ucal.csv", S)
    got = tc.load_calendar(out, sha, S)
    assert got[0] == D(2007, 1, 2) and got[-1] == D(2016, 5, 31)
    assert D(2015, 12, 25) not in got and all(d.weekday() < 5 for d in got)
    assert n == len(got) == len([d for d in days if S["dev_start"] <= d < S["holdout_start"]])
    assert out.read_bytes().startswith(b"date\n2007-01-02\n") and out.read_bytes().endswith(b"2016-05-31\n")


def test_build_rejects_weekend_bar():
    with pytest.raises(ValueError, match="weekend"):
        tc.build_sessions([D(2010, 5, 14), D(2010, 5, 15)], S["dev_start"], S["holdout_start"])


def test_calendar_outside_window_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    sha = tc.write_calendar([D(2016, 5, 31), D(2016, 6, 1)], p)
    with pytest.raises(ValueError, match="outside the DEV window"):
        tc.load_calendar(p, sha, S)
