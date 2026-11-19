"""V1 synthetic mechanics suite — parent §5 + erratum E1–E4.

Amended per validator preflight
the internal review record

(RETURN FOR AMENDMENT — NOT authorised to run).

Deterministic fixture tests only. No market returns, no R1–R7 synthetic P&L,
no production construct/risk_state imports as engines.

Run (ONLY after a future validator AUTHORISE ONE RUN decision — not now):
  python3 --version
  python3 -m unittest discover -s . -p 'test_*.py' -v \
    2>&1 | tee intended-output/pytest-output.txt

Intended output (only): ./intended-output/pytest-output.txt
(mechanics-results.json dropped — no writer; B6)
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from quant_research.strategies.carry.v1_mechanics import (
    DomainError,
    apply_base_derisk,
    apply_restoration,
    apply_v1_clamp,
    is_v1_valid_close,
    run_fixture,
    validate_w_vix_domain,
)

HERE = Path(__file__).resolve().parent
FIXTURES_PATH = HERE / "fixtures.json"


def load_fixtures():
    data = json.loads(FIXTURES_PATH.read_text())
    assert data["meta"]["no_optional_synthetic_pnl"] is True
    assert set(data["meta"]["excluded"]) >= {"R1", "R2", "R3", "R4", "R5", "R6", "R7"}
    assert data["meta"]["planned_outputs"] == ["pytest-output.txt"]
    return {fx["id"]: fx for fx in data["fixtures"]}


FX = load_fixtures()


def _almost(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def _weights_le(prior, after):
    return all(float(v) <= float(prior.get(k, 0.0)) + 1e-12 for k, v in after.items())


class TestV1Mechanics(unittest.TestCase):
    def _run(self, fid):
        self.assertIn(fid, FX, f"missing fixture {fid}")
        return run_fixture(FX[fid])

    # --- Breaker B1–B7 ---
    def test_B1_normal_v1_off_passthrough(self):
        r = self._run("B1")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["breaker"]["state"], "NORMAL")
        self.assertTrue(r["breaker"]["new_trades_allowed"])
        for k, v in FX["B1"]["expect"]["w_final"].items():
            self.assertTrue(_almost(r["log"]["w_final"][k], v), f"{k}")

    def test_B2_normal_v1_on_halves_longs_shorts_flat_unchanged(self):
        r = self._run("B2")
        self.assertEqual(r["vix_state"], "ON")
        exp = FX["B2"]["expect"]["w_vix"]
        for k, v in exp.items():
            self.assertTrue(_almost(r["log"]["w_vix"][k], v), f"{k}")
        self.assertTrue(_almost(r["log"]["w_vix"]["CCC"], -0.05))
        self.assertTrue(_almost(r["log"]["w_vix"]["DDD"], 0.0))

    def test_B3_halved_cannot_exceed_30pct_path(self):
        r = self._run("B3")
        self.assertEqual(r["vix_state"], "ON")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)
        self.assertLessEqual(r["long_gross"], 0.30 + 1e-12)

    def test_B4_halted_no_nta_flip_no_increase(self):
        r = self._run("B4")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["breaker"]["state"], "HALTED")
        self.assertIs(r["breaker"]["new_trades_allowed"], False)
        self.assertTrue(_weights_le(FX["B4"]["prior_weights"], r["log"]["w_final"]))
        # B4: lift_paths are declaration constants only — NOT certified.
        self.assertIs(r["lift_paths_certified"], False)
        self.assertIs(r["lifts"]["lift_paths_certified"], False)

    def test_B5_resumed_disarmed_no_clear_backstop_no_60(self):
        r = self._run("B5")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["breaker"]["state"], "RESUMED_DISARMED")
        self.assertIs(r["breaker"]["fail_safe"], False)
        self.assertLessEqual(r["long_gross"], 0.30 + 1e-12)
        self.assertEqual(r["breaker"]["backstop_equity"], 90000.0)
        self.assertIs(r["breaker"]["halt_armed"], False)
        self.assertIs(r["lift_paths_certified"], False)

    def test_B6_failsafe_breaker_halved_nta_true(self):
        r = self._run("B6")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertIs(r["breaker"]["fail_safe"], True)
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)
        self.assertLessEqual(r["long_gross"], 0.30 + 1e-12)
        self.assertEqual(r["vix_state"], "ON")

    def test_B7_backstop_breach_treated_halted_nta_false(self):
        r = self._run("B7")
        self.assertEqual(r["breaker"]["state"], "HALTED")
        self.assertIs(r["breaker"]["new_trades_allowed"], False)
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)
        self.assertTrue(_weights_le(FX["B7"]["prior_weights"], r["log"]["w_final"]))

    def test_BRK_FS_RESUMED_NO_BACKSTOP(self):
        r = self._run("BRK_FS_RESUMED_NO_BACKSTOP")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertIs(r["breaker"]["fail_safe"], True)
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)

    def test_BRK_FS_HALT_ARMED_FALSE_NORMAL(self):
        r = self._run("BRK_FS_HALT_ARMED_FALSE_NORMAL")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertIs(r["breaker"]["fail_safe"], True)
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)

    # --- Hold ---
    def test_H1_cio_hold_nta_false_no_increase(self):
        r = self._run("H1")
        self.assertEqual(r["breaker"]["state"], "NORMAL")
        self.assertIs(r["breaker"]["new_trades_allowed"], False)
        self.assertIs(r["breaker"]["trading_hold"], True)
        self.assertIs(r["breaker"]["cio_hold"], True)
        self.assertTrue(_weights_le(FX["H1"]["prior_weights"], r["log"]["w_final"]))
        self.assertIs(r["increase_blockers"]["cio_or_ops_hold"], True)

    def test_H2_off_does_not_clear_hold(self):
        r = self._run("H2")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertIs(r["breaker"]["new_trades_allowed"], False)
        self.assertIs(r["breaker"]["trading_hold"], True)
        self.assertTrue(_weights_le(FX["H2"]["prior_weights"], r["log"]["w_final"]))
        self.assertIs(r["lift_paths_certified"], False)

    # --- Panic ---
    def test_P1_panic_false_logs_separate(self):
        r = self._run("P1")
        self.assertEqual(r["vix_state"], "ON")
        self.assertIs(r["panic"]["panic"], False)
        self.assertIs(r["panic"]["binding"], False)
        self.assertTrue(_almost(r["log"]["panic_factor"], 1.0))
        for field in ("m", "panic_factor", "vix_state", "w_base", "w_vix", "w_final"):
            self.assertIn(field, r["log"])

    def test_P2_panic_true_responses_intact(self):
        r = self._run("P2")
        self.assertIs(r["panic"]["panic"], True)
        self.assertIs(r["panic"]["binding"], True)
        self.assertIs(r["panic"]["loser_short_ban"], True)
        self.assertEqual(r["vix_state"], "ON")

    def test_P3_stale_fail_closed_exact_failsafe_panic(self):
        r = self._run("P3")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 3)
        self.assertIs(r["panic"]["panic"], True)
        self.assertIs(r["panic"]["binding"], True)
        self.assertIs(r["panic"]["fail_safe"], True)
        self.assertTrue(_almost(r["panic"]["multiplier_momentum_trend"], 0.5))
        self.assertTrue(_almost(r["panic"]["momentum_short_notional_multiplier"], 0.5))
        self.assertIs(r["panic"]["new_loser_shorts_allowed"], False)
        self.assertTrue(_almost(r["panic"]["net_beta_floor"], -0.10))

    def test_P4_provisional_panic_true_context_only(self):
        r = self._run("P4")
        self.assertIs(r["panic"]["panic"], True)
        self.assertIs(r["panic"]["provisional"], True)
        self.assertIs(r["panic"]["binding"], False)
        self.assertTrue(_almost(r["panic"]["multiplier_momentum_trend"], 1.0))
        self.assertEqual(r["vix_state"], "ON")
        self.assertTrue(_weights_le(FX["P4"]["prior_weights"], r["log"]["w_final"]))

    def test_P4_STATUS_PROVISIONAL(self):
        r = self._run("P4_STATUS_PROVISIONAL")
        self.assertIs(r["panic"]["panic"], True)
        self.assertIs(r["panic"]["provisional"], True)
        self.assertIs(r["panic"]["binding"], False)
        self.assertTrue(_almost(r["panic"]["multiplier_momentum_trend"], 1.0))
        self.assertTrue(_weights_le(FX["P4_STATUS_PROVISIONAL"]["prior_weights"], r["log"]["w_final"]))

    def test_P_BIND_BLOCKS_RESTORE(self):
        r = self._run("P_BIND_BLOCKS_RESTORE")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertIs(r["panic"]["binding"], True)
        self.assertEqual(r["restoration_mode"], "none")
        self.assertIs(r["increase_blockers"]["binding_panic"], True)
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.05))

    # --- Scaler m (B3: computed m_applied_once) ---
    def test_M1_m_once_required_logs(self):
        r = self._run("M1")
        self.assertIs(r["m_applied_once"], True)
        self.assertEqual(r["m_apply_count"], 1)
        self.assertTrue(_almost(r["log"]["m"], 0.75))
        self.assertTrue(_almost(r["log"]["w_base"]["AAA"], 0.075))
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.0375))
        for field in ("m", "panic_factor", "vix_state", "w_base", "w_vix", "w_final"):
            self.assertIn(field, r["log"])

    def test_M2_m_one_only_v1_reduces(self):
        r = self._run("M2")
        # M2 bakes m into w_base — m not applied in-engine this step
        self.assertIs(r["m_applied_once"], False)
        self.assertEqual(r["m_apply_count"], 0)
        self.assertTrue(_almost(r["log"]["m"], 1.0))
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.05))

    def test_M_PANIC_APPLY(self):
        r = self._run("M_PANIC_APPLY")
        self.assertIs(r["m_applied_once"], True)
        self.assertIs(r["panic_applied_once"], True)
        self.assertTrue(_almost(r["panic"]["panic_factor"], 0.5))
        self.assertTrue(_almost(r["log"]["w_base"]["AAA"], 0.10))
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.05))

    # --- Stops ---
    def test_S1_full_quantity_atr_stops(self):
        r = self._run("S1")
        self.assertIs(r["stop_ok"], True)

    def test_S1_NEG_UNDERCOVER(self):
        r = self._run("S1_NEG_UNDERCOVER")
        self.assertIs(r["stop_ok"], False)

    def test_S2_h1_h2_h3_caps_after_v1(self):
        r = self._run("S2")
        self.assertEqual(r["vix_state"], "ON")
        for v in r["log"]["w_final"].values():
            if v > 0:
                self.assertLessEqual(v, 0.10 + 1e-12)

    def test_S3_h6_h7_etf_h7_na(self):
        r = self._run("S3")
        self.assertIs(r["h7_applicable"], False)
        self.assertIs(r["stop_ok"], True)
        self.assertEqual(r["vix_state"], "ON")

    # --- V1 transitions ---
    def test_V1_off_to_on_reduce_only(self):
        r = self._run("V1")
        self.assertEqual(r["vix_state"], "ON")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.05))
        self.assertTrue(_almost(r["log"]["w_vix"]["BBB"], 0.0))
        self.assertTrue(_weights_le(FX["V1"]["prior_weights"], r["log"]["w_final"]))
        self.assertIs(r["increase_blockers"]["v1_reduced_or_block_new"], True)

    def test_V2_four_valid_still_on(self):
        r = self._run("V2")
        self.assertEqual(r["vix_state"], "ON")
        self.assertEqual(r["streak_valid_le1"], 4)

    def test_V3a_fifth_valid_restore_toward_base(self):
        r = self._run("V3a")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["restoration_mode"], "full_base")
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.10))
        self.assertIs(r["increase_blockers"]["any"], False)
        self.assertIs(r["lift_paths_certified"], False)

    def test_V3b_nta_false_no_restore_increase(self):
        r = self._run("V3b")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["restoration_mode"], "none")
        self.assertIs(r["breaker"]["new_trades_allowed"], False)
        self.assertIs(r["breaker"]["trading_hold"], True)
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.05))
        self.assertTrue(_weights_le(FX["V3b"]["prior_weights"], r["log"]["w_final"]))

    def test_V3c_halted_no_increase_no_lift(self):
        r = self._run("V3c")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["breaker"]["state"], "HALTED")
        self.assertIs(r["breaker"]["new_trades_allowed"], False)
        self.assertEqual(r["restoration_mode"], "none")
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.05))
        self.assertTrue(_weights_le(FX["V3c"]["prior_weights"], r["log"]["w_final"]))
        self.assertIs(r["lift_paths_certified"], False)

    def test_V3d_resumed_disarmed_min_base_30(self):
        r = self._run("V3d")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["breaker"]["state"], "RESUMED_DISARMED")
        self.assertEqual(r["restoration_mode"], "min_base_30")
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.30))
        self.assertTrue(_almost(r["long_gross"], 0.30))
        self.assertEqual(r["breaker"]["backstop_equity"], 88000.0)
        self.assertIs(r["breaker"]["halt_armed"], False)

    def test_V4_missing_breaks_streak(self):
        # B5: prior 3 + valid => 4, then missing freezes at 4
        r = self._run("V4")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 4)

    def test_V5_hashfail_stale_reduced_streak_frozen(self):
        r = self._run("V5")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 4)
        self.assertEqual(r["breaker"]["state"], "NORMAL")
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.04))
        self.assertTrue(_weights_le(FX["V5"]["prior_weights"], r["log"]["w_final"]))

    def test_V6_availability_lag_unsatisfied(self):
        r = self._run("V6")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)

    def test_V_REDUCED_BLOCK_NO_INCREASE(self):
        r = self._run("V_REDUCED_BLOCK_NO_INCREASE")
        self.assertEqual(r["vix_state"], "ON")
        self.assertEqual(r["breaker"]["state"], "NORMAL")
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.03))
        self.assertTrue(_weights_le(FX["V_REDUCED_BLOCK_NO_INCREASE"]["prior_weights"], r["log"]["w_final"]))
        self.assertIs(r["increase_blockers"]["v1_reduced_or_block_new"], True)

    # --- E1 domain ---
    def test_E1_domain_long_halved(self):
        r = self._run("E1_domain_long")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.05))

    def test_E1_domain_short_unchanged(self):
        r = self._run("E1_domain_short")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], -0.10))

    def test_E1_domain_flat_unchanged(self):
        r = self._run("E1_domain_flat")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.0))

    def test_E1_no_redeploy_cash_absorbs(self):
        r = self._run("E1_no_redeploy")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.05))
        self.assertTrue(_almost(r["log"]["w_vix"]["BBB"], 0.025))
        base_gross = sum(v for v in FX["E1_no_redeploy"]["w_base"].values() if v > 0)
        self.assertLess(r["long_gross"] + 1e-12, base_gross)

    def test_E1_domain_guard_rejects_deepened_short(self):
        wv = apply_v1_clamp({"AAA": -0.10}, v1_on_or_failsafe_reduced=True)
        self.assertTrue(abs(wv["AAA"] + 0.10) <= 1e-12)
        with self.assertRaises(DomainError):
            validate_w_vix_domain({"AAA": -0.10}, {"AAA": -0.20})

    def test_meta_excludes_optional_pnl(self):
        data = json.loads(FIXTURES_PATH.read_text())
        self.assertIs(data["meta"]["no_optional_synthetic_pnl"], True)
        for rid in ("R1", "R2", "R3", "R4", "R5", "R6", "R7"):
            self.assertIn(rid, data["meta"]["excluded"])
        self.assertEqual(data["meta"]["planned_outputs"], ["pytest-output.txt"])

    def test_fixture_rejects_restoration_mode_override(self):
        bad = dict(FX["V3a"])
        bad["restoration_mode"] = "full_base"
        with self.assertRaises(ValueError):
            run_fixture(bad)

    def test_B6_failsafe_field_values(self):
        r = self._run("B6")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertIs(r["breaker"]["fail_safe"], True)

    def test_BRK_FS_RESUMED_failsafe_field_values(self):
        r = self._run("BRK_FS_RESUMED_NO_BACKSTOP")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertIs(r["breaker"]["fail_safe"], True)
        self.assertIs(r["breaker"]["backstop_equity"], None)

    def test_BRK_FS_HALT_ARMED_failsafe_field_values(self):
        r = self._run("BRK_FS_HALT_ARMED_FALSE_NORMAL")
        self.assertEqual(r["breaker"]["state"], "HALVED")
        self.assertEqual(r["breaker"]["gross_cap_pct"], 30.0)
        self.assertIs(r["breaker"]["new_trades_allowed"], True)
        self.assertIs(r["breaker"]["fail_safe"], True)

    def test_P3_failsafe_panic_field_values(self):
        r = self._run("P3")
        self.assertIs(r["panic"]["fail_safe"], True)
        self.assertIs(r["panic"]["panic"], True)
        self.assertTrue(_almost(r["panic"]["multiplier_momentum_trend"], 0.5))
        self.assertTrue(_almost(r["panic"]["momentum_short_notional_multiplier"], 0.5))
        self.assertIs(r["panic"]["new_loser_shorts_allowed"], False)
        self.assertTrue(_almost(r["panic"]["net_beta_floor"], -0.10))

    # --- B1 invalid R ---
    def test_B1_R_NAN(self):
        r = self._run("B1_R_NAN")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 2)

    def test_B1_R_POSINF(self):
        r = self._run("B1_R_POSINF")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 2)

    def test_B1_R_NEGINF(self):
        r = self._run("B1_R_NEGINF")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 2)

    def test_B1_R_NEG(self):
        r = self._run("B1_R_NEG")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 2)

    def test_B1_R_NONNUM(self):
        r = self._run("B1_R_NONNUM")
        self.assertEqual(r["vix_state"], "FAILSAFE_REDUCED")
        self.assertIs(r["block_new"], True)
        self.assertEqual(r["streak_valid_le1"], 2)

    def test_B1_is_v1_valid_close_unit(self):
        self.assertFalse(is_v1_valid_close({"R": float("nan"), "available": True, "hash_ok": True}))
        self.assertFalse(is_v1_valid_close({"R": float("inf"), "available": True, "hash_ok": True}))
        self.assertFalse(is_v1_valid_close({"R": float("-inf"), "available": True, "hash_ok": True}))
        self.assertFalse(is_v1_valid_close({"R": -0.1, "available": True, "hash_ok": True}))
        self.assertFalse(is_v1_valid_close({"R": "x", "available": True, "hash_ok": True}))
        self.assertFalse(is_v1_valid_close({"R": True, "available": True, "hash_ok": True}))
        self.assertTrue(is_v1_valid_close({"R": 0.0, "available": True, "hash_ok": True}))
        self.assertTrue(is_v1_valid_close({"R": 1.2, "available": True, "hash_ok": True}))

    # --- B2 restoration semantics ---
    def test_V3d_PRIOR_ABOVE_PATH(self):
        r = self._run("V3d_PRIOR_ABOVE_PATH")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["restoration_mode"], "min_base_30")
        # Restoration stage must not cut prior 0.35 (assert w_vix, pre hard-cap path)
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.35))

    def test_V3a_PRIOR_ABOVE_BASE(self):
        r = self._run("V3a_PRIOR_ABOVE_BASE")
        self.assertEqual(r["vix_state"], "OFF")
        self.assertEqual(r["restoration_mode"], "full_base")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.12))

    def test_REST_SHORT_UNCHANGED(self):
        r = self._run("REST_SHORT_UNCHANGED")
        self.assertTrue(_almost(r["log"]["w_vix"]["AAA"], 0.10))
        self.assertTrue(_almost(r["log"]["w_vix"]["SSS"], -0.08))

    def test_REST_FLAT_PRIOR_ONLY_NO_NEW(self):
        r = self._run("REST_FLAT_PRIOR_ONLY_NO_NEW")
        wv = r["log"]["w_vix"]
        self.assertTrue(_almost(wv["AAA"], 0.10))
        self.assertTrue(_almost(wv["FLAT"], 0.0))
        self.assertTrue(_almost(wv["ONLY"], 0.04))
        self.assertTrue(_almost(wv["NEW"], 0.0))

    def test_BASE_DERISK_SEPARATE(self):
        r = self._run("BASE_DERISK_SEPARATE")
        self.assertTrue(_almost(r["log"]["w_final"]["AAA"], 0.10))
        # Direct API: derisk cuts; restoration would preserve
        derisked = apply_base_derisk({"AAA": 0.12}, {"AAA": 0.10})
        self.assertTrue(_almost(derisked["AAA"], 0.10))
        restored = apply_restoration({"AAA": 0.12}, {"AAA": 0.10}, mode="full_base", gross_cap_pct=60.0)
        self.assertTrue(_almost(restored["AAA"], 0.12))

    def test_apply_restoration_unit_below_and_above_target(self):
        # below target -> restore up
        out = apply_restoration({"AAA": 0.05}, {"AAA": 0.10}, mode="full_base", gross_cap_pct=60.0)
        self.assertTrue(_almost(out["AAA"], 0.10))
        # above target -> preserve (no cut)
        out2 = apply_restoration({"AAA": 0.15}, {"AAA": 0.10}, mode="full_base", gross_cap_pct=60.0)
        self.assertTrue(_almost(out2["AAA"], 0.15))
        # path: prior above capped target -> preserve
        out3 = apply_restoration({"AAA": 0.35}, {"AAA": 0.50}, mode="min_base_30", gross_cap_pct=30.0)
        self.assertTrue(_almost(out3["AAA"], 0.35))
        # path: prior below capped target -> restore to 0.30
        out4 = apply_restoration({"AAA": 0.25}, {"AAA": 0.50}, mode="min_base_30", gross_cap_pct=30.0)
        self.assertTrue(_almost(out4["AAA"], 0.30))


if __name__ == "__main__":
    raise SystemExit(
        "Execution not authorised. Validator preflight RETURN FOR AMENDMENT "
        "(3bed621e…). No run until AUTHORISE ONE RUN decision after re-pin."
    )
