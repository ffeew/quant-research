"""SYNTHETIC unit tests for the §5 as-of control adapters in prereg_run.py.
Every input below is invented (fake symbols, fake CIKs, fake accessions, a 2030 business-day calendar). No historical news,
prices, returns, events or SUE values are read. Run: python3 -m unittest discover -s tests -v   (from news_sentiment/)."""
import os, sys, unittest
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant_research.strategies.news_sentiment import prereg_run as pr

CAL = pd.bdate_range("2030-03-01", "2030-06-28")          # synthetic sessions (spans the 2030-03-10 US DST change)
NY = "America/New_York"


def et(s):   # ET wall time -> UTC instant
    return pd.Timestamp(s).tz_localize(NY).tz_convert("UTC")


def universe(rows):
    return pd.DataFrame(rows, columns=["symbol", "gics_sector", "cik"])


def membership(rows):
    m = pd.DataFrame(rows, columns=["symbol", "start", "end"])
    m["start"] = pd.to_datetime(m.start).fillna(pd.Timestamp("1900-01-01"))
    m["end"] = pd.to_datetime(m.end).fillna(pd.Timestamp("2100-01-01"))
    return m


def events(rows):
    """rows: (accession, cik, acceptance ET string, in_sp500, index_symbols). session_date_0925 computed independently."""
    e = pd.DataFrame(rows, columns=["accession", "cik", "acc_et", "in_sp500", "index_symbols"])
    e["acceptance_utc"] = pd.DatetimeIndex([et(x) for x in e.acc_et])
    cut = [d + pd.Timedelta(hours=9, minutes=25) for d in CAL]
    e["session_date_0925"] = [next((d.date() for d, c in zip(CAL, cut) if c > pd.Timestamp(x)), None) for x in e.acc_et]
    return e.drop(columns="acc_et")


U = universe([("AAA", "Tech", 101), ("AAB", "Tech", 102), ("GGA", "Tech", 103), ("GGB", "Tech", 103),
              ("CCC", "Util", 201), ("DDD", "Util", 202), ("EEE", "Energy", 301), ("OLD", None, np.nan)])
M = membership([("AAA", None, None), ("AAB", None, None), ("GGA", None, None), ("GGB", None, None),
                ("CCC", None, None), ("DDD", "2030-04-01", "2030-04-15"), ("EEE", None, None), ("OLD", None, None)])
FM = pr.firm_map(U)
D = pd.Timestamp("2030-04-10")                                 # Wednesday
I = CAL.get_loc(D)


class TestStrictCutoff(unittest.TestCase):
    def test_exact_0925_maps_to_next_session(self):
        p = pr.first_session_after(pd.DatetimeIndex([et("2030-04-10 09:25:00")]), CAL)[0]
        self.assertEqual(CAL[p], pd.Timestamp("2030-04-11"))
        p = pr.first_session_after(pd.DatetimeIndex([et("2030-04-10 09:24:59.999")]), CAL)[0]
        self.assertEqual(CAL[p], pd.Timestamp("2030-04-10"))

    def test_dst_and_weekend(self):   # 09:25 ET is 14:25 UTC before 2030-03-10 and 13:25 UTC after
        self.assertEqual(CAL[pr.first_session_after(pd.DatetimeIndex([pd.Timestamp("2030-03-11 13:30", tz="UTC")]), CAL)[0]],
                         pd.Timestamp("2030-03-12"))
        self.assertEqual(CAL[pr.first_session_after(pd.DatetimeIndex([et("2030-04-13 12:00")]), CAL)[0]], pd.Timestamp("2030-04-15"))

    def test_naive_rejected_and_out_of_calendar(self):
        with self.assertRaises(pr.ControlInputError): pr.first_session_after(pd.DatetimeIndex([pd.Timestamp("2030-04-10")]), CAL)
        self.assertEqual(pr.first_session_after(pd.DatetimeIndex([et("2030-02-01 12:00"), et("2030-06-28 10:00")]), CAL).tolist(), [-1, -1])

    def test_annshare_same_time_event_excluded(self):
        ev = events([("a1", 101, "2030-04-10 09:25:00", True, "AAA")])
        a = pr.annshare_panel(ev, CAL, [D], M, FM)
        self.assertEqual(a.at[D, "Tech"], 0.0)                         # visible only from 2030-04-11
        a2 = pr.annshare_panel(ev, CAL, [CAL[I + 1]], M, FM)
        self.assertAlmostEqual(a2.at[CAL[I + 1], "Tech"], 1 / 3)       # Tech firms: AAA, AAB, G-firm (GGA/GGB) = 3


class TestAnnshare(unittest.TestCase):
    def test_window_bounds(self):   # §5: s in [d-5, d]
        acc = lambda k: (CAL[I - k] - pd.Timedelta(days=1)).strftime("%Y-%m-%d") + " 20:00"   # evening before -> s = d-k
        for k, want in [(0, 1 / 3), (5, 1 / 3), (6, 0.0), (-1, 0.0)]:
            if k < 0: acc_s = CAL[I].strftime("%Y-%m-%d") + " 16:30"                             # s = d+1: future
            else: acc_s = acc(k)
            ev = events([("x", 101, acc_s, True, "AAA")])
            self.assertAlmostEqual(pr.annshare_panel(ev, CAL, [D], M, FM).at[D, "Tech"], want, msg=f"k={k}")

    def test_share_classes_count_once(self):
        ev = events([("g1", 103, "2030-04-09 16:30", True, "GGA,GGB"), ("g2", 103, "2030-04-09 16:31", True, "GGB")])
        self.assertAlmostEqual(pr.annshare_panel(ev, CAL, [D], M, FM).at[D, "Tech"], 1 / 3)   # 1 firm of 3, not 2/4

    def test_duplicate_symbol_token(self):
        ev = events([("s1", 101, "2030-04-09 16:30", True, "AAA,AAA")])
        self.assertAlmostEqual(pr.annshare_panel(ev, CAL, [D], M, FM).at[D, "Tech"], 1 / 3)

    def test_no_event_sector_zero_and_no_member_sector_nan(self):
        ev = events([("a1", 101, "2030-04-09 16:30", True, "AAA")])
        a = pr.annshare_panel(ev, CAL, [D], M, FM)
        self.assertEqual(a.at[D, "Util"], 0.0); self.assertEqual(a.at[D, "Energy"], 0.0)
        m2 = membership([("AAA", None, None)]); a2 = pr.annshare_panel(ev, CAL, [D], m2, FM)
        self.assertTrue(np.isnan(a2.at[D, "Util"]))                   # no eligible firms: undefined, not 0

    def test_membership_start_end(self):   # DDD member [2030-04-01, 2030-04-15): end exclusive
        ev = events([("d1", 202, "2030-04-09 16:30", True, "DDD")])
        self.assertAlmostEqual(pr.annshare_panel(ev, CAL, [D], M, FM).at[D, "Util"], 0.5)
        e2 = pd.Timestamp("2030-04-15"); ev2 = events([("d2", 202, "2030-04-14 16:30", True, "DDD")])
        self.assertEqual(pr.annshare_panel(ev2, CAL, [e2], M, FM).at[e2, "Util"], 0.0)       # DDD gone, CCC no event
        b = pd.Timestamp("2030-03-29"); ev3 = events([("d3", 202, "2030-03-28 16:30", True, "DDD")])
        self.assertEqual(pr.annshare_panel(ev3, CAL, [b], M, FM).at[b, "Util"], 0.0)          # before DDD's start

    def test_not_in_sp500_ignored(self):
        ev = events([("n1", 101, "2030-04-09 16:30", False, None)])
        self.assertEqual(pr.annshare_panel(ev, CAL, [D], M, FM).at[D, "Tech"], 0.0)

    def test_cik_fallback_only_when_symbols_empty(self):
        ev = events([("c1", 102, "2030-04-09 16:30", True, None)])
        a = pr.annshare_panel(ev, CAL, [D], M, FM)
        self.assertAlmostEqual(a.at[D, "Tech"], 1 / 3); self.assertEqual(a.attrs["diag"]["events_cik_fallback_used"], 1)
        ev = events([("c2", 999, "2030-04-09 16:30", True, None)])
        a = pr.annshare_panel(ev, CAL, [D], M, FM)
        self.assertEqual(a.at[D, "Tech"], 0.0); self.assertEqual(a.attrs["diag"]["events_unattributed"], 1)

    def test_former_alias_symbol_and_identity_conflict(self):
        ev = events([("o1", 101, "2030-04-09 16:30", True, "AAA,OLD")])          # OLD has no sector: credits AAA only
        self.assertAlmostEqual(pr.annshare_panel(ev, CAL, [D], M, FM).at[D, "Tech"], 1 / 3)
        ev = events([("x1", 101, "2030-04-09 16:30", True, "AAA,AAB")])          # two different eligible firms: refuse
        with self.assertRaises(pr.IdentityConflict): pr.annshare_panel(ev, CAL, [D], M, FM)

    def test_reviewed_session_mismatch_and_duplicates_fail(self):
        ev = events([("a1", 101, "2030-04-09 16:30", True, "AAA")]); ev.loc[0, "session_date_0925"] = pd.Timestamp("2030-04-09").date()
        with self.assertRaises(pr.ControlInputError): pr.annshare_panel(ev, CAL, [D], M, FM)
        ev = events([("a1", 101, "2030-04-09 16:30", True, "AAA"), ("a1", 101, "2030-04-09 16:31", True, "AAA")])
        with self.assertRaises(pr.ControlInputError): pr.annshare_panel(ev, CAL, [D], M, FM)

    def test_firm_spanning_sectors_rejected(self):
        with self.assertRaises(pr.IdentityConflict): pr.firm_map(universe([("X1", "Tech", 5), ("X2", "Util", 5)]))


EV = events([("e_aaa_1", 101, "2030-01-28 16:30", True, "AAA"), ("e_aaa_2", 101, "2030-03-27 16:30", True, "AAA"),
             ("e_aab", 102, "2030-03-30 16:30", True, "AAB"), ("e_g", 103, "2030-03-31 16:30", True, "GGA,GGB"),
             ("e_ccc", 201, "2030-03-31 16:30", True, "CCC")])


def sue(rows, **extra):
    s = pd.DataFrame(rows, columns=["accession", "sue", "kt"])
    s["xbrl_knowledge_time_utc"] = pd.DatetimeIndex([et(x) for x in s.kt]); s = s.drop(columns="kt")
    for k, v in extra.items(): s[k] = v
    return s


class TestSUE(unittest.TestCase):
    def panel(self, s, d=D): return pr.sue_sector_panel(s, EV, CAL, [d], M, FM)

    def test_most_recent_out_of_order_and_mean_over_firms(self):
        s = sue([("e_aaa_2", 2.0, "2030-04-08 17:00"), ("e_aab", -1.0, "2030-04-07 17:00"), ("e_aaa_1", 9.0, "2030-03-02 17:00")])
        p = self.panel(s)
        self.assertAlmostEqual(p.at[D, "Tech"], (2.0 + -1.0) / 2)       # AAA uses its later value; G-firm has none
        self.assertEqual(p.at[D, "Util"], 0.0)                           # eligible firms, no SUE -> 0
        self.assertEqual(p.at[D, "Energy"], 0.0)

    def test_exact_cutoff_and_future_excluded(self):
        s = sue([("e_aaa_2", 2.0, "2030-04-10 09:25:00"), ("e_aaa_1", 9.0, "2030-04-09 09:24:59")])
        self.assertAlmostEqual(self.panel(s).at[D, "Tech"], 9.0)        # 09:25:00 on d is not visible at d
        s = sue([("e_aaa_2", 2.0, "2030-04-10 16:00")])
        self.assertEqual(self.panel(s).at[D, "Tech"], 0.0)              # knowledge after d: ignored

    def test_63_session_boundary(self):
        base = pd.Timestamp("2030-06-28"); ib = CAL.get_loc(base)
        for age, want in [(62, 1.5), (63, 0.0)]:
            s_day = CAL[ib - age]; kt = (s_day - pd.Timedelta(days=1)).strftime("%Y-%m-%d") + " 20:00"   # s = base-age
            if pr.first_session_after(pd.DatetimeIndex([et(kt)]), CAL)[0] != ib - age:                   # weekend: use 09:00 same day
                kt = s_day.strftime("%Y-%m-%d") + " 09:00"
            ev_kt = et(kt) - pd.Timedelta(days=1)
            ev = events([("z", 101, (ev_kt.tz_convert(NY)).strftime("%Y-%m-%d %H:%M"), True, "AAA")])
            ev = ev[ev.session_date_0925.notna()]
            p = pr.sue_sector_panel(sue([("z", 1.5, kt)]), ev, CAL, [base], M, FM)
            self.assertAlmostEqual(p.at[base, "Tech"], want, msg=f"age {age}")

    def test_nan_sue_ignored_inf_rejected(self):
        self.assertEqual(self.panel(sue([("e_aaa_2", np.nan, "2030-04-08 17:00")])).at[D, "Tech"], 0.0)
        with self.assertRaises(pr.ControlInputError): self.panel(sue([("e_aaa_2", np.inf, "2030-04-08 17:00")]))

    def test_duplicates_fail(self):
        with self.assertRaises(pr.ControlInputError):
            self.panel(sue([("e_aaa_2", 2.0, "2030-04-08 17:00"), ("e_aaa_2", 3.0, "2030-04-08 18:00")]))
        with self.assertRaises(pr.ControlInputError):   # same firm, same knowledge time (would be last-write)
            self.panel(sue([("e_aaa_2", 2.0, "2030-04-08 17:00"), ("e_aaa_1", 3.0, "2030-04-08 17:00")]))
        with self.assertRaises(pr.ControlInputError):
            self.panel(sue([("e_aaa_2", 2.0, "2030-04-08 17:00"), ("e_aab", 3.0, "2030-04-08 18:00")], xbrl_accn=["q1", "q1"]))
        with self.assertRaises(pr.ControlInputError):
            self.panel(sue([("e_aaa_2", 2.0, "2030-04-08 17:00"), ("e_aaa_1", 3.0, "2030-04-01 18:00")],
                           fiscal_period_end=[pd.Timestamp("2030-03-31")] * 2))

    def test_schema_fail_closed(self):
        good = sue([("e_aaa_2", 2.0, "2030-04-08 17:00")])
        with self.assertRaises(pr.ControlInputError): self.panel(good.drop(columns="sue"))
        with self.assertRaises(pr.ControlInputError):    # synonym only: not guessed
            self.panel(good.rename(columns={"xbrl_knowledge_time_utc": "knowledge_time"}))
        with self.assertRaises(pr.ControlInputError):    # canonical + synonym: ambiguous
            g = good.copy(); g["knowledge_time"] = g.xbrl_knowledge_time_utc; self.panel(g)
        with self.assertRaises(pr.ControlInputError):    # naive timestamps
            g = good.copy(); g["xbrl_knowledge_time_utc"] = g.xbrl_knowledge_time_utc.dt.tz_localize(None); self.panel(g)
        with self.assertRaises(pr.ControlInputError):    # non-UTC tz
            g = good.copy(); g["xbrl_knowledge_time_utc"] = g.xbrl_knowledge_time_utc.dt.tz_convert(NY); self.panel(g)
        with self.assertRaises(pr.ControlInputError): self.panel(sue([("nope", 1.0, "2030-04-08 17:00")]))
        with self.assertRaises(pr.ControlInputError): self.panel(sue([("e_aaa_2", 1.0, "2030-04-08 17:00")], cik=[999]))
        with self.assertRaises(pr.ControlInputError): self.panel(sue([("e_aaa_2", 1.0, "2030-04-08 17:00")], symbol=["AAB"]))
        g = good.copy(); g["sue"] = g.sue.astype(object)
        with self.assertRaises(pr.ControlInputError): self.panel(g)

    def test_knowledge_before_8k_flagged(self):
        with self.assertRaises(pr.SemanticReviewNeeded): self.panel(sue([("e_aaa_2", 1.0, "2030-03-27 16:00")]))

    def test_not_public_share(self):
        ev = events([("w1", 101, "2030-04-08 16:30", True, "AAA"), ("w2", 102, "2030-04-08 16:30", True, "AAB")])
        s = sue([("w1", 1.0, "2030-04-09 08:00"), ("w2", 1.0, "2030-04-20 08:00")])
        self.assertAlmostEqual(pr.sue_not_public_share(s, ev, CAL, D), 0.5)


class TestGuards(unittest.TestCase):
    def test_loaders_require_strict(self):
        self.assertFalse(pr._STRICT_OK)
        for f in (pr.load_events, pr.load_sue): 
            with self.assertRaises(RuntimeError): f()
        with self.assertRaises(RuntimeError): pr.controls({}, CAL, [D])

    def test_same_eligible_sectors_and_leg_difference(self):
        L = pd.DataFrame({"Tech": [0.1, np.nan], "Util": [0.2, 0.3]}, index=[D, CAL[I + 1]])
        X = pd.DataFrame({"Tech": [0.5, 0.9], "Util": [np.nan, 0.1]}, index=L.index)
        with self.assertRaises(pr.ControlInputError): pr.on_primary_eligibility(L, X, "REV5")
        X2 = X.fillna(0.4); Xa = pr.on_primary_eligibility(L, X2, "REV5")
        self.assertTrue(np.isnan(Xa.at[CAL[I + 1], "Tech"]))               # masked to L's eligibility
        ld = pr.leg_difference(Xa, {D: (["Tech"], ["Util"])})
        self.assertAlmostEqual(ld[D], 0.1); self.assertEqual(len(ld), 1)   # unformed days absent, not 0
        with self.assertRaises(pr.ControlInputError): pr.leg_difference(Xa, {CAL[I + 1]: (["Tech"], ["Util"])})

    def test_rules_unchanged(self):
        self.assertEqual((pr.N_FAMILY, pr.N_HYPEFADE), (153, 345))
        self.assertEqual((pr.BORROW_BASE, pr.BORROW_HTB_SENS, pr.COST_MULT_STRESS, pr.HTB_GATE_APPLIES), (0.01, 0.10, 2.0, True))
        self.assertEqual(pr.PRIMARY, dict(hold=5, k=3, min_stocks=3, min_sectors=6, scorer="lm", filt=True, window="overnight_full"))
        self.assertEqual(pr.EVENTS_SHA, "d568a60d19348ad2948083df6a95f64e501f25615d773cdac14ebd9629216d2e")
        self.assertIsNone(pr.SUE_SHA)


if __name__ == "__main__":
    unittest.main()
