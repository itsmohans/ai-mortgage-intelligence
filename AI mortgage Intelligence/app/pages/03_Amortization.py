"""
app/pages/03_Amortization.py
==============================
Full month-by-month amortization schedule.

Features
--------
* Colour-coded rows: historical (green tint) vs projected (blue tint).
* Filterable by term or year.
* Exportable to CSV.
* Key columns: period, date, opening balance, payment, prepayment,
  interest, principal repaid, closing balance, annual rate.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from app.state import get_schedule, has_mortgage

st.set_page_config(
    page_title="Amortization | Mortgage Intelligence",
    page_icon="📋",
    layout="wide",
)
st.title("📋 Amortization Schedule")

if not has_mortgage():
    st.info("No mortgage configured. Go to **Setup** to get started.")
    st.stop()

schedule = get_schedule()
if schedule is None:
    st.warning("No terms configured yet. Add terms in **Setup**.")
    st.stop()

payments = schedule.payments

# ─────────────────────────────────────────────────────────────────────────────
# Filters
# ─────────────────────────────────────────────────────────────────────────────
col_f1, col_f2, col_f3 = st.columns([2, 2, 3])

available_terms = sorted({p.term_number for p in payments})
selected_terms  = col_f1.multiselect(
    "Filter by Term",
    options=available_terms,
    default=available_terms,
    format_func=lambda t: f"Term {t}",
)

available_years = sorted({p.payment_date.year for p in payments})
selected_years  = col_f2.multiselect(
    "Filter by Year",
    options=available_years,
    default=available_years,
)

show_historical = col_f3.checkbox("Show historical payments",   value=True)
show_projected  = col_f3.checkbox("Show projected payments",    value=True)

# Apply filters
filtered = [
    p for p in payments
    if p.term_number in selected_terms
    and p.payment_date.year in selected_years
    and (p.is_historical and show_historical or not p.is_historical and show_projected)
]

st.caption(f"Showing **{len(filtered)}** of **{len(payments)}** payments")

# ─────────────────────────────────────────────────────────────────────────────
# Build DataFrame
# ─────────────────────────────────────────────────────────────────────────────
rows = []
for p in filtered:
    rows.append({
        "#":          p.period_number,
        "Term":       p.term_number,
        "Date":       p.payment_date,
        "Status":     (
            "Interest Adj."  if getattr(p, "is_interest_adjustment", False)
            else "Capitalized" if getattr(p, "is_capitalization", False)
            else "Actual"      if p.is_historical
            else "Projected"
        ),
        "Bal. Open":  float(p.balance_opening),
        "Payment":    float(p.regular_payment),
        "Prepayment": float(p.prepayment),
        "Interest":   float(p.interest_amount),
        "Principal":  float(p.principal_repaid),
        "Bal. Close": float(p.balance_closing),
        "Rate %":     round(float(p.annual_rate) * 100, 4),
        "Days":       p.days_in_period,
    })

df = pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────────────────────
# Style the DataFrame
# ─────────────────────────────────────────────────────────────────────────────
HIST_BG  = "#EEF5EE"   # soft green — historical (actual)
PROJ_BG  = "#EEF2F8"   # soft blue — projected
ADJ_BG   = "#FFF8E7"   # soft amber — interest adjustment (balance unchanged)
CAP_BG   = "#FEF0E6"   # soft orange — capitalised interest (balance grows)
NEG_FG   = "#C0392B"   # red for negative principal (balance growing)

def _style(row):
    if row["Status"] == "Interest Adj.":
        bg = ADJ_BG
    elif row["Status"] == "Capitalized":
        bg = CAP_BG
    elif row["Status"] == "Actual":
        bg = HIST_BG
    else:
        bg = PROJ_BG
    # Explicitly set text colour so it's readable in both light and dark mode
    base = f"background-color: {bg}; color: #111111"
    styles = [base] * len(row)
    # Highlight negative principal in red
    principal_idx = list(df.columns).index("Principal") if "Principal" in df.columns else -1
    if principal_idx >= 0 and row["Principal"] < 0:
        styles[principal_idx] = f"background-color: {bg}; color: {NEG_FG}; font-weight: bold"
    return styles

styler = (
    df.style
    .apply(_style, axis=1)
    .format({
        "Bal. Open":  "${:,.2f}",
        "Payment":    "${:,.2f}",
        "Prepayment": "${:,.2f}",
        "Interest":   "${:,.2f}",
        "Principal":  "${:,.2f}",
        "Bal. Close": "${:,.2f}",
        "Rate %":     "{:.4f}%",
        "Date":       lambda d: d.strftime("%Y-%m-%d"),
    })
)

st.dataframe(styler, use_container_width=True, hide_index=True, height=520)

# ─────────────────────────────────────────────────────────────────────────────
# Summary strip below the table
# ─────────────────────────────────────────────────────────────────────────────
if filtered:
    total_interest  = sum(p.interest_amount  for p in filtered)
    total_principal = sum(max(p.principal_repaid, Decimal("0")) for p in filtered)
    total_prepay    = sum(p.prepayment        for p in filtered)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Interest (filtered)",   f"${float(total_interest):,.2f}")
    c2.metric("Principal (filtered)",  f"${float(total_principal):,.2f}")
    c3.metric("Prepayments (filtered)",f"${float(total_prepay):,.2f}")
    c4.metric("Payments shown",        len(filtered))

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────────────────────────────────────
csv = df.to_csv(index=False)
st.download_button(
    label="⬇️  Download as CSV",
    data=csv,
    file_name="amortization_schedule.csv",
    mime="text/csv",
    use_container_width=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# Legend
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("Legend"):
    st.markdown(f"""
- 🟡 **Amber rows** — Interest adjustment period (partial month at disbursement). Balance unchanged — interest collected separately at closing.
- 🟠 **Orange rows** — Capitalised interest period (no payment collected; interest added to balance).
- 🟢 **Green rows** — Actual historical payments (date < today)
- 🔵 **Blue rows** — Projected future payments
- 🔴 **Red Principal** — Month where interest exceeded the payment (balance was growing)
    """)
