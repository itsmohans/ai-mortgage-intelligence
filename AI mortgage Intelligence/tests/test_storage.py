"""
tests/test_storage.py
======================
Tests for the storage layer (database + repository).

All tests use an in-memory SQLite database so they:
  * Run fast (no disk I/O)
  * Are fully isolated (each test gets a fresh DB)
  * Leave no files behind

What we are validating
-----------------------
1. Full round-trip: save a complete Mortgage, load it back, verify every field.
2. Relations: terms, rate changes, and prepayments survive the round-trip exactly.
3. Decimal precision: "0.0389" is stored and loaded back as Decimal("0.0389"), not 0.03890000001.
4. Date fidelity: dates come back as date objects, not strings.
5. update / delete operations work correctly.
6. Engine integration: a loaded Mortgage runs through generate_schedule without error.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from mortgage.engine.amortization import generate_schedule
from mortgage.engine.renewal import calculate_monthly_payment
from mortgage.models.entities import (
    Mortgage,
    MortgageTerm,
    PrepaymentEvent,
    RateChangeEvent,
)
from mortgage.storage.database import get_engine, metadata, reset_engine
from mortgage.storage.repository import MortgageRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def repo():
    """
    Fresh in-memory repository for each test.
    Using "sqlite:///:memory:" gives a completely clean database every time.
    """
    reset_engine()
    r = MortgageRepository("sqlite:///:memory:")
    yield r
    reset_engine()


def _make_mortgage() -> Mortgage:
    """Build a realistic two-term mortgage for storage testing."""
    start1 = date(2021, 5, 21)
    rate_change = RateChangeEvent(
        effective_date=date(2022, 3, 21),
        new_annual_rate=Decimal("0.0164"),
    )
    prepay1 = PrepaymentEvent(
        payment_date=date(2022, 5, 21),
        amount=Decimal("1000.00"),
        recurrence="monthly",
        note="regular top-up",
    )
    term1 = MortgageTerm(
        term_number=1,
        start_date=start1,
        end_date=date(2026, 6, 21),
        term_years=5,
        rate_type="variable",
        initial_annual_rate=Decimal("0.0139"),
        monthly_payment=Decimal("1430.43"),
        rate_changes=[rate_change],
        prepayments=[prepay1],
    )

    start2 = date(2026, 7, 21)
    prepay2 = PrepaymentEvent(
        payment_date=date(2027, 2, 21),
        amount=Decimal("5000.00"),
        recurrence="annual",
        note="annual February lump sum",
    )
    term2 = MortgageTerm(
        term_number=2,
        start_date=start2,
        end_date=date(2029, 7, 21),
        term_years=3,
        rate_type="fixed",
        initial_annual_rate=Decimal("0.0389"),
        monthly_payment=Decimal("1863.49"),
        prepayments=[prepay2],
    )

    return Mortgage(
        original_principal=Decimal("420880.00"),
        start_date=date(2021, 5, 21),
        amortization_years=30,
        prepayment_limit_pct=Decimal("0.20"),
        lender="First National",
        payment_day=21,
        terms=[term1, term2],
    )


# ---------------------------------------------------------------------------
# 1. Basic round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:

    def test_save_returns_id(self, repo):
        m  = _make_mortgage()
        id = repo.save_mortgage(m)
        assert isinstance(id, int)
        assert id > 0

    def test_load_returns_mortgage(self, repo):
        id = repo.save_mortgage(_make_mortgage())
        m  = repo.load_mortgage(id)
        assert isinstance(m, Mortgage)
        assert m.id == id

    def test_not_found_raises(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.load_mortgage(9999)


# ---------------------------------------------------------------------------
# 2. Mortgage field fidelity
# ---------------------------------------------------------------------------

class TestMortgageFields:

    @pytest.fixture(autouse=True)
    def _setup(self, repo):
        self.repo = repo
        self.mid  = repo.save_mortgage(_make_mortgage())
        self.m    = repo.load_mortgage(self.mid)

    def test_original_principal(self):
        assert self.m.original_principal == Decimal("420880.00")
        assert isinstance(self.m.original_principal, Decimal)

    def test_start_date(self):
        assert self.m.start_date == date(2021, 5, 21)
        assert isinstance(self.m.start_date, date)

    def test_amortization_years(self):
        assert self.m.amortization_years == 30

    def test_prepayment_limit(self):
        assert self.m.prepayment_limit_pct == Decimal("0.20")

    def test_lender(self):
        assert self.m.lender == "First National"

    def test_payment_day(self):
        assert self.m.payment_day == 21

    def test_two_terms_loaded(self):
        assert len(self.m.terms) == 2


# ---------------------------------------------------------------------------
# 3. Term field fidelity
# ---------------------------------------------------------------------------

class TestTermFields:

    @pytest.fixture(autouse=True)
    def _setup(self, repo):
        self.repo = repo
        mid       = repo.save_mortgage(_make_mortgage())
        m         = repo.load_mortgage(mid)
        self.t1   = m.terms[0]
        self.t2   = m.terms[1]

    def test_term_numbers_ordered(self):
        assert self.t1.term_number == 1
        assert self.t2.term_number == 2

    def test_term1_rate_type(self):
        assert self.t1.rate_type == "variable"

    def test_term2_rate_type(self):
        assert self.t2.rate_type == "fixed"

    def test_term1_initial_rate_decimal(self):
        assert self.t1.initial_annual_rate == Decimal("0.0139")
        assert isinstance(self.t1.initial_annual_rate, Decimal)

    def test_term2_initial_rate_decimal(self):
        assert self.t2.initial_annual_rate == Decimal("0.0389")

    def test_term1_payment(self):
        assert self.t1.monthly_payment == Decimal("1430.43")

    def test_term1_dates(self):
        assert self.t1.start_date == date(2021, 5, 21)
        assert self.t1.end_date   == date(2026, 6, 21)
        assert isinstance(self.t1.start_date, date)


# ---------------------------------------------------------------------------
# 4. Rate change event fidelity
# ---------------------------------------------------------------------------

class TestRateChangeEvents:

    @pytest.fixture(autouse=True)
    def _setup(self, repo):
        mid     = repo.save_mortgage(_make_mortgage())
        m       = repo.load_mortgage(mid)
        self.t1 = m.terms[0]
        self.t2 = m.terms[1]

    def test_term1_has_one_rate_change(self):
        assert len(self.t1.rate_changes) == 1

    def test_term2_has_no_rate_changes(self):
        assert len(self.t2.rate_changes) == 0

    def test_rate_change_date(self):
        rc = self.t1.rate_changes[0]
        assert rc.effective_date == date(2022, 3, 21)
        assert isinstance(rc.effective_date, date)

    def test_rate_change_value_is_decimal(self):
        rc = self.t1.rate_changes[0]
        assert rc.new_annual_rate == Decimal("0.0164")
        assert isinstance(rc.new_annual_rate, Decimal)


# ---------------------------------------------------------------------------
# 5. Prepayment event fidelity
# ---------------------------------------------------------------------------

class TestPrepaymentEvents:

    @pytest.fixture(autouse=True)
    def _setup(self, repo):
        mid     = repo.save_mortgage(_make_mortgage())
        m       = repo.load_mortgage(mid)
        self.t1 = m.terms[0]
        self.t2 = m.terms[1]

    def test_term1_has_one_prepayment(self):
        assert len(self.t1.prepayments) == 1

    def test_term1_prepayment_amount(self):
        p = self.t1.prepayments[0]
        assert p.amount == Decimal("1000.00")
        assert isinstance(p.amount, Decimal)

    def test_term1_prepayment_recurrence(self):
        assert self.t1.prepayments[0].recurrence == "monthly"

    def test_term1_prepayment_note(self):
        assert self.t1.prepayments[0].note == "regular top-up"

    def test_term2_prepayment_recurrence(self):
        assert self.t2.prepayments[0].recurrence == "annual"

    def test_prepayment_end_date_none(self):
        # Neither prepayment has an end_date set
        assert self.t1.prepayments[0].end_date is None


# ---------------------------------------------------------------------------
# 6. list_mortgages
# ---------------------------------------------------------------------------

class TestListMortgages:

    def test_empty_initially(self, repo):
        assert repo.list_mortgages() == []

    def test_returns_all(self, repo):
        repo.save_mortgage(_make_mortgage())
        repo.save_mortgage(_make_mortgage())
        assert len(repo.list_mortgages()) == 2

    def test_list_does_not_load_terms(self, repo):
        repo.save_mortgage(_make_mortgage())
        listings = repo.list_mortgages()
        # list_mortgages returns header info only; terms are empty
        assert listings[0].terms == []


# ---------------------------------------------------------------------------
# 7. Update and delete
# ---------------------------------------------------------------------------

class TestUpdateDelete:

    def test_update_mortgage_lender(self, repo):
        id = repo.save_mortgage(_make_mortgage())
        m  = repo.load_mortgage(id)
        m.lender = "TD Bank"
        repo.update_mortgage(m)
        reloaded = repo.load_mortgage(id)
        assert reloaded.lender == "TD Bank"

    def test_update_without_id_raises(self, repo):
        m = _make_mortgage()
        with pytest.raises(ValueError, match="without an id"):
            repo.update_mortgage(m)

    def test_delete_mortgage(self, repo):
        id = repo.save_mortgage(_make_mortgage())
        repo.delete_mortgage(id)
        with pytest.raises(ValueError):
            repo.load_mortgage(id)

    def test_delete_cascades_to_terms(self, repo):
        import sqlalchemy as sa
        from mortgage.storage.database import mortgage_terms
        id = repo.save_mortgage(_make_mortgage())
        repo.delete_mortgage(id)
        with repo._engine.connect() as conn:
            count = conn.execute(
                sa.select(sa.func.count()).select_from(mortgage_terms)
                .where(mortgage_terms.c.mortgage_id == id)
            ).scalar()
        assert count == 0

    def test_add_rate_change(self, repo):
        id   = repo.save_mortgage(_make_mortgage())
        m    = repo.load_mortgage(id)
        t1   = m.terms[0]
        orig = len(t1.rate_changes)
        new_event = RateChangeEvent(
            effective_date=date(2023, 7, 21),
            new_annual_rate=Decimal("0.0589"),
        )
        repo.add_rate_change(t1.id, new_event)
        reloaded = repo.load_rate_changes(t1.id)
        assert len(reloaded) == orig + 1

    def test_add_prepayment(self, repo):
        id   = repo.save_mortgage(_make_mortgage())
        m    = repo.load_mortgage(id)
        t2   = m.terms[1]
        orig = len(t2.prepayments)
        new_event = PrepaymentEvent(
            payment_date=date(2028, 2, 21),
            amount=Decimal("6500.00"),
            recurrence="once",
            note="bonus lump sum",
        )
        repo.add_prepayment(t2.id, new_event)
        reloaded = repo.load_prepayments(t2.id)
        assert len(reloaded) == orig + 1
        assert reloaded[-1].amount == Decimal("6500.00")


# ---------------------------------------------------------------------------
# 8. Engine integration — loaded mortgage runs the amortization engine
# ---------------------------------------------------------------------------

class TestEngineIntegration:

    def test_loaded_mortgage_generates_schedule(self, repo):
        """
        The ultimate integration test: save a mortgage, load it back,
        run it through the amortization engine. If any field was corrupted
        during storage (Decimal precision loss, date type mismatch, etc.),
        this would fail or produce wrong numbers.
        """
        id  = repo.save_mortgage(_make_mortgage())
        m   = repo.load_mortgage(id)
        sch = generate_schedule(m)

        assert len(sch.payments) > 0
        assert sch.lifetime_summary.total_interest > Decimal("0")
        # Balance must be non-negative throughout
        for p in sch.payments:
            assert p.balance_closing >= Decimal("0.00")

    def test_decimal_precision_not_lost(self, repo):
        """
        If we stored 0.0389 as a float (0.038899999...) and reloaded it,
        interest calculations would drift. Verify the rate is exact.
        """
        id  = repo.save_mortgage(_make_mortgage())
        m   = repo.load_mortgage(id)
        t2  = m.terms[1]
        assert str(t2.initial_annual_rate) == "0.0389"
