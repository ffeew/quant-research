"""Synthetic tests for runner.py. Reader is MOCKED; no real chain/spot/dates file is read."""

import os
import random
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from quant_research.strategies.iv_gap import runner as R
from quant_research.utils.pins import desk_pin


def trading_days():
    d, out = date(2008, 1, 2), []
    while d < date(2016, 6, 1):
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def synth_chain(
    trade_date,
    S=100.0,
    F=100.5,
    DF=0.999,
    sigma=0.20,
    av_bias=0.0,
    root="SPY",
    expiries=(30,),
    strikes=None,
    extra=None,
):
    td = date.fromisoformat(trade_date)
    rows = []
    strikes = strikes or [80 + 2.5 * i for i in range(17)]
    for dte in expiries:
        exp = (td + timedelta(days=dte)).isoformat()
        T = dte / 365.0
        for K in strikes:
            for cp, t in (("C", "call"), ("P", "put")):
                p = R.black76(F, K, T, DF, sigma, cp)
                bid, ask = p * 0.99, p * 1.01
                rows.append(
                    {
                        "date": trade_date,
                        "expiration": exp,
                        "strike": str(K),
                        "type": t,
                        "bid": "%.6f" % bid,
                        "ask": "%.6f" % ask,
                        "mark": "%.6f" % p,
                        "implied_volatility": "%.6f" % (sigma + av_bias),
                        "contractID": root + exp + t + str(K),
                    }
                )
    rows.extend(extra or [])
    return rows


class MockReader:
    """Mirrors reader semantics: SPY/QQQ only, refuses QQQQ and dates >= 2016-06-01 (raises)."""

    def __init__(self, chain_fn=None, spot=100.0, dates=None, missing_spot=()):
        self.chain_fn = chain_fn or (lambda sym, d: synth_chain(d))
        self.spot, self.dates, self.missing_spot = spot, dates, set(missing_spot)
        self.calls = []

    def _g(self, sym, d=None):
        if sym not in ("SPY", "QQQ"):
            raise ValueError("UNKNOWN_SYMBOL %s" % sym)
        if d is not None and date.fromisoformat(d) >= date(2016, 6, 1):
            raise ValueError("HOLDOUT_RANGE")

    def list_dev_dates(self, sym):
        self._g(sym)
        self.calls.append(("dates", sym))
        return tuple(self.dates if self.dates is not None else trading_days())

    def read_underlying_spot(self, sym, s, e):
        self._g(sym, s)
        self._g(sym, e)
        self.calls.append(("spot", sym, s))
        return [] if s in self.missing_spot else [{"date": s, "close": str(self.spot)}]

    def read_option_chain(self, sym, s, e):
        self._g(sym, s)
        self._g(sym, e)
        self.calls.append(("chain", sym, s))
        return self.chain_fn(sym, s)


def mock_map_option_root(root, d):
    """Reader-contract mirror (api.map_option_root): QQQQ before 2011-03-23, QQQ on/after."""
    d = date.fromisoformat(d)
    if d >= date(2016, 6, 1):
        raise ValueError("HOLDOUT_RANGE")
    if root == "QQQQ":
        if d >= date(2011, 3, 23):
            raise ValueError("CROSS_ERA_ROOT")
        return "QQQ"
    if root == "QQQ":
        if d < date(2011, 3, 23):
            raise ValueError("CROSS_ERA_ROOT")
        return "QQQ"
    return root


class T(unittest.TestCase):
    def tmp(self):
        return os.path.join(tempfile.mkdtemp(), "run")

    # Black-76 round trip
    def test_b76_roundtrip(self):
        for cp in "CP":
            for K in (70, 90, 100, 110, 130):
                for sig in (0.05, 0.2, 0.6, 1.5):
                    for T_ in (3 / 365, 0.25, 1.0):
                        p = R.black76(100, K, T_, 0.99, sig, cp)
                        intr = 0.99 * max((100 - K) if cp == "C" else (K - 100), 0)
                        if p - intr < 1e-6:  # no time value: sigma not identifiable (FREEZE_NOTE A-9)
                            continue
                        iv = R.implied_vol_b76(p, 100, K, T_, 0.99, cp)
                        self.assertIsNotNone(iv)
                        self.assertAlmostEqual(iv, sig, delta=1e-5)

    def test_b76_no_bracket_is_iv_fail(self):
        self.assertIsNone(R.implied_vol_b76(10.0, 100, 80, 0.25, 0.99, "C"))  # below sigma=1e-4 price (intrinsic 19.8)
        self.assertIsNone(R.implied_vol_b76(1000.0, 100, 100, 0.25, 0.99, "C"))  # above sigma=5 price

    def test_brent_params(self):
        self.assertEqual((R.IV_LO, R.IV_HI, R.IV_XTOL, R.IV_MAXIT), (1e-4, 5.0, 1e-8, 200))

    # parity OLS
    def test_parity_recovery(self):
        F, DF, S = 101.3, 0.987, 100.0
        pairs = {K: (R.black76(F, K, 0.5, DF, 0.2, "C"), R.black76(F, K, 0.5, DF, 0.2, "P")) for K in range(80, 121, 5)}
        got = R.parity_fit(pairs, S)
        self.assertAlmostEqual(got[0], F, places=8)
        self.assertAlmostEqual(got[1], DF, places=10)

    def test_parity_fail_rules(self):
        mk = lambda F, DF, ks: {K: (DF * (F - K) + 5, 5.0) for K in ks}
        self.assertIsNone(R.parity_fit(mk(100, 0.99, [99, 100]), 100))  # < 3 pairs
        self.assertIsNotNone(R.parity_fit(mk(100, 0.99, [98, 99, 100]), 100))  # exactly 3 ok
        self.assertIsNone(R.parity_fit(mk(100, 0.95, [98, 99, 100, 101, 102]), 100))  # DF=0.95 excluded
        self.assertIsNotNone(R.parity_fit(mk(100, 0.95001, [98, 99, 100, 101, 102]), 100))
        self.assertIsNotNone(R.parity_fit(mk(100, 1.00999, [98, 99, 100, 101, 102]), 100))  # DF<=1.01 included
        self.assertIsNone(R.parity_fit(mk(100, 1.0101, [98, 99, 100, 101, 102]), 100))
        self.assertIsNotNone(R.parity_fit(mk(109.999, 0.99, [98, 99, 100, 101, 102]), 100))  # F/S<=1.10 in
        self.assertIsNone(R.parity_fit(mk(110.001, 0.99, [98, 99, 100, 101, 102]), 100))
        self.assertIsNotNone(R.parity_fit(mk(90.001, 0.99, [98, 99, 100, 101, 102]), 100))  # F/S>=0.90 in
        self.assertIsNone(R.parity_fit(mk(89.999, 0.99, [98, 99, 100, 101, 102]), 100))

    def test_no_clamping(self):
        # DF just outside: must fail, never be clamped
        self.assertIsNone(R.parity_fit({K: (0.94 * (100 - K) + 5, 5.0) for K in (98, 99, 100, 101, 102)}, 100))

    # 5-nearest strikes
    def test_five_nearest(self):
        self.assertEqual(R.nearest_strikes([90, 95, 99, 100, 101, 105, 110, 120], 100.2), [100, 101, 99, 105, 95])
        self.assertEqual(R.nearest_strikes([98, 102, 99, 101, 100, 103, 97], 100), [100, 99, 101, 98, 102])

    def test_five_nearest_uses_only_valid_pairs(self):
        # strike 100 has only a call valid -> not a pair -> fit uses 5 nearest among pairs
        F, DF = 100.0, 0.99
        pairs = {
            K: (R.black76(F, K, 0.5, DF, 0.2, "C"), R.black76(F, K, 0.5, DF, 0.2, "P"))
            for K in (90, 95, 105, 110, 115, 120)
        }
        # a wildly off pair far away (120) must NOT be used when 5 nearer exist
        pairs[120] = (999.0, 0.0)
        got = R.parity_fit(pairs, 100.0)
        self.assertAlmostEqual(got[0], F, places=8)

    # sampling determinism
    def test_sampling_deterministic_and_seeded(self):
        days = trading_days()
        a, nd = R.sample_dates("SPY", days)
        b, _ = R.sample_dates("SPY", list(reversed(days)))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 89)
        self.assertEqual(nd, [])
        ym = "2012-07"
        cands = sorted(d for d in days if d.startswith(ym))
        self.assertEqual(a[ym], random.Random("20261113:SPY:2012-07").sample(cands, 1)[0])
        q, _ = R.sample_dates("QQQ", days)
        self.assertNotEqual(a, q)
        self.assertTrue(all("2009-01" <= k <= "2016-05" for k in a))
        self.assertEqual(len(R.dev_months()), 89)

    def test_sampling_no_date_logged(self):
        days = [d for d in trading_days() if not d.startswith("2010-02")]
        p, nd = R.sample_dates("SPY", days)
        self.assertEqual(nd, ["2010-02"])
        self.assertNotIn("2010-02", p)

    # QQQQ -> QQQ (mapping is reader-side; runner never maps and never requests QQQQ)
    def test_qqqq_mapping_reader_side(self):
        self.assertEqual(mock_map_option_root("QQQQ", "2011-03-22"), "QQQ")
        self.assertRaises(ValueError, mock_map_option_root, "QQQQ", "2011-03-23")
        self.assertEqual(mock_map_option_root("QQQ", "2011-03-23"), "QQQ")
        self.assertRaises(ValueError, mock_map_option_root, "QQQ", "2011-03-22")
        m = MockReader(chain_fn=lambda s, d: synth_chain(d, root="QQQQ" if d < "2011-03-23" else s))
        R.run(self.tmp(), m)
        syms = {c[1] for c in m.calls}
        self.assertEqual(syms, {"SPY", "QQQ"})
        self.assertNotIn("QQQQ", R.SYMBOLS)
        self.assertNotIn("map_option_root", open(R.__file__).read().split("def run(")[1])

    # holdout refusal
    def test_holdout_listed_date_stops(self):
        m = MockReader(dates=[*trading_days(), "2016-06-01"])
        self.assertRaises(R.RunStop, R.run, self.tmp(), m)

    def test_holdout_row_stops(self):
        self.assertRaises(
            R.RunStop, R.process_day, [dict(synth_chain("2016-05-31")[0], date="2016-06-01")], 100.0, "2016-06-01"
        )

    def test_never_requests_holdout(self):
        m = MockReader()
        R.run(self.tmp(), m)
        for c in m.calls:
            if len(c) == 3:
                self.assertLess(c[2], "2016-06-01")

    # n>=20 gate
    def test_n20_gate(self):
        self.assertEqual(R._stats([0.01] * 19)[1:], ["", "", "", ""])
        self.assertEqual(R._stats([0.01] * 19)[0], 19)
        s = R._stats([0.01] * 20)
        self.assertEqual(s[0], 20)
        self.assertNotEqual(s[1], "")

    # flag/drop boundaries
    def test_flag_drop_boundaries(self):
        self.assertFalse(R.is_flag(0.05))
        self.assertTrue(R.is_flag(0.0500001))
        self.assertTrue(R.is_flag(-0.06))
        self.assertFalse(R.is_drop(0.10))
        self.assertTrue(R.is_drop(0.1000001))
        self.assertTrue(R.is_drop(-0.11))
        self.assertFalse(R.is_flag(-0.05))
        self.assertFalse(R.is_drop(-0.10))

    def test_rates_over_legs(self):
        gaps = [0.0] * 17 + [0.06, 0.11, -0.2]
        s = R._stats(gaps)
        self.assertEqual(s[3], "%.6f" % (3 / 20))
        self.assertEqual(s[4], "%.6f" % (2 / 20))

    # cell usable rule / kill
    def test_cell_usable(self):
        self.assertTrue(R.cell_usable(20, 0.10))
        self.assertFalse(R.cell_usable(20, 0.1000001))
        self.assertFalse(R.cell_usable(19, 0.0))

    def test_symbol_year_kill(self):
        self.assertFalse(R.symbol_year_killed(0.10))
        self.assertTrue(R.symbol_year_killed(0.1000001))

    def test_kill_end_to_end_rates(self):
        # every kept leg has gap 0.2 -> symbol-year drop_rate 1.0 -> killed by rule
        m = MockReader(chain_fn=lambda s, d: synth_chain(d, av_bias=0.2))
        out = R.run(self.tmp(), m)
        rows = [l.split(",") for l in open(os.path.join(out, "coverage.csv")).read().splitlines()[1:]]
        for r in rows:
            self.assertTrue(R.symbol_year_killed(float(r[-1])))

    # buckets
    def test_buckets(self):
        self.assertEqual(R.mny_bucket(-0.30), "[-0.3,-0.15)")
        self.assertEqual(R.mny_bucket(0.30), "[0.15,0.3]")
        self.assertEqual(R.mny_bucket(0.025), "[0.025,0.075)")
        self.assertEqual(R.dte_bucket(3), "[3,8)")
        self.assertEqual(R.dte_bucket(365), "[181,366)")
        self.assertIsNone(R.dte_bucket(366))

    # exclusions incl. straddle
    def test_straddle_excluded(self):
        extra = [dict(synth_chain("2012-03-05")[0], type="straddle", contractID="X")]
        out = R.process_day(synth_chain("2012-03-05", extra=extra), 100.0, "2012-03-05")
        self.assertEqual(out["non_cp"], 1)
        self.assertEqual(out["seen"], 34)
        self.assertEqual(sum(out["excl"].values()) + len(out["kept"]), 34)

    def test_exclusion_order_and_counts(self):
        d = "2012-03-05"
        base = synth_chain(d)
        b0 = base[0]
        extra = [
            dict(b0, bid="1.0", ask="0.5"),
            dict(b0, bid="", ask="1"),  # crossed x2
            dict(b0, bid="0", ask="0.5"),  # zero_bid
            dict(b0, implied_volatility=""),
            dict(b0, implied_volatility="0"),
        ]  # av_iv_missing x2
        b = R.process_day(base, 100.0, d)
        out = R.process_day(base + extra, 100.0, d)
        self.assertEqual(out["excl"]["crossed"] - b["excl"]["crossed"], 2)
        self.assertEqual(out["excl"]["zero_bid"] - b["excl"]["zero_bid"], 1)
        self.assertEqual(out["excl"]["av_iv_missing"] - b["excl"]["av_iv_missing"], 2)
        self.assertEqual(out["excl"]["mny_out"], 0)
        self.assertEqual(len(out["kept"]), len(b["kept"]))
        self.assertGreaterEqual(len(b["kept"]), 30)
        self.assertEqual(out["seen"], 39)
        for _, _, _, g in out["kept"]:
            self.assertAlmostEqual(g, 0.0, delta=1e-4)

    def test_dte_and_mny_scope(self):
        d = "2012-03-05"
        rows = synth_chain(d, expiries=(2, 30, 400), strikes=[60, 100, 140], sigma=0.9)
        rows += synth_chain(d, expiries=(30,), strikes=[95, 97.5, 102.5, 105], sigma=0.9)
        out = R.process_day(rows, 100.0, d)
        self.assertEqual(out["excl"]["zero_bid"] + out["excl"]["dte_lt_3"], 6)  # zero_bid precedes dte_lt_3
        self.assertEqual(out["excl"]["dte_lt_3"], 4)
        self.assertEqual(out["excl"]["dte_gt_365"], 6)
        self.assertEqual(out["excl"]["mny_out"], 4)  # K=60,140 at 30d, C+P

    def test_parity_fail_whole_expiry(self):
        d = "2012-03-05"
        rows = synth_chain(d, strikes=[100, 105])  # only 2 pairs
        out = R.process_day(rows, 100.0, d)
        self.assertEqual(out["excl"]["parity_fail"], 4)
        self.assertEqual(out["kept"], [])

    def test_below_intrinsic(self):
        d = "2012-03-05"
        rows = synth_chain(d)
        deep = [r for r in rows if r["type"] == "call" and float(r["strike"]) == 85.0][0]
        deep.update(bid="5.0", ask="5.02")
        out = R.process_day(rows, 100.0, d)
        self.assertGreaterEqual(out["excl"]["below_intrinsic"], 1)

    def test_no_greek_fields_used(self):
        src = open(R.__file__).read()
        for g in ("delta", "gamma", "vega", "theta", "rho"):
            self.assertNotIn('"%s"' % g, src)

    def test_no_underlying(self):
        days = trading_days()
        picks, _ = R.sample_dates("SPY", days)
        m = MockReader(missing_spot=[picks["2013-04"]])
        out = R.run(self.tmp(), m)
        cov = open(os.path.join(out, "coverage.csv")).read().splitlines()
        row = [l for l in cov if l.startswith("SPY,2013,")][0].split(",")
        self.assertEqual(row[4], "1")
        self.assertEqual(row[2], "11")

    # N ledger
    def test_n_ledger(self):
        self.assertEqual(R.n_ledger(False), 3)
        self.assertEqual(R.n_ledger(True), 4)
        self.assertEqual(dict(R.N_LEDGER), {"F1": 1, "F1b": 1, "F1c": 1, "F2": 0, "F3": 1})

    # outputs / overwrite
    def test_outputs_and_perms(self):
        out = R.run(self.tmp(), MockReader())
        self.assertEqual(sorted(os.listdir(out)), sorted(R.OUTPUT_FILES))
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o555)
        for n in R.OUTPUT_FILES:
            self.assertEqual(os.stat(os.path.join(out, n)).st_mode & 0o777, 0o444)
        gs = open(os.path.join(out, "gap_stats.csv")).read()
        self.assertNotIn("implied_volatility", gs)
        self.assertNotIn("2012-03-", gs)  # no per-date rows
        log = open(os.path.join(out, "run.log")).read()
        self.assertIn("n_ledger_total\t4", log)
        san = open(os.path.join(out, "sanity_bidask.csv")).read().splitlines()
        self.assertTrue(san[1].startswith("QQQ,2009,") and san[9].startswith("SPY,2009,"))

    def test_refuse_overwrite(self):
        p = self.tmp()
        os.mkdir(p)
        self.assertRaises(R.RunStop, R.run, p, MockReader())
        out = R.run(self.tmp(), MockReader())
        self.assertRaises(R.RunStop, R.prepare_run_dir, out)

    def test_output_name_allowlist(self):
        d = tempfile.mkdtemp()
        self.assertRaises(R.RunStop, R.write_new, d, "extra.csv", "x")

    def test_key_in_env_stops(self):
        os.environ["ALPHAVANTAGE_API_KEY"] = "dummy-test-value"
        try:
            self.assertRaises(R.RunStop, R.guard_env)
        finally:
            del os.environ["ALPHAVANTAGE_API_KEY"]

    def test_rule6_budget(self):
        ticks = iter(range(0, 10**6, 10**4))
        self.assertRaises(R.RunStop, R.run, self.tmp(), MockReader(), None, lambda: next(ticks))

    def test_static_pins(self):
        # pins come from the desk pin file (PENDING in the public copy)
        for name in ("PREREG_SHA256", "W1D_CP_SUMS_SHA256", "DEV_DATES_SHA256"):
            self.assertEqual(getattr(R, name), desk_pin("strategies.iv_gap.runner", name))
        bad = dict(R.EXPECTED_PINS, DEV_BOUND="2016-07-01")

        class A:
            @staticmethod
            def pins():
                return bad

        self.assertRaises(R.RunStop, R.verify_reader_pins, A)


if __name__ == "__main__":
    unittest.main(verbosity=2)
