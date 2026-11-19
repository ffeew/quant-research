from quant_research.utils import paths as _QR  # data/desk roots from env (QR_DATA_DIR, ...)
import sys, math, unittest, itertools, importlib.util
from datetime import date
from decimal import Decimal
from fractions import Fraction as F
D = f"{_QR.COSTS_DIR}"
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
v12 = load("cm12", D + "/cost_model_v1_2.py")
v11 = load("cm11", f"{_QR.COSTS_DIR}/cost_model_v1_1_baseline_20261107.py")
HOL, NORM = date(2026, 10, 30), date(2027, 2, 1)

class Ceil(unittest.TestCase):
    def test_adversarial(self):
        c = v12._ceil_cent
        self.assertEqual(c("0.010000001"), 0.02)
        self.assertEqual(v11._ceil_cent(0.010000001), 0.01)  # documents the v1.1 undercharge
        self.assertEqual(c("0.01"), 0.01); self.assertEqual(c(Decimal("0.01")), 0.01)
        self.assertEqual(c("0.0100000000000000000000000000000000000000000001"), 0.02)
        for t in ("1e-30", "0.000000000000000000000000000000000000001"): self.assertEqual(c(t), 0.01)
        for z in ("0", "0.000", 0, 0.0, Decimal("0")): self.assertEqual(c(z), 0.0)
        self.assertEqual(c("0.29999999"), 0.30); self.assertEqual(c("0.30"), 0.30); self.assertEqual(c("0.30000001"), 0.31)
    def test_float_compat(self):
        # floats via shortest repr: 0.01 -> exact 0.01 (not binary 0.01000000000000000020816...)
        self.assertEqual(v12._ceil_cent(0.01), 0.01); self.assertEqual(v12._ceil_cent(0.010000001), 0.02)
    def test_reject(self):
        for bad in (float("nan"), float("inf"), True, "NaN", "Infinity", "1,0", "", "abc", Decimal("NaN"), None, "0x10"):
            with self.assertRaises((TypeError, ValueError)): v12._exact(bad)
        with self.assertRaises(ValueError): v12._ceil_cent_exact(F(-1, 10**12))
        with self.assertRaises(ValueError): v12._ceil_cent("-0.01")  # negative raw rejected

class Fees(unittest.TestCase):
    def test_integration_undercharge_fixed(self):
        # CAT raw = 0.000003 * 3333.3337 = 0.0100000011 -> v1.2 0.02 ; v1.1 0.01
        self.assertEqual(v12.regulatory_fees_usd("buy", "50", "3333.3337", HOL)["cat_usd"], 0.02)
        self.assertEqual(v11.regulatory_fees_usd("buy", 50.0, 3333.3337, HOL)["cat_usd"], 0.01)
        self.assertEqual(v12.regulatory_fees_usd("buy", "50", "3333.3337", HOL)["cat_usd_exact"], "0.02")
    def test_exact_penny(self):
        # SEC raw exactly 1.00: 0.0000206 * 48543.6893... no; use notional 50000 -> 1.03 exact
        f = v12.regulatory_fees_usd("sell", "100", "500", HOL)
        self.assertEqual(f["sec_usd_exact"], "1.03"); self.assertEqual(f["taf_usd"], 0.0)
    def test_cap(self):
        f = v12.regulatory_fees_usd("sell", "10", "1000000", NORM, round_per_trade=False)
        self.assertEqual(f["taf_usd"], 9.79); self.assertEqual(f["taf_usd_exact"], "979/100")
        self.assertEqual(v12.regulatory_fees_usd("sell", "10", "50205", NORM)["taf_usd"], 9.79)   # raw 9.789975 -> 9.79
        self.assertEqual(v12.regulatory_fees_usd("sell", "10", "50206", NORM)["taf_usd"], 9.79)   # raw 9.79017 capped 9.79
    def test_split_fills(self):
        one = v12.regulatory_fees_usd("sell", "100", "100", NORM)["fees_usd"]
        two = 2 * v12.regulatory_fees_usd("sell", "100", "50", NORM)["fees_usd"]
        self.assertAlmostEqual(one, 0.21 + 0.02 + 0.01); self.assertAlmostEqual(two, 2 * (0.11 + 0.01 + 0.01))
        self.assertGreaterEqual(two, one)
    def test_selftest_cases_match_v11(self):
        for args in [("sell",100.0,100,HOL),("sell",100.0,100,NORM),("buy",100.0,100,HOL),("sell",187.3,50,NORM),("buy",656.71,15,NORM)]:
            a, b = v11.regulatory_fees_usd(*args), v12.regulatory_fees_usd(*args)
            for k in ("sec_usd","taf_usd","cat_usd"): self.assertEqual(a[k], b[k], (args, k))
            self.assertAlmostEqual(a["fees_usd"], b["fees_usd"], places=12)  # v1.1 float-sums components; v1.2 sums exactly

class Regression(unittest.TestCase):
    NONFEE = ("half_spread_bps","impact_bps","paper_buffer_bps","participation","notional_usd","bucket","half_spread_usd","impact_usd","paper_buffer_usd","k","sigma_daily","warnings","side","venue")
    def test_nonfee_identical_grid(self):
        grid = itertools.product(["buy","sell"],[12.34,100.0,656.71],[1,50,3333,10**6],[None,4.2e7,1e5],[None,0.016],[None,1.2],["continuous","close","open"],[True,False])
        n = 0
        for side,p,sh,adv,sig,spr,ven,cross in grid:
            a = v11.trade_cost(side,p,sh,adv,sig,spr,venue=ven,crossing=cross,trade_date=NORM)
            b = v12.trade_cost(side,p,sh,adv,sig,spr,venue=ven,crossing=cross,trade_date=NORM)
            for k in self.NONFEE:
                x, y = a[k], b[k]
                self.assertTrue(x == y or (isinstance(x,float) and math.isnan(x) and math.isnan(y)), (k,x,y))
            n += 1
        self.assertGreater(n, 1000)
    def test_stress_and_helpers_identical(self):
        self.assertEqual(v11.net_edge(10, 8), v12.net_edge(10, 8))
        self.assertEqual(v11.borrow_cost(50000, 30), v12.borrow_cost(50000, 30))
        self.assertEqual(v11.impact_grid(), v12.impact_grid())
        self.assertEqual(v11.annual_cost_drag(0.5, 12, 6.0, 0.5, 2.0), v12.annual_cost_drag(0.5, 12, 6.0, 0.5, 2.0))
        for name in ("SEC_FEE_PER_DOLLAR","TAF_PER_SHARE","TAF_MAX_PER_TRADE","TAF_HOLIDAY","CAT_PER_SHARE","K_IMPACT_DEFAULT","BUCKETS","VENUES","BORROW_RATE_ETB_DEFAULT","MAX_RELIABLE_PARTICIPATION"):
            self.assertEqual(getattr(v11,name), getattr(v12,name), name)
    def test_string_inputs_trade_cost(self):
        a = v12.trade_cost("sell", "100", "100", 4.2e7, 0.016, 1.2, trade_date=NORM)
        b = v12.trade_cost("sell", 100.0, 100, 4.2e7, 0.016, 1.2, trade_date=NORM)
        for k in self.NONFEE + ("fees_usd","total_bps"): self.assertEqual(a[k], b[k], k)
        with self.assertRaises(ValueError): v12.trade_cost("sell", "-1", "1")
        with self.assertRaises((TypeError, ValueError)): v12.trade_cost("sell", True, 1)
    def test_no_auto_upgrade(self):
        import subprocess
        out = subprocess.run(["grep","-rlE","cost_model_v1_2",f"{_QR.DESK_DIR}","--include=*.py"],capture_output=True,text=True).stdout.split()
        self.assertTrue(all("cost_model_v1_2" in p for p in out), out)  # only the new module and its tests reference it
if __name__ == "__main__": unittest.main(verbosity=1)
