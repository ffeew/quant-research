"""All news/market/events/rates/signatures below are FABRICATED. No external values."""

import copy
import hashlib
import json
import math
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

from quant_research.strategies.rank1_single_name import rank1_adapters as A
from quant_research.strategies.rank1_single_name import rank1_book as B
from quant_research.strategies.rank1_single_name import rank1_bootstrap as Boot
from quant_research.strategies.rank1_single_name import rank1_core as C
from quant_research.strategies.rank1_single_name import rank1_gates as G
from quant_research.strategies.rank1_single_name import rank1_news as N
from quant_research.strategies.rank1_single_name import rank1_pipeline as P
from tests.strategies.rank1_single_name.test_rank1_synthetic import fake_calendar, fake_fees, synthetic_days

START = "2090-01-01T00:00:00Z"
END = "2200-01-01T00:00:00Z"

from quant_research.strategies.rank1_single_name.rank1_sigma import DEFINITION_BYTES, TOMAS_SIGNED_NOTE_SHA256, TRClose
from quant_research.strategies.rank1_single_name.rank1_sigma import SIGMA_DEFINITION_SHA256 as SIGMA_SHA

MOCK_BASIS_SHA = hashlib.sha256(b"INVENTED single TR provider receipt for software fixtures only").hexdigest()


def mock_sigma_contract():
    return dict(
        synthetic_only=True,
        signed_note_sha256=TOMAS_SIGNED_NOTE_SHA256,
        definition_bytes=DEFINITION_BYTES,
        tr_basis=dict(
            synthetic_only=True,
            status="MOCK_CERTIFIED_SINGLE_TR_PATH",
            sha256=MOCK_BASIS_SHA,
            definition_sha256=SIGMA_SHA,
            distribution_inclusive_once=True,
            price_only_substitute=False,
        ),
    )


def cost_adapter(change=None):
    sources = {"S12_ETHAN_COST_INPUTS": b"SYNTHETIC 09:31 source, not a signed real artifact"}
    s = dict(
        schema="rank1_single_name_cost_binding/1",
        synthetic_only=True,
        status="BINDING_RAISE_ONLY_SIGNED",
        signed_by="SYNTHETIC_TOMAS",
        signed_at="2099-01-01 00:00 SGT",
        statement="FABRICATED ONLY raise-only",
        units="bp per leg (one-way); round trip = actual entry leg + actual exit leg",
        validity={
            "from": "Rank1 freeze (Victor pin)",
            "until": "Rank1 evaluation receipt",
            "no_expiry_before_evaluation_receipt": True,
        },
        sources={k: dict(sha256=hashlib.sha256(v).hexdigest()) for k, v in sources.items()},
        fees=fake_fees(),
        bucket_lower_bounds_bp={},
    )
    for i, (h, m, e, x, p) in enumerate(
        zip(
            ("2.75", "5", "12", "30"),
            ("10.09", "23.57", "42.88", "53.77"),
            ("20", "28.6", "52.9", "80"),
            ("20", "20", "22", "50"),
            ("2", "4", "8", "15"),
        )
    ):
        s["bucket_lower_bounds_bp"]["L" + str(i + 1)] = dict(
            h_default_half_bp=h, m0931_half_bp=m, entry_c_lower_bound_bp=e, exit_c_lower_bound_bp=x, b_paper_bp=p
        )
    if change:
        change(s)
    raw = json.dumps(s).encode()
    return A.SignedCostAdapter(
        raw, hashlib.sha256(raw).hexdigest(), sources, True, sigma_contract=mock_sigma_contract()
    )


def market(n=120, names=("SYNTH_A",), patches=None, distributions=(), actions=(), identities=None, rf=None):
    cal = fake_calendar(synthetic_days(n))
    bars = []
    patches = patches or {}
    for sec in (*names, "SYNTH_SPY"):
        for i in range(n):
            b = B.Bar(
                sec,
                i,
                "100",
                "100",
                "2000000000",
                "0",
                True,
                False,
                True,
                volume="20000000",
                sip=True,
                close_known_at=(cal.sessions[i].close + timedelta(seconds=1)).isoformat(),
                lag_available_at=(cal.sessions[i - 1].close + timedelta(seconds=1)).isoformat() if i else START,
                lag_end_index=i - 1,
                sigma_estimator_sha256=SIGMA_SHA,
                sigma20_closes=tuple(
                    TRClose(j, "100", (cal.sessions[j].close + timedelta(seconds=1)).isoformat(), MOCK_BASIS_SHA, True)
                    for j in range(max(0, i - 21), i)
                ),
            )
            bars.append(replace(b, **patches.get((sec, i), {})))
    ids = (
        [B.Identity(sec, sec, START, END, START, True) for sec in (*names, "SYNTH_SPY")]
        if identities is None
        else identities
    )
    return B.Market(cal, bars, ids, distributions, actions, dict.fromkeys(range(n), "0") if rf is None else rf)


def ir(m, names=("SYNTH_A",), extra=()):
    return A.IRCalendar(
        [A.IRSnapshot(x, "base", START, "2199-01-01T00:00:00Z", END, False, True) for x in names] + list(extra)
    )


def candidate(m, issuer="SYNTH_A", t=40, score=".3"):
    return N.Candidate(
        issuer, issuer, "SYNTH_ACTION", m.cal.cutoff(m.cal.sessions[t]) - timedelta(seconds=1), D(score), ()
    )


def book(m=None, schedule=None, start=40, end=80, extras=(), ledger="primary", cfg=None):
    m = m or market()
    schedule = schedule or {40: [candidate(m)]}
    return B.FixtureBook(
        m, ir(m, extra=extras), cost_adapter(), cfg or C.Config("H48", 48), start, end, "NONCASH_BUFFER_PINNED_RF", True
    ).run(lambda t: schedule.get(t, ()), ledger)


def alias(issuer="SYNTH_A", word=None, ticker=True):
    return N.Alias(issuer, word or issuer, ticker, START, END, START)


def story(
    m,
    id,
    h,
    day,
    k=None,
    summary="Invented facts for synthetic tests",
    url=None,
    symbols=("SYNTH_A",),
    created_delta=48,
):
    k = k or m.cal.cutoff(m.cal.sessions[day]) - timedelta(hours=1)
    created = k - timedelta(hours=created_delta)
    return N.Story(
        id,
        h,
        summary,
        symbols,
        created.isoformat(),
        created.isoformat(),
        "2199-01-01T00:00:00Z",
        url,
        synthetic_only=True,
    )


class Extraction(unittest.TestCase):
    def test_normalization_exact_case_markup_and_nodes(self):
        self.assertEqual(
            N.normalize("<p>UP &amp; down</p><!--x--><script>BUY</script><style>x</style><b>Now</b>\nEND"),
            "UP & down Now END",
        )
        self.assertEqual(N.normalize("A&nbsp; B &amp;amp; C"), "A B & C")
        self.assertEqual(N.normalize(None), "")

    def test_exclusion_ascii_word_phrase_boundaries(self):
        for s in ("EPS report", "new quarterly   results", "round-up tonight", "Acquisition pending"):
            self.assertTrue(N.phrases(s, N.EXCLUSIONS))
        self.assertFalse(N.phrases("stepson guidanceful cost", N.EXCLUSIONS))

    def test_parser_ontology_broker_unicode_and_ambiguity(self):
        m = market()
        co = N.NewsCompiler(
            m.cal,
            [alias(), alias(word="Amber Unit Company", ticker=False)],
            {"SYNTH_A": "SYNTH_A"},
            N.FixedFixtureScorer({}),
        )

        def parse(h):
            return co.action(co.prepare([story(m, "a", h, 40)], C.Config("H48", 48))[0])

        self.assertEqual(parse("Bróker & Co. upgrades Amber Unit Company to Strong Buy"), ("bróker co", "upgrades"))
        for h in (
            "Broker upgrades SYNTH_A to Buyer",
            "Broker upgrades SYNTH_A to Sector Outperform",
            "Broker maintains SYNTH_A to Buy",
            "Broker upgrades SYNTH_A and downgrades other to Buy",
            "Broker raises price target SYNTH_A to 200",
            "Broker upgrades SYNTH_AX to Buy",
        ):
            self.assertIsNone(parse(h))
        self.assertEqual(parse("Broker downgrades SYNTH_A to Neutral"), ("broker", "downgrades"))
        amb = N.NewsCompiler(m.cal, [alias(), alias("SYNTH_B", "SYNTH_A", False)], {"SYNTH_A": "SYNTH_A"}, None)
        p = amb.prepare([story(m, "x", "Broker upgrades SYNTH_A to Buy", 40)], C.Config("H48", 48))[0]
        self.assertIsNone(amb.action(p))

    def test_source_tags_missing_background_and_common_filters(self):
        m = market()
        co = N.NewsCompiler(m.cal, [alias()], {"SYNTH_A": "SYNTH_A"}, None)
        records = [
            story(m, "two", "Broker upgrades SYNTH_A to Buy", 40, symbols=("SYNTH_A", "SYNTH_A")),
            replace(story(m, "source", "Broker upgrades SYNTH_A to Buy", 40), source="OTHER"),
            story(m, "exclude", "Broker upgrades SYNTH_A to Buy", 40, summary="EPS invented"),
            story(m, "empty", "Broker upgrades SYNTH_A to Buy", 40, summary=None),
        ]
        out = co.prepare(records, C.Config("H48", 48))
        self.assertEqual([p.story.id for p in out], ["empty"])

    def test_final_versions_no_earlier_text_and_conflict(self):
        m = market()
        s = story(m, "x", "Fictional factory closure", 35)
        revised = replace(
            s, headline="Later changed text", updated=(C.clock(s.updated) + timedelta(days=100)).isoformat()
        )
        co = N.NewsCompiler(m.cal, [alias()], {"SYNTH_A": "SYNTH_A"}, None)
        self.assertEqual(co.prepare([s, revised], C.Config("H48", 48))[0].headline, "Later changed text")
        self.assertEqual(co.prepare([s, revised], C.Config("NE48", 48, never_edited=True)), ())
        with self.assertRaises(C.Blocked):
            N.final_versions([s, replace(s, headline="conflicting text")])
        with self.assertRaises(C.Blocked):
            N.final_versions([replace(s, payload_version_hash="a" * 64), replace(s, payload_version_hash="b" * 64)])

    def test_canonical_url_and_jaccard_greedy_definitions(self):
        self.assertEqual(N.canonical("HTTPS://Example.COM/Case/Path/?x=1#y"), "https://example.com/Case/Path")
        self.assertEqual(N.jaccard("Company shares THIS with factory closure", "factory closure stock from"), 1)
        self.assertEqual(N.jaccard("a b", "a c"), 0)

    def compiler_fixture(self):
        m = market()
        heads = [
            "Factory closure threatens workflow",
            "Product recalls damage operations",
            "Customer cancellation disrupts services",
            "Warehouse shutdown hinders logistics",
        ]
        records = [story(m, str(i), h, 36 + i, url=f"https://unit.invalid/{i}") for i, h in enumerate(heads)]
        records.append(story(m, "up", "Broker upgrades SYNTH_A to Buy", 40))
        scores = {N.normalize(s.headline) + ". " + N.normalize(s.summary): "-.3" for s in records[:-1]}
        return m, records, scores

    def test_full_signal_clock_coverage_threshold_and_downgrade_veto(self):
        m, records, scores = self.compiler_fixture()
        cfg = C.Config("H48", 48)
        compiler = N.NewsCompiler(m.cal, [alias()], {"SYNTH_A": "SYNTH_A"}, N.FixedFixtureScorer(scores))
        prepared = compiler.prepare(records, cfg)
        complete = {"SYNTH_A": set(range(120))}
        cs = compiler.candidates(prepared, cfg, 40, complete)
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0].score, D(".3"))
        self.assertEqual(len(cs[0].background_ids), 4)
        down = story(m, "down", "Other Broker downgrades SYNTH_A to Hold", 40)
        self.assertEqual(compiler.candidates(compiler.prepare([*records, down], cfg), cfg, 40, complete), ())
        with self.assertRaises(C.Insufficient):
            compiler.candidates(prepared, cfg, 40, {"SYNTH_A": set(range(21, 40))})

    def test_duplicate_url_nearcopy_id_and_future_news_not_backfilled(self):
        m, records, scores = self.compiler_fixture()
        cfg = C.Config("H48", 48, stories=4)
        compiler = N.NewsCompiler(m.cal, [alias()], {"SYNTH_A": "SYNTH_A"}, N.FixedFixtureScorer(scores))
        complete = {"SYNTH_A": set(range(120))}
        duplicate = replace(records[1], id="dup", headline=records[0].headline, url=records[0].url)
        xs = [records[0], duplicate, records[2], records[3], records[4]]
        self.assertEqual(compiler.candidates(compiler.prepare(xs, cfg), cfg, 40, complete), ())
        delayed = replace(records[0], updated="2190-01-01T00:00:00Z")
        self.assertEqual(compiler.candidates(compiler.prepare([delayed, *records[1:]], cfg), cfg, 40, complete), ())

    def test_scorer_virtual_byte_version_locks_and_neutral_removal(self):
        class FakeAnalyzer:
            lexicon = dict.fromkeys((*N.NEUTRAL, "risk", "risks"), 5)

            def polarity_scores(self, text):
                self.text = text
                return {"compound": -0.1234}

        vb = {k: ("SYNTHETIC " + k).encode() for k in N.FinanceScorer.COMPONENTS}
        vb["METADATA"] = b"Name: vaderSentiment\nVersion: 3.3.2\n"
        vb["neutral_list"] = ("# SYNTHETIC neutral artifact\n" + "\n".join(N.NEUTRAL)).encode()
        pins = {k: hashlib.sha256(v).hexdigest() for k, v in vb.items()}
        a = FakeAnalyzer()
        sc = N.FinanceScorer(a, vb, pins, True)
        self.assertEqual(sc.score("UPPER! Input"), D("-.1234"))
        self.assertEqual(a.text, "UPPER! Input")
        self.assertIn("risk", a.lexicon)
        self.assertIn("risks", a.lexicon)
        self.assertNotIn("cost", a.lexicon)
        with self.assertRaises(C.Blocked):
            N.FinanceScorer(a, vb, pins)
        bad = dict(pins)
        bad["vader_lexicon.txt"] = "0" * 64
        with self.assertRaises(C.Blocked):
            N.FinanceScorer(a, vb, bad, True)


class Accounting(unittest.TestCase):
    def test_whole_share_gap_and_ten_session_exit(self):
        m = market(patches={("SYNTH_A", 40): dict(open="110")})
        b = book(m)
        tr = b.trades[0]
        self.assertEqual(tr.notional, 5500)
        self.assertEqual(tr.exit - tr.entry, 10)
        self.assertEqual(tr.entry, 40)
        self.assertEqual(b.max_concurrent, 1)

    def test_no_data_no_renewal_cooldown_and_reset(self):
        m = market()
        schedule = {i: [candidate(m, t=i)] for i in (40, 41, 60, 70, 71)}
        b = book(m, schedule, end=100)
        self.assertEqual([(t.entry, t.exit) for t in b.trades], [(40, 50), (71, 81)])
        fresh = book(m, {60: [candidate(m, t=60)]}, start=60, end=80)
        self.assertEqual(fresh.trades[0].entry, 60)
        with self.assertRaises(C.Blocked):
            b.run(lambda t: ())

    def test_five_slots_ticker_ties_discard_not_queue_and_exits_first(self):
        names = tuple("SYNTH_" + x for x in "ABCDEF")
        m = market(names=names)
        cs = [candidate(m, x, 40) for x in reversed(names)]
        schedule = {40: cs, 50: [candidate(m, "SYNTH_F", 50)]}
        b = B.FixtureBook(
            m, ir(m, names), cost_adapter(), C.Config("H48", 48), 40, 80, "NONCASH_BUFFER_PINNED_RF", True
        ).run(lambda t: schedule.get(t, ()))
        self.assertEqual(b.max_concurrent, 5)
        self.assertIn(("SYNTH_F", 40), b.discarded)
        self.assertEqual([(t.entry, t.exit) for t in b.trades if t.issuer == "SYNTH_F"], [(50, 60)])

    def test_nav_cash_rf_and_buffer_applied_once(self):
        b = book(end=50)
        self.assertEqual(b.rows[-1]["nav"], D(99970))
        self.assertEqual(b.rows[-1]["cash_nav"], D(99980))
        self.assertEqual(b.penalty, 10)
        self.assertEqual(b.rows[-1]["shadow_nav"], 100000)
        m = market(rf=dict.fromkeys(range(120), ".001"))
        b = book(m, end=50)
        self.assertEqual(b.rows[0]["cash"], D(94990) * D("1.001"))
        self.assertEqual(b.rows[0]["nav"], D(94990) * D("1.001") + 5000 - 5)
        self.assertEqual(b.rows[0]["shadow_nav"], D(95000) * D("1.001") + 5000)

    def test_distributions_ex_entitlement_receivables_payment_after_exit(self):
        d = B.Distribution("SYNTH_A", 42, 55, "1", True, START)
        b = book(market(distributions=[d]), end=60)
        self.assertEqual(b.trades[0].gross_matched_excess, D(".01"))
        self.assertEqual(b.rows[-1]["nav"], 100020)
        self.assertEqual(b.rows[54 - 40]["nav"], b.rows[55 - 40]["nav"])
        self.assertEqual(b.receivables, [])
        # Buying at the ex-date open does NOT receive prior-close entitlement.
        b = book(market(distributions=[B.Distribution("SYNTH_A", 40, 55, "1", True, START)]), end=60)
        self.assertEqual(b.rows[-1]["nav"], 99970)

    def test_shadow_distribution_inclusive_same_capital_no_costs(self):
        ds = [
            B.Distribution("SYNTH_A", 42, 55, "1", True, START),
            B.Distribution("SYNTH_SPY", 42, 55, "1", True, START),
        ]
        b = book(market(distributions=ds), end=60)
        self.assertEqual(b.trades[0].gross_matched_excess, 0)
        self.assertEqual(b.rows[-1]["shadow_nav"], 100050)

    def test_lagged_z_exact_five_links_weights_no_today_entrant(self):
        patches = {("SYNTH_A", j): dict(close=str(100 + 2 * (j - 35))) for j in range(35, 41)}
        patches["SYNTH_A", 41] = dict(close="999")
        m = market(patches=patches)
        b = book(m, end=55)
        self.assertEqual(b.rows[0]["z"], 0)
        expected = D(46) * 110 / b.rows[0]["nav"] * D(".1")
        self.assertLess(abs(b.rows[1]["z"] - expected), D("1e-20"))
        patches["SYNTH_A", 41] = dict(close="1")
        b2 = book(market(patches=patches), end=55)
        self.assertEqual(b.rows[1]["z"], b2.rows[1]["z"])

    def test_ir_reschedule_before_equal_and_after_cutoff(self):
        for seconds, expected in ((-1, 42), (0, 43), (1, 43)):
            m = market()
            s = m.cal.sessions[42]
            row = A.IRSnapshot(
                "SYNTH_A",
                "change",
                (m.cal.cutoff(s) + timedelta(seconds=seconds)).isoformat(),
                m.cal.sessions[45].open.isoformat(),
                END,
                False,
                True,
            )
            b = book(m, extras=[row])
            self.assertEqual(b.trades[0].exit, expected)
        m = market()
        row = A.IRSnapshot("SYNTH_A", "date", START, m.cal.sessions[45].day.isoformat(), END, True, True)
        with self.assertRaises(C.Blocked):
            book(m, extras=[row])  # tied known clock conflicts, not choose favorable

    def test_ir_missing_coverage_and_next_release_exact_exit(self):
        m = market()
        c = cost_adapter()
        empty = A.IRCalendar([])
        with self.assertRaises(C.Blocked):
            B.FixtureBook(m, empty, c, C.Config("H48", 48), 40, 60, "NONCASH_BUFFER_PINNED_RF", True).run(
                lambda t: [candidate(m)] if t == 40 else []
            )
        row = A.IRSnapshot("SYNTH_A", "x", START, m.cal.sessions[50].open.isoformat(), END, False, True)
        b = B.FixtureBook(m, A.IRCalendar([row]), c, C.Config("H48", 48), 40, 60, "NONCASH_BUFFER_PINNED_RF", True).run(
            lambda t: [candidate(m)] if t == 40 else []
        )
        self.assertEqual(b.trades, [])

    def test_halt_exit_delayed_no_stale_fill_stage_boundary_blocks(self):
        m = market(patches={("SYNTH_A", 50): dict(open=None, open_tradable=False, verified_halt=True)})
        b = book(m, end=60)
        self.assertEqual(b.trades[0].exit, 51)
        self.assertEqual(b.halts, [("SYNTH_A", 50)])
        with self.assertRaises(C.Insufficient):
            book(m, end=50)
        m = market(patches={("SYNTH_A", 40): dict(open=None, open_tradable=False, verified_halt=True)})
        with self.assertRaises(C.Blocked):
            book(m)

    def test_missing_close_rf_capacity_or_identity_block(self):
        cases = [
            market(patches={("SYNTH_A", 45): dict(close=None)}),
            market(rf={i: "0" for i in range(120) if i != 45}),
            market(patches={("SYNTH_A", 40): dict(adv20=None)}),
            market(identities=[]),
        ]
        for m in cases:
            with self.subTest(case=m), self.assertRaises(C.Blocked):
                book(m)

    def test_bounded_terminal_full_loss_original_notional_no_zero_return(self):
        m = market()
        a = B.Action(
            "SYNTH_A",
            45,
            m.cal.sessions[45].open.isoformat(),
            "BOUND",
            0,
            0,
            None,
            True,
            True,
            m.cal.sessions[44].open.isoformat(),
            synthetic_only=True,
        )
        b = book(market(actions=[a]), end=60)
        self.assertEqual(b.trades[0].gross_matched_excess, -1)
        self.assertEqual(b.trades[0].reason, "BOUND")
        self.assertEqual(b.rows[-1]["nav"], 94970)
        self.assertEqual(b.trades[0].all_in_cost_fraction, D(".006"))
        bad = replace(a, identity_verified=False)
        with self.assertRaises(C.Blocked):
            market(actions=[bad])

    def test_intraday_terminal_comparator_official_close(self):
        m = market()
        a = B.Action(
            "SYNTH_A",
            45,
            (m.cal.sessions[45].open + timedelta(hours=2)).isoformat(),
            "BOUND",
            0,
            0,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )
        b = book(market(actions=[a]))
        self.assertEqual(b.intraday_terminal_shadow[0]["reference"], "SAME_SESSION_OFFICIAL_CLOSE_NO_COST")

    def test_split_and_security_exchange_preserve_economics_and_z(self):
        m = market()
        a = B.Action(
            "SYNTH_A",
            45,
            m.cal.sessions[45].open.isoformat(),
            "SPLIT",
            2,
            0,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )
        patches = {("SYNTH_A", j): dict(open="50", close="50") for j in range(45, 120)}
        b = book(market(actions=[a], patches=patches))
        self.assertEqual(b.rows[-1]["nav"], 99970)
        self.assertEqual(b.rows[6]["z"], 0)
        change = m.cal.sessions[45].open.isoformat()
        ids = [
            B.Identity("SYNTH_A", "SYNTH_A", START, change, START, True),
            B.Identity("SYNTH_A", "SYNTH_NEW", change, END, START, True),
            B.Identity("SYNTH_SPY", "SYNTH_SPY", START, END, START, True),
        ]
        a = replace(a, kind="EXCHANGE", new_security="SYNTH_NEW")
        patches = {("SYNTH_NEW", j): dict(open="50", close="50", adv20="1000000000") for j in range(120)}
        b = book(market(names=("SYNTH_A", "SYNTH_NEW"), actions=[a], identities=ids, patches=patches))
        self.assertEqual(b.rows[-1]["nav"], 99970)

    def test_cost_schema_pin_minima_units_validity_fail_closed(self):
        for mutate in (
            lambda s: s.update(units="roundtrip"),
            lambda s: s["bucket_lower_bounds_bp"]["L2"].update(entry_c_lower_bound_bp="20"),
            lambda s: s["validity"].update(until="freeze"),
            lambda s: s["sources"]["S12_ETHAN_COST_INPUTS"].update(sha256="0" * 64),
            lambda s: s["fees"]["intervals"].append(s["fees"]["intervals"][0]),
        ):
            with self.assertRaises(C.Blocked):
                cost_adapter(mutate)

    def test_lag_cost_endpoint_knowledge_sigma_pin_and_sip_volume(self):
        m = market()
        future = (m.cal.cutoff(m.cal.sessions[40]) + timedelta(seconds=1)).isoformat()
        for patch in (dict(lag_end_index=40), dict(lag_available_at=future), dict(sigma_estimator_sha256=None)):
            with self.assertRaises(C.Blocked):
                book(market(patches={("SYNTH_A", 40): patch}))
        for patch in (dict(volume=None), dict(sip=False), dict(close_known_at=future)):
            with self.assertRaises(C.Blocked):
                book(market(patches={("SYNTH_A", 39): patch}))

    def test_z_no_future_distribution_revisions_or_close_versions(self):
        m = market()
        future = (m.cal.cutoff(m.cal.sessions[43]) + timedelta(seconds=1)).isoformat()
        d = B.Distribution("SYNTH_A", 42, 55, "1", True, future)
        with self.assertRaises(C.Blocked):
            book(market(distributions=[d]))
        # Prior close revised after current cutoff cannot determine today's whole-share size.
        with self.assertRaises(C.Blocked):
            book(market(patches={("SYNTH_A", 39): dict(close_known_at="2199-01-01T00:00:00Z")}))

    def test_terminal_prior_close_dividend_entitlement_survives_extinguishment(self):
        m = market()
        a = B.Action(
            "SYNTH_A",
            45,
            m.cal.sessions[45].open.isoformat(),
            "BOUND",
            0,
            0,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )
        d = B.Distribution("SYNTH_A", 45, 55, "1", True, START)
        b = book(market(actions=[a], distributions=[d]), end=60)
        self.assertEqual(b.rows[-1]["nav"], 95020)
        self.assertEqual(b.trades[0].gross_matched_excess, D("-.99"))

    def test_failed_book_cannot_reopen_mutated_state(self):
        m = market(patches={("SYNTH_A", 40): dict(open=None)})
        b = B.FixtureBook(m, ir(m), cost_adapter(), C.Config("H48", 48), 40, 60, "NONCASH_BUFFER_PINNED_RF", True)
        with self.assertRaises(C.Blocked):
            b.run(lambda t: [candidate(m)] if t == 40 else [])
        with self.assertRaises(C.Blocked):
            b.run(lambda t: [])

    def test_fractional_split_needs_cash_in_lieu_and_cash_terminal_internal_fee(self):
        m = market()
        a = B.Action(
            "SYNTH_A",
            45,
            m.cal.sessions[45].open.isoformat(),
            "SPLIT",
            "1.01",
            0,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )
        with self.assertRaises(C.Blocked):
            book(market(actions=[a]))
        a = replace(a, kind="CASH_TERMINAL", cash_per_old_share=100)
        b = book(market(actions=[a]))
        self.assertGreater(b.cash_terminal_costs[0]["fee_bp"], 0)
        a = replace(a, fee_bp=0)
        with self.assertRaisesRegex(C.Blocked, "caller fee"):
            book(market(actions=[a]))

    def test_positive_cash_and_known_zero_extinguishment_are_distinct_from_unknown_bound(self):
        m = market()
        a = B.Action(
            "SYNTH_A",
            45,
            m.cal.sessions[45].open.isoformat(),
            "CASH_TERMINAL",
            0,
            0,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )
        b = book(market(actions=[a]))
        self.assertEqual(b.rows[-1]["nav"], 94970)
        self.assertEqual(b.trades[0].reason, "CASH_TERMINAL")

    def test_shadow_split_preserves_fractional_null_units_without_fee(self):
        m = market()
        a = B.Action(
            "SYNTH_SPY",
            45,
            m.cal.sessions[45].open.isoformat(),
            "SPLIT",
            2,
            0,
            None,
            True,
            True,
            START,
            synthetic_only=True,
        )
        patches = {("SYNTH_SPY", j): dict(open="50", close="50") for j in range(45, 120)}
        b = book(market(actions=[a], patches=patches))
        self.assertEqual(b.rows[-1]["shadow_nav"], 100000)
        self.assertEqual(b.rows[-1]["nav"], 99970)

    def test_stage_admission_and_single_use_failure(self):
        m = market()
        b = book(m, {75: [candidate(m, t=75)]}, end=80)
        self.assertEqual(b.trades, [])
        with self.assertRaises(C.Blocked):
            B.FixtureBook(m, ir(m), cost_adapter(), C.Config("H48", 48), 40, 80, "UNDECLARED", True)


class GatesAndIntegration(unittest.TestCase):
    def test_full23_configuration_end_to_end_all_fixed_cost_paths(self):
        m = market()
        heads = [
            "Factory closure threatens workflow",
            "Product recalls damage operations",
            "Customer cancellation disrupts services",
            "Warehouse shutdown hinders logistics",
        ]
        stories = [story(m, str(i), h, 36 + i, url=f"https://unit.invalid/{i}") for i, h in enumerate(heads)] + [
            story(m, "up", "Broker upgrades SYNTH_A to Buy", 40)
        ]
        vals = {N.normalize(s.headline) + ". " + N.normalize(s.summary): "-.3" for s in stories[:-1]}
        r = P.evaluate_fabricated_card(
            m,
            ir(m),
            cost_adapter(),
            [alias()],
            {"SYNTH_A": "SYNTH_A"},
            stories,
            lambda: N.FixedFixtureScorer(vals),
            35,
            80,
            {"SYNTH_A": set(range(120))},
            True,
        )
        self.assertEqual(len(r["books"]["primary"]), 23)
        self.assertFalse(r["production_enabled"])
        self.assertEqual(r["dev_gate"]["disposition"], "INSUFFICIENT")
        for cfg in C.configurations():
            a = r["books"]["primary"][cfg.id]
            b = r["books"]["global_2x"][cfg.id]
            self.assertEqual([(x.entry, x.exit) for x in a.trades], [(x.entry, x.exit) for x in b.trades])
            for t in a.trades:
                self.assertEqual(t.exit - t.entry, cfg.hold)
        self.assertEqual(len(r["books"]["primary"]["H48"].trades), 1)
        with self.assertRaises(C.Blocked):
            P.evaluate_fabricated_card(m, None, None, [], {}, [], None, 35, 80, {}, False)

    def test_universe_prior20_as_known_class_ties_and_no_future_screen(self):
        ds = tuple(d.isoformat() for d in synthetic_days(20))
        rows = []
        for issuer, ticker, volume in (
            ("SYNTH_A", "ZZZ", 10000000),
            ("SYNTH_A", "AAA", 10000000),
            ("SYNTH_B", "BBB", 5000000),
        ):
            for d in ds:
                rows.append(
                    dict(
                        synthetic_only=True,
                        issuer=issuer,
                        ticker=ticker,
                        session=d,
                        unadjusted_close=100,
                        volume=volume,
                        known_at=START,
                        SIP=True,
                        split_treatment_evidenced=True,
                    )
                )
        out = P.select_fixture_universe(START, END, ds[-1], ds, rows, True)
        self.assertEqual([(a, b) for a, b, _ in out], [("SYNTH_A", "AAA")])
        with self.assertRaises(C.Blocked):
            P.select_fixture_universe(END, START, ds[-1], ds, rows, True)
        with self.assertRaises(C.Blocked):
            P.select_fixture_universe(START, END, ds[-1], ds, rows[:-1], True)

    def test_regimes_strict_lag_equalities_and_missingness(self):
        m = market(260)
        labels, _median = G.regime_labels(m, [230, 231], {229: 25, 230: 26}, [25, 25], True)
        self.assertEqual(labels["BELOW"], [True, True])
        self.assertEqual(labels["HIGH"], [False, True])
        self.assertEqual(labels["VIX_GT25"], [False, True])
        with self.assertRaises(C.Insufficient):
            G.regime_labels(m, [199], {198: 25}, [25], True)
        with self.assertRaises(C.Blocked):
            G.regime_labels(m, [230], {}, [25], True)

    def test_fixed_covid_windows_insufficiency_no_rolling_or_waiver(self):
        b = book()
        labels = {k: [k in {"BELOW", "LOW"}] * len(b.rows) for k in ("ABOVE", "BELOW", "HIGH", "LOW", "VIX_GT25")}
        problems, failed, _detail = G.regimes_covid_concentration(b, b, b, labels, "NET_POSITIVE_AGGREGATE")
        self.assertIn("COVID_2020 fixed window empty", problems)
        self.assertIn("EX2020 fixed window empty", problems)
        self.assertIn("aggregate net PnL<=0", failed)
        with self.assertRaises(C.Blocked):
            G.regimes_covid_concentration(b, b, b, labels)

    def test_entire_regime_hold_required_not_only_entry_exit(self):
        tr = B.CompletedTrade("SYNTH_A", 2, 5, D(5000), D(0), D(0), D(0), "x")
        self.assertFalse(G.entirely_within(tr, {2, 3, 5}))
        self.assertTrue(G.entirely_within(tr, {2, 3, 4, 5}))

    def test_bootstrap_geometry_all10000_linear_quantile_mock_cannot_pass(self):
        class Sampler:
            mock_only = True

            def __init__(self):
                self.calls = 0

            def integers(self, low, high, size):
                self.calls += 1
                return [((self.calls + j) % high) for j in range(size)]

        sampler = Sampler()
        rows = [
            dict(
                synthetic_only=True,
                opportunity_pct=float(i),
                opportunity_usd_over_100k=float(i) * 2,
                paired_factor=3 * i,
            )
            for i in range(43)
        ]
        indices = Boot.block_indices(43, sampler)
        self.assertEqual(len(indices), 43)
        self.assertEqual(indices[:20], tuple(range(1, 21)))
        r = Boot.mock_bootstrap_joint(rows, sampler, True)
        self.assertEqual(r["detail"]["replications"], 10000)
        self.assertFalse(r["rng_accepted"])
        self.assertEqual(r["disposition"], "BLOCKED")
        with self.assertRaises(C.Blocked):
            Boot.required_pcg64()

    def test_one_opening_and_missing_rng_not_fake_pass(self):
        state = G.OneOpeningState()
        with self.assertRaises(C.Blocked):
            state.mock_open()
        with self.assertRaises(C.Blocked):
            state.mock_freeze(True, False)
        state.mock_freeze(True, True)
        state.record_dev(C.report("SYNTHETIC_ONLY_PASS", "mock"))
        self.assertEqual(state.mock_open(), "MOCK_ONLY_NO_ACTUAL_UNLOCK")
        with self.assertRaises(C.Blocked):
            state.mock_open()
        b = book()
        problems, failed = G.baseline_numbers(b, b, 4, 0.99, dict(rng_accepted=False))
        self.assertIn("approved exact PCG64/runtime unavailable", problems)
        r = G.aggregate_oos([(problems, failed)], ([], []), ([], [], {}), None)
        self.assertEqual(r["real_data_disposition"], "BLOCKED")
        self.assertFalse(r["production_enabled"])

    def test_positive_fixed_covid_and_regime_adequacy_then_stress_failure(self):
        from types import SimpleNamespace

        days = []
        d = date(2020, 3, 2)
        while d <= date(2025, 5, 22):
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        cal = fake_calendar(days)
        rows = [
            dict(
                synthetic_only=True, index=i, day=d, nav=D(100000) + D(i + 1) / 10, excess=0.001 + 0.0001 * math.sin(i)
            )
            for i, d in enumerate(days)
        ]
        trades = [
            B.CompletedTrade("SYNTH_A", i, i + 1, D(5000), D(".01"), D(".001"), D(".009"), "MOCK")
            for i in range(2, len(days) - 2, 3)
        ]
        toy = SimpleNamespace(rows=rows, trades=trades, m=SimpleNamespace(cal=cal), start=0, end=len(days) - 1)
        flags = [i // 20 % 2 == 0 for i in range(len(days))]
        labels = {
            "ABOVE": flags,
            "BELOW": [not b for b in flags],
            "HIGH": flags,
            "LOW": [not b for b in flags],
            "VIX_GT25": flags,
        }
        problems, failed, detail = G.regimes_covid_concentration(toy, toy, toy, labels, "NET_POSITIVE_AGGREGATE")
        self.assertEqual(problems, [])
        self.assertEqual(failed, [])
        self.assertIn("COVID_2020", detail)
        self.assertIn("EX2020", detail)
        self.assertIn("MAR_JUN_SHOCK", detail)
        negative = copy.deepcopy(toy)
        for r in negative.rows:
            if r["day"] >= date(2021, 1, 4):
                r["excess"] = -0.001 + 0.0001 * math.sin(r["index"])
        problems, failed, _ = G.regimes_covid_concentration(toy, negative, toy, labels, "NET_POSITIVE_AGGREGATE")
        self.assertIn("EX2020 required positive Sharpe", failed)

    def test_calendar_year_concentration_strict40percent_boundary(self):
        from types import SimpleNamespace

        days = [date(2020, 3, 2), date(2021, 1, 4), date(2022, 1, 3), date(2023, 1, 3), date(2024, 1, 2)]
        cal = fake_calendar(days)

        def make(first):
            rows = [
                dict(index=i, day=d, nav=D(str(v)), excess=0.001 + i * 0.0001)
                for i, (d, v) in enumerate(zip(days, [first, 100055, 100070, 100085, 100100]))
            ]
            return SimpleNamespace(rows=rows, trades=[], m=SimpleNamespace(cal=cal))

        labels = {
            "ABOVE": [True] * 5,
            "BELOW": [False] * 5,
            "HIGH": [True] * 5,
            "LOW": [False] * 5,
            "VIX_GT25": [False] * 5,
        }
        b = make(100040)
        _, fails, _ = G.regimes_covid_concentration(b, b, b, labels, "NET_POSITIVE_AGGREGATE")
        self.assertNotIn("calendar-year contribution>40% net positive aggregate", fails)
        b = make(100040.01)
        _, fails, _ = G.regimes_covid_concentration(b, b, b, labels, "NET_POSITIVE_AGGREGATE")
        self.assertIn("calendar-year contribution>40% net positive aggregate", fails)

    def test_oos_wiring_derives_z_rejects_external_z_and_remains_insufficient(self):
        m = market()
        r = P.evaluate_fabricated_card(
            m,
            ir(m),
            cost_adapter(),
            [alias()],
            {"SYNTH_A": "SYNTH_A"},
            [],
            lambda: N.FixedFixtureScorer({}),
            35,
            80,
            {"SYNTH_A": set(range(120))},
            True,
        )
        base = r["books"]["primary"]["H48"]
        from quant_research.strategies.rank1_single_name import rank1_inference as inf

        fields = [k for k in inf.FACTOR_FIELDS if k != "z"]
        factors = []
        for i, row in enumerate(base.rows):
            f = {k: (0.0 if k == "RF" else 0.01 * math.sin((i + 1) * (j + 1) * 0.17)) for j, k in enumerate(fields)}
            factors.append(dict(f, day=row["day"].isoformat(), synthetic_only=True))
        lab = {k: [k in {"BELOW", "LOW"}] * len(base.rows) for k in ("ABOVE", "BELOW", "HIGH", "LOW", "VIX_GT25")}
        ref = dict(synthetic_only=True, prototype_count=72, sha256="a" * 64, sigma_ann=0.75)
        fam = dict(synthetic_only=True, family_N=177, sha256="a" * 64)
        out = P.evaluate_fabricated_oos(
            r,
            factors,
            {"H48": lab, "H120": lab},
            "decimal",
            [-999],
            177,
            0.75,
            ref,
            fam,
            "NET_POSITIVE_AGGREGATE",
            True,
        )
        self.assertEqual(out["real_data_disposition"], "BLOCKED")
        self.assertEqual(out["disposition"], "INSUFFICIENT")
        self.assertEqual(out["card_columns"], 23)
        factors[0]["z"] = 99
        with self.assertRaises(C.Blocked):
            P.evaluate_fabricated_oos(
                r,
                factors,
                {"H48": lab, "H120": lab},
                "decimal",
                [-999],
                177,
                0.75,
                ref,
                fam,
                "NET_POSITIVE_AGGREGATE",
                True,
            )

    def test_cost_path_stress_same_signal_not_extra_card_column(self):
        a = cost_adapter()
        p = a.leg("buy", "2099-01-10", 50, 100, 2000000000, ".02", "primary")
        s = a.leg("buy", "2099-01-10", 50, 100, 2000000000, ".02", "global_2x")
        self.assertEqual(p["all_in_bp"], 30)
        self.assertEqual(s["all_in_bp"], 50)
        self.assertEqual(p["buffer_usd"], s["buffer_usd"])

    def test_concentration_unknown_sector_never_uses_current_gics(self):
        b = book()
        d = G.concentration_disclosure(b, {})
        self.assertIn("UNKNOWN_AT_VINTAGE", d["mean_daily_sector_weights"])
        self.assertFalse(d["actual_independent_N_claimed"])

    def test_locked_plan_metadata_cannot_move_dates_or_activate_optional(self):
        self.assertTrue(P.validate_locked_plan_metadata(dict(P.LOCKED_PLAN)))
        for k, v in (
            ("evaluation_end", "2026-10-30"),
            ("family_floor", 176),
            ("card_configs", 24),
            ("optional_activated", True),
            ("liquidity_end", "2016-01-04"),
        ):
            q = dict(P.LOCKED_PLAN)
            q[k] = v
            with self.assertRaises(C.Blocked):
                P.validate_locked_plan_metadata(q)

    def test_robustness50percent_exact_counts_and_each_row_mandatory(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        def fake(score, n=100, blocks=30):
            return SimpleNamespace(rows=[dict(excess=score)], trades=[None] * n, occupied_blocks=lambda: blocks)

        prim = {c.id: fake(1.0 if c.id in {"H48", "H120"} else 0.5) for c in C.configurations()}
        stress = {c.id: fake(0.1) for c in C.configurations()}
        with patch.object(G, "sharpe", side_effect=lambda xs: float(xs[0])):
            self.assertEqual(G.robustness_numbers(prim, stress), ([], []))
            prim["NE48"] = fake(0.499999)
            self.assertIn("NE48 robustness Sharpe", G.robustness_numbers(prim, stress)[1])
            prim["H120_JOINT12"] = fake(0.5, n=29)
            self.assertIn("H120_JOINT12 counts", G.robustness_numbers(prim, stress)[0])

    def test_baseline_strict_net_cost_sharpe_and_inclusive_alpha_dsr(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        tr = B.CompletedTrade("SYNTH_A", 0, 10, D(5000), D(".02"), D(".005"), D(".015"), "MOCK")
        p = SimpleNamespace(
            trades=[tr] * 100, occupied_blocks=lambda: 30, rows=[dict(day=date(2099, 1, 1), excess=0.5)]
        )
        stress = SimpleNamespace(rows=[dict(day=date(2099, 1, 1), excess=0.1)])
        rng = dict(
            rng_accepted=True,
            joint_draws=True,
            fields_read=["opportunity_pct", "opportunity_usd_over_100k"],
            series={k: dict(mean=0.1, lower_05=0.01) for k in ("opportunity_pct", "opportunity_usd_over_100k")},
        )  # fake NUMBER-GATE receipt, not a real RNG approval
        with patch.object(G, "sharpe", side_effect=lambda xs: float(xs[0])):
            self.assertIn("primary Sharpe", G.baseline_numbers(p, stress, 3.0, 0.95, rng)[1])
            p.rows[0]["excess"] = 0.500001
            self.assertEqual(G.baseline_numbers(p, stress, 3.0, 0.95, rng), ([], []))
            self.assertIn("alpha t>=3 and DSR>=.95", G.baseline_numbers(p, stress, 2.999, 0.95, rng)[1])
            tr.gross_matched_excess = D(".01")  # equality with twice .005 is NOT enough
            self.assertIn(
                "gross matched excess <= twice mean primary all-in cost",
                G.baseline_numbers(p, stress, 3.0, 0.95, rng)[1],
            )

    def test_monthly_coverage90percent_exact_all113months_both_clocks(self):
        rows = [
            dict(
                synthetic_only=True,
                year=y,
                month=m,
                clock=c,
                covered=90,
                active_denominator=100,
                fixed_cohort_denominator=100,
                shards_complete=True,
                pagination_complete=True,
                terminal_denominator_verified=True,
            )
            for y in range(2016, 2026)
            for m in range(1, 13)
            if (y, m) <= (2025, 5)
            for c in ("H48", "H120")
        ]
        self.assertEqual(G.synthetic_monthly_coverage(rows, True, True)["disposition"], "SYNTHETIC_ONLY_PASS")
        rows[0]["covered"] = 89
        self.assertEqual(G.synthetic_monthly_coverage(rows, True, True)["disposition"], "INSUFFICIENT")
        rows[0]["terminal_denominator_verified"] = False
        with self.assertRaises(C.Blocked):
            G.synthetic_monthly_coverage(rows, True, True)
        with self.assertRaises(C.Insufficient):
            G.synthetic_monthly_coverage(rows[1:], True, True)

    def test_parser_totals_private_only_min30_exact90_95_each_year_clock(self):
        rows = [
            dict(
                synthetic_only=True,
                year=y,
                clock=c,
                partial_2025=y == 2025,
                truth_up=100,
                correct_up=90,
                truth_down=100,
                correct_down=90,
                predictions=100,
                correct_predictions=95,
                private_receipt_sha256="a" * 64,
                independent_truth_inventory=True,
            )
            for y in range(2016, 2026)
            for c in ("H48", "H120")
        ]
        out = G.synthetic_parser_totals_gate(rows)
        self.assertEqual(out["disposition"], "SYNTHETIC_ONLY_PASS")
        self.assertFalse(out["detail"]["actual_audit_occurred"])
        rows[0]["correct_predictions"] = 94
        self.assertEqual(G.synthetic_parser_totals_gate(rows)["disposition"], "FAIL")
        rows[0].update(truth_up=29, correct_up=29)
        self.assertEqual(G.synthetic_parser_totals_gate(rows)["disposition"], "INSUFFICIENT")
        rows[0]["headline"] = "SYNTHETIC_FORBIDDEN_EXPORT"
        with self.assertRaises(C.Blocked):
            G.synthetic_parser_totals_gate(rows)

    def test_robustness_requires_every_row_no_pruning(self):
        with self.assertRaises(C.Blocked):
            G.robustness_numbers({}, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
