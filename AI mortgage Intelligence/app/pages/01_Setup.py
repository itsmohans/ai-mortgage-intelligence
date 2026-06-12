"""
app/pages/01_Setup.py
======================
Mortgage Setup — enter and edit all mortgage data.

Four tabs:
  1. Mortgage   — principal, start date, amortization period, lender, payment day
  2. Terms      — add/edit/delete renewal terms
  3. Rate Changes — add/delete rate change events for variable-rate terms
  4. Prepayments  — add/delete prepayment events for any term

Design notes
------------
* All saves go through the Repository, then call state.invalidate() so the
  schedule is regenerated on the next Dashboard/Amortization visit.
* st.form() batches inputs — the DB is only written when the user clicks Save.
* For new terms, the monthly payment is auto-calculated using calculate_monthly_payment()
  but the user can override it.
"""

from __future__ import annotations

from datetime import date

import streamlit as st
from dateutil.relativedelta import relativedelta

from app.state import get_active_mortgage, get_repo, has_mortgage, invalidate
from mortgage.engine.renewal import calculate_monthly_payment, remaining_amortization_months
from mortgage.models.entities import (
    Mortgage,
    MortgageTerm,
    PrepaymentEvent,
    RateChangeEvent,
)
from decimal import Decimal

st.set_page_config(page_title="Setup | Mortgage Intelligence", page_icon="⚙️", layout="wide")
st.title("⚙️ Mortgage Setup")

repo = get_repo()

# ─────────────────────────────────────────────────────────────────────────────
# Tab layout
# ─────────────────────────────────────────────────────────────────────────────
tab_mortgage, tab_terms, tab_rates, tab_prepay = st.tabs(
    ["🏠 Mortgage Details", "📅 Terms", "📈 Rate Changes", "💰 Prepayments"]
)


# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — Mortgage Details
# ═══════════════════════════════════════════════════════════════════════════
with tab_mortgage:
    existing = get_active_mortgage()
    mode     = "edit" if existing else "new"

    if mode == "new":
        st.info("No mortgage found. Fill in the details below to get started.")

    with st.form("form_mortgage_details"):
        st.subheader("Mortgage Details")

        col1, col2 = st.columns(2)
        with col1:
            principal = st.number_input(
                "Original Principal ($)",
                min_value=10_000.0, max_value=5_000_000.0,
                value=float(existing.original_principal) if existing else 500_000.0,
                step=1000.0, format="%.2f",
                help="The amount you borrowed on your mortgage start date.",
            )
            amort_years = st.number_input(
                "Amortization Period (years)",
                min_value=5, max_value=30,
                value=existing.amortization_years if existing else 30,
                step=1,
                help="Total repayment horizon (typically 25 or 30 years in Canada).",
            )
            prepay_pct = st.number_input(
                "Annual Prepayment Privilege (%)",
                min_value=0.0, max_value=30.0,
                value=float(existing.prepayment_limit_pct) * 100 if existing else 20.0,
                step=1.0, format="%.1f",
                help="Lender's annual prepayment limit as % of original principal.",
            )

        with col2:
            start_date = st.date_input(
                "Mortgage Start Date",
                value=existing.start_date if existing else date(2023, 1, 1),
                help="The disbursement date — the day you received the funds.",
            )
            lender = st.text_input(
                "Lender",
                value=existing.lender if existing else "",
                placeholder="e.g. First National, TD, CIBC",
            )
            payment_day = st.number_input(
                "Monthly Payment Day",
                min_value=1, max_value=28,
                value=existing.payment_day if existing else 1,
                step=1,
                help="Day of the month on which payments are due (1–28).",
            )

        submitted = st.form_submit_button(
            "💾 Save Mortgage Details", use_container_width=True, type="primary"
        )

    if submitted:
        m = Mortgage(
            id                   = existing.id if existing else None,
            original_principal   = Decimal(str(principal)),
            start_date           = start_date,
            amortization_years   = int(amort_years),
            prepayment_limit_pct = Decimal(str(round(prepay_pct / 100, 4))),
            lender               = lender,
            payment_day          = int(payment_day),
        )
        if mode == "new":
            mid = repo.save_mortgage(m)
            st.session_state["mortgage_id"] = mid
        else:
            repo.update_mortgage(m)
        invalidate()
        st.success("Mortgage details saved." if mode == "new" else "Mortgage details updated.")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — Terms
# ═══════════════════════════════════════════════════════════════════════════
with tab_terms:
    if not has_mortgage():
        st.warning("Save mortgage details first.")
        st.stop()

    m = get_active_mortgage()

    # Show existing terms
    if m.terms:
        st.subheader("Existing Terms")
        for term in sorted(m.terms, key=lambda t: t.term_number):
            with st.expander(
                f"Term {term.term_number} — {term.label}  |  "
                f"{float(term.initial_annual_rate)*100:.2f}%  |  "
                f"${float(term.monthly_payment):,.2f}/mo  |  "
                f"{'Variable' if term.rate_type == 'variable' else 'Fixed'}",
                expanded=False,
            ):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Start:** {term.start_date}")
                c2.write(f"**End:** {term.end_date}")
                c3.write(f"**Term:** {term.term_years} year(s)")
                c1.write(f"**Rate type:** {term.rate_type.capitalize()}")
                c2.write(f"**Initial rate:** {float(term.initial_annual_rate)*100:.4f}%")
                c3.write(f"**Payment:** ${float(term.monthly_payment):,.2f}")

                btn_col1, btn_col2 = st.columns(2)
                if btn_col1.button(f"✏️ Edit Term {term.term_number}", key=f"edit_term_{term.id}"):
                    st.session_state["editing_term_id"] = term.id
                if btn_col2.button(f"🗑️ Delete Term {term.term_number}", key=f"del_term_{term.id}"):
                    repo.delete_term(term.id)
                    st.session_state.pop("editing_term_id", None)
                    invalidate()
                    st.rerun()

    # ── Inline term edit form ─────────────────────────────────────────────────
    editing_term_id = st.session_state.get("editing_term_id")
    if editing_term_id is not None:
        term_to_edit = next((t for t in m.terms if t.id == editing_term_id), None)
        if term_to_edit:
            st.divider()
            st.subheader(f"✏️ Editing Term {term_to_edit.term_number} — {term_to_edit.label}")

            tid = editing_term_id
            _tinit_key = f"et_init_{tid}"
            if _tinit_key not in st.session_state:
                st.session_state[f"et_start_{tid}"]   = term_to_edit.start_date
                st.session_state[f"et_end_{tid}"]     = term_to_edit.end_date
                st.session_state[f"et_years_{tid}"]   = term_to_edit.term_years
                st.session_state[f"et_rtype_{tid}"]   = term_to_edit.rate_type
                st.session_state[f"et_rate_{tid}"]    = float(term_to_edit.initial_annual_rate) * 100
                st.session_state[f"et_pmt_{tid}"]     = float(term_to_edit.monthly_payment)
                st.session_state[f"et_override_{tid}"]= False
                _fpd = getattr(term_to_edit, "first_payment_date", None)
                st.session_state[f"et_has_fpd_{tid}"] = _fpd is not None
                st.session_state[f"et_fpd_{tid}"]     = _fpd or (term_to_edit.start_date + relativedelta(months=2)).replace(day=1)
                st.session_state[_tinit_key]          = True

            def _cleanup_term_keys(tid):
                for k in [f"et_start_{tid}", f"et_end_{tid}", f"et_years_{tid}", f"et_rtype_{tid}",
                          f"et_rate_{tid}", f"et_pmt_{tid}", f"et_override_{tid}",
                          f"et_has_fpd_{tid}", f"et_fpd_{tid}", f"et_init_{tid}"]:
                    st.session_state.pop(k, None)
                st.session_state.pop("editing_term_id", None)

            ec1, ec2 = st.columns(2)
            e_start = ec1.date_input("Term Start Date", key=f"et_start_{tid}")
            e_end   = ec2.date_input(
                "Term End Date",
                key=f"et_end_{tid}",
                help="Override if your lender's renewal date differs from start + term years.",
            )
            e_years = ec1.selectbox(
                "Term Length (years)", [1, 2, 3, 4, 5],
                index=[1, 2, 3, 4, 5].index(st.session_state[f"et_years_{tid}"]),
                key=f"et_years_{tid}",
            )
            e_rtype = ec2.selectbox(
                "Rate Type", ["fixed", "variable"],
                index=0 if st.session_state[f"et_rtype_{tid}"] == "fixed" else 1,
                key=f"et_rtype_{tid}",
            )
            e_rate_pct = ec1.number_input(
                "Annual Interest Rate (%)",
                min_value=0.01, max_value=20.0, step=0.01, format="%.4f",
                key=f"et_rate_{tid}",
            )

            remaining = remaining_amortization_months(m, e_start)
            auto_pmt = calculate_monthly_payment(
                principal=Decimal(str(m.original_principal)),
                annual_rate=Decimal(str(round(e_rate_pct / 100, 6))),
                remaining_amortization_months=remaining,
                compounding="monthly_simple",
            )
            st.info(f"Calculated payment for {remaining} remaining months: **${float(auto_pmt):,.2f} / month**")

            e_override = st.checkbox("Override calculated payment", key=f"et_override_{tid}")
            e_pmt = auto_pmt
            if e_override:
                e_pmt_val = st.number_input(
                    "Monthly Payment ($)", min_value=0.01,
                    value=st.session_state[f"et_pmt_{tid}"],
                    step=10.0, format="%.2f",
                    key=f"et_pmt_{tid}",
                )
                e_pmt = Decimal(str(round(e_pmt_val, 2)))

            e_has_fpd = st.checkbox(
                "Set first payment date (if lender deferred first payment by one extra month)",
                key=f"et_has_fpd_{tid}",
                help="In Canada, when a mortgage is disbursed mid-month, the first payment is "
                     "sometimes deferred to the month after next. Interest for the skipped month "
                     "is capitalised (added to balance). Check this box to set that date explicitly.",
            )
            e_fpd = None
            if e_has_fpd:
                e_fpd = st.date_input(
                    "First Regular Payment Date",
                    key=f"et_fpd_{tid}",
                    help="The date of the first actual monthly payment (e.g. 2021-07-01).",
                )

            tsave_col, tcancel_col = st.columns(2)
            do_term_save   = tsave_col.button("💾 Save Term", type="primary", use_container_width=True, key=f"et_save_{tid}")
            do_term_cancel = tcancel_col.button("Cancel", use_container_width=True, key=f"et_cancel_{tid}")

            if do_term_save:
                updated_term = MortgageTerm(
                    id                  = term_to_edit.id,
                    term_number         = term_to_edit.term_number,
                    start_date          = e_start,
                    end_date            = e_end,
                    term_years          = int(e_years),
                    rate_type           = e_rtype,
                    initial_annual_rate = Decimal(str(round(e_rate_pct / 100, 6))),
                    monthly_payment     = e_pmt,
                    first_payment_date  = e_fpd,
                )
                repo.update_term(updated_term)
                invalidate()
                _cleanup_term_keys(tid)
                st.success(f"Term {term_to_edit.term_number} updated.")
                st.rerun()

            if do_term_cancel:
                _cleanup_term_keys(tid)
                st.rerun()

    st.divider()
    st.subheader("Add New Term")

    next_term_num = max((t.term_number for t in m.terms), default=0) + 1
    prev_end = m.terms[-1].end_date if m.terms else m.start_date

    with st.form("form_add_term"):
        col1, col2 = st.columns(2)
        with col1:
            term_num = st.number_input("Term Number", value=next_term_num, min_value=1, step=1)
            term_start = st.date_input(
                "Term Start Date",
                value=prev_end + relativedelta(days=1) if m.terms else m.start_date,
            )
            rate_type = st.selectbox("Rate Type", ["fixed", "variable"])
        with col2:
            term_years = st.selectbox("Term Length (years)", [1, 2, 3, 4, 5], index=2)
            initial_rate_pct = st.number_input(
                "Annual Interest Rate (%)",
                min_value=0.1, max_value=20.0, value=3.89, step=0.01, format="%.4f",
            )
            override_payment = st.checkbox("Override calculated payment", value=False)

        # Default end date = start + term years, but user can override
        # (e.g. when disbursement date differs from first payment date)
        default_end = term_start + relativedelta(years=int(term_years))
        term_end = st.date_input(
            "Term End Date",
            value=default_end,
            help="Defaults to start + term length. Override if your lender's renewal date differs "
                 "(e.g. first payment was on the 1st but disbursement was mid-month).",
        )

        # Auto-calculate payment using rate/12 (matches most Canadian lender statements)
        remaining = remaining_amortization_months(m, term_start)
        auto_pmt  = calculate_monthly_payment(
            principal                    = Decimal(str(m.original_principal)),
            annual_rate                  = Decimal(str(round(initial_rate_pct / 100, 6))),
            remaining_amortization_months= remaining,
            compounding                  = "monthly_simple",
        )
        st.info(f"Calculated payment for {remaining} remaining months: **${float(auto_pmt):,.2f} / month**")

        manual_payment = 0.0
        if override_payment:
            manual_payment = st.number_input(
                "Monthly Payment ($)", min_value=0.01, value=float(auto_pmt), format="%.2f"
            )

        set_first_payment = st.checkbox(
            "Set first payment date (if lender deferred first payment by one extra month)",
            value=False,
            help="In Canada, when disbursed mid-month, the first payment is sometimes deferred "
                 "to the month after next. Interest for the skipped month capitalises into balance.",
        )
        first_payment_date_val = None
        if set_first_payment:
            first_payment_date_val = st.date_input(
                "First Regular Payment Date",
                value=(term_start + relativedelta(months=2)).replace(day=term_start.day),
                help="The date of the first actual monthly payment (e.g. 2021-07-01).",
            )

        add_term = st.form_submit_button("➕ Add Term", type="primary", use_container_width=True)

    if add_term:
        payment = Decimal(str(round(manual_payment, 2))) if override_payment else auto_pmt
        term = MortgageTerm(
            term_number         = int(term_num),
            start_date          = term_start,
            end_date            = term_end,
            term_years          = int(term_years),
            rate_type           = rate_type,
            initial_annual_rate = Decimal(str(round(initial_rate_pct / 100, 6))),
            monthly_payment     = payment,
            first_payment_date  = first_payment_date_val if set_first_payment else None,
        )
        repo.add_term(m.id, term)
        invalidate()
        st.success(f"Term {int(term_num)} added.")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — Rate Changes
# ═══════════════════════════════════════════════════════════════════════════
with tab_rates:
    if not has_mortgage():
        st.warning("Save mortgage details first.")
        st.stop()

    m = get_active_mortgage()
    if not m.terms:
        st.warning("Add at least one term before managing rate changes.")
        st.stop()

    var_terms = [t for t in m.terms if t.rate_type == "variable"]
    if not var_terms:
        st.info("Rate changes only apply to variable-rate terms. All your terms are fixed-rate.")
        st.stop()

    term_labels = {t.id: f"Term {t.term_number} ({t.label})" for t in var_terms}
    selected_term_id = st.selectbox(
        "Select Variable-Rate Term",
        options=list(term_labels.keys()),
        format_func=lambda x: term_labels[x],
    )
    selected_term = next(t for t in m.terms if t.id == selected_term_id)

    # Show existing rate changes
    if selected_term.rate_changes:
        st.subheader("Existing Rate Changes")
        for rc in sorted(selected_term.rate_changes, key=lambda r: r.effective_date):
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.write(f"📅 {rc.effective_date}")
            col2.write(f"**{float(rc.new_annual_rate)*100:.4f}%**")
            if col3.button("🗑️", key=f"del_rc_{rc.id}", help="Delete"):
                repo.delete_rate_change(rc.id)
                invalidate()
                st.rerun()
    else:
        st.info("No rate changes recorded for this term yet.")

    st.divider()
    st.subheader("Add Rate Change")

    with st.form("form_add_rate_change"):
        col1, col2 = st.columns(2)
        rc_date = col1.date_input(
            "Effective Date",
            value=selected_term.start_date + relativedelta(months=1),
            min_value=selected_term.start_date,
            max_value=selected_term.end_date,
        )
        new_rate_pct = col2.number_input(
            "New Annual Rate (%)", min_value=0.01, max_value=20.0, value=1.64,
            step=0.01, format="%.4f",
        )
        add_rc = st.form_submit_button("➕ Add Rate Change", type="primary", use_container_width=True)

    if add_rc:
        event = RateChangeEvent(
            effective_date  = rc_date,
            new_annual_rate = Decimal(str(round(new_rate_pct / 100, 6))),
        )
        repo.add_rate_change(selected_term_id, event)
        invalidate()
        st.success(f"Rate change added: {float(new_rate_pct):.4f}% from {rc_date}.")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# TAB 4 — Prepayments
# ═══════════════════════════════════════════════════════════════════════════
with tab_prepay:
    if not has_mortgage():
        st.warning("Save mortgage details first.")
        st.stop()

    m = get_active_mortgage()
    if not m.terms:
        st.warning("Add at least one term before managing prepayments.")
        st.stop()

    term_labels_all = {t.id: f"Term {t.term_number} ({t.label})" for t in m.terms}
    selected_prep_term_id = st.selectbox(
        "Select Term",
        options=list(term_labels_all.keys()),
        format_func=lambda x: term_labels_all[x],
        key="prepay_term_select",
    )
    selected_prep_term = next(t for t in m.terms if t.id == selected_prep_term_id)

    annual_limit = m.annual_prepayment_limit
    st.caption(f"Annual prepayment privilege: **${float(annual_limit):,.2f}** "
               f"({float(m.prepayment_limit_pct)*100:.0f}% of ${float(m.original_principal):,.2f})")

    # ── Existing prepayments list ────────────────────────────────────────────
    if selected_prep_term.prepayments:
        st.subheader("Existing Prepayments")

        # Column headers
        h1,h2,h3,h4,h5,h6,h7 = st.columns([2, 2, 1.5, 2, 2, 0.6, 0.6])
        h1.caption("Start Date"); h2.caption("Amount"); h3.caption("Recurrence")
        h4.caption("End Date");   h5.caption("Note");   h6.caption("Edit"); h7.caption("Del")

        for p in sorted(selected_prep_term.prepayments, key=lambda x: x.payment_date):
            c1,c2,c3,c4,c5,c6,c7 = st.columns([2, 2, 1.5, 2, 2, 0.6, 0.6])
            c1.write(f"📅 {p.payment_date}")
            c2.write(f"**${float(p.amount):,.2f}**")
            c3.write(p.recurrence.capitalize())
            c4.write(str(p.end_date) if p.end_date else "— (open-ended)")
            c5.write(p.note or "—")
            if c6.button("✏️", key=f"edit_prep_{p.id}", help="Edit"):
                # Set session state — do NOT call st.rerun() here.
                # The button click already triggers a rerun. Calling st.rerun()
                # explicitly resets the active tab back to tab 1, hiding the form.
                # The session_state value is readable immediately in this same run.
                st.session_state["editing_prep_id"] = p.id
            if c7.button("🗑️", key=f"del_prep_{p.id}", help="Delete"):
                repo.delete_prepayment(p.id)
                st.session_state.pop("editing_prep_id", None)
                invalidate()
                st.rerun()
    else:
        st.info("No prepayments recorded for this term.")

    # ── Inline edit form ─────────────────────────────────────────────────────
    # We use plain widgets (not st.form) so that:
    # 1. The checkbox toggling end-date immediately shows/hides the date input.
    # 2. We have full control over session state initialisation from DB values.
    # 3. st.rerun() after save/cancel works cleanly without form caching issues.
    editing_id = st.session_state.get("editing_prep_id")
    if editing_id is not None:
        prep_to_edit = next(
            (p for p in selected_prep_term.prepayments if p.id == editing_id), None
        )
        if prep_to_edit:
            st.divider()
            st.subheader(f"✏️ Editing Prepayment — {prep_to_edit.payment_date}  ${float(prep_to_edit.amount):,.2f}")

            eid = editing_id

            # Initialise session state from DB values exactly once per edit session.
            # The guard key prevents widget interactions from resetting values mid-edit.
            _init_key = f"ep_init_{eid}"
            if _init_key not in st.session_state:
                st.session_state[f"ep_date_{eid}"]       = prep_to_edit.payment_date
                st.session_state[f"ep_amount_{eid}"]     = float(prep_to_edit.amount)
                st.session_state[f"ep_recurrence_{eid}"] = prep_to_edit.recurrence
                st.session_state[f"ep_has_end_{eid}"]    = prep_to_edit.end_date is not None
                st.session_state[f"ep_end_{eid}"]        = prep_to_edit.end_date or selected_prep_term.end_date
                st.session_state[f"ep_note_{eid}"]       = prep_to_edit.note or ""
                st.session_state[_init_key]              = True

            ec1, ec2 = st.columns(2)
            e_date = ec1.date_input(
                "Payment Date",
                min_value=selected_prep_term.start_date,
                max_value=selected_prep_term.end_date,
                key=f"ep_date_{eid}",
            )
            e_amount = ec2.number_input(
                "Amount ($)",
                min_value=1.0, max_value=float(annual_limit),
                step=100.0, format="%.2f",
                key=f"ep_amount_{eid}",
            )
            e_recurrence = ec1.selectbox(
                "Recurrence", ["once", "monthly", "annual"],
                key=f"ep_recurrence_{eid}",
            )
            e_has_end = ec2.checkbox(
                "Set end date",
                key=f"ep_has_end_{eid}",
            )
            e_end = None
            if e_has_end:
                e_end = st.date_input(
                    "End Date",
                    min_value=selected_prep_term.start_date,
                    max_value=selected_prep_term.end_date,
                    key=f"ep_end_{eid}",
                )
            e_note = st.text_input(
                "Note",
                key=f"ep_note_{eid}",
            )

            def _cleanup_edit_keys(eid):
                for k in [f"ep_date_{eid}", f"ep_amount_{eid}", f"ep_recurrence_{eid}",
                          f"ep_has_end_{eid}", f"ep_end_{eid}", f"ep_note_{eid}",
                          f"ep_init_{eid}"]:
                    st.session_state.pop(k, None)
                st.session_state.pop("editing_prep_id", None)

            btn_save, btn_cancel = st.columns(2)
            do_save   = btn_save.button("💾 Save Changes", type="primary", use_container_width=True, key=f"ep_save_{eid}")
            do_cancel = btn_cancel.button("Cancel", use_container_width=True, key=f"ep_cancel_{eid}")

            if do_save:
                repo.delete_prepayment(prep_to_edit.id)
                repo.add_prepayment(selected_prep_term_id, PrepaymentEvent(
                    payment_date = e_date,
                    amount       = Decimal(str(round(e_amount, 2))),
                    recurrence   = e_recurrence,
                    end_date     = e_end,
                    note         = e_note,
                ))
                invalidate()
                _cleanup_edit_keys(eid)
                st.rerun()

            if do_cancel:
                _cleanup_edit_keys(eid)
                st.rerun()

    st.divider()
    st.subheader("Add Prepayment")

    with st.form("form_add_prepayment"):
        col1, col2 = st.columns(2)
        prep_date = col1.date_input(
            "Payment Date",
            value=selected_prep_term.start_date + relativedelta(months=1),
            min_value=selected_prep_term.start_date,
            max_value=selected_prep_term.end_date,
        )
        prep_amount = col2.number_input(
            "Amount ($)", min_value=1.0, max_value=float(annual_limit),
            value=1000.0, step=100.0, format="%.2f",
        )
        recurrence = col1.selectbox(
            "Recurrence", ["once", "monthly", "annual"],
            help="once = one-time lump sum | monthly = every month | annual = same month each year",
        )
        has_end_date = col2.checkbox("Set end date (for recurring prepayments)")
        prep_end = None
        if has_end_date:
            prep_end = st.date_input(
                "End Date",
                value=selected_prep_term.end_date,
                min_value=prep_date,
                max_value=selected_prep_term.end_date,
            )
        note = st.text_input("Note (optional)", placeholder="e.g. annual February lump sum")

        add_prep = st.form_submit_button("➕ Add Prepayment", type="primary", use_container_width=True)

    if add_prep:
        event = PrepaymentEvent(
            payment_date = prep_date,
            amount       = Decimal(str(round(prep_amount, 2))),
            recurrence   = recurrence,
            end_date     = prep_end,
            note         = note,
        )
        repo.add_prepayment(selected_prep_term_id, event)
        invalidate()
        st.success(f"Prepayment added: ${prep_amount:,.2f} ({recurrence}) from {prep_date}.")
        st.rerun()
