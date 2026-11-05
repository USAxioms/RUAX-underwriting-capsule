"""Gap-audit tests: display fields, thresholds metadata and 1-cent guard values were never asserted."""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import wad18 as W
from loan_application import LoanApplication, Borrower
from underwriting_engine import underwrite, compute_front_dti, compute_reserve_months


def _app(loan=28_000_000, val=40_000_000, pmt=170_000, score=780, income=900_000, debt=50_000,
         emp=84, assets=800_000, loan_type="CONVENTIONAL"):
    b = Borrower("B", income, "W2", emp, score, debt, assets)
    return LoanApplication("A", loan_type, loan, val, "SINGLE_FAMILY", "PRIMARY", pmt, [b], "2026-11-01")

PRIME = dict()
STANDARD = dict(score=700, loan=19_000_000, val=20_000_000, income=550_000, debt=80_000, pmt=130_000, emp=36)
FHA = dict(score=640, loan_type="FHA", loan=17_750_000, val=18_400_000, income=450_000, debt=60_000, pmt=125_000, emp=18)
DECLINE = dict(score=580)


class TestDisplayFields(unittest.TestCase):
    def test_percent_and_months_strings_exact_and_truncated(self):
        r = underwrite(_app())
        self.assertEqual(r["ltv_pct"], "70.00")
        self.assertEqual(r["dti_back_pct"], "24.44")
        self.assertEqual(r["dti_front_pct"], "18.88")      # 18.888.. truncated, not rounded to 18.89
        self.assertEqual(r["reserve_months_str"], "4.70")  # 4.705.. truncated, not rounded to 4.71


class TestThresholdMetadata(unittest.TestCase):
    def test_per_tier(self):
        for kw, tier, smin, dti, ltv in ((PRIME, "PRIME", 720, "0.3600", "0.8000"),
                                          (STANDARD, "STANDARD", 680, "0.4300", "0.9500"),
                                          (FHA, "FHA_GRADE", 620, "0.5000", "0.9650"),
                                          (DECLINE, "DECLINE", 620, "0.5000", "0.9650")):  # decline reports FHA bounds
            r = underwrite(_app(**kw))
            self.assertEqual(r["tier"], tier)
            self.assertEqual(r["thresholds"], {"score_min": smin, "dti_max_str": dti, "ltv_max_str": ltv}, tier)


class TestOneCentGuards(unittest.TestCase):
    def test_zero_income_sentinel_front_dti(self):
        self.assertEqual(compute_front_dti(_app(income=0)), W.from_int(999))
    def test_one_cent_income_is_a_real_ratio_not_the_sentinel(self):
        self.assertEqual(compute_front_dti(_app(income=1, pmt=170_000)), W.from_int(170_000))
    def test_one_cent_payment_is_a_real_ratio_not_the_sentinel(self):
        self.assertEqual(compute_reserve_months(_app(pmt=1, assets=1000)), W.from_int(1000))

if __name__ == "__main__":
    unittest.main()
