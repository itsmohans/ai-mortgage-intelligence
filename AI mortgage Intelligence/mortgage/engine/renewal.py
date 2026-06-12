"""
mortgage/engine/renewal.py
===========================
Renewal payment calculator and renewal term comparison tools.

Canadian mortgage compounding convention
-----------------------------------------
By law (Interest Act of Canada), Canadian mortgages must compound
semi-annually (twice per year), not monthly. This is different from
the US convention. The PMT formula must use the effective monthly rate
derived from semi-annual compounding.

The calculation:
  semi_annual_rate = annual_rate / 2
  monthly_rate     = (1 + semi_annual_rate) ^ (1/6) - 1

This monthly_rate is then used in the standard PMT formula:
  PMT = P × i / (1 − (1 + i)^−n)

Where:
  P = principal (outstanding balance)
  i = effective monthly rate
  n = number of remaining monthly payments

Why this matters
-----------------
At 3.89 % annual rate:
  Monthly compounding:    i = 0.0389 / 12 = 0.003242  → PMT = $1,862.94
  Semi-annual (Canadian): i = (1+0.0389/2)^(1/6)-1 = 0.003224  → PMT = $1,852.98

The difference compounds over 30 years. Always use Canadian convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from math import pow as fpow

from dateutil.relativedelta import relativedelta

from mortgage.models.entities import Mortgage, MortgageTerm

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _round(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# Core PMT calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_monthly_payment(
    principal: Decimal,
    annual_rate: Decimal,
    remaining_amortization_months: int,
    compounding: str = "semi_annual",
) -> Decimal:
    """
    Calculate the monthly payment for a Canadian mortgage.

    Parameters
    ----------
    principal                    : Outstanding balance at renewal.
    annual_rate                  : New annual interest rate (e.g. Decimal("0.0389")).
    remaining_amortization_months: Months remaining in the total amortization period.
    compounding                  : Monthly rate convention:
                                   "semi_annual" (default) — Canadian Interest Act standard.
                                       monthly_rate = (1 + annual_rate/2)^(1/6) - 1
                                   "monthly_simple" — rate/12, as used by some lenders
                                       for the PMT calculation (daily interest accrual
                                       still uses Actual/365).

    Returns
    -------
    Monthly payment amount, rounded to the nearest cent.

    Note on the $0.80 discrepancy
    ------------------------------
    Many Canadian lenders compute the payment with rate/12 ("monthly_simple") even
    though the Interest Act mandates semi-annual compounding for the interest rate
    definition. The difference is small (~$0.80 on a $420k mortgage at 1.39%) but
    causes a mismatch if you compare against a bank-issued amortization statement.
    Use compounding="monthly_simple" when you want to reproduce your bank's figure.
    """
    if remaining_amortization_months <= 0:
        raise ValueError(
            "remaining_amortization_months must be > 0. "
            "The mortgage amortization period has been exhausted."
        )

    if annual_rate == _ZERO:
        return _round(principal / Decimal(remaining_amortization_months))

    r = float(annual_rate)
    if compounding == "monthly_simple":
        monthly_rate = r / 12.0
    else:
        # Canadian semi-annual compounding (default)
        monthly_rate = fpow(1.0 + r / 2.0, 1.0 / 6.0) - 1.0

    n   = remaining_amortization_months
    pmt = float(principal) * monthly_rate / (1.0 - fpow(1.0 + monthly_rate, -n))

    return _round(Decimal(str(pmt)))


def remaining_amortization_months(
    mortgage: Mortgage,
    as_of_date: date,
) -> int:
    """
    Calculate how many months of the original amortization period remain
    as of `as_of_date`.

    This drives the payment re-calculation at each renewal.
    If the mortgage started May 21, 2021 with a 30-year amortization,
    then as of July 21, 2026 there are 30×12 − 62 = 298 months remaining.
    """
    start = mortgage.start_date
    # Number of full months elapsed
    months_elapsed = (
        (as_of_date.year - start.year) * 12
        + (as_of_date.month - start.month)
    )
    total_months = mortgage.amortization_months
    remaining    = total_months - months_elapsed
    return max(0, remaining)


# ─────────────────────────────────────────────────────────────────────────────
# Renewal comparison
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RenewalOption:
    """
    One option in a renewal comparison.

    term_years        : Length of this renewal term (1–5).
    annual_rate       : Assumed rate for this term.
    monthly_payment   : Computed monthly payment (PMT).
    term_total_interest: Total interest paid during this term only.
    term_total_repaid : Total cash paid during this term (payment + prepayments).
    balance_at_end    : Outstanding balance when this term expires.
    projected_payoff  : Projected payoff date under this term (rough estimate,
                        assumes the same rate continues after term end).
    projected_total_interest: Total lifetime interest from now to payoff.
    """
    term_years:               int
    annual_rate:              Decimal
    monthly_payment:          Decimal
    term_total_interest:      Decimal
    term_total_repaid:        Decimal
    balance_at_end:           Decimal
    projected_payoff:         date
    projected_total_interest: Decimal


def compare_renewal_options(
    current_balance: Decimal,
    renewal_date: date,
    mortgage: Mortgage,
    rate_by_term: dict[int, Decimal],
    monthly_prepayment: Decimal = _ZERO,
) -> list[RenewalOption]:
    """
    Compare multiple renewal options side by side.

    Parameters
    ----------
    current_balance   : Outstanding balance at the renewal date.
    renewal_date      : Date the new term starts.
    mortgage          : The Mortgage entity (for amortization period).
    rate_by_term      : {term_years: annual_rate} for each option to evaluate.
                        E.g. {1: Decimal("0.035"), 3: Decimal("0.039"), 5: Decimal("0.042")}
    monthly_prepayment: A fixed extra monthly payment assumed for all options.
                        Set to 0 for a pure payment comparison.

    Returns
    -------
    List of RenewalOption, one per term length, sorted by term_years.

    Use this to populate the renewal comparison table in the Streamlit UI.
    """
    options: list[RenewalOption] = []
    remaining_months = remaining_amortization_months(mortgage, renewal_date)

    for term_years, annual_rate in sorted(rate_by_term.items()):
        payment = calculate_monthly_payment(
            principal                    = current_balance,
            annual_rate                  = annual_rate,
            remaining_amortization_months= remaining_months,
        )

        # Simulate this term to get interest and closing balance
        term_months     = term_years * 12
        balance         = current_balance
        term_interest   = _ZERO
        term_repaid     = _ZERO
        monthly_rate_f  = fpow(1 + float(annual_rate) / 2, 1/6) - 1
        monthly_rate    = Decimal(str(monthly_rate_f))

        for _ in range(min(term_months, remaining_months)):
            if balance <= _ZERO:
                break
            interest        = _round(balance * monthly_rate)
            principal_paid  = _round(payment + monthly_prepayment - interest)
            balance         = _round(max(_ZERO, balance - principal_paid))
            term_interest  += interest
            term_repaid    += payment + monthly_prepayment

        balance_at_end = balance

        # Rough projection: how many months at current payment to pay off remainder?
        # Solves for n in PMT formula: n = -log(1 - P*i/PMT) / log(1+i)
        if balance_at_end > _ZERO and payment > _ZERO:
            i = float(monthly_rate)
            p = float(balance_at_end)
            r = float(payment + monthly_prepayment)
            try:
                import math
                n_remaining = math.ceil(
                    -math.log(1 - p * i / r) / math.log(1 + i)
                )
            except (ValueError, ZeroDivisionError):
                n_remaining = remaining_months

            # Project additional interest after term end (at same rate)
            additional_interest = _ZERO
            bal = balance_at_end
            for _ in range(min(n_remaining, remaining_months)):
                if bal <= _ZERO:
                    break
                int_ = _round(bal * monthly_rate)
                bal  = _round(max(_ZERO, bal - (payment + monthly_prepayment - int_)))
                additional_interest += int_

            projected_total_interest = _round(term_interest + additional_interest)
            projected_months_total   = term_months + n_remaining
            projected_payoff         = renewal_date + relativedelta(months=projected_months_total)
        else:
            projected_total_interest = _round(term_interest)
            projected_payoff         = renewal_date + relativedelta(months=term_months)

        options.append(RenewalOption(
            term_years               = term_years,
            annual_rate              = annual_rate,
            monthly_payment          = payment,
            term_total_interest      = _round(term_interest),
            term_total_repaid        = _round(term_repaid),
            balance_at_end           = balance_at_end,
            projected_payoff         = projected_payoff,
            projected_total_interest = projected_total_interest,
        ))

    return options
