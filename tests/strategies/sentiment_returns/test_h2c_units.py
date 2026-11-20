import json
import math
import os
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from scipy import stats as st

from quant_research.strategies.sentiment_returns.h2c import config as cfg
from quant_research.strategies.sentiment_returns.h2c import errors, gating, schema, signal, target
from quant_research.strategies.sentiment_returns.h2c import stats as hstats
from quant_research.utils import config as _cfg

from ._h2c_synth import params


def _raises(exc: type[BaseException], fn: Callable[..., object], *a: object, **k: object) -> None:
    try:
        fn(*a, **k)
    except exc:
        return
    raise AssertionError(f"{exc.__name__} not raised")


def test_repo_config_loads_and_has_no_expected_counts() -> None:
    p = cfg.load_h2c_params()
    assert len(p.universe) == 50 and p.hedge == "SPY"
    dev, ho = p.partition("DEV"), p.partition("HOLDOUT")
    assert len(dev.scored_quarters) == 24 and len(ho.scored_quarters) == 12
    assert ho.exclude_mapped_before == ho.lo and dev.exclude_mapped_before is None
    with open(Path(_cfg.CONFIG_DIR) / "sentiment_returns.toml", encoding="utf-8") as fh:
        text = fh.read().lower()
    assert "expected" not in text.split("[h2c]")[1].replace("expected counts are runtime", "")
    _raises(errors.ConfigError, p.partition, "NOPE")


def test_holdout_expectations_runtime_only() -> None:
    old = os.environ.pop(cfg.HOLDOUT_EXPECTED_ENV, None)
    try:
        e = cfg.load_holdout_expectations()
        assert e.purge is None and e.rows is None and e.excluded_mapped is None
        _raises(errors.ConfigError, e.require, "purge")
        with tempfile.TemporaryDirectory() as d:
            fp = os.path.join(d, "exp.json")
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(
                    dict(purge=dict(in_window_rows=3, purged=1, kept=2, excl_no_reporttime=0), excluded_mapped=1), fh
                )
            os.environ[cfg.HOLDOUT_EXPECTED_ENV] = fp
            e = cfg.load_holdout_expectations()
            assert e.purge is not None and e.purge["kept"] == 2 and e.excluded_mapped == 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(dict(purge=dict(in_window_rows=3, purged=1, kept=2)), fh)
            _raises(errors.ConfigError, cfg.load_holdout_expectations)
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(dict(purge=dict(in_window_rows=3.0, purged=1, kept=2, excl_no_reporttime=0)), fh)
            _raises(errors.ConfigError, cfg.load_holdout_expectations)
    finally:
        os.environ.pop(cfg.HOLDOUT_EXPECTED_ENV, None)
        if old is not None:
            os.environ[cfg.HOLDOUT_EXPECTED_ENV] = old


def test_nw_t_matches_plain_t_at_lag0_and_shrinks_with_positive_autocorr() -> None:
    x = np.array([0.1, 0.2, -0.05, 0.3, 0.15, 0.05])
    assert math.isclose(hstats.nw_t(x, 0), x.mean() / (x.std(ddof=0) / math.sqrt(len(x))))
    y = np.array([1, 1.1, 1.2, 1.1, 1.0, 0.9, 1.0, 1.1]) - 0.9
    assert hstats.nw_t(y, 1) < hstats.nw_t(y, 0)


def test_call_tone_and_surprise() -> None:
    ents = [dict(sentiment=str(v)) for v in (0.1, 0.3, "nan", "x")] + [dict(sentiment=None)]
    n, t = signal.call_tone(ents, tone_min=2)
    assert n == 2 and math.isclose(t, 0.2)
    assert math.isnan(signal.call_tone(ents, tone_min=3)[1])
    prior = [dict(day0=f"2020-0{i}-01", label=f"L{i}", tone=float(i)) for i in range(1, 7)]
    k, s = signal.tone_surprise(10.0, prior, "2020-06-01", nprior_max=4, nprior_min=2)
    assert k == 4 and math.isclose(s, 10 - np.mean([2, 3, 4, 5]))  # strictly earlier day0 only
    assert math.isnan(signal.tone_surprise(1.0, prior[:1], "2020-06-01", 4, 2)[1])


def test_beta_adjusted_target() -> None:
    rng = np.random.default_rng(1)
    sess = [f"d{i:03d}" for i in range(60)]
    m = rng.normal(0, 0.01, 60)
    y = 2 * m + rng.normal(0, 1e-4, 60)
    pm, py = 100 * np.cumprod(1 + m), 50 * np.cumprod(1 + y)
    rows = [dict(symbol="A", date=d, adjusted_close=py[i]) for i, d in enumerate(sess)]
    rows += [dict(symbol="H", date=d, adjusted_close=pm[i]) for i, d in enumerate(sess)]
    panel = target.build_return_panel(rows, sess, ["A", "H"])
    stt, b, raw, tg = target.beta_adjusted_target(panel, "A", "H", sess[30], beta_n=20, h0=1, h1=5)
    assert stt == "" and abs(b - 2) < 0.05
    r = panel.returns
    gj, gm = np.prod(1 + r[32:36, 0]) - 1, np.prod(1 + r[32:36, 1]) - 1
    assert math.isclose(raw, gj) and math.isclose(tg, gj - b * gm)
    assert target.beta_adjusted_target(panel, "A", "H", sess[10], 20, 1, 5)[0] == "excl_beta_warmup"
    assert target.beta_adjusted_target(panel, "A", "H", sess[57], 20, 1, 5)[0] == "excl_missing_target"
    _raises(
        errors.PartitionError, target.build_return_panel, [dict(symbol="A", date="zz", adjusted_close=1.0)], sess, ["A"]
    )
    _raises(errors.SchemaError, target.build_return_panel, rows[:1] * 2, sess, ["A", "H"])


def test_schema_validators() -> None:
    ok = dict.fromkeys(schema.PRICE_KEYS, "1.5")
    rows = schema.parse_prices({"A": [["2020-01-03", ok], ["2020-01-02", ok]]}, ["A"])
    assert [r["date"] for r in rows] == ["2020-01-02", "2020-01-03"]
    _raises(errors.SchemaError, schema.parse_prices, {"A": [["2020-01-03", dict(ok, extra="1")]]}, ["A"])
    _raises(errors.SchemaError, schema.parse_prices, {"A": []}, ["A", "B"])
    er = dict.fromkeys(schema.EARN_KEYS, "x")
    out = schema.parse_earnings({"A": [er], "H": [{"anything": 1}]}, ["A", "H"], held=["H"])
    assert len(out) == 1 and out[0]["symbol"] == "A"
    assert schema.parse_earnings({"A": [er]}, ["A", "B"], exact=False)
    _raises(errors.SchemaError, schema.parse_earnings, {"A": [er]}, ["A", "B"])
    h = "a" * 64
    assert schema.parse_sums(f"{h}  ./A/2020Q1.json\n{h} *B/2020Q2.json\n") == {"A/2020Q1.json": h, "B/2020Q2.json": h}
    _raises(errors.PathError, schema.parse_sums, f"{h}  ../x.json\n")
    _raises(errors.PathError, schema.parse_sums, f"{h}  /abs.json\n")
    _raises(errors.SchemaError, schema.parse_sums, f"{h}  a.json\n{h}  a.json\n")
    assert schema.parse_transcript_label("A/2020Q3.json", ["A"]) == ("A", "2020Q3")
    _raises(errors.SchemaError, schema.parse_transcript_label, "A/2020Q5.json", ["A"])
    b = b"abc"
    assert schema.verify_sha(b, schema.sha256_hex(b)) is b
    _raises(errors.IntegrityError, schema.verify_sha, b, "0" * 64)
    ent = dict(content="c", sentiment="0.1", speaker="s", title="t")
    assert schema.validate_transcript(dict(symbol="A", quarter="2020Q1", transcript=[ent]), "A", "2020Q1") == [ent]
    _raises(
        errors.MappingError,
        schema.validate_transcript,
        dict(symbol="B", quarter="2020Q1", transcript=[]),
        "A",
        "2020Q1",
    )
    _raises(
        errors.SchemaError,
        schema.validate_transcript,
        dict(symbol="A", quarter="2020Q1", transcript=[{}]),
        "A",
        "2020Q1",
    )


def test_purge_table_and_checks() -> None:
    hdr = "\t".join(schema.PURGE_HEADER)
    text = f"{hdr}\nB1\t5\t2\t3\t0\nB2\t9\t4\t4\t1\n"
    ref = gating.read_purge_row(text, "B2", n_data_rows=2)
    assert ref == dict(in_window_rows=9, purged=4, kept=4, excl_no_reporttime=1)
    _raises(errors.SchemaError, gating.read_purge_row, text, "B3")
    _raises(errors.SchemaError, gating.read_purge_row, text, "B2", n_data_rows=3)
    _raises(errors.SchemaError, gating.read_purge_row, text.replace("\t4\t1", "\tx\t1"), "B2")
    _raises(errors.ConfigError, gating.check_purge, ref, ref, None)
    gating.check_purge(ref, ref, dict(ref))
    _raises(errors.PurgeMismatch, gating.check_purge, dict(ref, kept=5), ref, dict(ref))
    _raises(errors.PurgeMismatch, gating.check_purge, ref, ref, dict(ref, purged=0))
    gating.check_expected_counts(dict(a=1, b=2), dict(a=1, b=2), ["a", "b"])
    _raises(errors.ConfigError, gating.check_expected_counts, dict(a=1), None, ["a"])
    _raises(errors.ConfigError, gating.check_expected_counts, dict(a=1), dict(b=1), ["a"])
    _raises(errors.SchemaError, gating.check_expected_counts, dict(a=1), dict(a=2), ["a"])


def test_assert_events_in_partition() -> None:
    part = params().partition("T")
    ok = dict(symbol="A", reportedDate="2020-05-01", quarter="2020Q2", status="included", ret_end="2020-05-10")
    gating.assert_events_in_partition([ok, dict(ok, status="warmup_not_scored", quarter="2018Q1")], part)
    _raises(errors.PartitionError, gating.assert_events_in_partition, [dict(ok, reportedDate="2021-01-04")], part)
    _raises(errors.PartitionError, gating.assert_events_in_partition, [dict(ok, quarter="2018Q4")], part)
    _raises(errors.PartitionError, gating.assert_events_in_partition, [dict(ok, ret_end="2021-01-05")], part)
    _raises(errors.PartitionError, gating.assert_events_in_partition, [dict(ok, status="candidate", ret_end="")], part)


def _periods(ics: Sequence[float], net: float = 0.01, borrow: float = 0.001) -> list[dict[str, float]]:
    return [
        dict(
            ic=i,
            ls_badj=net + 0.004,
            ls_raw=net,
            net10_badj=net,
            net20_badj=net - 0.004,
            net10_badj_borrow=net - borrow,
            turnover_units=4.0,
        )
        for i in ics
    ]


def test_g1_and_g2_gates() -> None:
    p = params()
    part = p.partition("T")
    qn = dict.fromkeys(part.scored_quarters, 10)
    ics = [0.10, 0.12, 0.09, 0.11, 0.13, 0.10, 0.12, 0.11]
    r1 = hstats.evaluate_g1(_periods(ics), qn, part, p)
    assert r1["G0_pass"] and r1["G1_pass"] and r1["verdict"].startswith("PASS")
    t = hstats.nw_t(np.array(ics), 1)
    assert math.isclose(r1["p_one_sided"], 1 - st.t.cdf(t, df=len(ics) - 1))
    r2 = hstats.evaluate_g2(_periods(ics), qn, part, p, dev_mean_ic=0.1)
    assert r2["G2_pass"] and r2["G2"]["iii"]
    assert not hstats.evaluate_g2(_periods(ics), qn, part, p, dev_mean_ic=0.5)["G2"]["iii"]
    assert not hstats.evaluate_g2(_periods(ics, borrow=0.02), qn, part, p, 0.1)["G2_pass"]
    thin = dict.fromkeys(part.scored_quarters, 1)
    assert not hstats.evaluate_g2(_periods(ics), thin, part, p, 0.1)["G2_pass"]
    one = hstats.evaluate_g2(_periods(ics[:1]), qn, part, p, 0.1)
    assert one["G2_pass"] is False and not any(one["G2"].values())
