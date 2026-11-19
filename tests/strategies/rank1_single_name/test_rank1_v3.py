"""v3 binding Q1-Q7 adversarial coverage. ALL inputs and signoffs INVENTED."""

import copy
import hashlib
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch

from quant_research.strategies.rank1_single_name import rank1_book as B
from quant_research.strategies.rank1_single_name import rank1_bootstrap as Boot
from quant_research.strategies.rank1_single_name import rank1_core as C
from quant_research.strategies.rank1_single_name import rank1_gates as G
from quant_research.strategies.rank1_single_name.rank1_sigma import SIGMA_DEFINITION_SHA256 as SIGMA_SHA
from tests.strategies.rank1_single_name.test_rank1_v2 import (
    END,
    MOCK_BASIS_SHA,
    START,
    book,
    candidate,
    cost_adapter,
    ir,
    market,
    mock_sigma_contract,
)


class V3Rulings(unittest.TestCase):
    def terminal(self, kind="BOUND", intraday=False, amount=0):
        m = market()
        s = m.cal.sessions[45]
        return B.Action(
            "SYNTH_A",
            45,
            (s.open + timedelta(hours=2) if intraday else s.open).isoformat(),
            kind,
            0,
            amount,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )

    def exchange(self, security="SYNTH_NEW", evidence=False):
        m = market()
        when = m.cal.sessions[45].open.isoformat()
        ids = [
            B.Identity("SYNTH_A", "SYNTH_A", START, when, START, True),
            B.Identity("SYNTH_A", "SYNTH_NEW", when, END, START, True),
            B.Identity("SYNTH_SPY", "SYNTH_SPY", START, END, START, True),
        ]
        a = B.Action("SYNTH_A", 45, when, "EXCHANGE", 2, 0, "SYNTH_NEW", True, True, START, synthetic_only=True)
        qty = 2 if security == "SYNTH_NEW" else 1
        e = B.ExchangeEntitlement(security, qty, 45, 55, START, "a" * 64, True) if evidence else None
        d = B.Distribution(security, 45, 55, 1, True, START, e)
        patches = {("SYNTH_NEW", j): dict(open="50", close="50", adv20="1000000000") for j in range(120)}
        return (
            market(names=("SYNTH_A", "SYNTH_NEW"), identities=ids, actions=[a], distributions=[d], patches=patches),
            a,
            d,
        )

    def test_q1_reject_old_and_unknown_policy_and_non_synthetic(self):
        m = market()
        for policy in ("NONCASH_BUFFER_NO_INTEREST_MOCK", "CASH_BUFFER", "", None):
            with self.subTest(policy=policy), self.assertRaisesRegex(C.Blocked, "Q1"):
                B.FixtureBook(m, ir(m), cost_adapter(), C.Config("H48", 48), 40, 80, policy, True)
        with self.assertRaises(C.Blocked):
            B.FixtureBook(m, ir(m), cost_adapter(), C.Config("H48", 48), 40, 80, "NONCASH_BUFFER_PINNED_RF", False)

    def test_q1_exact_recurrence_new_legs_not_interest_bearing_until_next_day(self):
        rf = D(".001")
        b = book(market(rf={i: str(rf) for i in range(120)}), end=50)
        penalty = D(0)
        for r in b.rows:
            penalty = penalty * (1 + rf) + (D(5) if r["index"] in (40, 50) else 0)
            self.assertEqual(r["penalty"], penalty)
            self.assertLess(abs((r["cash_nav"] - r["nav"]) - penalty), D("1e-20"))
        self.assertEqual(b.rows[0]["penalty"], 5)
        self.assertGreater(b.penalty, 10)
        self.assertEqual(b.rows[0]["cash"], D(94990) * (1 + rf))

    def test_q1_missing_rf_blocks_even_on_cash_only_day(self):
        with self.assertRaises(C.Blocked):
            book(market(rf={i: "0" for i in range(120) if i != 52}), end=60)

    def test_q1_z_denominator_is_accrued_prior_all_in_nav(self):
        patches = {("SYNTH_A", j): dict(close=str(100 + 2 * (j - 35))) for j in range(35, 41)}
        b = book(market(patches=patches, rf=dict.fromkeys(range(120), ".001")), end=55)
        expected = D(46) * 110 / b.rows[0]["nav"] * D(".1")
        self.assertLess(abs(b.rows[1]["z"] - expected), D("1e-20"))

    def test_q2_named_percentage_and_dollar_over_100k_arithmetic(self):
        b = book(market(rf=dict.fromkeys(range(120), ".001")), end=50)
        prev_nav = prev_shadow = D(100000)
        for r in b.rows:
            self.assertNotIn("opportunity", r)
            self.assertNotIn("opportunity_dollar", r)
            self.assertEqual(
                r["opportunity_usd_over_100k"], ((r["nav"] - prev_nav) - (r["shadow_nav"] - prev_shadow)) / 100000
            )
            self.assertEqual(r["opportunity_pct"], r["nav"] / prev_nav - r["shadow_nav"] / prev_shadow)
            prev_nav, prev_shadow = r["nav"], r["shadow_nav"]
        self.assertNotEqual(b.rows[-1]["opportunity_pct"], b.rows[-1]["opportunity_usd_over_100k"])

    def sampler(self):
        class CyclicMock:
            mock_only = True

            def __init__(self):
                self.calls = 0

            def integers(self, low, high, size):
                self.calls += 1
                return [(self.calls + i) % high for i in range(size)]

        return CyclicMock()

    def test_q2_bootstrap_same_draws_exact_fields_and_both_bounds(self):
        read = []

        class Traced(dict):
            def __getitem__(self, k):
                read.append(k)
                return super().__getitem__(k)

        rows = [
            Traced(
                synthetic_only=True, opportunity_pct=i * 0.001, opportunity_usd_over_100k=i * 0.002, other_factor=9000
            )
            for i in range(43)
        ]
        sampler = self.sampler()
        r = Boot.mock_bootstrap_joint(rows, sampler, True)
        self.assertEqual(sampler.calls, 10000)
        self.assertEqual(set(read), {"opportunity_pct", "opportunity_usd_over_100k"})
        self.assertEqual(set(r["fields_read"]), set(read))
        self.assertTrue(r["joint_draws"])
        for stat in ("mean", "lower_05"):
            self.assertAlmostEqual(
                r["series"]["opportunity_usd_over_100k"][stat], 2 * r["series"]["opportunity_pct"][stat]
            )
        self.assertFalse(r["rng_accepted"])
        self.assertEqual(r["disposition"], "BLOCKED")

    def test_q2_legacy_missing_nonfinite_and_unaccepted_rng_refused(self):
        good = dict(synthetic_only=True, opportunity_pct=1, opportunity_usd_over_100k=1)
        for mutate in (
            lambda r: r.update(opportunity=1000),
            lambda r: r.update(opportunity_dollar=1000),
            lambda r: r.pop("opportunity_pct"),
            lambda r: r.pop("opportunity_usd_over_100k"),
            lambda r: r.update(opportunity_pct=float("nan")),
        ):
            rs = [dict(good) for _ in range(20)]
            mutate(rs[0])
            with self.assertRaises(C.Blocked):
                Boot.mock_bootstrap_joint(rs, self.sampler(), True)
        with self.assertRaises(C.Blocked):
            Boot.required_pcg64()

    def gate_inputs(self):
        tr = B.CompletedTrade("SYNTH_A", 0, 10, D(5000), D(".02"), D(".005"), D(".015"), "MOCK")
        p = SimpleNamespace(
            trades=[tr] * 100, occupied_blocks=lambda: 30, rows=[dict(day=date(2099, 1, 1), excess=0.6)]
        )
        s = SimpleNamespace(rows=[dict(day=date(2099, 1, 1), excess=0.1)])
        r = dict(
            rng_accepted=True,
            joint_draws=True,
            fields_read=["opportunity_pct", "opportunity_usd_over_100k"],
            series={k: dict(mean=0.1, lower_05=0.01) for k in ("opportunity_pct", "opportunity_usd_over_100k")},
        )
        return p, s, r

    def test_q2_and_gate_both_means_and_bounds_strict_zero(self):
        p, s, r = self.gate_inputs()
        with patch.object(G, "sharpe", side_effect=lambda xs: float(xs[0])):
            self.assertEqual(G.baseline_numbers(p, s, 3, 0.95, r), ([], []))
            for field in r["series"]:
                for stat in ("mean", "lower_05"):
                    bad = copy.deepcopy(r)
                    bad["series"][field][stat] = 0
                    self.assertIn(field + " mean/lower bound", G.baseline_numbers(p, s, 3, 0.95, bad)[1])
            for mutate in (
                lambda x: x.pop("joint_draws"),
                lambda x: x["series"].pop("opportunity_pct"),
                lambda x: x.update(fields_read=["opportunity"]),
            ):
                bad = copy.deepcopy(r)
                mutate(bad)
                with self.assertRaises(C.Blocked):
                    G.baseline_numbers(p, s, 3, 0.95, bad)

    def test_q3_nonpositive_aggregate_fails_and_wrong_denominator_refused(self):
        b = book()
        labels = {k: [k in {"BELOW", "LOW"}] * len(b.rows) for k in ("ABOVE", "BELOW", "HIGH", "LOW", "VIX_GT25")}
        for nav in (D(100000), D(99999)):
            b.rows[-1]["nav"] = nav
            self.assertIn(
                "aggregate net PnL<=0", G.regimes_covid_concentration(b, b, b, labels, "NET_POSITIVE_AGGREGATE")[1]
            )
        for policy in (None, "NET_POSITIVE_AGGREGATE_MOCK", "SUM_POSITIVE_YEARS"):
            with self.assertRaisesRegex(C.Blocked, "Q_CONCENTRATION_DENOMINATOR"):
                G.regimes_covid_concentration(b, b, b, labels, policy)

    def test_q4_actual_pin_equality_not_merely_64_hex(self):
        self.assertEqual(cost_adapter().sigma_estimator_pin(), SIGMA_SHA)
        with self.assertRaisesRegex(C.Blocked, "does not match signed"):
            book(market(patches={("SYNTH_A", 40): dict(sigma_estimator_sha256="f" * 64)}))
        m = market()
        with self.assertRaisesRegex(C.Blocked, "Q4"):
            m.lag_inputs("SYNTH_A", 40)
        for mutate in (
            lambda c: c.update(definition_bytes=b"WRONG"),
            lambda c: c.update(signed_note_sha256="f" * 64),
            lambda c: c.update(tr_basis=None),
        ):
            a = cost_adapter()
            mutate(a.sigma_contract)
            with self.assertRaises(C.Blocked):
                B.FixtureBook(m, ir(m), a, C.Config("H48", 48), 40, 60, "NONCASH_BUFFER_PINNED_RF", True).run(
                    lambda t: [candidate(m)] if t == 40 else []
                )

    def test_q5_verified_intraday_terminal_uses_only_same_session_official_close(self):
        a = self.terminal(intraday=True)
        patches = {("SYNTH_SPY", 45): dict(open=None, open_tradable=False, verified_halt=True, close="120")}
        b = book(market(actions=[a], patches=patches), end=60)
        self.assertEqual(b.rows[-1]["shadow_nav"], 101000)
        self.assertEqual(
            b.intraday_terminal_shadow,
            [dict(index=45, issuer="SYNTH_A", shadow_pnl_usd=D(1000), reference="SAME_SESSION_OFFICIAL_CLOSE_NO_COST")],
        )
        self.assertEqual(b.trades[0].exit, 45)
        for patches in ({("SYNTH_SPY", 45): dict(close=None)},):
            with self.assertRaises(C.Blocked):
                book(market(actions=[a], patches=patches))
        for bad in (
            replace(a, time_verified=False),
            replace(a, identity_verified=False),
            replace(a, time=None),
            replace(a, issuer="SYNTH_UNKNOWN"),
        ):
            with self.assertRaises(C.Blocked):
                book(market(actions=[bad]))

    def test_q5_intraday_cash_credit_after_rf_not_at_open(self):
        a = self.terminal("CASH_TERMINAL", True, 100)
        m = market(actions=[a], rf=dict.fromkeys(range(120), ".001"))
        b = book(m, end=50)
        previous = b.rows[4]["cash"]
        charge = cost_adapter().cash_terminal_leg(
            m.cal.sessions[45].day.isoformat(), 50, 100, 2000000000, ".02", "primary"
        )
        self.assertEqual(b.rows[5]["cash"], previous * D("1.001") + 5000 - charge["transaction_usd"])
        self.assertEqual(len(b.intraday_terminal_shadow), 1)

    def test_q6_caller_zero_positive_negative_fees_refused(self):
        a = self.terminal("CASH_TERMINAL", False, 100)
        for fee in (0, "0", ".1", -1):
            with self.assertRaisesRegex(C.Blocked, "caller fee"):
                book(market(actions=[replace(a, fee_bp=fee)]))
        b = book(market(actions=[a]))
        self.assertGreater(b.cash_terminal_costs[0]["fee_bp"], 0)
        from quant_research.strategies.rank1_single_name.rank1_cost import fee_bps

        adapter = cost_adapter()
        day = market().cal.sessions[45].day.isoformat()
        expected = D(fee_bps(adapter.fees, "sell", day, [("50", "100")], "5000").numerator) / D(
            fee_bps(adapter.fees, "sell", day, [("50", "100")], "5000").denominator
        )
        self.assertEqual(b.cash_terminal_costs[0]["fee_bp"], expected)

    def test_q6_zero_internal_sale_fee_and_missing_date_refused(self):
        adapter = cost_adapter(lambda s: [r.update(simulation_rate="0") for r in s["fees"]["intervals"]])
        with self.assertRaisesRegex(C.Blocked, "fee=0"):
            adapter.cash_terminal_leg("2099-03-01", 50, 100, 2000000000, ".02", "primary")
        with self.assertRaises(C.Blocked):
            cost_adapter().cash_terminal_leg("2100-01-01", 50, 100, 2000000000, ".02", "primary")

    def test_q6_exchange_dividend_missing_entitlement_zero_for_old_and_new_order(self):
        for security in ("SYNTH_A", "SYNTH_NEW"):
            m, _, _ = self.exchange(security, False)
            b = book(m)
            self.assertEqual(b.trades[0].gross_matched_excess, 0)
            self.assertEqual(len(b.exchange_dividends_zeroed), 1)
            self.assertEqual(b.rows[6]["z"], 0)
            self.assertEqual(b.rows[-1]["shadow_nav"], 100000)

    def test_q6_exchange_dividend_explicit_old_and_new_quantities(self):
        for security, want in (("SYNTH_A", D(".01")), ("SYNTH_NEW", D(".02"))):
            m, _, _ = self.exchange(security, True)
            b = book(m)
            self.assertEqual(b.trades[0].gross_matched_excess, want)
            self.assertEqual(b.exchange_dividends_zeroed, [])
            self.assertGreater(b.rows[6]["z"], 0)

    def test_q6_exchange_unknown_security_entitlement_timing_identity_blocks(self):
        for bad in (
            lambda e: replace(e, security="SYNTH_UNKNOWN"),
            lambda e: replace(e, ex_index=44),
            lambda e: replace(e, known_at=None),
            lambda e: replace(e, source_sha256=None),
            lambda e: replace(e, quantity_per_old_share=None),
            lambda e: replace(e, quantity_per_old_share=0),
        ):
            m, a, d = self.exchange(evidence=True)
            d = replace(d, entitlement=bad(d.entitlement))
            with self.assertRaises(C.Blocked):
                book(B.Market(m.cal, m.bars.values(), m.identities, [d], [a], m.rf))
        m, a, d = self.exchange()
        a = replace(a, new_security="SYNTH_UNKNOWN")
        with self.assertRaises(C.Blocked):
            B.Market(m.cal, m.bars.values(), m.identities, [d], [a], m.rf)

    def test_q6_terminal_dividend_both_open_and_intraday_ordering(self):
        for intraday in (False, True):
            for kind, amount in (("BOUND", 0), ("CASH_TERMINAL", 100)):
                a = self.terminal(kind, intraday, amount)
                d = B.Distribution("SYNTH_A", 45, 55, 1, True, START)
                b = book(market(actions=[a], distributions=[d]), end=60)
                want = D("-.99") if kind == "BOUND" else D(".01")
                self.assertEqual(b.trades[0].gross_matched_excess, want)
                self.assertEqual(b.receivables, [])

    def test_q6_terminal_same_day_new_entry_before_intraday_extinction(self):
        a = self.terminal(intraday=True)
        a = replace(
            a,
            index=40,
            time=(market().cal.sessions[40].open + timedelta(hours=2)).isoformat(),
            public_known_at=(market().cal.sessions[40].open + timedelta(hours=1)).isoformat(),
        )
        b = book(market(actions=[a]), end=60)
        self.assertEqual(len(b.trades), 1)
        self.assertEqual(b.trades[0].exit, 40)

    def test_d3_prefix_exact_constants_and_unconditional_production_disable(self):
        for status in ("FAIL", "INSUFFICIENT", "BLOCKED", "SYNTHETIC_ONLY_PASS"):
            r = C.report(status, {"synthetic_test_only": True})
            self.assertEqual(r["claim_label_context"], "fixed D3 claim limitation (not a test result)")
            self.assertEqual(r["claim_labels"], [C.SHORT_LABEL, C.FULL_LABEL])
            self.assertFalse(r["paper_trade_promote_capital_allowed"])
        with self.assertRaises(C.Blocked):
            C.production_entrypoint("SYNTHETIC_ONLY")


class SignedSigmaCorrection(unittest.TestCase):
    def observations(self, m, t=40):
        from quant_research.strategies.rank1_single_name.rank1_sigma import TRClose

        return tuple(
            TRClose(j, "100", (m.cal.sessions[j].close + timedelta(seconds=1)).isoformat(), MOCK_BASIS_SHA, True)
            for j in range(t - 21, t)
        )

    def test_actual_signed_definition_bytes_and_hash_pin(self):
        from quant_research.strategies.rank1_single_name import rank1_sigma as S

        self.assertEqual(
            hashlib.sha256(S.DEFINITION_BYTES).hexdigest(),
            "75da49ee5c68dd95587f7a26917870dbae3c6ddae81ce77634485e871acd7ef2",
        )
        self.assertEqual(cost_adapter().sigma_estimator_pin(), S.SIGMA_DEFINITION_SHA256)
        c = mock_sigma_contract()
        c["definition_bytes"] = S.DEFINITION_BYTES.rstrip(b"\n")
        with self.assertRaisesRegex(C.Blocked, "exact TCA owner signed hash"):
            S.validate_contract(c)

    def test_ddof1_twenty_simple_total_returns_daily_not_log_or_annual(self):
        from quant_research.strategies.rank1_single_name.rank1_sigma import canonical_sigma20

        m = market()
        obs = self.observations(m)
        prices = [D(100)]
        for i in range(20):
            prices.append(prices[-1] * (D("1.01") if i % 2 == 0 else D(1)))
        obs = tuple(replace(r, value=prices[i]) for i, r in enumerate(obs))
        out = canonical_sigma20(obs, 40, m.cal, mock_sigma_contract(), True)
        expected = (D(20) * (D(".005") ** 2) / 19).sqrt()
        self.assertLess(abs(out["sigma20"] - expected), D("1e-24"))
        self.assertEqual((out["observations"], out["returns"], out["ddof"], out["window_end"]), (21, 20, 1, 39))
        self.assertEqual(out["units"], "daily decimal; not annualized")

    def test_missing_nonfinite_nonpositive_close_blocks_no_imputation(self):
        from quant_research.strategies.rank1_single_name.rank1_sigma import canonical_sigma20

        m = market()
        for value in (None, 0, -1, "NaN", "Infinity", "-Infinity"):
            obs = list(self.observations(m))
            obs[9] = replace(obs[9], value=value)
            with self.subTest(value=value), self.assertRaises(C.Blocked):
                canonical_sigma20(obs, 40, m.cal, mock_sigma_contract(), True)

    def test_exact_consecutive_prior21_and_endpoint_not_same_day(self):
        from quant_research.strategies.rank1_single_name.rank1_sigma import canonical_sigma20

        m = market()
        obs = self.observations(m)
        cases = (
            obs[:-1],
            (*obs, obs[-1]),
            (*obs[:-1], None),
            tuple(replace(r, index=r.index + 1) for r in obs),
            tuple(replace(r, index=obs[0].index) if i == 1 else r for i, r in enumerate(obs)),
        )
        for rows in cases:
            with self.assertRaises(C.Blocked):
                canonical_sigma20(rows, 40, m.cal, mock_sigma_contract(), True)
        for t in (0, 20, len(m.cal.sessions)):
            with self.assertRaises(C.Blocked):
                canonical_sigma20(obs, t, m.cal, mock_sigma_contract(), True)

    def test_signed_receipt_satisfied_but_actual_tr_basis_missing_separate_gate(self):
        from quant_research.strategies.rank1_single_name import rank1_sigma as S

        c = mock_sigma_contract()
        c["tr_basis"] = None
        m = market()
        with self.assertRaisesRegex(C.Blocked, "data owner total-return adjustment BASIS CERTIFICATION MISSING"):
            S.canonical_sigma20(self.observations(m), 40, m.cal, c, True)
        for key, value in (
            ("price_only_substitute", True),
            ("distribution_inclusive_once", False),
            ("definition_sha256", "0" * 64),
        ):
            c = mock_sigma_contract()
            c["tr_basis"][key] = value
            with self.assertRaises(C.Blocked):
                S.canonical_sigma20(self.observations(m), 40, m.cal, c, True)
        with self.assertRaises(C.Blocked):
            S.canonical_sigma20(self.observations(m), 40, m.cal, mock_sigma_contract(), False)

    def test_tr_availability_and_basis_unknown_blocks(self):
        from quant_research.strategies.rank1_single_name.rank1_sigma import canonical_sigma20

        m = market()
        rows = self.observations(m)
        for override in (
            dict(known_at=m.cal.cutoff(m.cal.sessions[40]).isoformat()),
            dict(known_at=None),
            dict(basis_sha256="f" * 64),
            dict(synthetic_only=False),
        ):
            bad = list(rows)
            bad[-1] = replace(bad[-1], **override)
            with self.assertRaises(C.Blocked):
                canonical_sigma20(bad, 40, m.cal, mock_sigma_contract(), True)

    def test_book_canonical_sigma_equals_supplied_value_and_closes_required(self):
        for override in (dict(sigma20_closes=None), dict(sigma20=".02")):
            with self.assertRaises(C.Blocked):
                book(market(patches={("SYNTH_A", 40): override}))
        # True zero volatility from21 valid constant TR closes is not an imputed default.
        b = book()
        self.assertEqual(b.positions, {})

    def test_zero_fee_components_and_buy_total_valid_positive_sell_total_required(self):
        def zero_components(s):
            for r in s["fees"]["intervals"]:
                r.update(effective_from="2023-01-01", effective_to="2025-05-31")
                if r["component"] == "CAT" or r["side"] == "buy":
                    r["simulation_rate"] = "0"

        a = cost_adapter(zero_components)
        from quant_research.strategies.rank1_single_name.rank1_cost import fill_fees

        comp = fill_fees(a.fees, "sell", "2023-06-01", 50, 100)
        self.assertEqual(comp["CAT"], 0)
        self.assertGreater(comp["SEC_SECTION_31"], 0)
        self.assertGreater(comp["FINRA_TAF"], 0)
        sell = a.leg("sell", "2023-06-01", 50, 100, 2000000000, 0, "primary")
        self.assertGreater(sell["fee_bp"], 0)
        cash = a.cash_terminal_leg("2023-06-01", 50, 100, 2000000000, 0, "primary")
        self.assertGreater(cash["fee_bp"], 0)
        buy = a.leg("buy", "2023-06-01", 50, 100, 2000000000, 0, "primary")
        self.assertEqual(buy["fee_bp"], 0)
        for side in ("buy", "sell"):
            with self.assertRaises(C.Blocked):
                a.leg(side, "2025-06-01", 50, 100, 2000000000, 0, "primary")
        zeros = cost_adapter(lambda s: [r.update(simulation_rate="0") for r in s["fees"]["intervals"]])
        self.assertEqual(zeros.leg("buy", "2099-03-01", 50, 100, 2000000000, 0, "primary")["fee_bp"], 0)
        with self.assertRaisesRegex(C.Blocked, "positive sale total fee=0"):
            zeros.leg("sell", "2099-03-01", 50, 100, 2000000000, 0, "primary")
        # Existing B8 zero-consideration write-off is not an ordinary sale.
        terminal = zeros.bounded_terminal(5000, 2000000000, 0, 2000000000, "2099-03-01", "primary", True, True)
        self.assertEqual(terminal["fee_bp"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
