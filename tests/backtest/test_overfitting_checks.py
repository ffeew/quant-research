"""Shared behavioural tests for the overfitting checks in quant_research.backtest.validation.

* Deflated Sharpe ratio (Bailey & Lopez de Prado 2014, eq. 1-2): `dsr`.
* Purged + embargoed K-fold cross-validation (Lopez de Prado 2018, ch. 7): `purged_kfold`.
* Hold-out guard: `assert_before_holdout` (and its enforcement inside `purged_kfold`).

All data is synthetic and generated here from a seeded numpy RNG; dates are deliberately in 2000-2001 and the
hold-out cutoff is always passed as a parameter. No files are read.
"""

import itertools
import math
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from quant_research.backtest import validation as V

EULER_GAMMA = 0.5772156649015329
CUTOFF = pd.Timestamp("2001-07-02")  # synthetic hold-out start used only in these tests


def _returns(values: Any, start: str = "2000-01-03") -> pd.Series:
    values = np.asarray(values, dtype=float)
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def _rng(seed: int = 20000103) -> np.random.Generator:
    return np.random.default_rng(seed)


def _match_moments(x: Any, mean: float = 0.001, sd: float = 0.01) -> np.ndarray:
    """Affine map of x onto a fixed sample mean and std. Skew and kurtosis are affine-invariant, so they are kept."""
    arr = np.asarray(x, dtype=float)
    return mean + sd * (arr - arr.mean()) / arr.std(ddof=1)


# ------------------------------------------------------------------------------------------------ deflated Sharpe
def _dsr_by_hand(r: Any, trial_srs: Any, n_trials: int) -> tuple[float, float]:
    """Independent evaluation of Bailey & Lopez de Prado (2014):

    SR0 = sqrt(V[SR_n]) * ((1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N e)))           (expected max of N trials)
    DSR = Z( (SR - SR0) * sqrt(T - 1) / sqrt(1 - g3 * SR + (g4 - 1) / 4 * SR^2) )
    with SR the per-period Sharpe, g3 the skewness and g4 the (non-excess) kurtosis of the selected returns.
    Moments use the bias-corrected sample estimators (scipy bias=False), computed here, not by the code under test."""
    x = np.asarray(r, dtype=float)
    T = len(x)
    sr = x.mean() / x.std(ddof=1)
    g3 = stats.skew(x, bias=False)
    g4 = stats.kurtosis(x, fisher=False, bias=False)
    v = np.var(trial_srs, ddof=1)
    sr0 = math.sqrt(v) * (
        (1 - EULER_GAMMA) * stats.norm.ppf(1 - 1 / n_trials) + EULER_GAMMA * stats.norm.ppf(1 - 1 / (n_trials * math.e))
    )
    z = (sr - sr0) * math.sqrt(T - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr**2)
    return stats.norm.cdf(z), sr0


# Small fixed example: 12 daily returns with an obvious positive drift, 5 logged trial Sharpes, N = 5 trials.
FIXED_R = [0.012, -0.004, 0.007, 0.010, -0.002, 0.015, 0.003, -0.008, 0.011, 0.006, 0.009, -0.001]
FIXED_TRIALS = np.array([0.05, 0.10, 0.12, 0.20, 0.30])


def test_dsr_matches_hand_computed_formula() -> None:
    expected, sr0 = _dsr_by_hand(FIXED_R, FIXED_TRIALS, 5)
    out = V.dsr(_returns(FIXED_R), FIXED_TRIALS, 5)
    assert out["SR0_daily"] == pytest.approx(sr0, rel=1e-9)
    assert out["DSR"] == pytest.approx(expected, rel=1e-6, abs=1e-9)
    assert out["T"] == len(FIXED_R) and out["N"] == 5
    # Sanity on the example itself: positive Sharpe well above the trial benchmark gives a DSR well above 0.5.
    assert 0.5 < expected < 1.0


def test_dsr_matches_formula_on_seeded_series() -> None:
    r = _rng(1).normal(0.0006, 0.01, 750)
    trials = _rng(2).normal(0.02, 0.015, 40)
    expected, _ = _dsr_by_hand(r, trials, 40)
    assert V.dsr(_returns(r), trials, 40)["DSR"] == pytest.approx(expected, rel=1e-6, abs=1e-9)


def test_dsr_single_trial_benchmark_is_zero() -> None:
    out = V.dsr(_returns(FIXED_R), np.array([0.1]), 1)
    assert out["SR0_daily"] == 0.0


def test_dsr_decreases_as_number_of_trials_grows() -> None:
    r = _returns(_rng(3).normal(0.0008, 0.01, 500))
    trials = _rng(4).normal(0.0, 0.02, 50)
    vals = [V.dsr(r, trials, n)["DSR"] for n in (2, 5, 10, 50, 100, 1000, 10000)]
    assert all(b < a for a, b in itertools.pairwise(vals)), vals


def test_dsr_falls_when_skew_becomes_more_negative() -> None:
    # Positively skewed sample and its reflection about the mean: same mean, std and kurtosis, skew negated.
    x = _match_moments(_rng(5).lognormal(0.0, 0.6, 500))
    x_neg = 2 * x.mean() - x
    assert stats.skew(x) > 0 > stats.skew(x_neg)
    one = np.array([0.0])
    pos, neg = V.dsr(_returns(x), one, 1)["DSR"], V.dsr(_returns(x_neg), one, 1)["DSR"]
    assert neg < pos


def test_dsr_falls_when_kurtosis_rises() -> None:
    # Mirrored (exactly symmetric) samples so skew is 0 for both; same mean and std, only the tails differ.
    rng = _rng(6)
    thin, fat = rng.normal(size=300), rng.standard_t(3, size=300)
    thin, fat = (_match_moments(np.concatenate([z, -z])) for z in (thin, fat))
    assert abs(float(stats.skew(thin))) < 1e-9 and abs(float(stats.skew(fat))) < 1e-9
    assert float(stats.kurtosis(fat)) > float(stats.kurtosis(thin))
    one = np.array([0.0])
    assert V.dsr(_returns(fat), one, 1)["DSR"] < V.dsr(_returns(thin), one, 1)["DSR"]


@pytest.mark.parametrize("seed", range(8))
def test_dsr_is_a_probability(seed: int) -> None:
    rng = _rng(100 + seed)
    r = _returns(rng.normal(rng.normal(0, 0.002), 0.01, 260))
    trials = rng.normal(0, 0.03, 20)
    for n in (1, 2, 20, 500):
        d = V.dsr(r, trials, n)["DSR"]
        assert 0.0 <= d <= 1.0


@pytest.mark.parametrize("n_trials", [0, -3])
def test_dsr_rejects_non_positive_trial_count(n_trials: int) -> None:
    with pytest.raises(ValueError):
        V.dsr(_returns(FIXED_R), FIXED_TRIALS, n_trials)


@pytest.mark.parametrize("n_obs", [1, 2, 3])
def test_dsr_rejects_too_short_series(n_obs: int) -> None:
    with pytest.raises(ValueError):
        V.dsr(_returns(FIXED_R[:n_obs]), FIXED_TRIALS, 5)


def test_dsr_accepts_minimum_length_series() -> None:
    assert V.DSR_MIN_OBS == 4
    out = V.dsr(_returns(FIXED_R[:4]), FIXED_TRIALS, 5)
    assert 0.0 <= out["DSR"] <= 1.0 and out["T"] == 4


def test_dsr_min_length_counts_non_nan_observations() -> None:
    r = _returns([0.01, np.nan, -0.02, 0.005, np.nan])  # 5 rows but only 3 usable returns
    with pytest.raises(ValueError):
        V.dsr(r, FIXED_TRIALS, 5)


@pytest.mark.parametrize("bad", [np.inf, -np.inf])
def test_dsr_rejects_non_finite_inputs(bad: float) -> None:
    r = list(FIXED_R)
    r[3] = bad
    with pytest.raises(ValueError):
        V.dsr(_returns(r), FIXED_TRIALS, 5)
    trials = FIXED_TRIALS.copy()
    trials[1] = bad
    with pytest.raises(ValueError):
        V.dsr(_returns(FIXED_R), trials, 5)


# Regression pin: exact dsr() outputs (float.hex) captured from the ORIGINAL dsr(), before the input checks were
# added, on seeded valid inputs. Case key: (returns seed, trials seed, T, mean, sd, n trial Sharpes, N). The last case
# puts NaNs in every 10th return (dropped by dsr()) and has no trial Sharpes; the sixth is the minimum length T = 4.
DSR_GOLDEN = [
    (
        (11, 4, 250, 0.0005, 0.01, 30, 1),
        {
            "DSR": "0x1.abc62190fa2dep-1",
            "SR_daily": "0x1.fbc7a19d8c13dp-5",
            "SR_ann": "0x1.f7cc12c7e13b5p-1",
            "SR0_daily": "0x0.0p+0",
            "SR0_ann": "0x0.0p+0",
            "N": 1,
            "T": 250,
            "skew": "-0x1.400a49034d8dbp-5",
            "kurt": "0x1.5d4d2c03e289ep+1",
            "V_trial_SR_daily": "0x1.2efb703eecc7ep-10",
            "n_trial_srs": 30,
        },
    ),
    (
        (12, 5, 250, 0.0005, 0.01, 30, 2),
        {
            "DSR": "0x1.74d29c54da00dp-1",
            "SR_daily": "0x1.ad54ad9f7bc37p-5",
            "SR_ann": "0x1.a9f6a2d49a03dp-1",
            "SR0_daily": "0x1.c2c90f9032574p-7",
            "SR0_ann": "0x1.bf3ff0c200d59p-3",
            "N": 2,
            "T": 250,
            "skew": "-0x1.211c837c2b958p-3",
            "kurt": "0x1.6d4497e27ec09p+1",
            "V_trial_SR_daily": "0x1.6f4ad26779227p-11",
            "n_trial_srs": 30,
        },
    ),
    (
        (13, 6, 500, -0.0002, 0.015, 10, 10),
        {
            "DSR": "0x1.0698297d01f12p-3",
            "SR_daily": "0x1.e86b865117998p-8",
            "SR_ann": "0x1.e496d6b8706dap-4",
            "SR0_daily": "0x1.dd5abef1ee871p-5",
            "SR0_ann": "0x1.d99c4736476a7p-1",
            "N": 10,
            "T": 500,
            "skew": "-0x1.3b94a8bc2737ap-4",
            "kurt": "0x1.b1bcf269a2876p+1",
            "V_trial_SR_daily": "0x1.6701b2e1377e9p-10",
            "n_trial_srs": 10,
        },
    ),
    (
        (14, 7, 60, 0.001, 0.02, 2, 100),
        {
            "DSR": "0x1.8801d49297c6ep-1",
            "SR_daily": "0x1.c7a8afea9962bp-4",
            "SR_ann": "0x1.c415c808c2966p+0",
            "SR0_daily": "0x1.05ac65c7919d6p-6",
            "SR0_ann": "0x1.039efd822fa22p-2",
            "N": 100,
            "T": 60,
            "skew": "-0x1.bcf037b507a28p-4",
            "kurt": "0x1.cc2d8e91d8ab0p+1",
            "V_trial_SR_daily": "0x1.4e226c099e5d1p-15",
            "n_trial_srs": 2,
        },
    ),
    (
        (15, 8, 1000, 0.0003, 0.008, 50, 1000),
        {
            "DSR": "0x1.508ec58ae19a8p-5",
            "SR_daily": "0x1.bd77af17cd562p-5",
            "SR_ann": "0x1.b9f93dc2c8d59p-1",
            "SR0_daily": "0x1.c07786c50a9eep-4",
            "SR0_ann": "0x1.bcf30fb4de973p+0",
            "N": 1000,
            "T": 1000,
            "skew": "-0x1.c064debe834ecp-5",
            "kurt": "0x1.5132dc5207bbep+1",
            "V_trial_SR_daily": "0x1.2895463d347dfp-10",
            "n_trial_srs": 50,
        },
    ),
    (
        (16, 9, 4, 0.001, 0.01, 1, 3),
        {
            "DSR": "0x1.931440200ff94p-1",
            "SR_daily": "0x1.9fd894b2f448bp-1",
            "SR_ann": "0x1.9c959d48962bdp+3",
            "SR0_daily": "0x0.0p+0",
            "SR0_ann": "0x0.0p+0",
            "N": 3,
            "T": 4,
            "skew": "-0x1.a9d4fb7999566p+0",
            "kurt": "0x1.68cae6c4823d0p+2",
            "V_trial_SR_daily": "0x0.0p+0",
            "n_trial_srs": 1,
        },
    ),
    (
        (17, 10, 120, 0.0004, 0.012, 0, 7),
        {
            "DSR": "0x1.3754771dd938cp-2",
            "SR_daily": "-0x1.96766b1f3ad1ep-5",
            "SR_ann": "-0x1.93464af23ed52p-1",
            "SR0_daily": "0x0.0p+0",
            "SR0_ann": "0x0.0p+0",
            "N": 7,
            "T": 108,
            "skew": "0x1.26c5b054ed87ap-8",
            "kurt": "0x1.9b9b35bc67ee1p+1",
            "V_trial_SR_daily": "0x0.0p+0",
            "n_trial_srs": 0,
        },
    ),
]


def _golden_inputs(rs: int, ts: int, T: int, mu: float, sd: float, nt: int) -> tuple[pd.Series, np.ndarray]:
    x = np.random.default_rng(rs).normal(mu, sd, T)
    if rs == 17:
        x[::10] = np.nan
    r = pd.Series(x, index=pd.bdate_range("2000-01-03", periods=T))
    return r, np.random.default_rng(ts).normal(0.0, 0.03, nt)


@pytest.mark.parametrize("case,expected", DSR_GOLDEN, ids=[f"case{i}" for i in range(len(DSR_GOLDEN))])
def test_dsr_valid_outputs_are_bit_identical_to_pre_check_version(
    case: tuple[Any, ...], expected: dict[str, Any]
) -> None:
    rs, ts, T, mu, sd, nt, N = case
    r, trials = _golden_inputs(rs, ts, T, mu, sd, nt)
    out = V.dsr(r, trials, N)
    assert set(out) == set(expected)
    got = {k: (v if isinstance(v, int) else float(v).hex()) for k, v in out.items()}
    assert got == expected


# ------------------------------------------------------------------------------------------------ purged K-fold
def _spans(T: int = 240, max_h: int = 10, seed: int = 7) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Synthetic label spans: one observation per business day from 2000-01-03, label horizon 0..max_h days."""
    t0 = pd.bdate_range("2000-01-03", periods=T)
    horizon = _rng(seed).integers(0, max_h + 1, T)
    t1 = pd.DatetimeIndex([t0[min(i + k, T - 1)] for i, k in enumerate(horizon)])
    return t0, t1


@pytest.mark.parametrize("n_splits,embargo", [(3, 0.0), (5, 0.0), (5, 0.02), (7, 0.05)])
def test_purged_kfold_train_never_overlaps_test_label_span(n_splits: int, embargo: float) -> None:
    t0, t1 = _spans()
    for train, test in V.purged_kfold(t0, t1, n_splits, embargo):
        lo, hi = t0[test].min(), t1[test].max()
        overlap = (t1[train] >= lo) & (t0[train] <= hi)
        assert not overlap.any()
        assert not set(train) & set(test)


@pytest.mark.parametrize("n_splits", [2, 4, 6, 9])
def test_purged_kfold_test_folds_partition_every_index_once(n_splits: int) -> None:
    t0, t1 = _spans(T=101)
    tests = [test for _, test in V.purged_kfold(t0, t1, n_splits)]
    assert len(tests) == n_splits
    allidx = np.concatenate(tests)
    assert sorted(allidx.tolist()) == list(range(101))
    assert all(np.all(np.diff(t) == 1) for t in tests)  # contiguous blocks


@pytest.mark.parametrize("embargo", [0.0, 0.01, 0.05, 0.1])
def test_purged_kfold_embargo_removes_configured_fraction_after_each_fold(embargo: float) -> None:
    # Zero-length labels (t1 == t0) so purging removes nothing and only the embargo can shrink the train set.
    T = 200
    t0 = pd.bdate_range("2000-01-03", periods=T)
    h = math.ceil(embargo * T)
    for train, test in V.purged_kfold(t0, t0, 5, embargo):
        after = set(range(test[-1] + 1, min(test[-1] + 1 + h, T)))
        expected = set(range(T)) - set(test.tolist()) - after
        assert set(train.tolist()) == expected


def test_purged_kfold_purges_overlapping_labels_before_and_after_fold() -> None:
    # 20 observations, every label spans 3 days; fold 2 of 4 is positions 5..9 (days 5..11 labelled).
    t0 = pd.bdate_range("2000-01-03", periods=20)
    t1 = pd.DatetimeIndex([t0[min(i + 2, 19)] for i in range(20)])
    train, test = V.purged_kfold(t0, t1, 4)[1]
    assert test.tolist() == [5, 6, 7, 8, 9]
    assert 3 not in train and 4 not in train  # labels running into the fold are purged
    assert {10, 11} & set(train.tolist()) == set()  # starts inside the fold's label span are purged
    assert {0, 1, 2, 12, 13}.issubset(set(train.tolist()))


def test_purged_kfold_is_deterministic() -> None:
    t0, t1 = _spans()
    a, b = V.purged_kfold(t0, t1, 5, 0.03), V.purged_kfold(t0, t1, 5, 0.03)
    assert len(a) == len(b)
    for (tr_a, te_a), (tr_b, te_b) in zip(a, b):
        np.testing.assert_array_equal(tr_a, tr_b)
        np.testing.assert_array_equal(te_a, te_b)


@pytest.mark.parametrize(
    "kwargs", [dict(n_splits=1), dict(n_splits=500), dict(embargo_pct=-0.1), dict(embargo_pct=1.0)]
)
def test_purged_kfold_rejects_bad_parameters(kwargs: dict[str, Any]) -> None:
    t0, t1 = _spans(T=50)
    with pytest.raises(ValueError):
        V.purged_kfold(t0, t1, **kwargs)


def test_purged_kfold_rejects_bad_spans() -> None:
    t0, t1 = _spans(T=50)
    with pytest.raises(ValueError):
        V.purged_kfold(t0[::-1], t1[::-1], 5)  # unsorted starts
    with pytest.raises(ValueError):
        V.purged_kfold(t0, t0 - pd.Timedelta(days=1), 5)  # label ends before it starts
    with pytest.raises(ValueError):
        V.purged_kfold(t0, t1[:-1], 5)  # length mismatch


# ------------------------------------------------------------------------------------------------ hold-out guard
def test_holdout_guard_passes_data_strictly_before_cutoff() -> None:
    ts = pd.bdate_range("2000-01-03", "2001-06-29")
    V.assert_before_holdout(ts, CUTOFF)
    V.assert_before_holdout([CUTOFF - pd.Timedelta(nanoseconds=1)], CUTOFF)


def test_holdout_guard_rejects_timestamp_exactly_at_cutoff() -> None:
    with pytest.raises(V.HoldoutViolation):
        V.assert_before_holdout(pd.DatetimeIndex(["2001-06-29", "2001-07-02"]), CUTOFF)


def test_holdout_guard_rejects_any_timestamp_after_cutoff() -> None:
    ts = pd.bdate_range("2000-01-03", "2001-06-29").append(pd.DatetimeIndex(["2001-09-14"]))
    with pytest.raises(V.HoldoutViolation):
        V.assert_before_holdout(ts, CUTOFF)
    with pytest.raises(V.HoldoutViolation):
        V.assert_before_holdout(ts[::-1], CUTOFF)  # order does not matter


def test_holdout_guard_rejects_missing_timestamps() -> None:
    with pytest.raises(V.HoldoutViolation):
        V.assert_before_holdout(pd.DatetimeIndex(["2000-03-01", None]), CUTOFF)


def test_holdout_violation_is_a_value_error() -> None:
    assert issubclass(V.HoldoutViolation, ValueError)


def test_purged_kfold_enforces_holdout_on_label_starts_and_ends() -> None:
    t0 = pd.bdate_range("2001-01-02", periods=120)
    assert t0[-1] < CUTOFF
    t1 = t0 + pd.Timedelta(days=1)
    V.purged_kfold(t0, t1, 4, holdout_start=CUTOFF + pd.Timedelta(days=30))  # clear of the cutoff: fine
    t1_late = t1[:-1].append(pd.DatetimeIndex([CUTOFF]))  # one label ends on the cutoff
    with pytest.raises(V.HoldoutViolation):
        V.purged_kfold(t0, t1_late, 4, holdout_start=CUTOFF)
    t0_late = pd.bdate_range("2001-03-01", periods=120)  # starts run past the cutoff
    with pytest.raises(V.HoldoutViolation):
        V.purged_kfold(t0_late, t0_late, 4, holdout_start=CUTOFF)
