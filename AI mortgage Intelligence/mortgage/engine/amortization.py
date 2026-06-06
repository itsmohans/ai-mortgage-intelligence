"""
mortgage/engine/amortization.py
================================
The core amortization calculation engine.

How it works (event-driven approach)
--------------------------------------
Given a Mortgage with its Terms, RateChangeEvents, and PrepaymentEvents,
the engine reconstructs the full month-by-month payment schedule.

For each month in each term:

  1. Determine the interest rate in effect (from initial rate + any
     RateChangeEvents up to this date).

  2. Count the ACTUAL calendar days since the last payment date.
     This is the Actual/365 day-count convention — different months have
     different interest amounts even at the same rate because of different
     day counts. February on a low-rate mortgage saves you real money.

  3. Calculate monthly interest:
        interest = opening_balance × (annual_rate / 365) × actual_days

  4. Determine any prepayment for this month (from PrepaymentEvents).

  5. Compute balance:
        principal_repaid  = regular_payment + prepayment - interest
        closing_balance   = max(0, opening_balance - principal_repaid)

  6. Stop when closing_balance reaches zero — that is the payoff date.

Key design rules enforced here
--------------------------------
* Decimal arithmetic throughout — no float contamination.
* Historical vs. projected rows are flagged automatically.
* Negative principal_repaid is allowed and preserved — it represents
  months where the payment did not cover interest (real in Term 1 at 1.39 %).
* The engine never modifies stored entities — it only reads them and
  produces new MonthlyPayment / AmortizationSchedule objects.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dateutil.relativedelta import relativedelta

from mortgage.models.entities import (
    AmortizationSchedule,
    LifetimeSummary,
    MonthlyPayment,
    Mortgage,
    MortgageTerm,
    PrepaymentEvent,
    RateChangeEvent,
    TermSummary,
)

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

_ZERO  = Decimal("0.00")
_365   = Decimal("365")
_CENT  = Decimal("0.01")
_TODAY = date.today()


def _round(value: Decimal) -> Decimal:
    """Round to the nearest cent using standard banker's rounding."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _next_payment_date(current: date, payment_day: int) -> date:
    """
    Return the payment date one calendar month after `current`.

    We advance by one month using relativedelta (which handles month-end
    edge cases automatically — e.g. Jan 31 → Feb 28).
    Then we set the day to `payment_day`, clamped to the last day of that month.

    Examples:
        _next_payment_date(date(2021, 5, 21), 21) → date(2021, 6, 21)
        _next_payment_date(date(2021, 1, 31), 31) → date(2021, 2, 28)
    """
    next_month = current + relativedelta(months=1)
    # Clamp payment day to the last day of the resulting month
    import calendar
    last_day = calendar.monthrange(next_month.year, next_month.month)[1]
    clamped_day = min(payment_day, last_day)
    return next_month.replace(day=clamped_day)


def _build_rate_lookup(term: MortgageTerm) -> list[tuple[date, Decimal]]:
    """
    Build a sorted list of (effective_date, rate) pairs for this term.
    The initial rate is inserted at the term start date so there is always
    a baseline entry to look up from.

    Returns: sorted by effective_date ascending.
    """
    entries: list[tuple[date, Decimal]] = [
        (term.start_date, term.initial_annual_rate)
    ]
    for event in term.rate_changes:
        entries.append((event.effective_date, event.new_annual_rate))
    entries.sort(key=lambda x: x[0])
    return entries


def _rate_for_date(rate_lookup: list[tuple[date, Decimal]], payment_date: date) -> Decimal:
    """
    Return the interest rate in effect on `payment_date`.
    Uses the most recent entry whose effective_date <= payment_date.
    """
    rate = rate_lookup[0][1]   # baseline: always have at least one entry
    for effective_date, r in rate_lookup:
        if effective_date <= payment_date:
            rate = r
        else:
            break
    return rate


def _build_prepayment_lookup(
    term: MortgageTerm,
    payment_dates: list[date],
) -> dict[date, Decimal]:
    """
    Given the list of all payment dates in this term, expand PrepaymentEvents
    into a {payment_date: total_prepayment_amount} mapping.

    Recurrence rules:
      "once"    → appears only on payment_date.
      "monthly" → appears on every payment date >= event.payment_date
                  (and <= event.end_date if set).
      "annual"  → appears on dates where month == event.payment_date.month,
                  year >= event.payment_date.year
                  (and <= event.end_date.year if set).
    """
    lookup: dict[date, Decimal] = {}

    for event in term.prepayments:
        end = event.end_date  # may be None

        for pd in payment_dates:
            if pd < event.payment_date:
                continue
            if end is not None and pd > end:
                continue

            applies = False
            if event.recurrence == "once":
                applies = (pd == event.payment_date)
            elif event.recurrence == "monthly":
                applies = True
            elif event.recurrence == "annual":
                applies = (pd.month == event.payment_date.month)

            if applies:
                lookup[pd] = lookup.get(pd, _ZERO) + event.amount

    return lookup


# ─────────────────────────────────────────────────────────────────────────────
# Term-level schedule generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_term_payments(
    term: MortgageTerm,
    opening_balance: Decimal,
    period_offset: int,
    payment_day: int,
) -> list[MonthlyPayment]:
    """
    Generate all MonthlyPayment rows for a single MortgageTerm.

    opening_balance : the outstanding balance at the START of this term
                      (= closing balance of the previous term, or original
                       principal for Term 1).
    period_offset   : how many periods have already been generated for
                      previous terms (so period_number is global across terms).
    payment_day     : day of month for payment dates (from Mortgage.payment_day).
    """
    if opening_balance <= _ZERO:
        return []

    rate_lookup    = _build_rate_lookup(term)

    # ── Build the list of payment dates for this term ──────────────────────
    # Payment dates run from term.start_date + 1 month through term.end_date.
    # The first payment date is one month after the term start.
    payment_dates: list[date] = []
    cursor = _next_payment_date(term.start_date, payment_day)
    while cursor <= term.end_date:
        payment_dates.append(cursor)
        cursor = _next_payment_date(cursor, payment_day)

    prepayment_lookup = _build_prepayment_lookup(term, payment_dates)

    # ── Walk through each payment date ─────────────────────────────────────
    payments: list[MonthlyPayment] = []
    balance          = opening_balance
    prev_date        = term.start_date   # the "last event" date for day counting

    for i, pd in enumerate(payment_dates):
        if balance <= _ZERO:
            break

        days_in_period = (pd - prev_date).days
        annual_rate    = _rate_for_date(rate_lookup, pd)
        prepayment     = prepayment_lookup.get(pd, _ZERO)

        # Core interest formula: Actual/365
        interest = _round(balance * (annual_rate / _365) * Decimal(days_in_period))

        principal_repaid = _round(term.monthly_payment + prepayment - interest)
        closing_balance  = _round(balance - principal_repaid)

        # Clamp at payoff — last payment may be smaller than the regular one
        if closing_balance < _ZERO:
            # Adjust: only collect what is owed
            principal_repaid = balance
            closing_balance  = _ZERO

        payment = MonthlyPayment(
            period_number    = period_offset + i + 1,
            term_number      = term.term_number,
            payment_date     = pd,
            balance_opening  = balance,
            annual_rate      = annual_rate,
            days_in_period   = days_in_period,
            interest_amount  = interest,
            regular_payment  = term.monthly_payment,
            prepayment       = prepayment,
            principal_repaid = principal_repaid,
            balance_closing  = closing_balance,
            is_historical    = pd < _TODAY,
        )
        payments.append(payment)

        balance   = closing_balance
        prev_date = pd

    return payments


# ─────────────────────────────────────────────────────────────────────────────
# Summary computation
# ─────────────────────────────────────────────────────────────────────────────

def _compute_term_summary(
    term: MortgageTerm,
    payments: list[MonthlyPayment],
) -> TermSummary:
    term_payments = [p for p in payments if p.term_number == term.term_number]
    if not term_payments:
        return TermSummary(
            term_number=term.term_number, label=term.label,
            opening_balance=_ZERO, closing_balance=_ZERO,
            total_repayments=_ZERO, principal_repaid=_ZERO,
            interest_paid=_ZERO, total_prepayments=_ZERO,
            avg_weighted_rate=_ZERO, payment_count=0,
        )

    total_interest   = sum((p.interest_amount  for p in term_payments), _ZERO)
    total_regular    = sum((p.regular_payment  for p in term_payments), _ZERO)
    total_prepay     = sum((p.prepayment       for p in term_payments), _ZERO)
    total_principal  = sum((p.principal_repaid for p in term_payments), _ZERO)

    # Weighted average rate: weight each period's rate by its interest amount
    total_weighted = sum(
        p.annual_rate * p.interest_amount for p in term_payments
    )
    avg_rate = _round(total_weighted / total_interest) if total_interest > _ZERO else _ZERO

    return TermSummary(
        term_number      = term.term_number,
        label            = term.label,
        opening_balance  = term_payments[0].balance_opening,
        closing_balance  = term_payments[-1].balance_closing,
        total_repayments = _round(total_regular + total_prepay),
        principal_repaid = _round(total_principal),
        interest_paid    = _round(total_interest),
        total_prepayments= _round(total_prepay),
        avg_weighted_rate= avg_rate,
        payment_count    = len(term_payments),
    )


def _compute_lifetime_summary(
    mortgage: Mortgage,
    payments: list[MonthlyPayment],
    term_summaries: list[TermSummary],
) -> LifetimeSummary:
    if not payments:
        raise ValueError("Cannot compute lifetime summary: no payments generated.")

    total_interest   = sum((ts.interest_paid    for ts in term_summaries), _ZERO)
    total_repayments = sum((ts.total_repayments for ts in term_summaries), _ZERO)
    total_prepay     = sum((ts.total_prepayments for ts in term_summaries), _ZERO)
    total_principal  = sum((ts.principal_repaid  for ts in term_summaries), _ZERO)

    last_payment     = payments[-1]
    net_interest_pct = _round(total_interest / mortgage.original_principal)

    # Weighted average rate across all payments
    total_weighted = sum(p.annual_rate * p.interest_amount for p in payments)
    total_int      = sum((p.interest_amount for p in payments), _ZERO)
    weighted_avg   = _round(total_weighted / total_int) if total_int > _ZERO else _ZERO

    return LifetimeSummary(
        total_repayments  = _round(total_repayments),
        total_principal   = _round(total_principal),
        total_interest    = _round(total_interest),
        net_interest_pct  = net_interest_pct,
        total_prepayments = _round(total_prepay),
        payoff_date       = last_payment.payment_date,
        payoff_month      = last_payment.period_number,
        weighted_avg_rate = weighted_avg,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def generate_schedule(mortgage: Mortgage) -> AmortizationSchedule:
    """
    Generate the complete amortization schedule for a mortgage.

    This is the main public function of the engine.
    It iterates through all terms in order, carries the closing balance
    from one term into the next, and collects all MonthlyPayment rows.

    Usage:
        schedule = generate_schedule(mortgage)
        for payment in schedule.payments:
            print(payment.payment_date, payment.balance_closing)
        print(schedule.lifetime_summary.payoff_date)

    Returns an AmortizationSchedule with:
      .payments         — list of MonthlyPayment (complete schedule)
      .term_summaries   — one TermSummary per term
      .lifetime_summary — overall totals and payoff date
    """
    if not mortgage.terms:
        raise ValueError("Mortgage has no terms configured. Add at least one MortgageTerm.")

    all_payments: list[MonthlyPayment] = []
    current_balance = mortgage.original_principal
    period_offset   = 0

    for term in sorted(mortgage.terms, key=lambda t: t.term_number):
        term_payments = _generate_term_payments(
            term            = term,
            opening_balance = current_balance,
            period_offset   = period_offset,
            payment_day     = mortgage.payment_day,
        )
        all_payments.extend(term_payments)

        if term_payments:
            current_balance = term_payments[-1].balance_closing
            period_offset   += len(term_payments)

        # If the mortgage is fully paid within this term, stop
        if current_balance <= _ZERO:
            break

    if not all_payments:
        raise ValueError("No payments were generated. Check that term dates are valid.")

    term_summaries   = [_compute_term_summary(t, all_payments) for t in mortgage.terms]
    lifetime_summary = _compute_lifetime_summary(mortgage, all_payments, term_summaries)

    return AmortizationSchedule(
        mortgage         = mortgage,
        payments         = all_payments,
        term_summaries   = term_summaries,
        lifetime_summary = lifetime_summary,
    )
