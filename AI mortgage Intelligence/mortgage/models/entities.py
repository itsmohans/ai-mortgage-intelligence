"""
mortgage/models/entities.py
============================
Core data model for the AI Mortgage Intelligence Agent.

Design philosophy
-----------------
* All financial values use `Decimal`, never `float`.
  Float arithmetic (e.g. 0.1 + 0.2 == 0.30000000000000004) is unacceptable
  for money. Decimal gives exact base-10 arithmetic.

* The model is EVENT-DRIVEN:
    - You store the events that change the schedule:
        RateChangeEvent  →  a new interest rate takes effect on a date
        PrepaymentEvent  →  a lump-sum payment on a date
    - The engine reconstructs every monthly row from these events.
    - This means far less data entry than a row-per-month approach,
      and scenario modelling becomes: "swap one event, re-run."

* MonthlyPayment is a COMPUTED value — it is never stored in the database.
  The engine generates it on demand from the stored events.
  Only the inputs (mortgage, terms, events) are persisted.

Entity hierarchy
----------------
Mortgage
  └── MortgageTerm  (one per renewal period)
        ├── RateChangeEvent  (variable rate terms only)
        └── PrepaymentEvent  (any lump sum or recurring prepayment)

Computed (engine output, not stored)
-------------------------------------
MonthlyPayment
AmortizationSchedule
LifetimeSummary
TermSummary
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Stored entities  (persisted to SQLite)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Mortgage:
    """
    Root entity.  One record per mortgage.

    original_principal   : The amount borrowed on start_date.
    start_date           : The disbursement date (day 0 — no payment made).
    amortization_years   : The total repayment horizon (e.g. 30).
    prepayment_limit_pct : Lender's annual prepayment privilege as a fraction
                           of original_principal (e.g. Decimal("0.20") = 20 %).
    lender               : Lender name — informational only.
    payment_day          : Day of month on which payments are made (e.g. 21).
    """
    original_principal:   Decimal
    start_date:           date
    amortization_years:   int
    prepayment_limit_pct: Decimal   = Decimal("0.20")
    lender:               str       = ""
    payment_day:          int       = 1       # day of month (1–28)
    id:                   Optional[int] = None

    # Populated by the repository after loading from DB
    terms: list[MortgageTerm] = field(default_factory=list)

    @property
    def amortization_months(self) -> int:
        return self.amortization_years * 12

    @property
    def annual_prepayment_limit(self) -> Decimal:
        return (self.original_principal * self.prepayment_limit_pct).quantize(
            Decimal("0.01")
        )


@dataclass
class MortgageTerm:
    """
    One renewal term.  Created when the homeowner (re)negotiates with the lender.

    term_number    : 1-based counter (Term 1 = first term after disbursement).
    start_date     : Date this term's interest rate takes effect.
                     Also the date of the first payment in this term.
    end_date       : Last payment date of this term.
    term_years     : Length of the term in years (1–5 for Canadian mortgages).
    rate_type      : "variable" or "fixed".
                     Variable → rate can change via RateChangeEvent.
                     Fixed    → initial_annual_rate holds for the entire term.
    initial_annual_rate : Starting rate for this term as a decimal fraction
                          (e.g. Decimal("0.0389") for 3.89 %).
    monthly_payment     : Regular monthly payment amount negotiated at term start.
                          For fixed terms this is computed by the renewal engine.
                          For variable terms it is typically held fixed even as
                          rates change (standard Canadian variable-rate practice).
    mortgage_id    : FK to Mortgage.id (set by repository).
    """
    term_number:         int
    start_date:          date
    end_date:            date
    term_years:          int
    rate_type:           str          # "variable" | "fixed"
    initial_annual_rate: Decimal
    monthly_payment:     Decimal
    mortgage_id:         Optional[int] = None
    id:                  Optional[int] = None

    # Populated by the repository after loading from DB
    rate_changes:  list[RateChangeEvent]  = field(default_factory=list)
    prepayments:   list[PrepaymentEvent]  = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.start_date.year}–{self.end_date.year}"


@dataclass
class RateChangeEvent:
    """
    A change in the interest rate within a MortgageTerm.

    Only meaningful for variable-rate terms.
    The engine applies this rate from `effective_date` onwards until
    the next RateChangeEvent (or the term end date).

    Example: Bank of Canada raised rates on 2022-03-02.
    You enter:  effective_date=date(2022, 3, 21),
                new_annual_rate=Decimal("0.0164")
    (Using the next payment date as the effective date is a common convention.)
    """
    effective_date:  date
    new_annual_rate: Decimal     # e.g. Decimal("0.0164") for 1.64 %
    term_id:         Optional[int] = None
    id:              Optional[int] = None


@dataclass
class PrepaymentEvent:
    """
    A lump-sum payment applied in addition to the regular monthly payment.
    Reduces the outstanding principal immediately in the month it is applied.

    recurrence controls how often it repeats:
      "once"    → single payment on payment_date
      "monthly" → applied every month from payment_date to end_date (or term end)
      "annual"  → applied every year in the same month as payment_date

    amount is the prepayment per occurrence (not the total).

    end_date (optional): stop recurring prepayments after this date.
    """
    payment_date: date
    amount:       Decimal
    recurrence:   str            = "once"   # "once" | "monthly" | "annual"
    end_date:     Optional[date] = None     # None = until term ends
    note:         str            = ""       # user-visible label
    term_id:      Optional[int]  = None
    id:           Optional[int]  = None


# ─────────────────────────────────────────────────────────────────────────────
# Computed entities  (engine output — NOT stored)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MonthlyPayment:
    """
    One row of the amortization schedule.
    Generated by the engine — never written to the database.

    period_number   : 1-based month number from the mortgage start date.
    term_number     : Which term this payment belongs to.
    payment_date    : Calendar date this payment is made.
    balance_opening : Outstanding balance at the START of this period.
    annual_rate     : The interest rate in effect for this period.
    days_in_period  : Actual calendar days since the previous payment.
                      This is what makes the Actual/365 convention work —
                      February has fewer days than March, so interest differs.
    interest_amount : Interest charged this period.
                      = balance_opening × (annual_rate / 365) × days_in_period
    regular_payment : The fixed monthly payment.
    prepayment      : Any extra lump-sum applied this month.
    principal_repaid: regular_payment + prepayment - interest_amount
                      (Can be negative in early months of a low-rate term where
                       the payment barely covers interest — this is real and valid.)
    balance_closing : balance_opening - principal_repaid
                      Clamped to Decimal("0.00") at payoff.
    is_historical   : True if payment_date < today.
                      Historical rows reflect real past payments.
                      Future rows are projections.
    """
    period_number:    int
    term_number:      int
    payment_date:     date
    balance_opening:  Decimal
    annual_rate:      Decimal
    days_in_period:   int
    interest_amount:  Decimal
    regular_payment:  Decimal
    prepayment:       Decimal
    principal_repaid: Decimal
    balance_closing:  Decimal
    is_historical:    bool


@dataclass
class TermSummary:
    """Aggregated statistics for one mortgage term."""
    term_number:        int
    label:              str        # "2021–2026"
    opening_balance:    Decimal
    closing_balance:    Decimal
    total_repayments:   Decimal    # sum of regular_payment + prepayment
    principal_repaid:   Decimal
    interest_paid:      Decimal
    total_prepayments:  Decimal
    avg_weighted_rate:  Decimal    # interest-amount-weighted average rate
    payment_count:      int


@dataclass
class LifetimeSummary:
    """Aggregated statistics across the entire mortgage life."""
    total_repayments:   Decimal
    total_principal:    Decimal    # = original_principal (sanity check)
    total_interest:     Decimal
    net_interest_pct:   Decimal    # total_interest / original_principal
    total_prepayments:  Decimal
    payoff_date:        date
    payoff_month:       int        # period_number of the final payment
    weighted_avg_rate:  Decimal


@dataclass
class AmortizationSchedule:
    """
    The complete output of the amortization engine for a given mortgage.
    Holds every MonthlyPayment plus the pre-computed summaries.
    """
    mortgage:         Mortgage
    payments:         list[MonthlyPayment]
    term_summaries:   list[TermSummary]
    lifetime_summary: LifetimeSummary
