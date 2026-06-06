"""
mortgage/ai/context.py
=======================
Builds a structured text snapshot of the mortgage for the AI system prompt.

Keeps the context concise but complete — the AI needs enough detail to answer
specific questions accurately without exceeding token limits.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from mortgage.engine.analytics import (
    balance_at_date,
    prepayment_remaining_this_year,
    prepayment_used_this_year,
    ytd_summary,
)
from mortgage.engine.amortization import generate_schedule
from mortgage.models.entities import AmortizationSchedule, Mortgage


def build_mortgage_context(schedule: AmortizationSchedule) -> str:
    """
    Return a structured text block describing the full mortgage state.
    This is injected into the Claude system prompt.
    """
    m     = schedule.mortgage
    ls    = schedule.lifetime_summary
    today = date.today()

    hist  = [p for p in schedule.payments if p.is_historical]
    today_bal   = next((p.balance_closing for p in reversed(hist)), m.original_principal)
    equity_built = m.original_principal - today_bal
    pct_paid    = float(equity_built / m.original_principal * 100) if m.original_principal else 0.0

    try:
        ytd = ytd_summary(schedule)
        ytd_block = (
            f"  Year-to-date {today.year}:\n"
            f"    Total repayments:  ${float(ytd.total_repayments):,.2f}\n"
            f"    Principal repaid:  ${float(ytd.principal_repaid):,.2f}\n"
            f"    Interest paid:     ${float(ytd.interest_paid):,.2f}\n"
            f"    Prepayments:       ${float(ytd.total_prepayments):,.2f}\n"
            f"    Payments made:     {ytd.payment_count}"
        )
    except Exception:
        ytd_block = "  Year-to-date data not available."

    try:
        prep_used      = prepayment_used_this_year(schedule)
        prep_remaining = prepayment_remaining_this_year(schedule)
        prep_limit_block = (
            f"  Annual prepayment privilege: ${float(m.annual_prepayment_limit):,.2f} "
            f"({float(m.prepayment_limit_pct)*100:.0f}% of original principal)\n"
            f"  Used this year ({today.year}): ${float(prep_used):,.2f}\n"
            f"  Remaining this year:           ${float(prep_remaining):,.2f}"
        )
    except Exception:
        prep_limit_block = f"  Annual prepayment limit: ${float(m.annual_prepayment_limit):,.2f}"

    # Terms
    terms_block = ""
    for t in sorted(m.terms, key=lambda x: x.term_number):
        status = "PAST" if t.end_date < today else ("CURRENT" if t.start_date <= today else "FUTURE")
        terms_block += (
            f"\n  Term {t.term_number} [{status}]:\n"
            f"    Period:        {t.start_date} to {t.end_date} ({t.term_years} year)\n"
            f"    Type:          {t.rate_type.capitalize()}\n"
            f"    Initial rate:  {float(t.initial_annual_rate)*100:.4f}%\n"
            f"    Monthly PMT:   ${float(t.monthly_payment):,.2f}\n"
        )
        if t.rate_changes:
            terms_block += "    Rate changes:\n"
            for rc in sorted(t.rate_changes, key=lambda r: r.effective_date):
                terms_block += f"      {rc.effective_date}: → {float(rc.new_annual_rate)*100:.4f}%\n"
        if t.prepayments:
            terms_block += "    Prepayments:\n"
            for pp in sorted(t.prepayments, key=lambda p: p.payment_date):
                end_info = f" until {pp.end_date}" if pp.end_date else " (open-ended)"
                terms_block += (
                    f"      ${float(pp.amount):,.2f} {pp.recurrence}"
                    f"{end_info if pp.recurrence != 'once' else ''}"
                    f" from {pp.payment_date}"
                    f"{(' — ' + pp.note) if pp.note else ''}\n"
                )

    # Term summaries
    term_summary_block = ""
    for ts in schedule.term_summaries:
        term_summary_block += (
            f"\n  {ts.label}:\n"
            f"    Opening balance:  ${float(ts.opening_balance):,.2f}\n"
            f"    Closing balance:  ${float(ts.closing_balance):,.2f}\n"
            f"    Principal repaid: ${float(ts.principal_repaid):,.2f}\n"
            f"    Interest paid:    ${float(ts.interest_paid):,.2f}\n"
            f"    Prepayments:      ${float(ts.total_prepayments):,.2f}\n"
            f"    Avg rate:         {float(ts.avg_weighted_rate)*100:.2f}%\n"
        )

    context = f"""
=== MORTGAGE DATA (as of {today}) ===

MORTGAGE OVERVIEW
  Lender:              {m.lender or 'Not specified'}
  Original principal:  ${float(m.original_principal):,.2f}
  Start date:          {m.start_date}
  Amortization:        {m.amortization_years} years ({m.amortization_months} months total)
  Payment day:         {m.payment_day} of each month

CURRENT STATUS
  Today's date:        {today}
  Outstanding balance: ${float(today_bal):,.2f}
  Equity built:        ${float(equity_built):,.2f} ({pct_paid:.1f}% paid off)
  Projected payoff:    {ls.payoff_date.strftime('%B %Y')} (payment #{ls.payoff_month})

LIFETIME PROJECTIONS (based on current terms and prepayments)
  Total interest:      ${float(ls.total_interest):,.2f}
  Total prepayments:   ${float(ls.total_prepayments):,.2f}
  Interest as % of principal: {float(ls.net_interest_pct)*100:.1f}%
  Weighted avg rate:   {float(ls.weighted_avg_rate)*100:.2f}%

PREPAYMENT PRIVILEGE
{prep_limit_block}

YEAR-TO-DATE SUMMARY
{ytd_block}

TERMS & RATE HISTORY
{terms_block}

TERM-BY-TERM PERFORMANCE
{term_summary_block}

CANADIAN MORTGAGE NOTES
  - Interest compounded semi-annually (Canadian Interest Act)
  - Day-count: Actual/365 (interest accrues on actual calendar days)
  - Prepayment privilege resets each calendar year
""".strip()

    return context
