"""
mortgage/engine/analytics.py
==============================
Higher-level analytics built on top of the amortization schedule.

These functions answer the specific questions a homeowner asks:
  - What is the impact of a lump-sum prepayment?
  - What if I increase my monthly payment?
  - What is my progress this year?
  - What is my outstanding balance at month N?

All functions are PURE — they take an AmortizationSchedule (or Mortgage)
and return computed results. They never write to storage.
They are the analytical layer between the engine and the UI/AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from mortgage.models.entities import (
    AmortizationSchedule,
    LifetimeSummary,
    MonthlyPayment,
    Mortgage,
    MortgageTerm,
    PrepaymentEvent,
)
from mortgage.engine.amortization import generate_schedule

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# Balance queries
# ─────────────────────────────────────────────────────────────────────────────

def balance_at_period(schedule: AmortizationSchedule, period_number: int) -> Decimal:
    """Return the closing balance after payment number `period_number`."""
    for p in schedule.payments:
        if p.period_number == period_number:
            return p.balance_closing
    raise ValueError(f"Period {period_number} not found in schedule.")


def balance_at_date(schedule: AmortizationSchedule, as_of: date) -> Decimal:
    """
    Return the closing balance for the payment closest to `as_of`.
    Looks for the payment on or immediately before that date.
    """
    result = None
    for p in schedule.payments:
        if p.payment_date <= as_of:
            result = p
        else:
            break
    if result is None:
        return schedule.mortgage.original_principal
    return result.balance_closing


# ─────────────────────────────────────────────────────────────────────────────
# YTD (year-to-date) summary
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class YTDSummary:
    year:             int
    total_repayments: Decimal
    principal_repaid: Decimal
    interest_paid:    Decimal
    total_prepayments:Decimal
    payment_count:    int


def ytd_summary(schedule: AmortizationSchedule, year: int | None = None) -> YTDSummary:
    """
    Summarise payments for a given calendar year.
    Defaults to the current year if `year` is not specified.
    """
    target_year = year or date.today().year
    payments = [p for p in schedule.payments if p.payment_date.year == target_year]

    return YTDSummary(
        year              = target_year,
        total_repayments  = _round(sum((p.regular_payment + p.prepayment for p in payments), _ZERO)),
        principal_repaid  = _round(sum((p.principal_repaid  for p in payments), _ZERO)),
        interest_paid     = _round(sum((p.interest_amount   for p in payments), _ZERO)),
        total_prepayments = _round(sum((p.prepayment        for p in payments), _ZERO)),
        payment_count     = len(payments),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prepayment impact analysis
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PrepaymentImpact:
    """The difference a prepayment makes."""
    prepayment_amount:   Decimal
    applied_on:          date

    # Baseline (without prepayment)
    baseline_payoff_date:    date
    baseline_total_interest: Decimal
    baseline_payoff_month:   int

    # With prepayment
    new_payoff_date:         date
    new_total_interest:      Decimal
    new_payoff_month:        int

    # Savings
    interest_saved:          Decimal
    months_saved:            int
    effective_annual_return: Decimal   # interest_saved / prepayment (annualised)


def prepayment_impact(
    mortgage: Mortgage,
    lump_sum: Decimal,
    applied_on: date,
) -> PrepaymentImpact:
    """
    Calculate the financial impact of adding a one-time lump-sum prepayment.

    Generates two schedules:
      1. The baseline schedule (mortgage as configured).
      2. A modified schedule with the additional prepayment inserted.

    Then computes the difference in interest and payoff date.

    Parameters
    ----------
    mortgage   : The Mortgage entity (with all existing terms and events).
    lump_sum   : Amount of the additional prepayment.
    applied_on : Date on which the prepayment is applied.
                 Must match a payment date in the schedule.
    """
    # ── Baseline schedule ────────────────────────────────────────────────────
    baseline = generate_schedule(mortgage)
    baseline_summary = baseline.lifetime_summary

    # ── Build modified mortgage with extra prepayment ────────────────────────
    # Find the term that contains this date
    target_term_idx = None
    for i, term in enumerate(mortgage.terms):
        if term.start_date <= applied_on <= term.end_date:
            target_term_idx = i
            break

    if target_term_idx is None:
        raise ValueError(
            f"applied_on date {applied_on} does not fall within any configured term."
        )

    # Deep-copy the mortgage terms and insert the extra prepayment event
    import copy
    modified_mortgage = copy.deepcopy(mortgage)
    extra_event = PrepaymentEvent(
        payment_date = applied_on,
        amount       = lump_sum,
        recurrence   = "once",
        note         = "What-if analysis prepayment",
    )
    modified_mortgage.terms[target_term_idx].prepayments.append(extra_event)

    # ── Modified schedule ────────────────────────────────────────────────────
    modified = generate_schedule(modified_mortgage)
    modified_summary = modified.lifetime_summary

    interest_saved = _round(baseline_summary.total_interest - modified_summary.total_interest)
    months_saved   = baseline_summary.payoff_month - modified_summary.payoff_month

    # Annualised return: how many years until payoff?
    years_remaining = max(
        Decimal("0.01"),
        Decimal(str(months_saved / 12)) if months_saved > 0
        else Decimal(str(baseline_summary.payoff_month / 12))
    )
    effective_return = _round(interest_saved / lump_sum / years_remaining) if lump_sum > _ZERO else _ZERO

    return PrepaymentImpact(
        prepayment_amount        = lump_sum,
        applied_on               = applied_on,
        baseline_payoff_date     = baseline_summary.payoff_date,
        baseline_total_interest  = baseline_summary.total_interest,
        baseline_payoff_month    = baseline_summary.payoff_month,
        new_payoff_date          = modified_summary.payoff_date,
        new_total_interest       = modified_summary.total_interest,
        new_payoff_month         = modified_summary.payoff_month,
        interest_saved           = interest_saved,
        months_saved             = months_saved,
        effective_annual_return  = effective_return,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Payment increase impact
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PaymentIncreaseImpact:
    additional_monthly:      Decimal
    effective_from:          date

    baseline_payoff_date:    date
    baseline_total_interest: Decimal

    new_payoff_date:         date
    new_total_interest:      Decimal

    interest_saved:          Decimal
    months_saved:            int


def payment_increase_impact(
    mortgage: Mortgage,
    additional_monthly: Decimal,
    effective_from: date,
) -> PaymentIncreaseImpact:
    """
    Calculate the impact of permanently increasing the monthly payment
    by `additional_monthly` starting from `effective_from`.

    Modelled as a monthly recurring PrepaymentEvent (since it is additional
    to the negotiated payment, not a renegotiation of the term).
    """
    baseline = generate_schedule(mortgage)
    baseline_summary = baseline.lifetime_summary

    target_term_idx = None
    for i, term in enumerate(mortgage.terms):
        if term.start_date <= effective_from <= term.end_date:
            target_term_idx = i
            break

    if target_term_idx is None:
        raise ValueError(
            f"effective_from date {effective_from} does not fall within any configured term."
        )

    import copy
    modified_mortgage = copy.deepcopy(mortgage)
    extra_event = PrepaymentEvent(
        payment_date = effective_from,
        amount       = additional_monthly,
        recurrence   = "monthly",
        note         = "What-if payment increase",
    )
    modified_mortgage.terms[target_term_idx].prepayments.append(extra_event)

    # Apply the same monthly increase to all subsequent terms too
    for i in range(target_term_idx + 1, len(modified_mortgage.terms)):
        term_start = modified_mortgage.terms[i].start_date
        extra = PrepaymentEvent(
            payment_date = term_start,
            amount       = additional_monthly,
            recurrence   = "monthly",
            note         = "What-if payment increase (continued)",
        )
        modified_mortgage.terms[i].prepayments.append(extra)

    modified = generate_schedule(modified_mortgage)
    modified_summary = modified.lifetime_summary

    interest_saved = _round(baseline_summary.total_interest - modified_summary.total_interest)
    months_saved   = baseline_summary.payoff_month - modified_summary.payoff_month

    return PaymentIncreaseImpact(
        additional_monthly       = additional_monthly,
        effective_from           = effective_from,
        baseline_payoff_date     = baseline_summary.payoff_date,
        baseline_total_interest  = baseline_summary.total_interest,
        new_payoff_date          = modified_summary.payoff_date,
        new_total_interest       = modified_summary.total_interest,
        interest_saved           = interest_saved,
        months_saved             = months_saved,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prepayment limit check
# ─────────────────────────────────────────────────────────────────────────────

def prepayment_used_this_year(schedule: AmortizationSchedule, year: int | None = None) -> Decimal:
    """Total prepayments made in the given calendar year."""
    y = year or date.today().year
    return _round(sum(
        (p.prepayment for p in schedule.payments if p.payment_date.year == y),
        _ZERO,
    ))


def prepayment_remaining_this_year(
    schedule: AmortizationSchedule,
    year: int | None = None,
) -> Decimal:
    """How much prepayment capacity remains within the annual lender limit."""
    limit = schedule.mortgage.annual_prepayment_limit
    used  = prepayment_used_this_year(schedule, year)
    return _round(max(_ZERO, limit - used))
