import math
from collections.abc import Callable

from quant_research.strategies.sentiment_returns.h2c import errors, run_h2c
from quant_research.strategies.sentiment_returns.h2c.config import HoldoutExpectations, load_h2c_params

from ._h2c_synth import SYMS, world


def _raises(exc: type[BaseException], fn: Callable[..., object], *a: object, **k: object) -> None:
    try:
        fn(*a, **k)
    except exc:
        return
    raise AssertionError(f"{exc.__name__} not raised")


def test_pipeline_runs_and_is_deterministic() -> None:
    p, kw = world(seed=3)
    a = run_h2c(p, "T", **kw)
    b = run_h2c(p, "T", **world(seed=3)[1])
    assert a["stats"] == b["stats"]
    st = a["counts"]["status"]
    assert st.get("warmup_not_scored", 0) == 3 * len(SYMS)  # 2018Q1..Q3 reports (2018Q4 reports in 2019)
    assert st.get("excl_dup_symbol_quarter", 0) == len(SYMS)  # Dec-01 report shares 2020Q4 with the Q3 report
    assert a["counts"]["purge"] == dict(in_window_rows=len(SYMS), purged=0, kept=len(SYMS), excl_no_reporttime=0)
    assert a["counts"]["mapping"]["mapped"] == 11 * len(SYMS)
    assert a["stats"]["periods"] == len(a["periods"]) >= 6
    for per in a["periods"]:
        assert per["k"] == per["n"] // p.quantile_div and math.isfinite(per["ic"])
        assert math.isclose(per["net10_badj"], per["ls_badj"] - p.cost_side * per["turnover_units"])
    assert {ev["status"] for ev in a["events"] if ev["quarter"] in ("2019Q1", "2019Q2")} <= {"included"}


def test_planted_signal_is_recovered() -> None:
    p, kw = world(seed=11, planted=0.05)
    r = run_h2c(p, "T", **kw)
    assert r["stats"]["mean_ic"] > 0.5 and r["stats"]["G0_pass"]
    p0, kw0 = world(seed=11, planted=0.0)
    assert run_h2c(p0, "T", **kw0)["stats"]["mean_ic"] < r["stats"]["mean_ic"]


def test_holdout_gate_needs_runtime_expectations() -> None:
    p, kw = world(seed=3)
    pc = run_h2c(p, "T", **kw)["counts"]["purge"]
    _raises(errors.ConfigError, run_h2c, p, "T", purge_reference=pc, **kw)
    _raises(
        errors.PurgeMismatch,
        run_h2c,
        p,
        "T",
        purge_reference=dict(pc, kept=0),
        expectations=HoldoutExpectations(purge=pc),
        **kw,
    )
    r = run_h2c(p, "T", purge_reference=pc, expectations=HoldoutExpectations(purge=dict(pc)), dev_mean_ic=0.0, **kw)
    assert "G2" in r["stats"] and r["stats"]["dev_mean_ic_frozen"] == 0.0


class _Untouchable(dict[str, int]):
    """Any read of this input fails the test: proves run_h2c refuses before touching inputs."""

    def _boom(self, *a: object, **k: object) -> None:
        raise AssertionError("input touched")

    __iter__ = __len__ = __getitem__ = __contains__ = get = items = keys = values = _boom  # type: ignore[assignment]


def _untouched_loader(sym: str, label: str) -> object:
    raise AssertionError("transcript loader touched")


def test_run_h2c_refuses_holdout() -> None:
    p, _ = world(seed=3)
    bomb = _Untouchable()
    kw = dict(
        calendar_sessions=bomb,
        price_sessions=bomb,
        price_rows=bomb,
        earnings_rows=bomb,
        transcript_keys=bomb,
        load_transcript=_untouched_loader,
        fye_months=bomb,
    )
    for name in ("HOLDOUT", "holdout", " Holdout "):
        try:
            run_h2c(p, name, **kw)  # type: ignore[arg-type]
        except errors.HoldoutRefusedError as e:
            assert isinstance(e, errors.PartitionError) and e.code == errors.PartitionError.code
            assert "spent" in str(e) and "must not be used" in str(e)
        else:
            raise AssertionError("HOLDOUT not refused")
    real = load_h2c_params()
    assert "HOLDOUT" in real.partitions
    _raises(errors.HoldoutRefusedError, run_h2c, real, "HOLDOUT", **kw)


def test_partition_violations_stop() -> None:
    p, kw = world(seed=3)
    bad = list(kw["earnings_rows"]) + [
        dict(kw["earnings_rows"][0], reportedDate="2021-02-01", fiscalDateEnding="2020-12-31")
    ]
    _raises(errors.PartitionError, run_h2c, p, "T", **dict(kw, earnings_rows=bad))
    early = list(kw["earnings_rows"]) + [
        dict(kw["earnings_rows"][0], reportedDate="2017-11-01", fiscalDateEnding="2017-09-30")
    ]
    _raises(errors.PartitionError, run_h2c, p, "T", **dict(kw, earnings_rows=early))
    _raises(
        errors.MappingError,
        run_h2c,
        p,
        "T",
        **dict(kw, transcript_keys=list(kw["transcript_keys"]) + [(SYMS[0], "2016Q1")]),
    )


def test_exclude_mapped_before_counts_and_occupies() -> None:
    from quant_research.strategies.sentiment_returns.h2c.config import params_from_dict

    from ._h2c_synth import params

    base = params()
    t = base.partition("T")
    d = {
        k: getattr(base, k)
        for k in (
            "universe",
            "hedge",
            "beta_n",
            "h0",
            "h1",
            "lag",
            "nprior_max",
            "nprior_min",
            "tone_min",
            "q_min_events",
            "quantile_div",
        )
    }
    d["partitions"] = dict(
        T=dict(
            lo="2018-01-01",
            hi=t.hi,
            score_lo=t.score_lo,
            scored_years=[2019, 2020],
            g0_min_quarters=6,
            purge_window=list(t.purge_window),
            purge_boundary="2020",
            exclude_mapped_before="2018-07-01",
        )
    )
    p = params_from_dict(d)
    _, kw = world(seed=3)
    r = run_h2c(p, "T", **kw)
    m = r["counts"]["mapping"]
    assert m["excluded_mapped"] == len(SYMS)  # only 2018Q1 calls are reported before 2018-07-01
    assert m["mapped"] + m["excluded_mapped"] == m["listed"]


def _spent(fn: Callable[..., object], *a: object, **k: object) -> str:
    try:
        fn(*a, **k)
    except errors.HoldoutRefusedError as e:
        assert isinstance(e, errors.PartitionError)
        assert "2011-01-01 to 2013-12-31" in str(e) and "spent" in str(e)
        return str(e)
    raise AssertionError("spent-window input not refused")


def _part(lo: str, hi: str, score_lo: str, y0: int, y1: int) -> dict[str, object]:
    return dict(
        lo=lo,
        hi=hi,
        score_lo=score_lo,
        scored_years=[y0, y1],
        g0_min_quarters=1,
        purge_window=[hi[:4] + "-11-01", hi],
        purge_boundary=hi[:4],
    )


def test_run_h2c_refuses_spent_window_dates() -> None:
    from ._h2c_synth import params

    bomb = _Untouchable()
    kw = dict(
        calendar_sessions=bomb,
        price_sessions=bomb,
        price_rows=bomb,
        earnings_rows=bomb,
        transcript_keys=bomb,
        load_transcript=_untouched_loader,
        fye_months=bomb,
    )
    windows = (
        ("2010-01-01", "2014-12-31", "2011-01-01", 2011, 2014),  # covers the window
        ("2013-12-31", "2016-12-31", "2015-01-01", 2015, 2016),  # touches only its last day
        ("2009-01-01", "2011-01-01", "2010-01-01", 2010, 2010),  # touches only its first day
        ("2012-01-01", "2012-12-31", "2012-04-01", 2012, 2012),  # inside it
    )
    for lo, hi, score_lo, y0, y1 in windows:
        p = params(partitions=dict(T=_part(lo, hi, score_lo, y0, y1)))
        assert "partition T" in _spent(run_h2c, p, "T", **kw)  # refused before any input is read


def test_run_h2c_refuses_spent_window_input_dates_outside_partition() -> None:
    import datetime as dt

    p, kw = world(seed=3)
    run_h2c(p, "T", **kw)  # partition bounds and all inputs outside 2011-2013: runs
    ps = list(kw["price_sessions"])
    cal = list(kw["calendar_sessions"])
    prow = dict(kw["price_rows"][0], date="2012-06-01")
    er = list(kw["earnings_rows"])
    # In-window session/price dates here are years before the partition start (2018-01-01): outside the beta
    # warm-up allowance, so still refused.
    cases = (
        dict(price_sessions=["2012-06-01", *ps]),
        dict(price_sessions=[dt.date(2012, 6, 1), *ps]),
        dict(calendar_sessions=["2013-12-31", *cal]),
        dict(price_rows=[*kw["price_rows"], prow]),
        dict(earnings_rows=[*er, dict(er[0], reportedDate="2012-02-01")]),
        dict(earnings_rows=[*er, dict(er[0], reportedDate=dt.date(2012, 2, 1))]),
    )
    for over in cases:
        _spent(run_h2c, p, "T", **dict(kw, **over))
    # fiscalDateEnding is a label, not an observation date: an in-window fiscal label alone is not refused.
    for fde_rows in (
        [*er, dict(er[0], fiscalDateEnding="2011-12-31")],
        iter([*er, dict(er[0], fiscalDateEnding="2011-01-01")]),
    ):
        r = run_h2c(p, "T", **dict(kw, earnings_rows=fde_rows))
        assert r["partition"] == "T" and r["stats"]["periods"] >= 6


def test_dev_call_with_2013_fiscal_label_and_2013_warmup_passes() -> None:
    p, kw = world(seed=3, dev=True)
    part = p.partition("T")
    assert part.lo == "2014-01-01"
    warm = [d for d in kw["price_sessions"] if d < part.lo]
    assert len(warm) == p.beta_n + 1 and all(d.startswith("2013-1") for d in warm)
    assert [d for d in kw["calendar_sessions"] if d < part.lo] == warm
    assert any(r["date"] in warm for r in kw["price_rows"])
    q4 = [e for e in kw["earnings_rows"] if e["fiscalDateEnding"] == "2013-12-31"]
    assert len(q4) == len(SYMS) and all(e["reportedDate"].startswith("2014-01") for e in q4)
    r = run_h2c(p, "T", **kw)
    assert r["counts"]["mapping"]["mapped"] == 12 * len(SYMS)  # the fiscal-2013 Q4 transcripts map too
    assert {ev["status"] for ev in r["events"] if ev["fiscalDateEnding"] == "2013-12-31"} == {"warmup_not_scored"}
    assert r["stats"]["periods"] == len(r["periods"]) >= 6
    assert all(ev["day0"] >= part.lo for ev in r["events"] if ev["day0"])
    # The earliest event day0 sits fewer than beta_n sessions into the partition, so a beta estimated at it draws
    # on the 2013 warm-up sessions.
    first = min(ev["day0"] for ev in r["events"] if ev["day0"])
    assert kw["price_sessions"].index(first) - p.beta_n < len(warm)


def test_2013_price_date_outside_warmup_lookback_is_refused() -> None:
    p, kw = world(seed=3, dev=True)
    early = "2013-06-03"  # before the partition start but far more than beta_n + 1 sessions before it
    ps = sorted([early, *kw["price_sessions"]])
    rows = [*kw["price_rows"], *(dict(symbol=s, date=early, adjusted_close=100.0) for s in [*SYMS, "HEDGE"])]
    for over in (
        dict(price_sessions=ps),
        dict(price_sessions=ps, price_rows=rows),
        dict(calendar_sessions=sorted([early, *kw["calendar_sessions"]])),
    ):
        msg = _spent(run_h2c, p, "T", **dict(kw, **over))
        assert early in msg and "warm-up" in msg
    # One session more than the lookback, prepended in order: the oldest one falls outside the allowance.
    extra = "2013-10-01"
    assert extra < kw["price_sessions"][0]
    msg = _spent(run_h2c, p, "T", **dict(kw, price_sessions=[extra, *kw["price_sessions"]]))
    assert extra in msg


def test_2013_return_row_feeding_outcome_is_refused() -> None:
    from quant_research.strategies.sentiment_returns.h2c import pipeline as pl

    # Helper: any session from day0 through day0 + h1 in the spent window is refused; in-window sessions before
    # day0 (beta estimation) are not checked by it.
    sess = ["2013-12-30", "2013-12-31", "2014-01-02", "2014-01-03", "2014-01-06", "2014-01-07", "2014-01-08"]
    pl._refuse_outcome_window("t", sess, 2, 4)
    try:
        pl._refuse_outcome_window("t", sess, 1, 4)
    except errors.HoldoutRefusedError as e:
        assert "outcome row: 2013-12-31" in str(e)
    else:
        raise AssertionError("in-window outcome row not refused")
    crafted = ["2014-01-02", "2014-01-03", "2013-12-31", "2014-01-06"]  # a 2013 row inside the horizon
    _spent(pl._refuse_outcome_window, "t", crafted, 0, 2)
    pl._refuse_outcome_window("t", crafted, 3, 5)  # window past the end is clipped

    # Through run_h2c: a DEV-style call whose price panel carries a 2013 warm-up session (allowed by the input
    # guard: before the partition start and within the lookback) moved so that its return row sits inside a
    # scored event's outcome window. The outcome guard must refuse it.
    p, kw = world(seed=3, dev=True)
    r = run_h2c(p, "T", **kw)
    d0 = min(ev["day0"] for ev in r["events"] if ev["status"] == "included")
    ps = list(kw["price_sessions"])
    moved = ps.pop(ps.index("2013-12-31"))
    ps.insert(ps.index(d0) + 2, moved)
    msg = _spent(run_h2c, p, "T", **dict(kw, price_sessions=ps))
    assert "outcome row: 2013-12-31" in msg


def test_spent_window_bounds_are_inclusive() -> None:
    import datetime as dt

    from quant_research.strategies.sentiment_returns.h2c import pipeline as pl

    assert dt.date(2011, 1, 1) == pl.SPENT_HOLDOUT_LO
    assert dt.date(2013, 12, 31) == pl.SPENT_HOLDOUT_HI
    for v in (
        "2011-01-01",
        "2013-12-31",
        "2012-07-04T00:00:00",
        dt.date(2012, 1, 1),
        dt.datetime(2013, 5, 1, 9, tzinfo=dt.UTC),
    ):
        assert pl._in_spent_window(v)
    outside: tuple[object, ...] = ("2010-12-31", "2014-01-01", dt.date(2015, 1, 1), "", None, "not a date", 2012)
    for w in outside:
        assert not pl._in_spent_window(w)
