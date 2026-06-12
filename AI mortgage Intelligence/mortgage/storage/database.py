"""
mortgage/storage/database.py
==============================
Database connection management and table schema definitions.

We use SQLAlchemy Core (not the ORM).

Storage design decisions
-------------------------
* Decimal stored as TEXT — SQLite REAL is a 64-bit float; "0.0389" as a float
  becomes 0.038899999999999997. TEXT preserves the exact decimal string.
* Dates stored as TEXT (ISO 8601: YYYY-MM-DD) — SQLite has no native DATE type.
  ISO 8601 strings sort lexicographically in date order, so ORDER BY still works.
* MonthlyPayment is NOT stored — it is computed by the engine on demand.
  Only inputs (mortgage, terms, events) are persisted.

Database file location
-----------------------
Default: data/mortgage.db relative to the project root.
Override via DATABASE_URL env variable or by passing url to get_engine().
"""

from __future__ import annotations

import os
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import MetaData

# MetaData is a container for Table objects — holds all table definitions.
metadata = MetaData()

# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

mortgages = sa.Table(
    "mortgages",
    metadata,
    sa.Column("id",                   sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("original_principal",   sa.Text,    nullable=False),   # Decimal as string
    sa.Column("start_date",           sa.Text,    nullable=False),   # YYYY-MM-DD
    sa.Column("amortization_years",   sa.Integer, nullable=False),
    sa.Column("prepayment_limit_pct", sa.Text,    nullable=False, default="0.20"),
    sa.Column("lender",               sa.Text,    nullable=False, default=""),
    sa.Column("payment_day",          sa.Integer, nullable=False, default=1),
    sa.Column("created_at",           sa.Text,    nullable=False),
    sa.Column("updated_at",           sa.Text,    nullable=False),
)

mortgage_terms = sa.Table(
    "mortgage_terms",
    metadata,
    sa.Column("id",                  sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("mortgage_id",         sa.Integer, sa.ForeignKey("mortgages.id", ondelete="CASCADE"), nullable=False),
    sa.Column("term_number",         sa.Integer, nullable=False),
    sa.Column("start_date",          sa.Text,    nullable=False),
    sa.Column("end_date",            sa.Text,    nullable=False),
    sa.Column("term_years",          sa.Integer, nullable=False),
    sa.Column("rate_type",           sa.Text,    nullable=False),   # "variable" | "fixed"
    sa.Column("initial_annual_rate", sa.Text,    nullable=False),   # Decimal as string
    sa.Column("monthly_payment",     sa.Text,    nullable=False),   # Decimal as string
    sa.Column("first_payment_date",  sa.Text,    nullable=True),    # YYYY-MM-DD or NULL
    sa.Column("created_at",          sa.Text,    nullable=False),
)

rate_change_events = sa.Table(
    "rate_change_events",
    metadata,
    sa.Column("id",              sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("term_id",         sa.Integer, sa.ForeignKey("mortgage_terms.id", ondelete="CASCADE"), nullable=False),
    sa.Column("effective_date",  sa.Text,    nullable=False),
    sa.Column("new_annual_rate", sa.Text,    nullable=False),
)

prepayment_events = sa.Table(
    "prepayment_events",
    metadata,
    sa.Column("id",           sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("term_id",      sa.Integer, sa.ForeignKey("mortgage_terms.id", ondelete="CASCADE"), nullable=False),
    sa.Column("payment_date", sa.Text,    nullable=False),
    sa.Column("amount",       sa.Text,    nullable=False),
    sa.Column("recurrence",   sa.Text,    nullable=False, default="once"),
    sa.Column("end_date",     sa.Text,    nullable=True),
    sa.Column("note",         sa.Text,    nullable=False, default=""),
)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

_engine: sa.Engine | None = None


def get_engine(url: str | None = None) -> sa.Engine:
    """
    Return the SQLAlchemy engine, creating it on first call.

    Parameters
    ----------
    url : SQLAlchemy database URL.
          None  → use DATABASE_URL env var, else data/mortgage.db.
          "sqlite:///:memory:"  → in-memory DB (tests).
    """
    global _engine

    if _engine is not None and url is None:
        return _engine

    if url is None:
        url = os.environ.get("DATABASE_URL")

    if url is None:
        project_root = Path(__file__).parent.parent.parent
        db_path      = project_root / "data" / "mortgage.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"

    engine = sa.create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # SQLite disables foreign key enforcement by default.
    # This listener fires PRAGMA foreign_keys = ON on every new connection,
    # enabling ON DELETE CASCADE to work correctly.
    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    # Create tables if they do not yet exist.
    metadata.create_all(engine)

    # Run incremental migrations for columns added after initial release.
    _migrate(engine)

    if "memory" not in url:
        _engine = engine

    return engine


def _migrate(engine: sa.Engine) -> None:
    """
    Apply schema migrations that cannot be expressed via create_all()
    (which only creates missing tables, not missing columns).

    Each migration is guarded by a column-existence check so it is safe
    to run on every startup — it is a no-op after the first application.
    """
    with engine.begin() as conn:
        # ── Migration 1: add first_payment_date to mortgage_terms ────────────
        existing = {
            row[1]  # column name is index 1 in PRAGMA table_info rows
            for row in conn.execute(
                sa.text("PRAGMA table_info(mortgage_terms)")
            ).fetchall()
        }
        if "first_payment_date" not in existing:
            conn.execute(
                sa.text(
                    "ALTER TABLE mortgage_terms "
                    "ADD COLUMN first_payment_date TEXT"
                )
            )


def reset_engine() -> None:
    """Clear the cached engine. Call between tests for a fresh in-memory DB."""
    global _engine
    _engine = None
