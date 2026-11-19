import math

from quant_research.strategies.sentiment_returns.h2c import errors, run_h2c
from quant_research.strategies.sentiment_returns.h2c.config import HoldoutExpectations

from ._h2c_synth import SYMS, world


def _raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return
    raise AssertionError(f"{exc.__name__} not raised")


def test_pipeline_runs_and_is_deterministic():
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


def test_planted_signal_is_recovered():
    p, kw = world(seed=11, planted=0.05)
    r = run_h2c(p, "T", **kw)
    assert r["stats"]["mean_ic"] > 0.5 and r["stats"]["G0_pass"]
    p0, kw0 = world(seed=11, planted=0.0)
    assert run_h2c(p0, "T", **kw0)["stats"]["mean_ic"] < r["stats"]["mean_ic"]


def test_holdout_gate_needs_runtime_expectations():
    p, kw = world(seed=3)
    pc = run_h2c(p, "T", **kw)["counts"]["purge"]
    _raises(errors.ConfigError, run_h2c, p, "T", purge_reference=pc, **kw)
    _raises(errors.PurgeMismatch, run_h2c, p, "T", purge_reference=dict(pc, kept=0),
            expectations=HoldoutExpectations(purge=pc), **kw)
    r = run_h2c(p, "T", purge_reference=pc, expectations=HoldoutExpectations(purge=dict(pc)), dev_mean_ic=0.0, **kw)
    assert "G2" in r["stats"] and r["stats"]["dev_mean_ic_frozen"] == 0.0


def test_partition_violations_stop():
    p, kw = world(seed=3)
    bad = list(kw["earnings_rows"]) + [dict(kw["earnings_rows"][0], reportedDate="2021-02-01", fiscalDateEnding="2020-12-31")]
    _raises(errors.PartitionError, run_h2c, p, "T", **dict(kw, earnings_rows=bad))
    early = list(kw["earnings_rows"]) + [dict(kw["earnings_rows"][0], reportedDate="2017-11-01", fiscalDateEnding="2017-09-30")]
    _raises(errors.PartitionError, run_h2c, p, "T", **dict(kw, earnings_rows=early))
    _raises(errors.MappingError, run_h2c, p, "T", **dict(kw, transcript_keys=list(kw["transcript_keys"]) + [(SYMS[0], "2016Q1")]))


def test_exclude_mapped_before_counts_and_occupies():
    from quant_research.strategies.sentiment_returns.h2c.config import params_from_dict
    from ._h2c_synth import params

    base = params()
    t = base.partition("T")
    d = {k: getattr(base, k) for k in ("universe", "hedge", "beta_n", "h0", "h1", "lag", "nprior_max", "nprior_min",
                                       "tone_min", "q_min_events", "quantile_div")}
    d["partitions"] = dict(T=dict(lo="2018-01-01", hi=t.hi, score_lo=t.score_lo, scored_years=[2019, 2020],
                                  g0_min_quarters=6, purge_window=list(t.purge_window), purge_boundary="2020",
                                  exclude_mapped_before="2018-07-01"))
    p = params_from_dict(d)
    _, kw = world(seed=3)
    r = run_h2c(p, "T", **kw)
    m = r["counts"]["mapping"]
    assert m["excluded_mapped"] == len(SYMS)  # only 2018Q1 calls are reported before 2018-07-01
    assert m["mapped"] + m["excluded_mapped"] == m["listed"]
