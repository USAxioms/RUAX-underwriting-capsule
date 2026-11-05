"""
Targeted survivor tests — Underwriting Capsule.
Each test is labelled with the mutant(s) it kills.
"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wad18 as W
from loan_application    import LoanApplication, Borrower
from underwriting_engine import (
    underwrite, compute_ltv, compute_back_dti, compute_reserve_months,
    APPROVE, APPROVE_WITH_CONDITIONS, REFER, DECLINE,
    COND_PMI, COND_EMPLOYMENT, COND_RESERVES, COND_SELF_EMPLOYED,
    PRIME_SCORE_MIN, STANDARD_SCORE_MIN, FHA_SCORE_MIN,
    PRIME_DTI_MAX, STANDARD_DTI_MAX, FHA_DTI_MAX,
    PRIME_LTV_MAX, STANDARD_LTV_MAX, FHA_LTV_MAX,
    PRIME_EMPLOYMENT_MIN, STANDARD_EMPLOYMENT_MIN, FHA_EMPLOYMENT_MIN,
    PRIME_RESERVES_MONTHS, STANDARD_RESERVES_MONTHS, FHA_RESERVES_MONTHS,
    PMI_LTV_THRESHOLD,
)

SCALE = W.SCALE


# ── helpers ──────────────────────────────────────────────────────────────

def _b(income=900_000, score=780, debt=50_000, emp=84,
       assets=800_000, emp_type="W2"):
    return Borrower("B", income, emp_type, emp, score, debt, assets)

def _app(loan=28_000_000, val=40_000_000, pmt=170_000,
         score=780, income=900_000, debt=50_000, emp=84,
         assets=800_000, loan_type="CONVENTIONAL",
         occ="PRIMARY", prop="SINGLE_FAMILY", emp_type="W2"):
    b = _b(income=income, score=score, debt=debt,
           emp=emp, assets=assets, emp_type=emp_type)
    return LoanApplication("APP", loan_type, loan, val, prop, occ, pmt, [b], "2026-11-01")


# ══════════════════════════════════════════════════════════
# wad18.py — rounding, sign, boundary tests
# (wad18 tests not included in test_all.py; must be here)
# ══════════════════════════════════════════════════════════

class TestWAD18Direct(unittest.TestCase):

    def test_rhe_half_even_round_down(self):
        """Kills wad18:28 '2→1/3' and wad18:29 mutations:
        2.5 must round to 2 (half-even: nearest even = 2)."""
        self.assertEqual(W._rhe(5, 2), 2)

    def test_rhe_half_even_round_up(self):
        """Kills wad18:29 '1→2' (q&1 → q&2): 3.5 must round to 4."""
        self.assertEqual(W._rhe(7, 2), 4)

    def test_rhe_plain_round_down(self):
        """Kills wad18:28 '2→3': 1.4 must round to 1, not 2."""
        self.assertEqual(W._rhe(7, 5), 1)   # 7/5=1.4 → 1

    def test_rhe_plain_round_up(self):
        """Kills wad18:28 '2→1': 1.6 must round to 2."""
        self.assertEqual(W._rhe(8, 5), 2)   # 8/5=1.6 → 2

    def test_rhe_zero_denominator_raises_value_error(self):
        """Kills wad18:25 '<=→<'."""
        try:
            W._rhe(1, 0)
            self.fail("Expected ValueError")
        except ValueError:
            pass
        except ZeroDivisionError:
            self.fail("Mutant let den=0 reach divmod")

    def test_rhe_unit_denominator_accepted(self):
        """Kills wad18:25 '0→1'."""
        self.assertEqual(W._rhe(3, 1), 3)

    def test_from_str_negative_parses_correctly(self):
        """Kills wad18:38 'or→and' and wad18:49 '-→+'."""
        self.assertLess(W.from_str("-0.360000000000000000"), 0)

    def test_from_str_integer_part_correct(self):
        """Kills wad18:48 'or→and': int(whole and '0') always gives 0."""
        self.assertEqual(W.from_str("3.0"), 3 * SCALE)

    def test_from_str_empty_string_is_zero(self):
        """Kills wad18:46 '!=→=='."""
        self.assertEqual(W.from_str(""), 0)

    def test_to_str_negative_exact(self):
        """Kills wad18:63 '-→+' and wad18:68 '+→-'."""
        self.assertEqual(W.to_str(-W.ONE, 4), "-1.0000")

    def test_to_str_positive_exact(self):
        """Kills wad18:68 '+→-': positive must not start with '-'."""
        self.assertEqual(W.to_str(W.ONE, 4), "1.0000")

    def test_to_str_truncation_correct(self):
        """Kills wad18:66 '<→<='."""
        self.assertEqual(W.to_str(W.from_str("0.360000000000000000"), 2), "0.36")

    def test_mul_negative_result(self):
        """Kills wad18:79 '-→+'."""
        self.assertLess(W.mul(-W.ONE, W.ONE), 0)

    def test_div_exact_fraction(self):
        """Kills wad18:28-30 mutations via hardcoded expected value."""
        # 1/4 exactly: _rhe(SCALE^2, 4*SCALE) = SCALE/4 = 250_000_000_000_000_000
        self.assertEqual(W.div(W.ONE, W.from_int(4)),
                         W.from_str("0.250000000000000000"))

    def test_div_third_rounds_down(self):
        """Kills wad18:29 via hardcoded expected value for 1/3."""
        # 1/3 = 0.333...recurring → rounds down
        result = W.div(W.ONE, W.from_int(3))
        self.assertEqual(result, 333_333_333_333_333_333)

    def test_div_zero_denominator_raises_zero_division(self):
        """Kills wad18:83 '0→1'."""
        try:
            W.div(W.ONE, W.ZERO)
            self.fail("Expected ZeroDivisionError")
        except ZeroDivisionError:
            pass
        except ValueError:
            self.fail("Mutant let b=0 reach _rhe")

    def test_div_negative_by_positive_is_negative(self):
        """Kills wad18:87 '-→+'."""
        self.assertLess(W.div(-W.ONE, W.from_int(2)), 0)

    def test_assert_wad_returns_true(self):
        """Kills wad18:105 'True→False'."""
        self.assertIs(W.assert_wad(W.ONE), True)

    def test_clamp_at_lower_bound(self):
        """Kills wad18:92 '<→<='."""
        self.assertEqual(W.clamp(W.ZERO, W.ZERO, W.ONE), W.ZERO)

    def test_clamp_at_upper_bound(self):
        """Kills wad18:94 '>→>='."""
        self.assertEqual(W.clamp(W.ONE, W.ZERO, W.ONE), W.ONE)

    def test_from_str_split_on_single_dot(self):
        """Kills wad18:39 '1→2/0' in split maxsplit."""
        self.assertEqual(W.from_str("36.000000000000000000"), 36 * SCALE)

    def test_from_str_negative_nonzero_integer_part(self):
        """Kills wad18:39 '1→2' in s[1:]: s[2:] of '-9.0' = '.0' gives 0,
        but correct parse of '-9.0' must give -9 * SCALE."""
        self.assertEqual(W.from_str("-9.000000000000000000"), -9 * SCALE)


# ══════════════════════════════════════════════════════════
# loan_application.py validation boundaries
# ══════════════════════════════════════════════════════════

class TestLoanApplicationBoundaries(unittest.TestCase):

    def test_zero_liquid_assets_is_valid(self):
        """Kills loan_application:52 '<→<=' and '0→1':
        assets=0 is a valid (penniless) borrower; must not raise."""
        b = Borrower("X", 500_000, "W2", 24, 720, 50_000, 0)
        self.assertEqual(b.liquid_assets_cents, 0)

    def test_zero_employment_months_is_valid(self):
        """Kills loan_application:56 '<→<=' and '0→1':
        emp=0 = brand new job; must not raise."""
        b = Borrower("X", 500_000, "W2", 0, 720, 50_000, 100_000)
        self.assertEqual(b.employment_months, 0)

    def test_minimum_credit_score_300_is_valid(self):
        """Kills loan_application:54 first '<=→<': score=300 must not raise."""
        b = Borrower("X", 500_000, "W2", 24, 300, 0, 100_000)
        self.assertEqual(b.credit_score, 300)

    def test_maximum_credit_score_850_is_valid(self):
        """Kills loan_application:54 second '<=→<': score=850 must not raise."""
        b = Borrower("X", 500_000, "W2", 24, 850, 0, 100_000)
        self.assertEqual(b.credit_score, 850)

    def test_zero_loan_amount_raises(self):
        """Kills loan_application:116 '<=→<': loan=0 must raise ValueError."""
        with self.assertRaises(ValueError):
            _app(loan=0)

    def test_zero_appraised_value_raises(self):
        """Kills loan_application:118 '<=→<': val=0 must raise ValueError."""
        with self.assertRaises(ValueError):
            _app(val=0)

    def test_zero_payment_raises(self):
        """Kills loan_application:120 '<=→<': pmt=0 must raise ValueError."""
        with self.assertRaises(ValueError):
            _app(pmt=0)

    def test_small_positive_loan_valid(self):
        """Kills loan_application:116 '0→1': loan=1 must NOT raise."""
        b = Borrower("X", 1_000_000, "W2", 24, 720, 0, 500_000)
        app = LoanApplication("X", "CONVENTIONAL", 1, 100, "SINGLE_FAMILY",
                              "PRIMARY", 1, [b], "2026-01-01")
        self.assertEqual(app.loan_amount_cents, 1)


# ══════════════════════════════════════════════════════════
# Tier exact-boundary tests
# (kills all >=→>, <=→< in tier classifiers)
# ══════════════════════════════════════════════════════════

class TestTierBoundaries(unittest.TestCase):
    """Each test verifies the tier at the EXACT threshold value."""

    # ── PRIME boundaries ──────────────────────────────────

    def test_score_720_qualifies_for_prime(self):
        """Kills underwriting_engine:188 '>=→>': score=720 must → PRIME."""
        app = _app(score=720, loan=16_000_000, val=20_000_000,
                   income=900_000, debt=50_000, pmt=170_000, emp=24)
        r = underwrite(app)
        self.assertEqual(r["tier"], "PRIME",
            f"score=720 should be PRIME, got {r['tier']}")

    def test_dti_exactly_36pct_is_prime(self):
        """Kills underwriting_engine:189 '<=→<': DTI=36% exactly → PRIME."""
        # (debt + pmt) / income = 0.36 exactly
        income = 500_000
        pmt    = 120_000
        debt   = int(0.36 * income) - pmt   # 60000
        app = _app(income=income, debt=debt, pmt=pmt,
                   score=720, loan=16_000_000, val=20_000_000, emp=24)
        dti = compute_back_dti(app)
        self.assertEqual(dti, PRIME_DTI_MAX,
            f"Expected DTI == PRIME_DTI_MAX, got {W.to_str(dti, 4)}")
        r = underwrite(app)
        self.assertEqual(r["tier"], "PRIME")

    def test_employment_24_months_qualifies_for_prime(self):
        """Kills underwriting_engine:191 '>=→>': emp=24 must → PRIME."""
        app = _app(score=720, loan=16_000_000, val=20_000_000,
                   income=900_000, debt=50_000, pmt=170_000, emp=24)
        r = underwrite(app)
        self.assertEqual(r["tier"], "PRIME")

    # ── STANDARD boundaries ────────────────────────────────

    def test_score_680_qualifies_for_standard(self):
        """Kills underwriting_engine:195 '>=→>': score=680 must → STANDARD."""
        app = _app(score=680, loan=19_000_000, val=20_000_000,
                   income=550_000, debt=80_000, pmt=130_000, emp=24)
        r = underwrite(app)
        self.assertEqual(r["tier"], "STANDARD",
            f"score=680 should be STANDARD, got {r['tier']}")

    def test_dti_exactly_43pct_is_standard(self):
        """Kills underwriting_engine:196 '<=→<': DTI=43% exactly → STANDARD."""
        income = 500_000
        pmt    = 130_000
        debt   = int(0.43 * income) - pmt   # 85000
        app = _app(income=income, debt=debt, pmt=pmt,
                   score=680, loan=19_000_000, val=20_000_000, emp=24)
        dti = compute_back_dti(app)
        self.assertEqual(dti, STANDARD_DTI_MAX)
        r = underwrite(app)
        self.assertEqual(r["tier"], "STANDARD")

    # ── FHA boundaries ────────────────────────────────────

    def test_score_620_qualifies_for_fha(self):
        """Kills underwriting_engine:206 '>=→>': score=620 → FHA_GRADE."""
        app = _app(score=620, loan_type="FHA",
                   loan=17_750_000, val=18_400_000,
                   income=450_000, debt=60_000, pmt=125_000, emp=12)
        r = underwrite(app)
        self.assertEqual(r["tier"], "FHA_GRADE",
            f"score=620 should be FHA_GRADE, got {r['tier']}")

    def test_dti_exactly_50pct_is_fha(self):
        """Kills underwriting_engine:207 '<=→<': DTI=50% exactly → FHA."""
        income = 500_000
        pmt    = 150_000
        debt   = int(0.50 * income) - pmt   # 100000
        app = _app(income=income, debt=debt, pmt=pmt,
                   score=620, loan_type="FHA",
                   loan=17_750_000, val=18_400_000, emp=12)
        dti = compute_back_dti(app)
        self.assertEqual(dti, FHA_DTI_MAX)
        r = underwrite(app)
        self.assertEqual(r["tier"], "FHA_GRADE")

    def test_ltv_exactly_965pct_is_fha(self):
        """Kills underwriting_engine:208 '<=→<': LTV=96.5% exactly → FHA."""
        # LTV = loan/val = 0.965 → loan = 965, val = 1000 (scaled)
        app = _app(score=620, loan_type="FHA",
                   loan=9_650_000, val=10_000_000,
                   income=450_000, debt=60_000, pmt=125_000, emp=12)
        ltv = compute_ltv(app)
        self.assertEqual(ltv, FHA_LTV_MAX)
        r = underwrite(app)
        self.assertEqual(r["tier"], "FHA_GRADE")

    def test_employment_12_months_qualifies_for_fha(self):
        """Kills underwriting_engine:209 '>=→>': emp=12 → FHA_GRADE."""
        app = _app(score=620, loan_type="FHA",
                   loan=17_750_000, val=18_400_000,
                   income=450_000, debt=60_000, pmt=125_000, emp=12)
        r = underwrite(app)
        self.assertEqual(r["tier"], "FHA_GRADE")

    # ── Reserve boundary ──────────────────────────────────

    def test_exactly_required_reserves_no_condition(self):
        """Kills underwriting_engine:175 '<→<=':
        reserves == required → NO reserve condition (exactly meeting threshold)."""
        # PRIME requires 2 months. Make assets = exactly 2 * pmt.
        pmt    = 170_000
        assets = 2 * pmt   # exactly 2 months
        app = _app(pmt=pmt, assets=assets,
                   loan=16_000_000, val=20_000_000,
                   income=900_000, debt=50_000, emp=24, score=720)
        res = compute_reserve_months(app)
        self.assertEqual(res, W.from_int(2))   # exactly 2 months
        r = underwrite(app)
        self.assertNotIn(COND_RESERVES, r["conditions"],
            "Exactly 2 months reserves should NOT trigger COND_RESERVES")

    def test_one_cent_below_required_reserves_triggers_condition(self):
        """Complementary to reserve boundary: slightly below triggers COND_RESERVES."""
        pmt    = 170_000
        assets = 2 * pmt - 1   # 1 cent below exactly 2 months
        app = _app(pmt=pmt, assets=assets,
                   loan=16_000_000, val=20_000_000,
                   income=900_000, debt=50_000, emp=24, score=720)
        r = underwrite(app)
        self.assertIn(COND_RESERVES, r["conditions"])


# ══════════════════════════════════════════════════════════
# REFER logic
# ══════════════════════════════════════════════════════════

class TestReferLogic(unittest.TestCase):

    def test_only_reserve_condition_gives_refer(self):
        """Kills underwriting_engine:257 '==→!=', '1→2', '1→0':
        When COND_RESERVES is the ONLY condition → decision must be REFER."""
        # Need: prime tier (score≥720, DTI≤36%, LTV≤80%, emp≥24)
        # but slightly below reserve requirement
        # No PMI (LTV≤80%), no employment condition (emp≥24), no self-employed
        pmt    = 170_000
        assets = 2 * pmt - 1   # just below 2-month reserve threshold
        app = _app(pmt=pmt, assets=assets,
                   loan=16_000_000, val=20_000_000,   # LTV=80%, no PMI
                   income=900_000, debt=50_000, emp=24, score=720)
        r = underwrite(app)
        self.assertEqual(r["tier"], "PRIME")
        self.assertEqual(r["conditions"], [COND_RESERVES],
                         f"Expected only [COND_RESERVES], got {r['conditions']}")
        self.assertEqual(r["decision"], REFER,
                         f"Only COND_RESERVES → REFER, got {r['decision']}")

    def test_reserve_plus_other_condition_gives_approve_with_conditions(self):
        """Complementary: COND_RESERVES + another condition → APPROVE_WITH_CONDITIONS."""
        pmt    = 170_000
        assets = 2 * pmt - 1
        # LTV=85% → adds PMI condition alongside COND_RESERVES
        app = _app(pmt=pmt, assets=assets,
                   loan=17_000_000, val=20_000_000,   # LTV=85%, adds PMI
                   income=900_000, debt=50_000, emp=24, score=720)
        r = underwrite(app)
        self.assertIn(COND_RESERVES, r["conditions"])
        self.assertIn(COND_PMI,      r["conditions"])
        self.assertEqual(r["decision"], APPROVE_WITH_CONDITIONS)


# ══════════════════════════════════════════════════════════
# Reserve threshold constants
# ══════════════════════════════════════════════════════════

class TestLoanValidationBoundary(unittest.TestCase):

    def test_appraised_value_of_1_cent_is_valid(self):
        """Kills loan_application:118 '0→1': val=1 cent must NOT raise."""
        b = Borrower("X", 1_000_000, "W2", 24, 720, 0, 500_000)
        app = LoanApplication("X", "CONVENTIONAL", 1, 1,
                              "SINGLE_FAMILY", "PRIMARY", 1, [b], "2026-01-01")
        self.assertEqual(app.appraised_value_cents, 1)


class TestDeficiencyBoundaries(unittest.TestCase):

    def test_dti_exactly_50pct_not_in_deficiencies(self):
        """Kills underwriting_engine:267 '>→>=':
        DTI = 50% exactly (FHA max) must NOT appear in deficiencies."""
        income = 500_000
        pmt    = 150_000
        debt   = int(0.50 * income) - pmt
        app = _app(income=income, debt=debt, pmt=pmt,
                   score=620, loan_type="FHA",
                   loan=17_750_000, val=18_400_000, emp=12)
        r = underwrite(app)
        self.assertNotIn("DTI_EXCEEDS_MAXIMUM", r["deficiencies"],
                         "DTI exactly at max should NOT be a deficiency")

    def test_ltv_exactly_965_not_in_deficiencies(self):
        """Kills underwriting_engine:269 '>→>=':
        LTV = 96.5% exactly must NOT appear in deficiencies."""
        app = _app(score=620, loan_type="FHA",
                   loan=9_650_000, val=10_000_000,
                   income=450_000, debt=60_000, pmt=125_000, emp=12)
        r = underwrite(app)
        self.assertNotIn("LTV_EXCEEDS_MAXIMUM", r["deficiencies"],
                         "LTV exactly at max should NOT be a deficiency")


class TestReserveConstants(unittest.TestCase):

    def test_prime_reserves_exactly_2_months(self):
        """Kills underwriting_engine:95 '2→3', '2→1':
        PRIME_RESERVES_MONTHS must equal 2, not 3 or 1."""
        self.assertEqual(PRIME_RESERVES_MONTHS, 2)

    def test_standard_reserves_exactly_2_months(self):
        """Kills underwriting_engine:96 '2→3', '2→1'."""
        self.assertEqual(STANDARD_RESERVES_MONTHS, 2)

    def test_fha_reserves_exactly_1_month(self):
        """Kills underwriting_engine:97 '1→2', '1→0'."""
        self.assertEqual(FHA_RESERVES_MONTHS, 1)

    def test_investment_reserves_extra_exactly_4(self):
        """Kills underwriting_engine:98 '4→5', '4→3'."""
        from underwriting_engine import INVESTMENT_RESERVES_EXTRA
        self.assertEqual(INVESTMENT_RESERVES_EXTRA, 4)


# ══════════════════════════════════════════════════════════
# Deficiency classification (kills L265-271)
# ══════════════════════════════════════════════════════════

class TestDeficiencies(unittest.TestCase):

    def test_low_score_in_deficiencies(self):
        """Kills underwriting_engine:265 '<→<=':
        score < 620 → SCORE_BELOW_MINIMUM in deficiencies."""
        app = _app(score=580)   # below FHA_SCORE_MIN
        r   = underwrite(app)
        self.assertEqual(r["tier"], "DECLINE")
        self.assertTrue(any("SCORE_BELOW_MINIMUM" in d for d in r["deficiencies"]))

    def test_score_at_fha_min_not_in_deficiencies(self):
        """Kills underwriting_engine:265 '<→<=':
        score exactly 620 must NOT appear in deficiencies."""
        app = _app(score=620, loan_type="FHA",
                   loan=17_750_000, val=18_400_000,
                   income=450_000, debt=60_000, pmt=125_000, emp=12)
        r = underwrite(app)
        self.assertFalse(any("SCORE_BELOW_MINIMUM" in d for d in r["deficiencies"]),
                         f"score=620 should not be in deficiencies: {r['deficiencies']}")

    def test_high_dti_in_deficiencies(self):
        """Kills underwriting_engine:267 '>→>=':
        DTI > 50% → DTI_EXCEEDS_MAXIMUM in deficiencies."""
        app = _app(score=580, income=500_000, debt=100_000, pmt=250_000)
        r   = underwrite(app)
        self.assertIn("DTI_EXCEEDS_MAXIMUM", r["deficiencies"])

    def test_high_ltv_in_deficiencies(self):
        """Kills underwriting_engine:269 '>→>=':
        LTV > 96.5% → LTV_EXCEEDS_MAXIMUM in deficiencies."""
        app = _app(loan=35_000_000, val=36_000_000, score=720,
                   income=500_000, debt=100_000, pmt=250_000)
        r   = underwrite(app)
        self.assertIn("LTV_EXCEEDS_MAXIMUM", r["deficiencies"])

    def test_short_employment_in_deficiencies(self):
        """Kills underwriting_engine:271 '<→<=':
        emp < 12 → INSUFFICIENT_EMPLOYMENT in deficiencies."""
        app = _app(score=580, emp=6)
        r   = underwrite(app)
        self.assertIn("INSUFFICIENT_EMPLOYMENT_HISTORY", r["deficiencies"])

    def test_employment_12_not_in_deficiencies(self):
        """Kills underwriting_engine:271 '<→<=':
        emp = 12 must NOT appear in deficiencies."""
        app = _app(score=620, loan_type="FHA",
                   loan=17_750_000, val=18_400_000,
                   income=450_000, debt=60_000, pmt=125_000, emp=12)
        r = underwrite(app)
        self.assertNotIn("INSUFFICIENT_EMPLOYMENT_HISTORY", r["deficiencies"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
