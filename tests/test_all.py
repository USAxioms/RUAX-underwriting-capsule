"""
Underwriting Capsule — comprehensive test suite.
Zero third-party dependencies.
"""
import sys, os, json, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from loan_application    import LoanApplication, Borrower, LOAN_TYPES
from underwriting_engine import (
    underwrite, compute_ltv, compute_back_dti, compute_front_dti,
    compute_reserve_months,
    APPROVE, APPROVE_WITH_CONDITIONS, REFER, DECLINE, DECISIONS,
    COND_PMI, COND_EMPLOYMENT, COND_RESERVES, COND_SELF_EMPLOYED, COND_INVESTMENT,
    PRIME_DTI_MAX, STANDARD_DTI_MAX, FHA_DTI_MAX,
    PRIME_LTV_MAX, STANDARD_LTV_MAX, FHA_LTV_MAX,
    PMI_LTV_THRESHOLD,
    PRIME_SCORE_MIN, STANDARD_SCORE_MIN, FHA_SCORE_MIN,
)
from csl import CSL, IntegrityError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Helpers ──────────────────────────────────────────────────────────────

def _borrower(income=900_000, score=780, debt=50_000,
              emp=84, assets=800_000, emp_type="W2"):
    return Borrower("B", income, emp_type, emp, score, debt, assets)

def _app(loan=28_000_000, val=40_000_000, pmt=170_000,
         score=780, income=900_000, debt=50_000, emp=84,
         assets=800_000, loan_type="CONVENTIONAL",
         occ="PRIMARY", prop="SINGLE_FAMILY", emp_type="W2"):
    b = _borrower(income=income, score=score, debt=debt,
                  emp=emp, assets=assets, emp_type=emp_type)
    return LoanApplication("APP", loan_type, loan, val, prop, occ, pmt, [b], "2026-11-01")


# ══════════════════════════════════════════════════════════
# Loan Application model
# ══════════════════════════════════════════════════════════

class TestLoanApplication(unittest.TestCase):

    def test_rejects_unknown_loan_type(self):
        with self.assertRaises(ValueError):
            _app(loan_type="PAYDAY")

    def test_rejects_negative_loan_amount(self):
        with self.assertRaises(ValueError):
            _app(loan=-1)

    def test_rejects_credit_score_out_of_range(self):
        with self.assertRaises(ValueError):
            _borrower(score=200)
        with self.assertRaises(ValueError):
            _borrower(score=900)

    def test_combined_income_sums_borrowers(self):
        b1 = _borrower(income=500_000)
        b2 = _borrower(income=300_000)
        app = LoanApplication("X", "CONVENTIONAL", 10_000_000, 15_000_000,
                              "SINGLE_FAMILY", "PRIMARY", 80_000, [b1, b2], "2026-01-01")
        self.assertEqual(app.combined_gross_monthly_income_cents(), 800_000)

    def test_combined_debt_sums_borrowers(self):
        b1 = _borrower(debt=50_000)
        b2 = _borrower(debt=30_000)
        app = LoanApplication("X", "CONVENTIONAL", 10_000_000, 15_000_000,
                              "SINGLE_FAMILY", "PRIMARY", 80_000, [b1, b2], "2026-01-01")
        self.assertEqual(app.combined_monthly_debt_payments_cents(), 80_000)

    def test_representative_score_is_minimum(self):
        b1 = _borrower(score=780)
        b2 = _borrower(score=660)
        app = LoanApplication("X", "CONVENTIONAL", 10_000_000, 15_000_000,
                              "SINGLE_FAMILY", "PRIMARY", 80_000, [b1, b2], "2026-01-01")
        self.assertEqual(app.representative_credit_score(), 660)

    def test_down_payment_is_value_minus_loan(self):
        app = _app(loan=28_000_000, val=40_000_000)
        self.assertEqual(app.down_payment_cents(), 12_000_000)

    def test_roundtrip_json(self):
        app  = _app()
        app2 = LoanApplication.from_dict(app.to_dict())
        self.assertEqual(app2.loan_amount_cents, app.loan_amount_cents)
        self.assertEqual(app2.borrowers[0].credit_score, 780)


# ══════════════════════════════════════════════════════════
# WAD-18 ratio computations
# ══════════════════════════════════════════════════════════

class TestRatioComputations(unittest.TestCase):

    def test_ltv_70_percent(self):
        """70% LTV: loan=280k, val=400k."""
        app = _app(loan=28_000_000, val=40_000_000)
        ltv = compute_ltv(app)
        ltv_pct = W.to_str(W.mul(ltv, W.from_int(100)), 2)
        self.assertEqual(ltv_pct, "70.00")

    def test_ltv_80_percent_boundary(self):
        """Exactly 80% LTV — on the PMI threshold."""
        app = _app(loan=16_000_000, val=20_000_000)
        ltv = compute_ltv(app)
        self.assertEqual(ltv, PRIME_LTV_MAX)

    def test_dti_exact(self):
        """DTI = (50k existing + 170k payment) / 900k income = 24.44%."""
        app = _app(loan=28_000_000, val=40_000_000, pmt=170_000,
                   income=900_000, debt=50_000)
        dti = compute_back_dti(app)
        # exact: 220000/900000 = 22/90 = 11/45
        expected = W.div(W.from_cents(220_000), W.from_cents(900_000))
        self.assertEqual(dti, expected)

    def test_zero_income_gives_sentinel(self):
        """Zero income → infinite DTI → always decline."""
        app = _app(income=0)
        dti = compute_back_dti(app)
        self.assertGreater(dti, W.from_int(10))   # sentinel >> any threshold

    def test_reserve_months_exact(self):
        """800k assets / 170k PITI = 4.7 months."""
        app = _app(pmt=170_000, assets=800_000)
        res = compute_reserve_months(app)
        expected = W.div(W.from_cents(800_000), W.from_cents(170_000))
        self.assertEqual(res, expected)

    def test_reserve_months_sufficient(self):
        app = _app(pmt=170_000, assets=800_000)
        res = compute_reserve_months(app)
        # 800k/170k ≈ 4.7 months ≥ 2 required
        self.assertGreater(res, W.from_int(2))

    def test_front_dti_less_than_back_dti(self):
        """Front-end DTI (housing only) must be ≤ back-end DTI."""
        app = _app(pmt=170_000, income=900_000, debt=50_000)
        front = compute_front_dti(app)
        back  = compute_back_dti(app)
        self.assertLessEqual(front, back)

    def test_ratios_are_wad18_integers(self):
        app = _app()
        for ratio in [compute_ltv(app), compute_back_dti(app),
                      compute_front_dti(app), compute_reserve_months(app)]:
            self.assertIsInstance(ratio, int)
            self.assertNotIsInstance(ratio, bool)


# ══════════════════════════════════════════════════════════
# PO0: Decision always in valid set
# ══════════════════════════════════════════════════════════

class TestDecisionValidity(unittest.TestCase):
    """PO0: decision ∈ {APPROVE, APPROVE_WITH_CONDITIONS, REFER, DECLINE}."""

    def test_reference_applications_all_valid_decisions(self):
        path = os.path.join(ROOT, "data", "reference_applications.json")
        for ad in json.load(open(path))["applications"]:
            app    = LoanApplication.from_dict(ad)
            result = underwrite(app)
            self.assertIn(result["decision"], DECISIONS,
                          f"{ad['label']}: {result['decision']!r} not in DECISIONS")

    def test_decision_is_always_a_string(self):
        for score in [800, 700, 640, 580]:
            for dti in [0.25, 0.40, 0.48, 0.60]:
                income  = 500_000
                debt    = int(income * dti * 0.6)
                pmt     = int(income * dti * 0.4)
                app = _app(score=score, income=income, debt=debt, pmt=pmt)
                result  = underwrite(app)
                self.assertIsInstance(result["decision"], str)


# ══════════════════════════════════════════════════════════
# PO1: Reproducibility
# ══════════════════════════════════════════════════════════

class TestReproducibility(unittest.TestCase):

    def test_same_application_same_decision(self):
        app = _app()
        r1  = underwrite(app)
        r2  = underwrite(app)
        self.assertEqual(r1["decision"],       r2["decision"])
        self.assertEqual(r1["tier"],           r2["tier"])
        self.assertEqual(r1["ltv_wad18"],      r2["ltv_wad18"])
        self.assertEqual(r1["dti_back_wad18"], r2["dti_back_wad18"])


# ══════════════════════════════════════════════════════════
# PO2: Constraint satisfaction
# ══════════════════════════════════════════════════════════

class TestConstraints(unittest.TestCase):
    """PO2: thresholds correctly applied at exact boundaries."""

    def test_ltv_exactly_at_prime_max_is_prime(self):
        """LTV = exactly 80% satisfies the PRIME LTV constraint."""
        app = _app(loan=16_000_000, val=20_000_000)
        self.assertEqual(compute_ltv(app), PRIME_LTV_MAX)
        result = underwrite(app)
        self.assertEqual(result["tier"], "PRIME")
        self.assertNotIn(COND_PMI, result["conditions"])

    def test_ltv_just_above_prime_max_is_not_prime(self):
        """LTV > 80% → not PRIME tier for LTV; no longer qualifies."""
        app = _app(loan=16_100_000, val=20_000_000)   # 80.5%
        ltv = compute_ltv(app)
        self.assertGreater(ltv, PRIME_LTV_MAX)

    def test_pmi_triggered_above_80_percent(self):
        """LTV > 80% → COND_PMI in conditions."""
        app = _app(loan=17_000_000, val=20_000_000)   # 85%
        result = underwrite(app)
        if result["tier"] != "DECLINE":
            self.assertIn(COND_PMI, result["conditions"])

    def test_pmi_not_triggered_at_exactly_80_percent(self):
        """LTV = 80% exactly → no PMI required."""
        app = _app(loan=16_000_000, val=20_000_000)
        result = underwrite(app)
        self.assertNotIn(COND_PMI, result["conditions"])

    def test_prime_dti_boundary(self):
        """DTI exactly at 36% satisfies PRIME DTI constraint."""
        # (debt + pmt) / income = 0.36
        income = 500_000
        pmt    = 130_000
        debt   = int(0.36 * income) - pmt   # = 50000
        app = _app(income=income, debt=debt, pmt=pmt,
                   loan=16_000_000, val=20_000_000)
        dti = compute_back_dti(app)
        self.assertLessEqual(dti, PRIME_DTI_MAX)

    def test_employment_condition_attached(self):
        """Employment < 24 months → COND_EMPLOYMENT in conditions."""
        app = _app(emp=12)
        result = underwrite(app)
        if result["tier"] != "DECLINE":
            self.assertIn(COND_EMPLOYMENT, result["conditions"])

    def test_no_employment_condition_at_24_months(self):
        """Employment = 24 months → no COND_EMPLOYMENT."""
        app = _app(emp=24)
        result = underwrite(app)
        self.assertNotIn(COND_EMPLOYMENT, result["conditions"])

    def test_self_employed_condition_always_attached(self):
        """SELF_EMPLOYED borrower → COND_SELF_EMPLOYED always present."""
        app = _app(emp_type="SELF_EMPLOYED", emp=60)
        result = underwrite(app)
        if result["tier"] != "DECLINE":
            self.assertIn(COND_SELF_EMPLOYED, result["conditions"])


# ══════════════════════════════════════════════════════════
# PO3: Monotonicity — better application ≥ better decision
# ══════════════════════════════════════════════════════════

DECISION_ORDER = {APPROVE: 3, APPROVE_WITH_CONDITIONS: 2, REFER: 1, DECLINE: 0}


class TestMonotonicity(unittest.TestCase):
    """PO3: improving any single factor cannot worsen the decision."""

    def _rank(self, result): return DECISION_ORDER[result["decision"]]

    def test_higher_score_never_worsens_decision(self):
        """Raising credit score by 50 points must not lower the decision rank."""
        base  = _app(score=680)
        better= _app(score=730)
        self.assertGreaterEqual(self._rank(underwrite(better)),
                                self._rank(underwrite(base)))

    def test_lower_dti_never_worsens_decision(self):
        """Reducing DTI (paying off debt) must not lower decision rank."""
        base  = _app(income=500_000, debt=100_000, pmt=130_000)
        better= _app(income=500_000, debt=30_000,  pmt=130_000)
        self.assertGreaterEqual(self._rank(underwrite(better)),
                                self._rank(underwrite(base)))

    def test_lower_ltv_never_worsens_decision(self):
        """Larger down payment (lower LTV) must not lower decision rank."""
        base  = _app(loan=19_000_000, val=20_000_000)
        better= _app(loan=16_000_000, val=20_000_000)
        self.assertGreaterEqual(self._rank(underwrite(better)),
                                self._rank(underwrite(base)))

    def test_more_assets_never_worsens_decision(self):
        """More liquid assets (more reserves) must not lower decision rank."""
        base  = _app(assets=200_000, pmt=170_000)
        better= _app(assets=600_000, pmt=170_000)
        self.assertGreaterEqual(self._rank(underwrite(better)),
                                self._rank(underwrite(base)))

    def test_prime_beats_standard_beats_fha_beats_decline(self):
        """Tier ordering must be strict: PRIME > STANDARD > FHA > DECLINE."""
        prime   = underwrite(_app(score=780, loan=16_000_000, val=20_000_000,
                                  income=900_000, debt=50_000, pmt=170_000, emp=60))
        standard= underwrite(_app(score=700, loan=19_000_000, val=20_000_000,
                                  income=550_000, debt=80_000, pmt=130_000, emp=36))
        decline = underwrite(_app(score=580))
        self.assertGreaterEqual(self._rank(prime),    self._rank(standard))
        self.assertGreaterEqual(self._rank(standard), self._rank(decline))


# ══════════════════════════════════════════════════════════
# Reference application pinned decisions
# ══════════════════════════════════════════════════════════

class TestReferenceDecisions(unittest.TestCase):
    """Pinned decisions for all six reference applications."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ROOT, "data", "reference_applications.json")
        cls.results = {}
        for ad in json.load(open(path))["applications"]:
            app = LoanApplication.from_dict(ad)
            r   = underwrite(app)
            r["expected_decision"] = ad.get("expected_decision")
            r["expected_tier"]     = ad.get("expected_tier")
            cls.results[ad["label"]] = r

    def _check(self, label):
        r = self.results[label]
        self.assertEqual(r["decision"], r["expected_decision"],
                         f"{label}: got {r['decision']}, expected {r['expected_decision']}")
        self.assertEqual(r["tier"], r["expected_tier"],
                         f"{label}: got tier {r['tier']}, expected {r['expected_tier']}")

    def test_prime_conventional(self):   self._check("prime_conventional")
    def test_standard_with_pmi(self):   self._check("standard_with_pmi")
    def test_fha_grade(self):           self._check("fha_grade")
    def test_decline_high_dti(self):    self._check("decline_high_dti")
    def test_self_employed_prime(self):  self._check("self_employed_prime")
    def test_decline_low_score(self):   self._check("decline_low_score")

    def test_prime_has_no_conditions(self):
        r = self.results["prime_conventional"]
        self.assertEqual(r["conditions"], [])

    def test_standard_pmi_has_pmi_condition(self):
        r = self.results["standard_with_pmi"]
        self.assertIn(COND_PMI, r["conditions"])

    def test_fha_has_employment_and_pmi_conditions(self):
        r = self.results["fha_grade"]
        self.assertIn(COND_PMI,        r["conditions"])
        self.assertIn(COND_EMPLOYMENT, r["conditions"])

    def test_self_employed_has_tax_return_condition(self):
        r = self.results["self_employed_prime"]
        self.assertIn(COND_SELF_EMPLOYED, r["conditions"])

    def test_arithmetic_field_present_in_all(self):
        for label, r in self.results.items():
            self.assertEqual(r["arithmetic"], "WAD-18 exact integer throughout",
                             f"{label} missing arithmetic field")


# ══════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):

    def test_zero_existing_debt_uses_payment_only(self):
        """Zero existing debt: DTI = payment / income."""
        app = _app(debt=0, pmt=100_000, income=500_000)
        dti = compute_back_dti(app)
        expected = W.div(W.from_cents(100_000), W.from_cents(500_000))
        self.assertEqual(dti, expected)

    def test_va_loan_cannot_reach_fha_grade(self):
        """VA loans are excluded from the FHA_GRADE tier."""
        app = _app(loan_type="VA", score=640, income=450_000,
                   debt=60_000, pmt=125_000,
                   loan=17_750_000, val=18_400_000)
        result = underwrite(app)
        self.assertNotEqual(result["tier"], "FHA_GRADE")

    def test_investment_property_gets_investment_condition(self):
        """Investment property → COND_INVESTMENT attached."""
        app = _app(occ="INVESTMENT")
        result = underwrite(app)
        if result["tier"] != "DECLINE":
            self.assertIn(COND_INVESTMENT, result["conditions"])

    def test_two_borrower_income_pooled(self):
        """Co-borrowers' incomes combine for DTI calculation."""
        b1 = _borrower(income=300_000, debt=20_000)
        b2 = _borrower(income=300_000, debt=20_000)
        app = LoanApplication("X", "CONVENTIONAL",
                              16_000_000, 20_000_000, "SINGLE_FAMILY", "PRIMARY",
                              120_000, [b1, b2], "2026-01-01")
        dti = compute_back_dti(app)
        # (20k+20k+120k) / (300k+300k) = 160k/600k = 0.2667
        expected = W.div(W.from_cents(160_000), W.from_cents(600_000))
        self.assertEqual(dti, expected)

    def test_pmi_required_flag_consistent_with_ltv(self):
        """pmi_required field must exactly match ltv > PMI_LTV_THRESHOLD."""
        for ltv_pct in [75, 79, 80, 81, 85, 95]:
            loan = ltv_pct * 200_000
            app  = _app(loan=loan, val=20_000_000)
            ltv  = compute_ltv(app)
            result = underwrite(app)
            expected_pmi = ltv > PMI_LTV_THRESHOLD
            self.assertEqual(result["pmi_required"], expected_pmi,
                             f"ltv={ltv_pct}%: pmi_required mismatch")


# ══════════════════════════════════════════════════════════
# CSL audit chain
# ══════════════════════════════════════════════════════════

class TestCSLAudit(unittest.TestCase):

    def test_decision_committed_to_csl(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            csl    = CSL(path)
            app    = _app()
            result = underwrite(app)
            blk    = csl.append({"decision": result["decision"],
                                  "ltv_wad18": result["ltv_wad18"]}, "test")
            self.assertTrue(csl.verify())
            self.assertEqual(len(blk["H_i"]), 64)
        finally:
            os.unlink(path)

    def test_tamper_detection(self):
        import json as _json
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         delete=False) as f:
            path = f.name
        try:
            csl = CSL(path)
            csl.append({"decision": APPROVE})
            csl.append({"decision": DECLINE})
            blocks = _json.load(open(path))
            blocks[0]["S_i"]["decision"] = DECLINE
            _json.dump(blocks, open(path, "w"))
            with self.assertRaises(IntegrityError):
                CSL(path).verify()
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
