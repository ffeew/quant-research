"""ALL fixtures fabricated, not issuer observations. No existing check scripts imported.
2099+ payload dates are a safety namespace, not the historical card's frozen windows.
2020 dates in cost shock / timezone tests are hypothetical boundary inputs ONLY.
"""

import ast
import copy
import hashlib
import json
import math
import unittest
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from fractions import Fraction as F
from pathlib import Path
from typing import cast
from unittest.mock import patch

from quant_research.strategies.rank1_single_name import rank1_core as core
from quant_research.strategies.rank1_single_name import rank1_cost as cost
from quant_research.strategies.rank1_single_name import rank1_inference as inf

HERE = (
    Path(cast(str, __import__("quant_research.strategies.rank1_single_name", fromlist=["_"]).__file__)).resolve().parent
)
H = "a" * 64


def gate():
    docs = {k: ("FABRICATED RECEIPT " + k).encode() for k in core.REQUIRED_EVIDENCE}
    e = {
        k: {
            "status": "VERIFIED_MOCK",
            "approved_by": "SYNTHETIC_VICTOR",
            "document_id": k,
            "sha256": hashlib.sha256(v).hexdigest(),
        }
        for k, v in docs.items()
    }
    g = {
        "synthetic_only": True,
        "sector_spec_sha256": H,
        "sector_freeze_token": H,
        "sector_runlog": {"status": "complete", "prereg_sha256": H, "receipt_sha256": H},
        "evidence": e,
        "family_N": 177,
        "pbo_columns": 23,
        "p1_owner_authorized_at_freeze": True,
        "tomas_binding_signature_verified": True,
        "victor_cost_pin_at_freeze": True,
    }
    return g, docs


def fixture_payload():
    return {
        "synthetic_only": True,
        "schema": "rank1.fabricated.clock.v1",
        "records": [
            {
                "synthetic_only": True,
                "issuer": "SYNTH_FICTIONAL_A",
                "created_at": "2099-03-05T12:00:00Z",
                "updated_at": "2099-03-05T12:00:00Z",
                "retrieved_at": "2099-03-15T12:00:00Z",
            }
        ],
    }


def fake_calendar(days):
    return core.Calendar(
        [
            core.Session(d, datetime.combine(d, time(9, 30), core.ET), datetime.combine(d, time(16), core.ET))
            for d in days
        ]
    )


def synthetic_days(n):
    out = []
    d = date(2099, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return tuple(out)  # fictional calendar; not claiming holiday correctness


def matrix(n, constant=False):
    xs = [1.0 if constant else (1 if i % 2 else -1) / 1024 for i in range(n)]
    return inf.SyntheticMatrix(synthetic_days(n), {k: tuple(xs) for k in inf.IDS}, True)


def measurement(value="10.09", unit="half_bp", basis="09:31", source_sha=H):
    return dict(value=value, unit=unit, basis=basis, source_sha=source_sha)


def fake_fees():
    # INVENTED rates, not actual regulatory history or a supplied price series.
    rows = []
    for side in ("buy", "sell"):
        for comp, r in (
            ("SEC_SECTION_31", "0" if side == "buy" else "0.00001"),
            ("FINRA_TAF", "0" if side == "buy" else "0.0002"),
            ("CAT", "0.00003"),
        ):
            row = dict(
                component=comp, side=side, effective_from="2099-01-01", effective_to="2099-12-31", simulation_rate=r
            )
            if comp == "FINRA_TAF":
                row["cap_usd_per_trade"] = "0.01"
            rows.append(row)
    return dict(intervals=rows, sec_transition_guards=[dict(guard_sessions=["2099-06-03"], guard_rate="0.00002")])


class GatesAndLoader(unittest.TestCase):
    def test_valid_mock_gate_is_not_production_authority(self):
        g, d = gate()
        self.assertTrue(core.validate_mock_gate(g, d))
        with (
            patch("builtins.open", side_effect=AssertionError("must not open any source")),
            self.assertRaises(core.Blocked),
        ):
            core.production_entrypoint("SYNTHETIC_ONLY")

    def test_missing_each_evidence_receipt(self):
        for key in core.REQUIRED_EVIDENCE:
            with self.subTest(key=key):
                g, d = gate()
                del g["evidence"][key]
                with self.assertRaises(core.Blocked):
                    core.validate_mock_gate(g, d)

    def test_mismatched_or_absent_dual_guard(self):
        for mutate in (
            lambda g: g.pop("sector_freeze_token"),
            lambda g: g.update(sector_freeze_token="b" * 64),
            lambda g: g.pop("sector_runlog"),
            lambda g: g["sector_runlog"].update(status="running"),
            lambda g: g["sector_runlog"].update(prereg_sha256="b" * 64),
            lambda g: g["sector_runlog"].pop("receipt_sha256"),
            lambda g: g.update(joint_unseal=True),
            lambda g: g.update(metadata_bypass=True),
        ):
            g, d = gate()
            mutate(g)
            with self.assertRaises(core.Blocked):
                core.validate_mock_gate(g, d)

    def test_no_loader_filesystem_access_before_guard(self):
        g, d = gate()
        g.pop("sector_runlog")
        with (
            patch.object(Path, "resolve", side_effect=AssertionError("guard must come first")),
            self.assertRaises(core.Blocked),
        ):
            core.BoundedFixtureLoader(g, d).load("SYNTHETIC_UNREAD.json")

    def test_receipt_tamper_and_signature_scope(self):
        g, d = gate()
        d["B1"] = b"TAMPERED SYNTHETIC RECEIPT"
        with self.assertRaises(core.Blocked):
            core.validate_mock_gate(g, d)
        for k, v in (
            ("family_N", 176),
            ("family_N", True),
            ("pbo_columns", 24),
            ("tomas_binding_signature_verified", False),
            ("victor_cost_pin_at_freeze", False),
            ("p1_owner_authorized_at_freeze", False),
            ("synthetic_only", False),
        ):
            g, d = gate()
            g[k] = v
            with self.assertRaises(core.Blocked):
                core.validate_mock_gate(g, d)
        g, d = gate()
        g["evidence"]["B1"]["approved_by"] = "Agent assertion"
        with self.assertRaises(core.Blocked):
            core.validate_mock_gate(g, d)

    def setUp(self):
        self.root = core.BoundedFixtureLoader.ROOT
        self.root.mkdir(exist_ok=True)
        self.paths = []

    def tearDown(self):
        for p in self.paths:
            if p.is_symlink() or p.exists():
                p.unlink()

    def put(self, name, contents):
        p = self.root / name
        if p.exists() or p.is_symlink():
            raise RuntimeError("never overwrite an existing fixture")
        p.write_text(contents)
        self.paths.append(p)
        return p

    def test_bounded_fixture_roundtrip(self):
        p = self.put("SYNTHETIC_TEST_valid.json", json.dumps(fixture_payload()))
        g, d = gate()
        self.assertEqual(core.BoundedFixtureLoader(g, d).load(p), fixture_payload())

    def test_arbitrary_path_and_symlink(self):
        g, d = gate()
        l = core.BoundedFixtureLoader(g, d)
        with self.assertRaises(core.Blocked):
            l.load(HERE / "rank1_core.py")
        p = self.root / "SYNTHETIC_TEST_link.json"
        p.symlink_to("SYNTHETIC_NONEXISTENT.json")
        self.paths.append(p)
        with self.assertRaises(core.Blocked):
            l.load(p)

    def test_fixture_payload_rejects_unmarked_historical_and_oversize(self):
        for i, mutate in enumerate(
            (
                lambda p: p.update(synthetic_only=False),
                lambda p: p["records"][0].update(issuer="NOT_FABRICATED"),
                lambda p: p["records"][0].update(created_at="2020-01-01T00:00:00Z"),
                lambda p: p["records"][0].pop("synthetic_only"),
                lambda p: p.update(records=[{}] * 2001),
            )
        ):
            data = fixture_payload()
            mutate(data)
            p = self.put(f"SYNTHETIC_TEST_bad_{i}.json", json.dumps(data))
            g, d = gate()
            with self.assertRaises(core.Blocked):
                core.BoundedFixtureLoader(g, d).load(p)
        for i, raw in enumerate(
            ('{"synthetic_only":true,"synthetic_only":true}', '{"x":NaN}', "[]", "42", "{bad", "x" * 262145)
        ):
            p = self.put(f"SYNTHETIC_TEST_json_{i}.json", raw)
            g, d = gate()
            with self.assertRaises(core.Blocked):
                core.BoundedFixtureLoader(g, d).load(p)


class ClockGridDev(unittest.TestCase):
    def test_exact_registered_grid_and_unconditional_reservation(self):
        g = core.configurations()
        self.assertEqual(len(g), 23)
        self.assertEqual(len({c.id for c in g}), 23)
        self.assertEqual(core.FAMILY_FLOOR, 153 + 2 + 1 + 20 + 1)
        self.assertEqual(sum(c.never_edited for c in g), 1)
        self.assertNotIn("H48_EARNINGS_CONTROL_OPTION_RESERVED_1", {c.id for c in g})
        for delay in (48, 120):
            rows = [c for c in g if c.id.startswith(f"H{delay}_")]
            self.assertEqual(len(rows), 10)
            self.assertEqual({c.hold for c in rows}, {8, 10, 12})
            self.assertEqual({c.stories for c in rows}, {2, 3, 4})
            self.assertEqual({c.tone for c in rows}, {"-0.16", "-0.20", "-0.24"})
            self.assertEqual(sum("JOINT" in c.id for c in rows), 2)

    def test_kmax_updated_delay_exact_and_no_earlier(self):
        c = "2099-03-05T12:00:00Z"
        u = "2099-03-07T12:00:00Z"
        r = "2099-04-01T00:00:00Z"
        a = core.usable_at(c, u, r, 48)
        b = core.usable_at(c, u, r, 120)
        self.assertEqual(a, core.clock(u) + timedelta(hours=48))
        self.assertEqual(b - a, timedelta(hours=72))
        self.assertGreaterEqual(a, core.clock(c))
        self.assertGreaterEqual(a, core.clock(u))

    def test_ne48_both_action_and_background_apply_same_clock_filter(self):
        c = "2099-03-05T12:00:00Z"
        r = "2099-04-01T00:00:00Z"
        self.assertIsNotNone(core.usable_at(c, "2099-03-05T12:00:01Z", r, 48, True))
        self.assertIsNone(core.usable_at(c, "2099-03-05T12:00:01.000001Z", r, 48, True))
        # This proves the record-level kernel, NOT full action/background integration.

    def test_invalid_clocks_and_overflow_fail_closed(self):
        c = "2099-03-05T12:00:00Z"
        r = "2099-04-01T00:00:00Z"
        for bad in (None, "", "2099-03-05T12:00:00", "not-a-clock"):
            with self.assertRaises(core.Blocked):
                core.usable_at(c, bad, r, 48)
        for args in (
            (r, c, r, 48),
            (c, r, c, 48),
            (c, c, r, 47),
            (c, c, r, True),
            ("9999-12-31T23:59:00Z",) * 3 + (120,),
        ):
            with self.assertRaises(core.Blocked):
                core.usable_at(*args)

    def test_strict_cutoff_weekend_and_explicit_holiday(self):
        days = (date(2099, 7, 2), date(2099, 7, 6))  # fictional omission, not an NYSE assertion
        cal = fake_calendar(days)
        cut = cal.cutoff(cal.sessions[0])
        self.assertEqual(cal.earliest(cut - timedelta(microseconds=1)).day, days[0])
        self.assertEqual(cal.earliest(cut).day, days[1])
        self.assertEqual(cal.earliest(cut + timedelta(hours=4)).day, days[1])
        with self.assertRaises(core.Insufficient):
            cal.earliest(cal.cutoff(cal.sessions[-1]))

    def test_dst_spring_and_fall_exchange_clocks(self):
        # Invented metadata timestamps at real timezone boundaries, no observed issuer data.
        for before, after, hour1, hour2 in (
            (date(2020, 3, 6), date(2020, 3, 9), 14, 13),
            (date(2020, 10, 30), date(2020, 11, 2), 13, 14),
        ):
            cal = fake_calendar((before, after))
            a, b = cal.sessions
            self.assertEqual(cal.cutoff(a).astimezone(UTC).hour, hour1)
            self.assertEqual(cal.cutoff(b).astimezone(UTC).hour, hour2)
            self.assertEqual(cal.earliest(cal.cutoff(a)).day, after)

    def test_h120_cannot_arrive_before_h48_across_cutoffs(self):
        cal = fake_calendar(synthetic_days(80))
        for hour in (0, 9, 13, 14, 23):
            c = f"2099-01-01T{hour:02}:25:00Z"
            r = "2099-12-01T00:00:00Z"
            k48 = core.usable_at(c, c, r, 48)
            k120 = core.usable_at(c, c, r, 120)
            self.assertLessEqual(cal.earliest(k48).day, cal.earliest(k120).day)

    def test_bad_session_calendar(self):
        with self.assertRaises(core.Blocked):
            core.Calendar([])
        c = fake_calendar(synthetic_days(2))
        with self.assertRaises(core.Blocked):
            core.Calendar(reversed(c.sessions))
        with self.assertRaises(core.Blocked):
            core.Calendar([c.sessions[0], c.sessions[0]])

    def summaries(self):
        return {c.id: core.DevSummary(30, 12, 0.001, 0.0001) for c in core.configurations()}

    def test_dev_pass_is_not_opening_and_no_winner(self):
        r = core.evaluate_synthetic_dev(self.summaries(), True)
        self.assertEqual(r["disposition"], "SYNTHETIC_ONLY_PASS")
        self.assertFalse(r["detail"]["holdout_opened"])
        self.assertFalse(r["paper_trade_promote_capital_allowed"])

    def test_dev_counts_costs_and_missing_config(self):
        for config, summary, status in (
            ("H48", core.DevSummary(29, 12, 1, 1), "INSUFFICIENT"),
            ("NE48", core.DevSummary(30, 11, 1, 1), "INSUFFICIENT"),
            ("H48_TONE08", core.DevSummary(14, 6, 1, 1), "INSUFFICIENT"),
            ("H120", core.DevSummary(30, 12, 1, 0), "FAIL"),
            ("H48", core.DevSummary(30, 12, float("nan"), 1), "INSUFFICIENT"),
        ):
            s = self.summaries()
            s[config] = summary
            self.assertEqual(core.evaluate_synthetic_dev(s, True)["disposition"], status)
        s = self.summaries()
        s.pop("NE48")
        self.assertEqual(core.evaluate_synthetic_dev(s, True)["disposition"], "BLOCKED")
        with self.assertRaises(core.Blocked):
            core.evaluate_synthetic_dev(s)

    def test_every_report_contains_exact_permanent_labels(self):
        for status in ("BLOCKED", "INSUFFICIENT", "FAIL", "SYNTHETIC_ONLY_PASS"):
            self.assertEqual(core.report(status, "fabricated")["claim_labels"], [core.SHORT_LABEL, core.FULL_LABEL])
        with self.assertRaises(core.Blocked):
            core.report("PASS", "not permitted")


class CostKernels(unittest.TestCase):
    def test_exact_rational_validation(self):
        for x in (True, 1.0, -1, "NaN", D("Infinity"), "1/3", "-2", "junk"):
            with self.assertRaises(core.Blocked):
                cost.rational(x)
        self.assertEqual(cost.rational("0.000001"), F(1, 1000000))

    def test_fee_component_ceiling_and_taf_cap(self):
        f = cost.fill_fees(fake_fees(), "sell", "2099-01-10", 100, "100")
        self.assertEqual(f, {"SEC_SECTION_31": F(10, 100), "FINRA_TAF": F(1, 100), "CAT": F(1, 100)})
        self.assertEqual(cost.cents(F(0)), 0)
        self.assertEqual(cost.cents(F(1, 10000)), F(1, 100))

    def test_per_fill_not_order_rounding_and_buy_zero(self):
        fees = fake_fees()
        a = cost.fee_bps(fees, "buy", "2099-01-10", [(1, 100), (1, 100)], 200)
        b = cost.fee_bps(fees, "buy", "2099-01-10", [(2, 100)], 200)
        self.assertEqual(a, F(1))
        self.assertEqual(b, F(1, 2))
        self.assertEqual(cost.fill_fees(fees, "buy", "2099-01-10", 2, 100)["SEC_SECTION_31"], 0)

    def test_sec_guard_and_inclusive_interval_boundaries(self):
        f = fake_fees()
        self.assertEqual(cost.fee_lookup(f, "SEC_SECTION_31", "sell", "2099-06-03")[0], F(2, 100000))
        for day in ("2099-01-01", "2099-12-31"):
            self.assertEqual(cost.fee_lookup(f, "SEC_SECTION_31", "sell", day)[0], F(1, 100000))
        for day in ("2098-12-31", "2100-01-01", "2099-1-1"):
            with self.assertRaises(core.Blocked):
                cost.fee_lookup(f, "CAT", "buy", day)

    def test_fee_missing_overlap_fractional_quantity_and_duplicate_guard(self):
        f = fake_fees()
        f["intervals"].append(copy.deepcopy(f["intervals"][0]))
        with self.assertRaises(core.Blocked):
            cost.fill_fees(f, "buy", "2099-02-01", 1, 100)
        f = fake_fees()
        f["sec_transition_guards"] *= 2
        with self.assertRaises(core.Blocked):
            cost.fill_fees(f, "sell", "2099-06-03", 1, 100)
        with self.assertRaises(core.Blocked):
            cost.fill_fees(fake_fees(), "buy", "2099-01-01", "1.5", 100)
        with self.assertRaises(core.Blocked):
            cost.fee_bps(fake_fees(), "buy", "2099-01-01", [], 0)

    def test_exact_liquidity_boundaries(self):
        for a, b in (
            ("1000000000.01", 0),
            (1000000000, 1),
            ("200000000.01", 1),
            (200000000, 2),
            (50000000, 2),
            (49999999, 3),
        ):
            self.assertEqual(cost.bucket(a), b)
        for x in (0, None, -1):
            with self.assertRaises(core.Blocked):
                cost.bucket(x)

    def test_spread_full_half_normalization_and_fail_closed(self):
        self.assertEqual(cost.halfspread0931(**measurement("20.18", "full_relative_bp")), D("10.09"))
        self.assertEqual(cost.halfspread0931(**measurement()), D("10.09"))
        for m in (
            measurement(basis="09:30"),
            measurement(unit="dollars"),
            measurement(source_sha=""),
            measurement("0"),
        ):
            with self.assertRaises(core.Blocked):
                cost.halfspread0931(**m)

    def test_signed_entry_and_exit_minima_per_leg(self):
        for a, m, ec, xc in (
            (2000000000, "10.09", "20", "20"),
            (500000000, "23.57", "28.6", "20"),
            (100000000, "42.88", "52.9", "22"),
            (10000000, "53.77", "80", "50"),
        ):
            e = cost.leg_cost(a, "0.000001", 5000, 0, True, measurement(m))
            x = cost.leg_cost(a, "0.000001", 5000, 0, False, measurement(m))
            self.assertEqual(e["c_bp"], D(ec))
            self.assertEqual(x["c_bp"], D(xc))
            self.assertEqual(e["h_eff_bp"], max(2 * cost.DEFAULT[e["bucket"]], D(m)))

    def test_missing_0931_is_blocked_even_default_would_bind(self):
        with self.assertRaises(core.Blocked):
            cost.leg_cost(10000000, ".001", 5000, 0, True)
        with self.assertRaises(core.Blocked):
            cost.leg_cost(10000000, ".001", 5000, 0, False)

    def test_raise_only_model_branch_fee_impact_paper_once(self):
        r = cost.leg_cost(2000000000, ".02", 5000, 100, True, measurement())
        self.assertLess(abs(r["c_bp"] - (D(100) + r["h_eff_bp"] + r["impact_bp"] + D(2))), D("1e-24"))
        r2 = cost.leg_cost(2000000000, ".02", 5000, 101, True, measurement())
        self.assertGreater(r2["c_bp"], r["c_bp"])
        self.assertEqual(cost.leg_cost(100000000, 0, 5000, 0, True, measurement())["impact_bp"], 0)
        with self.assertRaises(core.Blocked):
            cost.leg_cost(100000000, None, 5000, 0, True, measurement())

    def test_primary_global_shock_no_4c_no_doubled_buffer(self):
        self.assertEqual(cost.all_in_bp(20, "primary", "2020-03-02"), 30)
        self.assertEqual(cost.all_in_bp(20, "global_2x", "2020-03-02"), 50)
        for d in ("2020-03-02", "2020-06-30"):
            self.assertEqual(cost.all_in_bp(20, "shock", d), 50)
        for d in ("2020-03-01", "2020-07-01"):
            self.assertEqual(cost.all_in_bp(20, "shock", d), 30)
        with self.assertRaises(core.Blocked):
            cost.all_in_bp(20, "global_2x+shock", "2020-03-02")
        # Entry L2 c28.6 +10 and exit L2 c20 +10 =>68.6 RT bp, not 2*entry.
        self.assertEqual(
            cost.all_in_bp("28.6", "primary", "2099-01-02") + cost.all_in_bp(20, "primary", "2099-01-16"), D("68.6")
        )

    def test_terminal_fallback_original_notional_separate_full_writeoff(self):
        r = cost.terminal_cost(
            5000, 2000000000, ".000001", "2099-01-05", "primary", True, True, measurement=measurement()
        )
        self.assertEqual(r["bucket"], 1)
        self.assertEqual(r["fallback_count"], 1)
        self.assertEqual(r["economic_writeoff_usd"], -5000)
        self.assertEqual(r["fee_bp"], 0)
        self.assertEqual(r["cost_usd"], 15)
        self.assertEqual(r["basis"], "ORIGINAL_ENTRY_NOTIONAL")
        r = cost.terminal_cost(
            5000,
            2000000000,
            ".000001",
            "2099-01-05",
            "global_2x",
            True,
            True,
            last_adv=10000000,
            measurement=measurement(),
        )
        self.assertEqual(r["bucket"], 3)
        self.assertEqual(r["cost_usd"], 55)

    def test_terminal_known_inputs_and_missing_identity_adv_fail_closed(self):
        r = cost.terminal_cost(
            5000,
            2000000000,
            ".000001",
            "2099-01-05",
            "primary",
            True,
            True,
            terminal_adv=100000000,
            terminal_sigma=".000001",
            measurement=measurement(),
        )
        self.assertEqual(r["bucket"], 2)
        self.assertEqual(r["fallback_count"], 0)
        for ident, eff, adv in ((False, True, 2000000000), (True, False, 2000000000), (True, True, None)):
            with self.assertRaises(core.Blocked):
                cost.terminal_cost(5000, adv, ".01", "2099-01-05", "primary", ident, eff, measurement=measurement())


class InferenceKernels(unittest.TestCase):
    def test_partitions_lengths_and_purge_only_cross_labels(self):
        p = inf.partitions(1603)
        self.assertEqual([b - a for a, b in p], [101] * 3 + [100] * 13)
        p = inf.partitions(1600)
        a, b = inf.scoring_segments(p, set(range(8)))
        self.assertEqual(a[-1], (700, 780))
        self.assertEqual(b[0], (820, 900))
        self.assertEqual(a[0], (0, 100))
        self.assertEqual(a[1], (100, 200))
        self.assertEqual(sum(y - x for x, y in a), 780)

    def test_exact23_pbo_all12870_splits_midrank_and_lexical_tie(self):
        r = inf.pbo_synthetic(matrix(1600))
        d = r["detail"]
        self.assertEqual(d["column_count"], 23)
        self.assertEqual(d["split_count"], 12870)
        self.assertEqual(d["pbo"], 1)
        self.assertFalse(d["winner_adopted"])
        self.assertEqual({s["winner"] for s in d["splits"]}, {min(inf.IDS)})
        self.assertEqual({s["OOS_midrank"] for s in d["splits"]}, {12.0})
        self.assertEqual({s["lambda"] for s in d["splits"]}, {0.0})

    def test_pbo_insufficient_split_or_constants_not_dropped(self):
        with self.assertRaises(core.Insufficient):
            inf.pbo_synthetic(matrix(160))
        with self.assertRaises(core.Insufficient):
            inf.pbo_synthetic(matrix(1600, True))

    def test_exact_matrix_schema_no_optional_column_missing_day_or_infinity(self):
        for mutate in (
            lambda m: m.columns.pop("NE48"),
            lambda m: m.columns.update(OPTIONAL=tuple([1] * 100)),
            lambda m: m.columns.update(H48=(0,)),
            lambda m: m.columns.update(H48=tuple([float("inf")] * 100)),
        ):
            m = matrix(100)
            mutate(m)
            with self.assertRaises(core.Blocked):
                m.validate()
        with self.assertRaises(core.Blocked):
            inf.SyntheticMatrix(matrix(100).days, matrix(100).columns).validate()

    def rows(self, n=200):
        days = synthetic_days(n)
        rows = []
        for t, d in enumerate(days):
            r = {k: math.sin((t + 1) * (j + 1) * 0.17) * 0.01 for j, k in enumerate(inf.FACTOR_FIELDS)}
            r.update(day=d.isoformat(), synthetic_only=True)
            rows.append(r)
        return days, rows

    def test_factor_units_once_rf_and_z_already_decimal(self):
        days, rows = self.rows(2)
        dec = inf.join_synthetic_factors(days, rows, "decimal", [-999], True)
        raw = copy.deepcopy(rows)
        for row in raw:
            for k in inf.FACTOR_FIELDS:
                if k != "z":
                    row[k] *= 100
        pct = inf.join_synthetic_factors(days, raw, "raw_percent", [-999], True)
        for a, b in zip(dec, pct):
            for k in inf.FACTOR_FIELDS:
                self.assertAlmostEqual(a[k], b[k])
        self.assertEqual(dec[0]["z"], rows[0]["z"])
        self.assertEqual(dec[0]["RF"], rows[0]["RF"])

    def test_factor_no_fills_duplicates_monthly_proxy_or_missing_strev(self):
        for action in (
            lambda rows: rows.pop(),
            lambda rows: rows.append(copy.deepcopy(rows[0])),
            lambda rows: rows[0].pop("ST_Rev"),
            lambda rows: rows[0].update(ST_Rev=-999),
            lambda rows: rows[0].update(RF=float("nan")),
        ):
            ds, rs = self.rows(40)
            action(rs)
            with self.assertRaises(core.Blocked):
                inf.join_synthetic_factors(ds, rs, "decimal", [-999], True)
        ds, rs = self.rows(40)
        with self.assertRaises(core.Blocked):
            inf.join_synthetic_factors(ds, rs, "unknown", [-999], True)
        with self.assertRaises(core.Blocked):
            inf.join_synthetic_factors(ds, rs, "decimal", None, True)

    def test_fixed_nw20_nine_columns_and_alpha(self):
        ds, rs = self.rows(300)
        f = inf.join_synthetic_factors(ds, rs, "decimal", [-999], True)
        y = [
            0.001 + sum(0.2 / (j + 1) * r[k] for j, k in enumerate(inf.REGRESSORS)) + 0.0001 * math.sin((t + 1) * 0.333)
            for t, r in enumerate(f)
        ]
        r = inf.nw20_synthetic(y, f, True)
        d = r["detail"]
        self.assertEqual(d["p"], 9)
        self.assertEqual(d["lags"], 20)
        self.assertIn("ST_Rev", d["regressors"])
        self.assertIn("z", d["regressors"])
        self.assertAlmostEqual(d["betas"][0], 0.001, delta=0.00001)
        self.assertAlmostEqual(d["finite_sample_factor"], 300 / 291)
        # Metamorphic alpha/covariance invariance check (not external estimator validation).
        # A constant alpha added to y changes alpha only; covariance and t denominator invariant.
        r2 = inf.nw20_synthetic([v + 0.01 for v in y], f, True)["detail"]
        self.assertAlmostEqual(r2["betas"][0] - d["betas"][0], 0.01, places=12)
        self.assertAlmostEqual(r2["covariance"][0][0], d["covariance"][0][0], places=15)
        for j in range(1, 9):
            self.assertAlmostEqual(r2["betas"][j], d["betas"][j], places=11)

    def test_nw20_independent_scalar_projected_score_hac(self):
        ds, rs = self.rows(180)
        f = inf.join_synthetic_factors(ds, rs, "decimal", [-999], True)
        X = [[1.0] + [r[k] for k in inf.REGRESSORS] for r in f]
        y = [
            0.002 + sum((j + 1) * 0.01 * r[k] for j, k in enumerate(inf.REGRESSORS)) + 0.001 * math.cos(t * 0.913)
            for t, r in enumerate(f)
        ]
        p = 9
        T = len(X)
        gram = [[sum(row[i] * row[j] for row in X) for j in range(p)] for i in range(p)]
        inv = inf._inverse(gram)  # same elementary inverse; independent scalar HAC summation below
        rhs = [sum(row[j] * v for row, v in zip(X, y)) for j in range(p)]
        beta = [sum(inv[i][j] * rhs[j] for j in range(p)) for i in range(p)]
        residuals = [v - sum(a * b for a, b in zip(row, beta)) for row, v in zip(X, y)]
        projected = [sum(a * b for a, b in zip(inv[0], row)) * e for row, e in zip(X, residuals)]
        variance = sum(v * v for v in projected)
        for lag in range(1, 21):
            variance += 2 * (1 - lag / 21) * sum(projected[t] * projected[t - lag] for t in range(lag, T))
        variance *= T / (T - p)
        got = inf.nw20_synthetic(y, f, True)["detail"]
        self.assertAlmostEqual(got["covariance"][0][0] / variance, 1.0, places=10)
        self.assertAlmostEqual(got["alpha_t"], beta[0] / math.sqrt(variance), places=8)

    def test_regression_rank_and_length_fail_closed(self):
        ds, rs = self.rows(40)
        f = list(inf.join_synthetic_factors(ds, rs, "decimal", [-999], True))
        for row in f:
            row["ST_Rev"] = row["Mom"]
        with self.assertRaises(core.Insufficient):
            inf.nw20_synthetic([1.0] * 40, f, True)
        with self.assertRaises(core.Insufficient):
            inf.nw20_synthetic([1.0] * 20, f[:20], True)
        with self.assertRaises(core.Blocked):
            inf.nw20_synthetic([1.0] * 40, f)

    def dsr_args(self):
        return dict(
            matrix=matrix(400),
            key="H48",
            N=177,
            sigma_ann=0.75,
            reference_receipt=dict(synthetic_only=True, prototype_count=72, sha256=H, sigma_ann=0.75),
            family_receipt=dict(synthetic_only=True, family_N=177, sha256=H),
        )

    def test_dsr_receipts_required_and_family_floor177(self):
        for k, v in (
            ("N", 176),
            ("sigma_ann", 0.4),
            ("reference_receipt", None),
            ("family_receipt", None),
            ("key", "NE48"),
            ("sigma_ann", 0.76),
        ):
            args = self.dsr_args()
            args[k] = v
            with self.assertRaises(core.Blocked):
                inf.dsr_synthetic(**args)

    def test_dsr_formula_zero_mean_and_serial_bound(self):
        args = self.dsr_args()
        d = inf.dsr_synthetic(**args)["detail"]
        self.assertEqual(d["N"], 177)
        self.assertGreaterEqual(d["T_eff"], 2)
        self.assertLessEqual(d["T_eff"], d["T"])
        self.assertAlmostEqual(d["SR_daily"], 0)
        self.assertGreaterEqual(d["DSR"], 0)
        self.assertLess(d["DSR"], 0.5)
        args["matrix"] = matrix(400, True)
        with self.assertRaises(core.Insufficient):
            inf.dsr_synthetic(**args)

    def test_unimplemented_paths_cannot_silently_default(self):
        with self.assertRaises(core.Blocked):
            inf.bootstrap_pcg64()
        with self.assertRaises(core.Blocked):
            inf.full_oos_evaluator()

    def test_bundle_imports_no_old_check_scripts_or_network_dependencies(self):
        allowed = {
            "__future__",
            "collections",
            "dataclasses",
            "datetime",
            "zoneinfo",
            "pathlib",
            "hashlib",
            "json",
            "math",
            "re",
            "decimal",
            "fractions",
            "itertools",
            "statistics",
            "typing",
            "rank1_core",
        }
        for name in ("rank1_core.py", "rank1_cost.py", "rank1_inference.py"):
            tree = ast.parse((HERE / name).read_text())
            roots = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots.update(x.name.split(".")[0] for x in node.names)
                if isinstance(node, ast.ImportFrom):
                    roots.add(
                        node.module.rsplit(".", 1)[-1]
                        if node.module.startswith("quant_research.strategies.rank1_single_name.")
                        else node.module.split(".")[0]
                    )
            self.assertTrue(roots <= allowed, (name, roots - allowed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
