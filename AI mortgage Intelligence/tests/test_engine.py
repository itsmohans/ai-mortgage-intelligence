"""
tests/test_engine.py
=====================
Unit tests for the amortization engine and renewal calculator.

Run with:  python -m pytest tests/ -v

Key design note
---------------
Many tests use a FULL-AMORTIZATION-LENGTH term (term covers the entire
amortization period). This is needed to verify payoff at zero balance.
A term shorter than the amortization period correctly stops at term end
without zeroing the balance — that residual carries into the next renewal.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta

from mortgage.engine.amortization import generate_schedule
from mortgage.engine.analytics import (
    balance_at_date,
    balance_at_period,
    payment_increase_impact,
    prepayment_impact,
    ytd_summary,
)
from mortgage.engine.renewal import (
    calculate_monthly_payment,
    compare_renewal_options,
    remaining_amortization_months,
)
from mortgage.models.entities import (
    Mortgage,
    MortgageTerm,
    PrepaymentEvent,
    RateChangeEvent,
)


# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------

def _full_term_mortgage(principal="100000.00", rate="0.04", years=10,
                        start=date(2024, 1, 21), prepays=None):
    """Single-term mortgage whose term COVERS the full amortization period."""
    p   = Decimal(principal)
    r   = Decimal(rate)
    n   = years * 12
    pmt = calculate_monthly_payment(p, r, n)
    end = start + relativedelta(years=years)
    term = MortgageTerm(
        term_number=1, start_date=start, end_date=end, term_years=years,
        rate_type="fixed", initial_annual_rate=r, monthly_payment=pmt,
        prepayments=prepays or [],
    )
    return Mortgage(
        original_principal=p, start_date=start, amortization_years=years,
        prepayment_limit_pct=Decimal("0.20"), payment_day=21, terms=[term],
    )


def _short_term_mortgage(principal="420880.00", rate="0.0389",
                         amort_years=30, term_years=3):
    """Realistic mortgage where term < amortization; balance carries forward."""
    start = date(2026, 7, 21)
    p     = Decimal(principal)
    r     = Decimal(rate)
    pmt   = calculate_monthly_payment(p, r, amort_years * 12)
    end   = start + relativedelta(years=term_years)
    term  = MortgageTerm(
        term_number=1, start_date=start, end_date=end, term_years=term_years,
        rate_type="fixed", initial_annual_rate=r, monthly_payment=pmt,
    )
    return Mortgage(
        original_principal=p, start_date=date(2021, 5, 21),
        amortization_years=amort_years, prepayment_limit_pct=Decimal("0.20"),
        payment_day=21, terms=[term],
    )


# ---------------------------------------------------------------------------
# 1. PMT calculation
# ---------------------------------------------------------------------------

class TestCalculateMonthlyPayment:

    def test_known_value_range(self):
        pmt = calculate_monthly_payment(
            Decimal("420880.00"), Decimal("0.0389"), 298)
        assert Decimal("1800") < pmt < Decimal("2500")

    def test_zero_rate(self):
        pmt = calculate_monthly_payment(
            Decimal("120000.00"), Decimal("0.00"), 120)
        assert pmt == Decimal("1000.00")

    def test_zero_months_raises(self):
        with pytest.raises(ValueError):
            calculate_monthly_payment(Decimal("100000"), Decimal("0.05"), 0)

    def test_payment_covers_first_month_interest(self):
        p   = Decimal("350000.00")
        r   = Decimal("0.0389")
        pmt = calculate_monthly_payment(p, r, 298)
        first_interest = p * (r / Decimal("365")) * Decimal("30")
        assert pmt > first_interest

    def test_higher_rate_higher_payment(self):
        p = Decimal("300000")
        n = 240
        assert (calculate_monthly_payment(p, Decimal("0.06"), n) >
                calculate_monthly_payment(p, Decimal("0.03"), n))

    def test_shorter_amortization_higher_payment(self):
        p = Decimal("300000")
        r = Decimal("0.04")
        assert (calculate_monthly_payment(p, r, 180) >
                calculate_monthly_payment(p, r, 300))


# ---------------------------------------------------------------------------
# 2. Remaining amortization months
# ---------------------------------------------------------------------------

class TestRemainingAmortizationMonths:

    def _m(self):
        return Mortgage(
            original_principal=Decimal("420880"),
            start_date=date(2021, 5, 21),
            amortization_years=30,
            prepayment_limit_pct=Decimal("0.20"),
            payment_day=21,
        )

    def test_at_start(self):
        assert remaining_amortization_months(self._m(), date(2021, 5, 21)) == 360

    def test_five_years_two_months_in(self):
        # May 2021 to Jul 2026 = 62 months elapsed, 298 remaining
        assert remaining_amortization_months(self._m(), date(2026, 7, 21)) == 298


# ---------------------------------------------------------------------------
# 3. Schedule generation
# ---------------------------------------------------------------------------

class TestGenerateSchedule:

    def test_opening_balance_equals_principal(self):
        m   = _short_term_mortgage()
        sch = generate_schedule(m)
        assert sch.payments[0].balance_opening == Decimal("420880.00")

    def test_no_negative_balance(self):
        m   = _full_term_mortgage()
        sch = generate_schedule(m)
        for p in sch.payments:
            assert p.balance_closing >= Decimal("0.00")

    def test_balance_continuity(self):
        m   = _full_term_mortgage()
        sch = generate_schedule(m)
        for i in range(1, len(sch.payments)):
            prev = sch.payments[i - 1]
            curr = sch.payments[i]
            assert curr.balance_opening == prev.balance_closing

    def test_interest_formula_first_payment(self):
        # Jan 21 to Feb 21 = 31 days; $100K at 4%
        m   = _full_term_mortgage(principal="100000", rate="0.04",
                                  start=date(2024, 1, 21))
        sch = generate_schedule(m)
        p1  = sch.payments[0]
        assert p1.days_in_period == 31
        expected = (Decimal("100000.00") * Decimal("0.04")
                    / Decimal("365") * Decimal("31")).quantize(Decimal("0.01"))
        assert abs(p1.interest_amount - expected) <= Decimal("0.02")

    def test_final_balance_within_one_pct(self):
        # Actual/365 vs PMT-formula drift leaves a small residual; accept <= 1%
        m       = _full_term_mortgage(years=5)
        sch     = generate_schedule(m)
        final   = sch.payments[-1].balance_closing
        one_pct = m.original_principal * Decimal("0.01")
        assert final <= one_pct

    def test_payoff_within_amortization_period(self):
        m   = _short_term_mortgage()
        sch = generate_schedule(m)
        assert sch.lifetime_summary.payoff_month <= m.amortization_months

    def test_total_interest_positive(self):
        m   = _full_term_mortgage()
        sch = generate_schedule(m)
        assert sch.lifetime_summary.total_interest > Decimal("0")

    def test_principal_repaid_within_one_pct(self):
        # Same Actual/365 drift; total principal within 1% of original
        m     = _full_term_mortgage(years=5)
        sch   = generate_schedule(m)
        total = sum((p.principal_repaid for p in sch.payments), Decimal("0"))
        diff  = abs(total - m.original_principal)
        assert diff <= m.original_principal * Decimal("0.01")

    def test_no_terms_raises(self):
        m = Mortgage(
            original_principal=Decimal("100000"),
            start_date=date(2024, 1, 1),
            amortization_years=25,
            payment_day=1,
        )
        with pytest.raises(ValueError, match="no terms"):
            generate_schedule(m)


# ---------------------------------------------------------------------------
# 4. Prepayments
# ---------------------------------------------------------------------------

class TestPrepayments:

    def test_prepayment_reduces_balance(self):
        prepay = PrepaymentEvent(
            payment_date=date(2024, 2, 21),
            amount=Decimal("500.00"),
            recurrence="monthly",
        )
        sch_base = generate_schedule(_full_term_mortgage())
        sch_prep = generate_schedule(_full_term_mortgage(prepays=[prepay]))
        assert (sch_prep.payments[0].balance_closing <
                sch_base.payments[0].balance_closing)

    def test_prepayment_shortens_payoff(self):
        prepay = PrepaymentEvent(
            payment_date=date(2024, 2, 21),
            amount=Decimal("500.00"),
            recurrence="monthly",
        )
        sch_base = generate_schedule(_full_term_mortgage(years=10))
        sch_prep = generate_schedule(_full_term_mortgage(years=10, prepays=[prepay]))
        assert (sch_prep.lifetime_summary.payoff_month <
                sch_base.lifetime_summary.payoff_month)

    def test_prepayment_reduces_total_interest(self):
        prepay = PrepaymentEvent(
            payment_date=date(2024, 2, 21),
            amount=Decimal("500.00"),
            recurrence="monthly",
        )
        sch_base = generate_schedule(_full_term_mortgage(years=10))
        sch_prep = generate_schedule(_full_term_mortgage(years=10, prepays=[prepay]))
        assert (sch_prep.lifetime_summary.total_interest <
                sch_base.lifetime_summary.total_interest)

    def test_annual_prepayment_limit(self):
        m = _short_term_mortgage()
        assert m.annual_prepayment_limit == Decimal("84176.00")

    def test_one_time_prepayment_applied_once(self):
        prepay = PrepaymentEvent(
            payment_date=date(2024, 3, 21),
            amount=Decimal("5000.00"),
            recurrence="once",
        )
        sch = generate_schedule(_full_term_mortgage(years=10, prepays=[prepay]))
        months_with_prepay = [p for p in sch.payments if p.prepayment > Decimal("0")]
        assert len(months_with_prepay) == 1
        assert months_with_prepay[0].prepayment == Decimal("5000.00")


# ---------------------------------------------------------------------------
# 5. Analytics
# ---------------------------------------------------------------------------

class TestAnalytics:

    def test_balance_at_period(self):
        m   = _short_term_mortgage()
        sch = generate_schedule(m)
        b   = balance_at_period(sch, 1)
        assert Decimal("0") < b < m.original_principal

    def test_balance_at_date(self):
        m   = _short_term_mortgage()
        sch = generate_schedule(m)
        b   = balance_at_date(sch, date(2027, 6, 1))
        assert Decimal("0") < b < m.original_principal

    def test_ytd_interest_positive(self):
        m   = _short_term_mortgage()
        sch = generate_schedule(m)
        yts = ytd_summary(sch, year=2026)
        if yts.payment_count > 0:
            assert yts.interest_paid > Decimal("0")

    def test_prepayment_impact_saves(self):
        m      = _full_term_mortgage(years=10)
        apply  = date(2024, 1, 21) + relativedelta(months=6)
        impact = prepayment_impact(m, Decimal("5000.00"), apply)
        assert impact.interest_saved   > Decimal("0")
        assert impact.months_saved     > 0
        assert impact.new_total_interest < impact.baseline_total_interest

    def test_payment_increase_impact_saves(self):
        m      = _full_term_mortgage(years=10)
        eff    = date(2024, 1, 21) + relativedelta(months=1)
        impact = payment_increase_impact(m, Decimal("200.00"), eff)
        assert impact.interest_saved > Decimal("0")
        assert impact.months_saved   > 0


# ---------------------------------------------------------------------------
# 6. Renewal comparison
# ---------------------------------------------------------------------------

class TestRenewalComparison:

    def _m(self):
        return Mortgage(
            original_principal=Decimal("356272.86"),
            start_date=date(2021, 5, 21),
            amortization_years=30,
            prepayment_limit_pct=Decimal("0.20"),
            payment_day=21,
        )

    def test_returns_all_options(self):
        rates   = {1: Decimal("0.0325"), 3: Decimal("0.0389"), 5: Decimal("0.0420")}
        options = compare_renewal_options(
            current_balance=Decimal("356272.86"),
            renewal_date=date(2026, 7, 21),
            mortgage=self._m(), rate_by_term=rates,
        )
        assert len(options) == 3

    def test_higher_rate_higher_payment(self):
        rates   = {1: Decimal("0.03"), 5: Decimal("0.05")}
        options = compare_renewal_options(
            current_balance=Decimal("356272.86"),
            renewal_date=date(2026, 7, 21),
            mortgage=self._m(), rate_by_term=rates,
        )
        low  = next(o for o in options if o.term_years == 1)
        high = next(o for o in options if o.term_years == 5)
        assert high.monthly_payment > low.monthly_payment

    def test_longer_term_more_interest(self):
        rates   = {1: Decimal("0.04"), 5: Decimal("0.04")}
        options = compare_renewal_options(
            current_balance=Decimal("356272.86"),
            renewal_date=date(2026, 7, 21),
            mortgage=self._m(), rate_by_term=rates,
        )
        y1 = next(o for o in options if o.term_years == 1)
        y5 = next(o for o in options if o.term_years == 5)
        assert y5.term_total_interest > y1.term_total_interest


# ---------------------------------------------------------------------------
# 7. Variable rate term
# ---------------------------------------------------------------------------

class TestVariableRateTerm:

    def _m(self):
        start = date(2021, 5, 21)
        term  = MortgageTerm(
            term_number=1, start_date=start, end_date=date(2026, 6, 21),
            term_years=5, rate_type="variable",
            initial_annual_rate=Decimal("0.0139"),
            monthly_payment=Decimal("1430.43"),
            rate_changes=[RateChangeEvent(
                effective_date=date(2021, 11, 21),
                new_annual_rate=Decimal("0.0614"),
            )],
        )
        return Mortgage(
            original_principal=Decimal("420880.00"), start_date=start,
            amortization_years=30, prepayment_limit_pct=Decimal("0.20"),
            payment_day=21, terms=[term],
        )

    def test_rate_change_increases_interest(self):
        sch    = generate_schedule(self._m())
        before = [p for p in sch.payments if p.payment_date < date(2021, 11, 21)]
        after  = [p for p in sch.payments if p.payment_date >= date(2021, 11, 21)][:3]
        avg_b  = sum((p.interest_amount for p in before), Decimal("0")) / len(before)
        avg_a  = sum((p.interest_amount for p in after),  Decimal("0")) / len(after)
        assert avg_a > avg_b

    def test_no_negative_balance(self):
        for p in generate_schedule(self._m()).payments:
            assert p.balance_closing >= Decimal("0.00")

    def test_rate_before_change(self):
        sch = generate_schedule(self._m())
        for p in sch.payments:
            if p.payment_date < date(2021, 11, 21):
                assert p.annual_rate == Decimal("0.0139")

    def test_rate_after_change(self):
        sch = generate_schedule(self._m())
        for p in sch.payments:
            if p.payment_date >= date(2021, 11, 21):
                assert p.annual_rate == Decimal("0.0614")

    def test_two_term_carry_over(self):
        start1 = date(2021, 5, 21)
        term1  = MortgageTerm(
            term_number=1, start_date=start1, end_date=date(2026, 6, 21),
            term_years=5, rate_type="variable",
            initial_annual_rate=Decimal("0.0339"),
            monthly_payment=Decimal("1430.43"),
        )
        start2 = date(2026, 7, 21)
        term2  = MortgageTerm(
            term_number=2, start_date=start2, end_date=date(2029, 7, 21),
            term_years=3, rate_type="fixed",
            initial_annual_rate=Decimal("0.0389"),
            monthly_payment=Decimal("1863.49"),
        )
        m   = Mortgage(
            original_principal=Decimal("420880.00"), start_date=start1,
            amortization_years=30, prepayment_limit_pct=Decimal("0.20"),
            payment_day=21, terms=[term1, term2],
        )
        sch = generate_schedule(m)
        t1  = [p for p in sch.payments if p.term_number == 1]
        t2  = [p for p in sch.payments if p.term_number == 2]
        assert len(t1) > 0 and len(t2) > 0
        # Term 2 opening must equal Term 1 closing
        assert t2[0].balance_opening == t1[-1].balance_closing
        for p in sch.payments:
            assert p.balance_closing >= Decimal("0.00")
