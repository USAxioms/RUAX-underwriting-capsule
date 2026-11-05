"""
Loan Application data model.

All monetary values are stored as integer cents.
All ratios are computed in WAD-18 by the underwriting engine — never here.
All string-coded fields use closed enumerations to prevent garbage input.

Loan types:
  CONVENTIONAL  — conforming loan, sold to GSEs (Fannie/Freddie)
  FHA           — government-insured (Federal Housing Administration)
  VA            — Veterans Affairs guaranteed
  JUMBO         — non-conforming (above GSE limits)

Employment types:
  W2            — salaried employee, most stable
  SELF_EMPLOYED — 1099 / business owner, requires 2yr avg income
  RETIRED       — fixed income (Social Security, pension)
  CONTRACT      — hourly/contract, requires 2yr continuity

Property types:
  SINGLE_FAMILY — 1-unit residential
  CONDO         — condominium
  MULTI_FAMILY  — 2-4 unit residential
  INVESTMENT    — non-owner-occupied
"""

import json

LOAN_TYPES        = frozenset(["CONVENTIONAL", "FHA", "VA", "JUMBO"])
EMPLOYMENT_TYPES  = frozenset(["W2", "SELF_EMPLOYED", "RETIRED", "CONTRACT"])
PROPERTY_TYPES    = frozenset(["SINGLE_FAMILY", "CONDO", "MULTI_FAMILY", "INVESTMENT"])
OCCUPANCY_TYPES   = frozenset(["PRIMARY", "SECONDARY", "INVESTMENT"])


class Borrower:
    """One borrower on the loan (primary or co-borrower)."""

    def __init__(self,
                 borrower_id: str,
                 gross_monthly_income_cents: int,
                 employment_type: str,
                 employment_months: int,
                 credit_score: int,
                 monthly_debt_payments_cents: int,
                 liquid_assets_cents: int):
        if employment_type not in EMPLOYMENT_TYPES:
            raise ValueError("unknown employment type: %r" % employment_type)
        if gross_monthly_income_cents < 0:
            raise ValueError("income cannot be negative")
        if monthly_debt_payments_cents < 0:
            raise ValueError("debt payments cannot be negative")
        if liquid_assets_cents < 0:
            raise ValueError("assets cannot be negative")
        if not (300 <= credit_score <= 850):
            raise ValueError("credit score out of range [300,850]: %d" % credit_score)
        if employment_months < 0:
            raise ValueError("employment months cannot be negative")

        self.borrower_id                    = str(borrower_id)
        self.gross_monthly_income_cents     = int(gross_monthly_income_cents)
        self.employment_type                = employment_type
        self.employment_months              = int(employment_months)
        self.credit_score                   = int(credit_score)
        self.monthly_debt_payments_cents    = int(monthly_debt_payments_cents)
        self.liquid_assets_cents            = int(liquid_assets_cents)

    def to_dict(self) -> dict:
        return {
            "borrower_id":                  self.borrower_id,
            "gross_monthly_income_cents":   self.gross_monthly_income_cents,
            "employment_type":              self.employment_type,
            "employment_months":            self.employment_months,
            "credit_score":                 self.credit_score,
            "monthly_debt_payments_cents":  self.monthly_debt_payments_cents,
            "liquid_assets_cents":          self.liquid_assets_cents,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Borrower":
        return cls(
            borrower_id                 = d["borrower_id"],
            gross_monthly_income_cents  = d["gross_monthly_income_cents"],
            employment_type             = d["employment_type"],
            employment_months           = d["employment_months"],
            credit_score                = d["credit_score"],
            monthly_debt_payments_cents = d["monthly_debt_payments_cents"],
            liquid_assets_cents         = d["liquid_assets_cents"],
        )


class LoanApplication:
    """
    Complete loan application for underwriting.

    The proposed_monthly_payment_cents is the TOTAL housing payment
    (PITI: principal, interest, taxes, insurance, HOA if applicable).
    It must be provided by the origination system from the loan terms.
    """

    def __init__(self,
                 application_id: str,
                 loan_type: str,
                 loan_amount_cents: int,
                 appraised_value_cents: int,
                 property_type: str,
                 occupancy_type: str,
                 proposed_monthly_payment_cents: int,
                 borrowers: list,
                 application_date: str):
        if loan_type not in LOAN_TYPES:
            raise ValueError("unknown loan type: %r" % loan_type)
        if property_type not in PROPERTY_TYPES:
            raise ValueError("unknown property type: %r" % property_type)
        if occupancy_type not in OCCUPANCY_TYPES:
            raise ValueError("unknown occupancy type: %r" % occupancy_type)
        if loan_amount_cents <= 0:
            raise ValueError("loan amount must be positive")
        if appraised_value_cents <= 0:
            raise ValueError("appraised value must be positive")
        if proposed_monthly_payment_cents <= 0:
            raise ValueError("proposed payment must be positive")
        if not borrowers:
            raise ValueError("at least one borrower required")

        self.application_id                  = str(application_id)
        self.loan_type                       = loan_type
        self.loan_amount_cents               = int(loan_amount_cents)
        self.appraised_value_cents           = int(appraised_value_cents)
        self.property_type                   = property_type
        self.occupancy_type                  = occupancy_type
        self.proposed_monthly_payment_cents  = int(proposed_monthly_payment_cents)
        self.borrowers                       = list(borrowers)
        self.application_date                = str(application_date)

    # ── Combined borrower aggregates ─────────────────────────────────────

    def combined_gross_monthly_income_cents(self) -> int:
        return sum(b.gross_monthly_income_cents for b in self.borrowers)

    def combined_monthly_debt_payments_cents(self) -> int:
        return sum(b.monthly_debt_payments_cents for b in self.borrowers)

    def combined_liquid_assets_cents(self) -> int:
        return sum(b.liquid_assets_cents for b in self.borrowers)

    def representative_credit_score(self) -> int:
        """Middle score of primary borrower; for co-borrowers use the lower
        of each borrower's score, then take the minimum across borrowers.
        (Simplified: use minimum credit score across all borrowers.)"""
        return min(b.credit_score for b in self.borrowers)

    def primary_employment_months(self) -> int:
        """Employment tenure of primary borrower (first in list)."""
        return self.borrowers[0].employment_months

    def down_payment_cents(self) -> int:
        return self.appraised_value_cents - self.loan_amount_cents

    def to_dict(self) -> dict:
        return {
            "application_id":                 self.application_id,
            "loan_type":                      self.loan_type,
            "loan_amount_cents":              self.loan_amount_cents,
            "appraised_value_cents":          self.appraised_value_cents,
            "property_type":                  self.property_type,
            "occupancy_type":                 self.occupancy_type,
            "proposed_monthly_payment_cents": self.proposed_monthly_payment_cents,
            "application_date":               self.application_date,
            "borrowers":                      [b.to_dict() for b in self.borrowers],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LoanApplication":
        borrowers = [Borrower.from_dict(b) for b in d["borrowers"]]
        return cls(
            application_id                  = d["application_id"],
            loan_type                       = d["loan_type"],
            loan_amount_cents               = d["loan_amount_cents"],
            appraised_value_cents           = d["appraised_value_cents"],
            property_type                   = d["property_type"],
            occupancy_type                  = d["occupancy_type"],
            proposed_monthly_payment_cents  = d["proposed_monthly_payment_cents"],
            borrowers                       = borrowers,
            application_date                = d["application_date"],
        )

    @classmethod
    def from_json(cls, path: str) -> "LoanApplication":
        with open(path) as fh:
            return cls.from_dict(json.load(fh))
