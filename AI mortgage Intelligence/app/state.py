"""
app/state.py
=============
Streamlit session-state helpers.

Why session state?
------------------
Streamlit reruns the entire script on every user interaction. Without session
state, every rerun would re-query the database and regenerate the amortization
schedule (which is expensive). We cache these in st.session_state so they
survive reruns within the same user session.

Three things we cache
----------------------
mortgage_id  : int   -- the active mortgage's database ID
mortgage     : Mortgage -- the full Mortgage object (with terms + events)
schedule     : AmortizationSchedule -- the computed schedule

When to invalidate
------------------
Call invalidate() after any write to the database (adding a term, saving a
prepayment, updating a rate change, etc.). The next call to get_schedule()
will reload the mortgage and regenerate the schedule.
"""

from __future__ import annotations

import streamlit as st

from mortgage.engine.amortization import generate_schedule
from mortgage.models.entities import AmortizationSchedule, Mortgage
from mortgage.storage.repository import MortgageRepository


# ---------------------------------------------------------------------------
# Repository  (one per session — cheap to create)
# ---------------------------------------------------------------------------

def get_repo() -> MortgageRepository:
    """Return a MortgageRepository using the default database file."""
    if "repo" not in st.session_state:
        st.session_state["repo"] = MortgageRepository()
    return st.session_state["repo"]


# ---------------------------------------------------------------------------
# Active mortgage
# ---------------------------------------------------------------------------

def get_active_mortgage() -> Mortgage | None:
    """
    Return the currently loaded Mortgage, or None if no mortgage exists.

    On first call, tries to load the first mortgage from the database.
    Subsequent calls return the cached object (until invalidated).
    """
    if "mortgage" in st.session_state:
        return st.session_state["mortgage"]

    repo     = get_repo()
    listings = repo.list_mortgages()
    if not listings:
        return None

    mortgage_id = st.session_state.get("mortgage_id", listings[0].id)
    try:
        m = repo.load_mortgage(mortgage_id)
    except ValueError:
        m = repo.load_mortgage(listings[0].id)

    st.session_state["mortgage_id"] = m.id
    st.session_state["mortgage"]    = m
    return m


def set_active_mortgage_id(mortgage_id: int) -> None:
    """Switch to a different mortgage. Clears all cached data."""
    st.session_state["mortgage_id"] = mortgage_id
    invalidate()


def has_mortgage() -> bool:
    """True if at least one mortgage exists in the database."""
    return get_active_mortgage() is not None


# ---------------------------------------------------------------------------
# Schedule cache
# ---------------------------------------------------------------------------

def get_schedule() -> AmortizationSchedule | None:
    """
    Return the cached AmortizationSchedule, generating it if needed.
    Returns None if no mortgage is configured yet.
    """
    if "schedule" not in st.session_state:
        m = get_active_mortgage()
        if m is None or not m.terms:
            return None
        st.session_state["schedule"] = generate_schedule(m)
    return st.session_state.get("schedule")


def invalidate() -> None:
    """
    Discard the cached mortgage and schedule so they are reloaded from
    the database on the next call. Call this after any write operation.
    """
    st.session_state.pop("mortgage", None)
    st.session_state.pop("schedule", None)
