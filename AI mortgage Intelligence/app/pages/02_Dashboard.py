"""
app/pages/02_Dashboard.py
==========================
Dashboard — mortgage health at a glance.

12 charts in 5 sections:
  1  Outstanding Balance Over Time
  2  Equity Built vs Remaining Balance
  3  Payoff Progress Gauge
  4  Principal vs Interest Split (per payment)
  5  Cumulative Interest Paid
  6  Annual Payment Breakdown
  7  Balance: With vs Without Prepayments
  8  Interest Saved by Prepayments
  9  Interest Rate History
  10 Term Comparison at Renewal
  11 Year-End Balance
  12 Interest vs Principal Ratio by Year
"""
from __future__ import annotations
import copy
from datetime import date
from decimal import Decimal
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from app.state import get_schedule, has_mortgage
from mortgage.engine.amortization import generate_schedule
from mortgage.engine.analytics import balance_at_date
from mortgage.engine.renewal import compare_renewal_options

st.set_page_config(page_title="Dashboard | Mortgage Intelligence", page_icon="📊", layout="wide")
st.title("📊 Dashboard")

if not has_mortgage():
    st.info("No mortgage configured. Go to **Setup** to get started.")
    st.stop()

schedule = get_schedule()
if schedule is None:
    st.warning("No terms configured yet. Add terms in **Setup**.")
    st.stop()

try:
    ls    = schedule.lifetime_summary
    m     = schedule.mortgage
    today = date.today()

    C = {
        "dark_blue":    "#1B3A6B",
        "mid_blue":     "#2E75B6",
        "light_blue":   "#9DC3E6",
        "orange":       "#C45911",
        "light_orange": "#F4B183",
        "green":        "#375623",
        "light_green":  "#70AD47",
        "grey":         "#595959",
    }

    _AXIS = dict(
        title_font=dict(size=12, color="#222222"),
        tickfont=dict(size=11, color="#333333"),
        showgrid=True, gridcolor="#E0E0E0",
        linecolor="#BBBBBB", linewidth=1,
        zeroline=False,
    )

    def _fig(title, height=370, **extra):
        fig = go.Figure()
        fig.update_layout(
            title=dict(text=title, font=dict(size=14, color="#111111"), x=0),
            plot_bgcolor="#F9F9F9", paper_bgcolor="white",
            font=dict(color="#333333", size=12),
            margin=dict(l=65, r=20, t=55, b=55),
            height=height, hovermode="x unified", **extra,
        )
        fig.update_xaxes(**_AXIS)
        fig.update_yaxes(**_AXIS)
        return fig

    def _legend():
        return dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=11, color="#333333"))

    def _vline_today(fig):
        fig.add_vline(x=today.isoformat(), line_width=1,
                      line_dash="dot", line_color=C["orange"])
        fig.add_annotation(
            x=today.isoformat(), y=1, yref="paper",
            text="Today", showarrow=False, xanchor="left",
            font=dict(color=C["orange"], size=11),
        )

    hist  = [p for p in schedule.payments if p.is_historical]
    proj  = [p for p in schedule.payments if not p.is_historical]
    all_p = schedule.payments

    today_balance = next((p.balance_closing for p in reversed(hist)), m.original_principal)
    equity_built  = m.original_principal - today_balance
    pct_paid      = float(equity_built / m.original_principal * 100) if m.original_principal else 0.0

    m_no_prep = copy.deepcopy(m)
    for term in m_no_prep.terms:
        term.prepayments = []
    sched_no_prep  = generate_schedule(m_no_prep)
    ls_no_prep     = sched_no_prep.lifetime_summary
    interest_saved = float(ls_no_prep.total_interest) - float(ls.total_interest)
    months_saved   = ls_no_prep.payoff_month - ls.payoff_month

    ann = {}
    for p in all_p:
        yr = str(p.payment_date.year)
        if yr not in ann:
            ann[yr] = {"interest": 0.0, "principal": 0.0, "prepayment": 0.0}
        ann[yr]["interest"]   += float(p.interest_amount)
        ann[yr]["principal"]  += max(0.0, float(p.principal_repaid))
        ann[yr]["prepayment"] += float(p.prepayment)
    ann_years = sorted(ann.keys())

    # ── KPI CARDS ─────────────────────────────────────────────────────────
    st.subheader("Summary")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Original Principal",  f"${float(m.original_principal):,.0f}")
    c2.metric("Outstanding Balance",  f"${float(today_balance):,.0f}",
              delta=f"-${float(equity_built):,.0f} paid", delta_color="inverse")
    c3.metric("Projected Payoff",     ls.payoff_date.strftime("%b %Y"),
              delta=f"{ls.payoff_month} payments total", delta_color="off")
    c4.metric("Lifetime Interest",    f"${float(ls.total_interest):,.0f}",
              delta=f"{float(ls.net_interest_pct)*100:.1f}% of principal", delta_color="off")
    c5.metric("Total Prepayments",    f"${float(ls.total_prepayments):,.0f}")
    c6.metric("Avg Interest Rate",    f"{float(ls.weighted_avg_rate)*100:.2f}%")
    st.divider()

    # ═══════════════════ SECTION A — BALANCE & EQUITY ═══════════════════════
    st.subheader("Balance & Equity")
    col_a1, col_a2 = st.columns(2)

    # Chart 1: Outstanding Balance Over Time
    fig1 = _fig("1 · Outstanding Balance Over Time",
                xaxis_title="Date", yaxis_title="Balance ($)")
    if hist:
        fig1.add_trace(go.Scatter(
            x=[p.payment_date.isoformat() for p in hist],
            y=[float(p.balance_closing) for p in hist],
            mode="lines", name="Actual Balance",
            line=dict(color=C["dark_blue"], width=2.5),
            hovertemplate="<b>%{x}</b><br>Balance: $%{y:,.0f}<extra></extra>",
        ))
    if proj:
        cx = ([hist[-1].payment_date.isoformat()] if hist else []) + [p.payment_date.isoformat() for p in proj]
        cy = ([float(hist[-1].balance_closing)] if hist else []) + [float(p.balance_closing) for p in proj]
        fig1.add_trace(go.Scatter(
            x=cx, y=cy, mode="lines", name="Projected Balance",
            line=dict(color=C["mid_blue"], width=2, dash="dash"),
            hovertemplate="<b>%{x}</b><br>Projected: $%{y:,.0f}<extra></extra>",
        ))
    _vline_today(fig1)
    fig1.update_layout(legend=_legend(), yaxis_tickformat="$,.0f")
    col_a1.plotly_chart(fig1, use_container_width=True)

    # Chart 2: Equity Built vs Remaining Balance
    fig2 = _fig("2 · Equity Built vs Remaining Balance",
                xaxis_title="Date", yaxis_title="Amount ($)")
    dates_all = [p.payment_date.isoformat() for p in all_p]
    fig2.add_trace(go.Scatter(
        x=dates_all,
        y=[float(m.original_principal - p.balance_closing) for p in all_p],
        mode="lines", name="Equity Built", stackgroup="eq",
        line=dict(color=C["light_green"], width=1),
        fillcolor="rgba(112,173,71,0.55)",
        hovertemplate="<b>%{x}</b><br>Equity: $%{y:,.0f}<extra></extra>",
    ))
    fig2.add_trace(go.Scatter(
        x=dates_all,
        y=[float(p.balance_closing) for p in all_p],
        mode="lines", name="Remaining Balance", stackgroup="eq",
        line=dict(color=C["mid_blue"], width=1),
        fillcolor="rgba(46,117,182,0.55)",
        hovertemplate="<b>%{x}</b><br>Balance: $%{y:,.0f}<extra></extra>",
    ))
    _vline_today(fig2)
    fig2.update_layout(legend=_legend(), yaxis_tickformat="$,.0f")
    col_a2.plotly_chart(fig2, use_container_width=True)
    st.divider()

    # ═══════════════════ SECTION B — PROGRESS ═══════════════════════════════
    st.subheader("Progress")
    col_b1, col_b2 = st.columns(2)

    # Chart 3: Payoff Progress Gauge
    fig3 = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(pct_paid, 1),
        number=dict(suffix="%", font=dict(size=32, color="#111111")),
        delta=dict(reference=0, valueformat=".1f",
                   suffix="% of mortgage paid", font=dict(size=13, color="#333333")),
        title=dict(text="3 · Payoff Progress", font=dict(size=14, color="#111111")),
        gauge=dict(
            axis=dict(range=[0, 100], tickfont=dict(size=11, color="#333333"),
                      tickcolor="#333333", tickwidth=1, dtick=25),
            bar=dict(color=C["light_green"], thickness=0.65),
            bgcolor="#F0F0F0", borderwidth=1, bordercolor="#CCCCCC",
            steps=[
                dict(range=[0, 25],   color="#FDE8D8"),
                dict(range=[25, 50],  color="#FAD7A0"),
                dict(range=[50, 75],  color="#D5E8D4"),
                dict(range=[75, 100], color="#B8E0B5"),
            ],
            threshold=dict(line=dict(color=C["orange"], width=3),
                           thickness=0.75, value=pct_paid),
        ),
    ))
    fig3.update_layout(paper_bgcolor="white", font=dict(color="#333333"),
                       height=370, margin=dict(l=30, r=30, t=40, b=30))
    col_b1.plotly_chart(fig3, use_container_width=True)

    # Chart 11: Year-End Balance
    yoy = {}
    for p in all_p:
        yoy[str(p.payment_date.year)] = float(p.balance_closing)
    yoy_years  = sorted(yoy.keys())
    yoy_colors = [C["dark_blue"] if int(y) <= today.year else C["light_blue"] for y in yoy_years]
    fig11 = _fig("11 · Year-End Outstanding Balance",
                 xaxis_title="Year", yaxis_title="Balance ($)")
    fig11.add_trace(go.Bar(
        x=yoy_years, y=[yoy[y] for y in yoy_years],
        marker_color=yoy_colors,
        hovertemplate="<b>%{x}</b><br>Balance: $%{y:,.0f}<extra></extra>",
    ))
    fig11.update_layout(showlegend=False, yaxis_tickformat="$,.0f")
    fig11.update_xaxes(type="category")
    col_b2.plotly_chart(fig11, use_container_width=True)
    st.divider()

    # ════════════════════ SECTION C — PAYMENT BREAKDOWN ═════════════════════
    st.subheader("Payment Breakdown")
    col_c1, col_c2 = st.columns(2)

    dates_str = [p.payment_date.isoformat() for p in all_p]

    # Chart 4: Principal vs Interest Split per Payment
    fig4 = _fig("4 · Principal vs Interest Split (Monthly)",
                xaxis_title="Date", yaxis_title="Amount ($)")
    fig4.add_trace(go.Scatter(
        x=dates_str,
        y=[float(p.interest_amount) for p in all_p],
        mode="lines", name="Interest", stackgroup="pay",
        line=dict(color=C["orange"], width=0),
        fillcolor="rgba(196,89,17,0.5)",
        hovertemplate="<b>%{x}</b><br>Interest: $%{y:,.0f}<extra></extra>",
    ))
    fig4.add_trace(go.Scatter(
        x=dates_str,
        y=[max(0.0, float(p.principal_repaid)) for p in all_p],
        mode="lines", name="Principal", stackgroup="pay",
        line=dict(color=C["mid_blue"], width=0),
        fillcolor="rgba(46,117,182,0.5)",
        hovertemplate="<b>%{x}</b><br>Principal: $%{y:,.0f}<extra></extra>",
    ))
    _vline_today(fig4)
    fig4.update_layout(legend=_legend(), yaxis_tickformat="$,.0f")
    col_c1.plotly_chart(fig4, use_container_width=True)

    # Chart 5: Cumulative Interest Paid
    cum, running = [], 0.0
    for p in all_p:
        running += float(p.interest_amount)
        cum.append(running)

    fig5 = _fig("5 · Cumulative Interest Paid",
                xaxis_title="Date", yaxis_title="Cumulative Interest ($)")
    if hist:
        fig5.add_trace(go.Scatter(
            x=dates_str[:len(hist)], y=cum[:len(hist)],
            mode="lines", name="Paid to Date",
            line=dict(color=C["orange"], width=2.5),
            hovertemplate="<b>%{x}</b><br>Cumulative: $%{y:,.0f}<extra></extra>",
        ))
    if proj:
        cx2 = ([dates_str[len(hist)-1]] if hist else []) + dates_str[len(hist):]
        cy2 = ([cum[len(hist)-1]] if hist else []) + cum[len(hist):]
        fig5.add_trace(go.Scatter(
            x=cx2, y=cy2, mode="lines", name="Projected",
            line=dict(color=C["light_orange"], width=2, dash="dash"),
            hovertemplate="<b>%{x}</b><br>Cumulative: $%{y:,.0f}<extra></extra>",
        ))
    _vline_today(fig5)
    fig5.update_layout(legend=_legend(), yaxis_tickformat="$,.0f")
    col_c2.plotly_chart(fig5, use_container_width=True)
    st.divider()

    # ═══════════════════ SECTION D — ANNUAL SUMMARY ═════════════════════════
    st.subheader("Annual Summary")
    col_d1, col_d2 = st.columns(2)

    # Chart 6: Annual Payment Breakdown
    fig6 = _fig("6 · Annual Payment Breakdown",
                xaxis_title="Year", yaxis_title="Amount ($)")
    fig6.add_trace(go.Bar(x=ann_years, y=[ann[y]["interest"]   for y in ann_years],
        name="Interest",    marker_color=C["orange"],
        hovertemplate="<b>%{x}</b><br>Interest: $%{y:,.0f}<extra></extra>"))
    fig6.add_trace(go.Bar(x=ann_years, y=[ann[y]["principal"]  for y in ann_years],
        name="Principal",   marker_color=C["mid_blue"],
        hovertemplate="<b>%{x}</b><br>Principal: $%{y:,.0f}<extra></extra>"))
    fig6.add_trace(go.Bar(x=ann_years, y=[ann[y]["prepayment"] for y in ann_years],
        name="Prepayments", marker_color=C["light_green"],
        hovertemplate="<b>%{x}</b><br>Prepayments: $%{y:,.0f}<extra></extra>"))
    fig6.update_layout(barmode="stack", legend=_legend(), yaxis_tickformat="$,.0f")
    fig6.update_xaxes(type="category")
    col_d1.plotly_chart(fig6, use_container_width=True)

    # Chart 12: Interest vs Principal Ratio by Year (100% stacked)
    fig12 = _fig("12 · Interest vs Principal Ratio by Year",
                 xaxis_title="Year", yaxis_title="Share (%)")
    int_pct, prin_pct = [], []
    for y in ann_years:
        tot = ann[y]["interest"] + ann[y]["principal"]
        if tot > 0:
            int_pct.append(round(ann[y]["interest"]  / tot * 100, 1))
            prin_pct.append(round(ann[y]["principal"] / tot * 100, 1))
        else:
            int_pct.append(0.0); prin_pct.append(0.0)
    fig12.add_trace(go.Bar(x=ann_years, y=int_pct,  name="Interest %",
        marker_color=C["orange"],
        hovertemplate="<b>%{x}</b><br>Interest: %{y:.1f}%<extra></extra>"))
    fig12.add_trace(go.Bar(x=ann_years, y=prin_pct, name="Principal %",
        marker_color=C["mid_blue"],
        hovertemplate="<b>%{x}</b><br>Principal: %{y:.1f}%<extra></extra>"))
    fig12.update_layout(barmode="stack", legend=_legend())
    fig12.update_xaxes(type="category")
    fig12.update_yaxes(range=[0, 100], ticksuffix="%")
    col_d2.plotly_chart(fig12, use_container_width=True)
    st.divider()

    # ════════════════════ SECTION E — PREPAYMENT IMPACT ═════════════════════
    st.subheader("Prepayment Impact")
    col_e1, col_e2 = st.columns(2)

    # Chart 7: Balance with vs without prepayments
    fig7 = _fig("7 · Balance: With vs Without Prepayments",
                xaxis_title="Date", yaxis_title="Balance ($)")
    fig7.add_trace(go.Scatter(
        x=[p.payment_date.isoformat() for p in sched_no_prep.payments],
        y=[float(p.balance_closing)   for p in sched_no_prep.payments],
        mode="lines", name="Without Prepayments",
        line=dict(color=C["orange"], width=2, dash="dot"),
        hovertemplate="<b>%{x}</b><br>No prepayments: $%{y:,.0f}<extra></extra>",
    ))
    fig7.add_trace(go.Scatter(
        x=[p.payment_date.isoformat() for p in all_p],
        y=[float(p.balance_closing)   for p in all_p],
        mode="lines", name="With Prepayments",
        line=dict(color=C["dark_blue"], width=2.5),
        hovertemplate="<b>%{x}</b><br>With prepayments: $%{y:,.0f}<extra></extra>",
    ))
    _vline_today(fig7)
    fig7.update_layout(legend=_legend(), yaxis_tickformat="$,.0f")
    if float(ls.total_prepayments) == 0:
        fig7.add_annotation(x=0.5, y=0.5, xref="paper", yref="paper",
            text="No prepayments configured — lines overlap",
            showarrow=False, font=dict(size=13, color="#888888"))
    col_e1.plotly_chart(fig7, use_container_width=True)

    # Chart 8: Interest Saved by Prepayments
    saved_lbl = f"${interest_saved:,.0f} saved  |  {months_saved} months sooner" if interest_saved > 0 else "No savings yet"
    fig8 = _fig(f"8 · Interest Saved by Prepayments  ({saved_lbl})",
                xaxis_title="", yaxis_title="Total Lifetime Interest ($)")
    fig8.add_trace(go.Bar(
        x=["Without Prepayments", "With Prepayments"],
        y=[float(ls_no_prep.total_interest), float(ls.total_interest)],
        marker_color=[C["orange"], C["light_green"]],
        text=[f"${float(ls_no_prep.total_interest):,.0f}",
              f"${float(ls.total_interest):,.0f}"],
        textposition="inside",
        textfont=dict(color="white", size=12),
        width=0.45,
        hovertemplate="<b>%{x}</b><br>Total Interest: $%{y:,.0f}<extra></extra>",
    ))
    fig8.update_layout(showlegend=False, yaxis_tickformat="$,.0f")
    fig8.update_xaxes(showgrid=False, tickfont=dict(size=13, color="#222222"))
    col_e2.plotly_chart(fig8, use_container_width=True)
    st.divider()

    # ════════════════════ SECTION F — RATES & TERMS ══════════════════════════
    st.subheader("Rates & Terms")
    col_f1, col_f2 = st.columns(2)

    # Chart 9: Interest Rate History
    rate_events = []
    for term in sorted(m.terms, key=lambda t: t.term_number):
        rate_events.append((term.start_date.isoformat(),
                            float(term.initial_annual_rate) * 100))
        for rc in sorted(term.rate_changes, key=lambda r: r.effective_date):
            rate_events.append((rc.effective_date.isoformat(),
                                float(rc.new_annual_rate) * 100))

    fig9 = _fig("9 · Interest Rate History",
                xaxis_title="Date", yaxis_title="Annual Rate (%)")
    if rate_events:
        rx, ry = zip(*rate_events)
        fig9.add_trace(go.Scatter(
            x=list(rx), y=list(ry),
            mode="lines+markers", name="Rate",
            line=dict(color=C["dark_blue"], width=2.5, shape="hv"),
            marker=dict(size=7, color=C["dark_blue"],
                        line=dict(color="white", width=1.5)),
            hovertemplate="<b>%{x}</b><br>Rate: %{y:.4f}%<extra></extra>",
        ))
    _vline_today(fig9)
    fig9.update_layout(showlegend=False)
    fig9.update_yaxes(ticksuffix="%")
    col_f1.plotly_chart(fig9, use_container_width=True)

    # Chart 10: Term Comparison at Renewal
    next_term = None
    for term in sorted(m.terms, key=lambda t: t.end_date):
        if term.end_date >= today:
            next_term = term
            break

    if next_term is not None:
        renewal_date = next_term.end_date
        renewal_bal  = balance_at_date(schedule, renewal_date)
        if next_term.rate_changes:
            base_rate = float(max(next_term.rate_changes,
                                  key=lambda r: r.effective_date).new_annual_rate)
        else:
            base_rate = float(next_term.initial_annual_rate)

        rate_offsets = {1: -0.0075, 2: -0.005, 3: -0.0025, 4: 0.0, 5: 0.0025}
        rate_by_term = {
            yr: Decimal(str(round(max(0.005, base_rate + off), 4)))
            for yr, off in rate_offsets.items()
        }
        try:
            options     = compare_renewal_options(renewal_bal, renewal_date, m, rate_by_term)
            opt_labels  = [f"{o.term_years}yr @ {float(o.annual_rate)*100:.2f}%"
                           for o in options]
            fig10 = _fig(f"10 · Term Comparison at Renewal  ({renewal_date})",
                         xaxis_title="Renewal Option", yaxis_title="Amount ($)")
            fig10.add_trace(go.Bar(x=opt_labels,
                y=[float(o.monthly_payment)     for o in options],
                name="Monthly Payment", marker_color=C["dark_blue"],
                hovertemplate="<b>%{x}</b><br>Monthly: $%{y:,.0f}<extra></extra>"))
            fig10.add_trace(go.Bar(x=opt_labels,
                y=[float(o.term_total_interest) for o in options],
                name="Term Interest",  marker_color=C["orange"],
                hovertemplate="<b>%{x}</b><br>Term Interest: $%{y:,.0f}<extra></extra>"))
            fig10.add_trace(go.Bar(x=opt_labels,
                y=[float(o.balance_at_end)      for o in options],
                name="Balance at End", marker_color=C["light_blue"],
                hovertemplate="<b>%{x}</b><br>Balance at End: $%{y:,.0f}<extra></extra>"))
            fig10.update_layout(barmode="group", legend=_legend(), yaxis_tickformat="$,.0f")
            fig10.update_xaxes(showgrid=False, tickfont=dict(size=11, color="#222222"))
            col_f2.plotly_chart(fig10, use_container_width=True)
        except Exception as ex:
            col_f2.warning(f"Term comparison unavailable: {ex}")
    else:
        col_f2.info("No upcoming renewal found. Add future terms in **Setup**.")

    st.divider()

    # ── Term Summary Table ─────────────────────────────────────────────────
    st.subheader("Term Summary")
    if schedule.term_summaries:
        rows = []
        for ts in schedule.term_summaries:
            rows.append({
                "Term":             ts.label,
                "Opening Balance":  f"${float(ts.opening_balance):,.2f}",
                "Closing Balance":  f"${float(ts.closing_balance):,.2f}",
                "Principal Repaid": f"${float(ts.principal_repaid):,.2f}",
                "Interest Paid":    f"${float(ts.interest_paid):,.2f}",
                "Prepayments":      f"${float(ts.total_prepayments):,.2f}",
                "Total Paid":       f"${float(ts.total_repayments):,.2f}",
                "Avg Rate":         f"{float(ts.avg_weighted_rate)*100:.2f}%",
                "Payments":         str(ts.payment_count),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

except Exception as e:
    st.error("Dashboard error — details below:")
    st.exception(e)
