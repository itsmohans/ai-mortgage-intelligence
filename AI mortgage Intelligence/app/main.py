"""
app/main.py  (Streamlit entry point)
=====================================
Run with:  python -m streamlit run app/main.py
"""

import streamlit as st
from decimal import Decimal

from app.state import get_schedule, has_mortgage
from mortgage.engine.amortization import true_payoff

st.set_page_config(
    page_title="Mortgage Intelligence",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏠 AI Mortgage Decision Intelligence")
st.caption("Your personal mortgage strategy assistant")

if not has_mortgage():
    st.info("No mortgage configured yet. Use **Setup** in the sidebar to get started.")
    st.stop()

schedule = get_schedule()
if schedule is None:
    st.warning("Mortgage found but no terms configured yet. Add a term in **Setup**.")
    st.stop()

ls = schedule.lifetime_summary
m  = schedule.mortgage
payoff_date, _ = true_payoff(schedule)

# Current balance = closing balance of most recent historical payment
today_balance = next(
    (p.balance_closing for p in reversed(schedule.payments) if p.is_historical),
    m.original_principal,
)
equity_built = m.original_principal - today_balance

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Original Principal",
    f"${float(m.original_principal):,.0f}",
)
col2.metric(
    "Outstanding Balance",
    f"${float(today_balance):,.0f}",
    delta=f"-${float(equity_built):,.0f} equity built",
    delta_color="inverse",
)
col3.metric(
    "Projected Payoff",
    payoff_date.strftime("%b %Y"),
)
col4.metric(
    "Lifetime Interest",
    f"${float(ls.total_interest):,.0f}",
    delta=f"{float(ls.net_interest_pct)*100:.1f}% of principal",
    delta_color="off",
)

st.divider()
st.markdown("""
**Navigate using the sidebar:**
- **Setup** — manage your mortgage details, terms, and prepayments
- **Dashboard** — charts and key metrics
- **Amortization** — full month-by-month schedule
""")
