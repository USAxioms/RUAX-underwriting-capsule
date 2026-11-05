"""
Underwriting Engine — WAD-18 exact arithmetic throughout.

Decision taxonomy (ordered best to worst):
  APPROVE                 All criteria met; loan may close as submitted.
  APPROVE_WITH_CONDITIONS Criteria met but documentation gaps; items
                          listed in conditions must be satisfied.
  REFER                   Borderline; requires manual underwriter review.
  DECLINE                 Criteria not met; loan cannot be approved.

Three tiers encode the GSE / FHA risk spectrum:

  PRIME (Tier 1 — Conventional)
    Credit score ≥ 720
    Back-end DTI  ≤ 36%
    LTV           ≤ 80%
    Employment    ≥ 24 months
    Reserves      ≥ 2 months PITI

  STANDARD (Tier 2 — Conforming)
    Credit score ≥ 680
    Back-end DTI  ≤ 43%
    LTV           ≤ 95%    (PMI required if LTV > 80%)
    Employment    ≥ 24 months
    Reserves      ≥ 2 months PITI

  FHA_GRADE (Tier 3 — FHA guidelines)
    Credit score ≥ 620
    Back-end DTI  ≤ 50%
    LTV           ≤ 96.5%
    Employment    ≥ 12 months
    Reserves      ≥ 1 month PITI

  DECLINE  — Below all tiers.

Ratios (DTI, LTV, reserves) are computed in WAD-18 exact arithmetic.
All threshold comparisons are exact WAD-18 integer comparisons.
No float is constructed anywhere in the engine.

Conditions attached:
  COND_PMI          LTV > 80% (private mortgage insurance required)
  COND_EMPLOYMENT   Employment < 24 months (documentation required)
  COND_RESERVES     Liquid assets < target reserve months
  COND_SELF_EMPLOYED Two years of tax returns required
  COND_INVESTMENT   Investment property — higher reserve requirement
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wad18 as W
from loan_application import LoanApplication

# ── Decision codes ────────────────────────────────────────────────────────

APPROVE                  = "APPROVE"
APPROVE_WITH_CONDITIONS  = "APPROVE_WITH_CONDITIONS"
REFER                    = "REFER"
DECLINE                  = "DECLINE"
DECISIONS = frozenset([APPROVE, APPROVE_WITH_CONDITIONS, REFER, DECLINE])

# Condition codes
COND_PMI          = "COND_PMI_REQUIRED"
COND_EMPLOYMENT   = "COND_EMPLOYMENT_DOCS"
COND_RESERVES     = "COND_RESERVE_SHORTFALL"
COND_SELF_EMPLOYED= "COND_SELF_EMPLOYED_TAX_RETURNS"
COND_INVESTMENT   = "COND_INVESTMENT_RESERVES"

# ── Tier thresholds (WAD-18) ─────────────────────────────────────────────

# Credit scores (plain integers — credit score is an integer field)
PRIME_SCORE_MIN    = 720
STANDARD_SCORE_MIN = 680
FHA_SCORE_MIN      = 620

# DTI thresholds
PRIME_DTI_MAX    = W.from_str("0.360000000000000000")   # 36%
STANDARD_DTI_MAX = W.from_str("0.430000000000000000")   # 43%
FHA_DTI_MAX      = W.from_str("0.500000000000000000")   # 50%

# LTV thresholds
PRIME_LTV_MAX    = W.from_str("0.800000000000000000")   # 80%
STANDARD_LTV_MAX = W.from_str("0.950000000000000000")   # 95%
FHA_LTV_MAX      = W.from_str("0.965000000000000000")   # 96.5%

# PMI trigger
PMI_LTV_THRESHOLD = W.from_str("0.800000000000000000")  # 80%

# Employment (months — plain integers)
PRIME_EMPLOYMENT_MIN    = 24
STANDARD_EMPLOYMENT_MIN = 24
FHA_EMPLOYMENT_MIN      = 12

# Reserve months (PITI multiples — plain integers)
PRIME_RESERVES_MONTHS    = 2
STANDARD_RESERVES_MONTHS = 2
FHA_RESERVES_MONTHS      = 1
INVESTMENT_RESERVES_EXTRA = 4  # investment properties need 6 months total

# ── Core ratio computations (WAD-18) ─────────────────────────────────────

def compute_ltv(app: LoanApplication) -> int:
    """LTV = loan_amount / appraised_value.  [WAD-18]"""
    return W.div(
        W.from_cents(app.loan_amount_cents),
        W.from_cents(app.appraised_value_cents),
    )


def compute_back_dti(app: LoanApplication) -> int:
    """Back-end DTI = (existing_debt + proposed_payment) / gross_income.  [WAD-18]

    Back-end DTI includes ALL monthly debt obligations plus the new housing
    payment (PITI).  This is the binding ratio for all three tiers.
    """
    income = app.combined_gross_monthly_income_cents()
    if income == 0:
        return W.from_int(999)   # sentinel: infinite DTI → always decline
    total_debt = (app.combined_monthly_debt_payments_cents()
                  + app.proposed_monthly_payment_cents)
    return W.div(W.from_cents(total_debt), W.from_cents(income))


def compute_front_dti(app: LoanApplication) -> int:
    """Front-end DTI = proposed_payment / gross_income.  [WAD-18]

    Housing-expense-only ratio; used for additional conditions but not
    the primary decision gate (back-end DTI governs).
    """
    income = app.combined_gross_monthly_income_cents()
    if income == 0:
        return W.from_int(999)
    return W.div(
        W.from_cents(app.proposed_monthly_payment_cents),
        W.from_cents(income),
    )


def compute_reserve_months(app: LoanApplication) -> int:
    """Reserve months = liquid_assets / proposed_monthly_payment.  [WAD-18]

    Returns the number of months of PITI the borrower can cover from
    liquid assets alone.  Returned as a WAD-18 ratio (not a plain int).
    """
    if app.proposed_monthly_payment_cents == 0:
        return W.from_int(999)   # no payment → infinite reserves
    return W.div(
        W.from_cents(app.combined_liquid_assets_cents()),
        W.from_cents(app.proposed_monthly_payment_cents),
    )


# ── Condition assembly ────────────────────────────────────────────────────

def _check_conditions(app: LoanApplication, ltv: int,
                      reserve_months_wad: int,
                      required_reserve_months: int) -> list:
    """Return list of condition codes that apply to this application."""
    conditions = []

    # PMI required if LTV > 80%
    if ltv > PMI_LTV_THRESHOLD:
        conditions.append(COND_PMI)

    # Employment documentation for short tenure
    if app.primary_employment_months() < STANDARD_EMPLOYMENT_MIN:
        conditions.append(COND_EMPLOYMENT)

    # Self-employed: 2 years tax returns required
    if any(b.employment_type == "SELF_EMPLOYED" for b in app.borrowers):
        conditions.append(COND_SELF_EMPLOYED)

    # Reserve shortfall
    required_wad = W.from_int(required_reserve_months)
    if reserve_months_wad < required_wad:
        conditions.append(COND_RESERVES)

    # Investment property: extra reserves
    if app.occupancy_type == "INVESTMENT":
        conditions.append(COND_INVESTMENT)

    return conditions


# ── Tier classifiers ──────────────────────────────────────────────────────

def _in_prime(score: int, dti: int, ltv: int, emp_months: int) -> bool:
    return (score >= PRIME_SCORE_MIN
            and dti <= PRIME_DTI_MAX
            and ltv <= PRIME_LTV_MAX
            and emp_months >= PRIME_EMPLOYMENT_MIN)


def _in_standard(score: int, dti: int, ltv: int, emp_months: int) -> bool:
    return (score >= STANDARD_SCORE_MIN
            and dti <= STANDARD_DTI_MAX
            and ltv <= STANDARD_LTV_MAX
            and emp_months >= STANDARD_EMPLOYMENT_MIN)


def _in_fha(score: int, dti: int, ltv: int, emp_months: int,
            loan_type: str) -> bool:
    # FHA tier applies only to FHA or CONVENTIONAL loans
    if loan_type not in ("FHA", "CONVENTIONAL"):
        return False
    return (score >= FHA_SCORE_MIN
            and dti <= FHA_DTI_MAX
            and ltv <= FHA_LTV_MAX
            and emp_months >= FHA_EMPLOYMENT_MIN)


# ── Main decision function ────────────────────────────────────────────────

def underwrite(app: LoanApplication) -> dict:
    """
    Underwrite a loan application.

    Returns a complete decision dict with every intermediate WAD-18 value,
    the tier classification, attached conditions, and the final decision code.
    The result is fully reproducible from the application alone.
    """
    # ── Compute ratios (WAD-18) ───────────────────────────────────────────
    ltv              = compute_ltv(app)
    dti              = compute_back_dti(app)
    front_dti        = compute_front_dti(app)
    reserve_months   = compute_reserve_months(app)
    score            = app.representative_credit_score()
    emp_months       = app.primary_employment_months()
    loan_type        = app.loan_type

    # ── Tier classification ───────────────────────────────────────────────
    if _in_prime(score, dti, ltv, emp_months):
        tier = "PRIME"
        required_reserves = PRIME_RESERVES_MONTHS
    elif _in_standard(score, dti, ltv, emp_months):
        tier = "STANDARD"
        required_reserves = STANDARD_RESERVES_MONTHS
    elif _in_fha(score, dti, ltv, emp_months, loan_type):
        tier = "FHA_GRADE"
        required_reserves = FHA_RESERVES_MONTHS
    else:
        tier = "DECLINE"
        required_reserves = 0

    # ── Conditions ────────────────────────────────────────────────────────
    if tier != "DECLINE":
        conditions = _check_conditions(app, ltv, reserve_months,
                                       required_reserves)
    else:
        conditions = []

    # ── Decision ──────────────────────────────────────────────────────────
    if tier == "DECLINE":
        decision = DECLINE
    elif not conditions:
        decision = APPROVE
    elif COND_RESERVES in conditions and len(conditions) == 1:
        # Reserve shortfall alone → REFER (may be resolved by gift funds or LOE)
        decision = REFER
    else:
        decision = APPROVE_WITH_CONDITIONS

    # ── Deficiency detail ─────────────────────────────────────────────────
    deficiencies = []
    if score < FHA_SCORE_MIN:
        deficiencies.append("SCORE_BELOW_MINIMUM_%d" % FHA_SCORE_MIN)
    if dti > FHA_DTI_MAX:
        deficiencies.append("DTI_EXCEEDS_MAXIMUM")
    if ltv > FHA_LTV_MAX:
        deficiencies.append("LTV_EXCEEDS_MAXIMUM")
    if emp_months < FHA_EMPLOYMENT_MIN:
        deficiencies.append("INSUFFICIENT_EMPLOYMENT_HISTORY")

    assert decision in DECISIONS, "engine produced invalid decision: %r" % decision

    return {
        "application_id":         app.application_id,
        "application_date":       app.application_date,
        "loan_type":              loan_type,
        # WAD-18 ratios
        "ltv_wad18":              ltv,
        "dti_back_wad18":         dti,
        "dti_front_wad18":        front_dti,
        "reserve_months_wad18":   reserve_months,
        # Readable strings
        "ltv_pct":                W.to_str(W.mul(ltv, W.from_int(100)), 2),
        "dti_back_pct":           W.to_str(W.mul(dti, W.from_int(100)), 2),
        "dti_front_pct":          W.to_str(W.mul(front_dti, W.from_int(100)), 2),
        "reserve_months_str":     W.to_str(reserve_months, 2),
        # Credit profile
        "credit_score":           score,
        "employment_months":      emp_months,
        "combined_income_cents":  app.combined_gross_monthly_income_cents(),
        "combined_debt_cents":    app.combined_monthly_debt_payments_cents(),
        "loan_amount_cents":      app.loan_amount_cents,
        "appraised_value_cents":  app.appraised_value_cents,
        "down_payment_cents":     app.down_payment_cents(),
        # Decision
        "tier":                   tier,
        "decision":               decision,
        "conditions":             conditions,
        "deficiencies":           deficiencies,
        "pmi_required":           ltv > PMI_LTV_THRESHOLD,
        # Thresholds applied
        "thresholds": {
            "score_min":       PRIME_SCORE_MIN if tier == "PRIME" else
                               STANDARD_SCORE_MIN if tier == "STANDARD" else
                               FHA_SCORE_MIN,
            "dti_max_str":     W.to_str(PRIME_DTI_MAX if tier == "PRIME" else
                               STANDARD_DTI_MAX if tier == "STANDARD" else
                               FHA_DTI_MAX, 4),
            "ltv_max_str":     W.to_str(PRIME_LTV_MAX if tier == "PRIME" else
                               STANDARD_LTV_MAX if tier == "STANDARD" else
                               FHA_LTV_MAX, 4),
        },
        "arithmetic":             "WAD-18 exact integer throughout",
    }
