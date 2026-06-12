"""
mortgage/storage/repository.py
================================
The Repository — the single place in the application that reads and writes
the database. Nothing else in the codebase touches SQL directly.

Repository pattern
------------------
A repository is an abstraction layer between your domain objects (dataclasses)
and the storage mechanism (SQLite). It exposes simple, intention-revealing
methods:

    repo.save_mortgage(mortgage)
    repo.load_mortgage(id)
    repo.list_mortgages()
    ...

The rest of the application (engine, UI, AI) never imports SQLAlchemy.
They only import from this module. This means you can swap SQLite for
PostgreSQL later by changing only this file.

Serialisation conventions
--------------------------
* Decimal  → str  when writing,  Decimal(str) when reading
* date     → str  when writing,  date.fromisoformat() when reading
* None     → None (SQLite NULL)

All conversion happens in the private _to_* and _from_* helpers below.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import sqlalchemy as sa

from mortgage.models.entities import (
    Mortgage,
    MortgageTerm,
    PrepaymentEvent,
    RateChangeEvent,
)
from mortgage.storage.database import (
    get_engine,
    mortgage_terms,
    mortgages,
    prepayment_events,
    rate_change_events,
)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(value: str | None) -> Optional[Decimal]:
    return Decimal(value) if value is not None else None


def _dt(value: str | None) -> Optional[date]:
    return date.fromisoformat(value) if value is not None else None


# ─────────────────────────────────────────────────────────────────────────────
# Public repository class
# ─────────────────────────────────────────────────────────────────────────────

class MortgageRepository:
    """
    All database operations for the mortgage application.

    Usage
    -----
    repo = MortgageRepository()                        # uses default DB
    repo = MortgageRepository("sqlite:///:memory:")    # in-memory (tests)

    mortgage_id = repo.save_mortgage(mortgage)
    mortgage    = repo.load_mortgage(mortgage_id)
    all_mortgages = repo.list_mortgages()
    """

    def __init__(self, db_url: str | None = None):
        self._engine = get_engine(db_url)

    # ── Mortgage ─────────────────────────────────────────────────────────────

    def save_mortgage(self, mortgage: Mortgage) -> int:
        """
        Insert a new Mortgage and all its Terms, RateChangeEvents,
        and PrepaymentEvents in a single transaction.

        Returns the auto-assigned mortgage ID.
        Any existing mortgage.id is ignored — use update_mortgage() to modify.
        """
        now = _now()
        with self._engine.begin() as conn:
            # 1. Insert mortgage row
            result = conn.execute(
                mortgages.insert().values(
                    original_principal   = str(mortgage.original_principal),
                    start_date           = mortgage.start_date.isoformat(),
                    amortization_years   = mortgage.amortization_years,
                    prepayment_limit_pct = str(mortgage.prepayment_limit_pct),
                    lender               = mortgage.lender,
                    payment_day          = mortgage.payment_day,
                    created_at           = now,
                    updated_at           = now,
                )
            )
            mortgage_id = result.inserted_primary_key[0]

            # 2. Insert each term and its events
            for term in mortgage.terms:
                term_id = self._insert_term(conn, mortgage_id, term)
                self._insert_rate_changes(conn, term_id, term.rate_changes)
                self._insert_prepayments(conn, term_id, term.prepayments)

        return mortgage_id

    def load_mortgage(self, mortgage_id: int) -> Mortgage:
        """
        Load a complete Mortgage (with all terms and events) by ID.
        Raises ValueError if not found.
        """
        with self._engine.connect() as conn:
            # 1. Load mortgage row
            row = conn.execute(
                mortgages.select().where(mortgages.c.id == mortgage_id)
            ).one_or_none()

            if row is None:
                raise ValueError(f"Mortgage {mortgage_id} not found.")

            m = Mortgage(
                id                   = row.id,
                original_principal   = Decimal(row.original_principal),
                start_date           = date.fromisoformat(row.start_date),
                amortization_years   = row.amortization_years,
                prepayment_limit_pct = Decimal(row.prepayment_limit_pct),
                lender               = row.lender or "",
                payment_day          = row.payment_day,
            )

            # 2. Load terms
            m.terms = self._load_terms(conn, mortgage_id)

        return m

    def list_mortgages(self) -> list[Mortgage]:
        """
        Return all mortgages (header info only — no terms loaded).
        Use load_mortgage(id) to get a mortgage with full detail.
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                mortgages.select().order_by(mortgages.c.id)
            ).fetchall()

        return [
            Mortgage(
                id                   = row.id,
                original_principal   = Decimal(row.original_principal),
                start_date           = date.fromisoformat(row.start_date),
                amortization_years   = row.amortization_years,
                prepayment_limit_pct = Decimal(row.prepayment_limit_pct),
                lender               = row.lender or "",
                payment_day          = row.payment_day,
            )
            for row in rows
        ]

    def update_mortgage(self, mortgage: Mortgage) -> None:
        """
        Update the scalar fields of a Mortgage (principal, dates, etc.).
        Does NOT touch terms or events — use add_term() / update_term() for those.
        Raises ValueError if mortgage.id is None or not found.
        """
        if mortgage.id is None:
            raise ValueError("Cannot update a Mortgage without an id.")

        with self._engine.begin() as conn:
            result = conn.execute(
                mortgages.update()
                .where(mortgages.c.id == mortgage.id)
                .values(
                    original_principal   = str(mortgage.original_principal),
                    start_date           = mortgage.start_date.isoformat(),
                    amortization_years   = mortgage.amortization_years,
                    prepayment_limit_pct = str(mortgage.prepayment_limit_pct),
                    lender               = mortgage.lender,
                    payment_day          = mortgage.payment_day,
                    updated_at           = _now(),
                )
            )
        if result.rowcount == 0:
            raise ValueError(f"Mortgage {mortgage.id} not found.")

    def delete_mortgage(self, mortgage_id: int) -> None:
        """
        Delete a mortgage and all its terms/events (CASCADE).
        """
        with self._engine.begin() as conn:
            conn.execute(
                mortgages.delete().where(mortgages.c.id == mortgage_id)
            )

    # ── Terms ─────────────────────────────────────────────────────────────────

    def add_term(self, mortgage_id: int, term: MortgageTerm) -> int:
        """
        Add a new MortgageTerm to an existing mortgage.
        Also inserts its rate changes and prepayments.
        Returns the new term ID.
        """
        with self._engine.begin() as conn:
            term_id = self._insert_term(conn, mortgage_id, term)
            self._insert_rate_changes(conn, term_id, term.rate_changes)
            self._insert_prepayments(conn, term_id, term.prepayments)
        return term_id

    def update_term(self, term: MortgageTerm) -> None:
        """
        Update scalar fields on an existing MortgageTerm.
        Does NOT touch its rate changes or prepayments.
        """
        if term.id is None:
            raise ValueError("Cannot update a MortgageTerm without an id.")

        with self._engine.begin() as conn:
            conn.execute(
                mortgage_terms.update()
                .where(mortgage_terms.c.id == term.id)
                .values(
                    term_number         = term.term_number,
                    start_date          = term.start_date.isoformat(),
                    end_date            = term.end_date.isoformat(),
                    term_years          = term.term_years,
                    rate_type           = term.rate_type,
                    initial_annual_rate = str(term.initial_annual_rate),
                    monthly_payment     = str(term.monthly_payment),
                    first_payment_date  = term.first_payment_date.isoformat() if term.first_payment_date else None,
                )
            )

    def delete_term(self, term_id: int) -> None:
        """Delete a term and all its events (CASCADE)."""
        with self._engine.begin() as conn:
            conn.execute(
                mortgage_terms.delete().where(mortgage_terms.c.id == term_id)
            )

    # ── Rate change events ────────────────────────────────────────────────────

    def add_rate_change(self, term_id: int, event: RateChangeEvent) -> int:
        """Add a single RateChangeEvent to a term. Returns the new event ID."""
        with self._engine.begin() as conn:
            result = conn.execute(
                rate_change_events.insert().values(
                    term_id         = term_id,
                    effective_date  = event.effective_date.isoformat(),
                    new_annual_rate = str(event.new_annual_rate),
                )
            )
        return result.inserted_primary_key[0]

    def delete_rate_change(self, event_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                rate_change_events.delete()
                .where(rate_change_events.c.id == event_id)
            )

    def load_rate_changes(self, term_id: int) -> list[RateChangeEvent]:
        """Load all rate change events for a term, sorted by effective date."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                rate_change_events.select()
                .where(rate_change_events.c.term_id == term_id)
                .order_by(rate_change_events.c.effective_date)
            ).fetchall()
        return [
            RateChangeEvent(
                id              = row.id,
                term_id         = row.term_id,
                effective_date  = date.fromisoformat(row.effective_date),
                new_annual_rate = Decimal(row.new_annual_rate),
            )
            for row in rows
        ]

    # ── Prepayment events ─────────────────────────────────────────────────────

    def add_prepayment(self, term_id: int, event: PrepaymentEvent) -> int:
        """Add a single PrepaymentEvent to a term. Returns the new event ID."""
        with self._engine.begin() as conn:
            result = conn.execute(
                prepayment_events.insert().values(
                    term_id      = term_id,
                    payment_date = event.payment_date.isoformat(),
                    amount       = str(event.amount),
                    recurrence   = event.recurrence,
                    end_date     = event.end_date.isoformat() if event.end_date else None,
                    note         = event.note or "",
                )
            )
        return result.inserted_primary_key[0]

    def delete_prepayment(self, event_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                prepayment_events.delete()
                .where(prepayment_events.c.id == event_id)
            )

    def load_prepayments(self, term_id: int) -> list[PrepaymentEvent]:
        """Load all prepayment events for a term, sorted by payment date."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                prepayment_events.select()
                .where(prepayment_events.c.term_id == term_id)
                .order_by(prepayment_events.c.payment_date)
            ).fetchall()
        return [
            PrepaymentEvent(
                id           = row.id,
                term_id      = row.term_id,
                payment_date = date.fromisoformat(row.payment_date),
                amount       = Decimal(row.amount),
                recurrence   = row.recurrence,
                end_date     = date.fromisoformat(row.end_date) if row.end_date else None,
                note         = row.note or "",
            )
            for row in rows
        ]

    # ── Private helpers ───────────────────────────────────────────────────────

    def _insert_term(
        self, conn: sa.Connection, mortgage_id: int, term: MortgageTerm
    ) -> int:
        result = conn.execute(
            mortgage_terms.insert().values(
                mortgage_id         = mortgage_id,
                term_number         = term.term_number,
                start_date          = term.start_date.isoformat(),
                end_date            = term.end_date.isoformat(),
                term_years          = term.term_years,
                rate_type           = term.rate_type,
                initial_annual_rate = str(term.initial_annual_rate),
                monthly_payment     = str(term.monthly_payment),
                first_payment_date  = term.first_payment_date.isoformat() if term.first_payment_date else None,
                created_at          = _now(),
            )
        )
        return result.inserted_primary_key[0]

    def _insert_rate_changes(
        self, conn: sa.Connection, term_id: int, events: list[RateChangeEvent]
    ) -> None:
        if not events:
            return
        conn.execute(
            rate_change_events.insert(),
            [
                {
                    "term_id":         term_id,
                    "effective_date":  e.effective_date.isoformat(),
                    "new_annual_rate": str(e.new_annual_rate),
                }
                for e in events
            ],
        )

    def _insert_prepayments(
        self, conn: sa.Connection, term_id: int, events: list[PrepaymentEvent]
    ) -> None:
        if not events:
            return
        conn.execute(
            prepayment_events.insert(),
            [
                {
                    "term_id":      term_id,
                    "payment_date": e.payment_date.isoformat(),
                    "amount":       str(e.amount),
                    "recurrence":   e.recurrence,
                    "end_date":     e.end_date.isoformat() if e.end_date else None,
                    "note":         e.note or "",
                }
                for e in events
            ],
        )

    def _load_terms(self, conn: sa.Connection, mortgage_id: int) -> list[MortgageTerm]:
        """Load all terms for a mortgage, with their events, ordered by term_number."""
        rows = conn.execute(
            mortgage_terms.select()
            .where(mortgage_terms.c.mortgage_id == mortgage_id)
            .order_by(mortgage_terms.c.term_number)
        ).fetchall()

        terms = []
        for row in rows:
            # Load events for this term
            rate_rows = conn.execute(
                rate_change_events.select()
                .where(rate_change_events.c.term_id == row.id)
                .order_by(rate_change_events.c.effective_date)
            ).fetchall()

            prep_rows = conn.execute(
                prepayment_events.select()
                .where(prepayment_events.c.term_id == row.id)
                .order_by(prepayment_events.c.payment_date)
            ).fetchall()

            terms.append(MortgageTerm(
                id                  = row.id,
                mortgage_id         = row.mortgage_id,
                term_number         = row.term_number,
                start_date          = date.fromisoformat(row.start_date),
                end_date            = date.fromisoformat(row.end_date),
                term_years          = row.term_years,
                rate_type           = row.rate_type,
                initial_annual_rate = Decimal(row.initial_annual_rate),
                monthly_payment     = Decimal(row.monthly_payment),
                first_payment_date  = date.fromisoformat(row.first_payment_date) if getattr(row, "first_payment_date", None) else None,
                rate_changes=[
                    RateChangeEvent(
                        id              = r.id,
                        term_id         = r.term_id,
                        effective_date  = date.fromisoformat(r.effective_date),
                        new_annual_rate = Decimal(r.new_annual_rate),
                    )
                    for r in rate_rows
                ],
                prepayments=[
                    PrepaymentEvent(
                        id           = p.id,
                        term_id      = p.term_id,
                        payment_date = date.fromisoformat(p.payment_date),
                        amount       = Decimal(p.amount),
                        recurrence   = p.recurrence,
                        end_date     = date.fromisoformat(p.end_date) if p.end_date else None,
                        note         = p.note or "",
                    )
                    for p in prep_rows
                ],
            ))

        return terms
