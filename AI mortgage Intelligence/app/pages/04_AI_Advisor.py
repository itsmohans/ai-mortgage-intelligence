"""
app/pages/04_AI_Advisor.py
===========================
AI Mortgage Advisor — powered by Claude.

Features:
  - Natural language Q&A about your mortgage
  - Scenario modeling via tool use (prepayment impact, payment increase, renewal comparison)
  - Proactive advice and recommendations
  - Full streaming responses
"""
from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st
from dotenv import load_dotenv

from app.state import get_schedule, has_mortgage
from mortgage.ai.context import build_mortgage_context
from mortgage.ai.retrieval import retrieve, retrieve_chunks_metadata, is_ready as rag_is_ready
from mortgage.engine.analytics import balance_at_date, prepayment_impact, payment_increase_impact
from mortgage.engine.renewal import compare_renewal_options

load_dotenv()

st.set_page_config(
    page_title="AI Advisor | Mortgage Intelligence",
    page_icon="🤖",
    layout="wide",
)
st.title("🤖 AI Mortgage Advisor")

# ─────────────────────────────────────────────────────────────────────────────
# Guard: mortgage + API key
# ─────────────────────────────────────────────────────────────────────────────
if not has_mortgage():
    st.info("No mortgage configured. Go to **Setup** to get started.")
    st.stop()

schedule = get_schedule()
if schedule is None:
    st.warning("No terms configured yet. Add terms in **Setup**.")
    st.stop()

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if not api_key:
    st.error(
        "**Anthropic API key not found.**\n\n"
        "Create a `.env` file in the project root and add:\n"
        "```\nANTHROPIC_API_KEY=sk-ant-...\n```\n"
        "Get your key at [console.anthropic.com](https://console.anthropic.com)."
    )
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions (what Claude can call)
# ─────────────────────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "calculate_prepayment_impact",
        "description": (
            "Calculate the financial impact of a one-time lump-sum prepayment. "
            "Returns interest saved, months saved, new payoff date, and effective annual return. "
            "Use this when the user asks what-if questions about making an extra payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lump_sum": {
                    "type": "number",
                    "description": "Amount of the lump-sum prepayment in dollars (e.g. 10000)"
                },
                "applied_on": {
                    "type": "string",
                    "description": "Date to apply the prepayment, YYYY-MM-DD format. Use the next upcoming payment date if not specified."
                }
            },
            "required": ["lump_sum", "applied_on"]
        }
    },
    {
        "name": "calculate_payment_increase_impact",
        "description": (
            "Calculate the impact of permanently increasing the monthly payment by a fixed amount. "
            "Returns interest saved, months saved, and new payoff date. "
            "Use this when the user asks about increasing their regular monthly payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "additional_monthly": {
                    "type": "number",
                    "description": "Extra amount to add to each monthly payment in dollars (e.g. 200)"
                },
                "effective_from": {
                    "type": "string",
                    "description": "Start date for the increased payment, YYYY-MM-DD format."
                }
            },
            "required": ["additional_monthly", "effective_from"]
        }
    },
    {
        "name": "compare_renewal_options",
        "description": (
            "Compare mortgage renewal options side by side for different term lengths and rates. "
            "Returns monthly payment, term interest, and balance at end for each option. "
            "Use this when the user asks about renewal, rate shopping, or comparing term lengths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "renewal_date": {
                    "type": "string",
                    "description": "Date of the renewal, YYYY-MM-DD format."
                },
                "options": {
                    "type": "array",
                    "description": "List of renewal options to compare.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "term_years": {"type": "integer", "description": "Term length in years (1-5)"},
                            "annual_rate_pct": {"type": "number", "description": "Annual interest rate as a percentage (e.g. 4.5 for 4.5%)"}
                        },
                        "required": ["term_years", "annual_rate_pct"]
                    }
                }
            },
            "required": ["renewal_date", "options"]
        }
    },
    {
        "name": "get_balance_at_date",
        "description": "Get the outstanding mortgage balance on a specific date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "as_of_date": {
                    "type": "string",
                    "description": "Date to check balance, YYYY-MM-DD format."
                }
            },
            "required": ["as_of_date"]
        }
    }
]

# ─────────────────────────────────────────────────────────────────────────────
# Tool execution
# ─────────────────────────────────────────────────────────────────────────────
def _run_tool(name: str, inputs: dict) -> str:
    m = schedule.mortgage
    today = date.today()

    try:
        if name == "calculate_prepayment_impact":
            lump_sum    = Decimal(str(inputs["lump_sum"]))
            applied_on  = date.fromisoformat(inputs["applied_on"])
            result      = prepayment_impact(m, lump_sum, applied_on)
            return (
                f"Prepayment impact for ${float(lump_sum):,.2f} applied on {applied_on}:\n"
                f"  Interest saved:       ${float(result.interest_saved):,.2f}\n"
                f"  Months saved:         {result.months_saved}\n"
                f"  New payoff date:      {result.new_payoff_date.strftime('%B %Y')}\n"
                f"  Original payoff date: {result.baseline_payoff_date.strftime('%B %Y')}\n"
                f"  Effective annual return on prepayment: {float(result.effective_annual_return)*100:.1f}%\n"
                f"  New total interest:   ${float(result.new_total_interest):,.2f}\n"
                f"  Baseline interest:    ${float(result.baseline_total_interest):,.2f}"
            )

        elif name == "calculate_payment_increase_impact":
            additional  = Decimal(str(inputs["additional_monthly"]))
            from_date   = date.fromisoformat(inputs["effective_from"])
            result      = payment_increase_impact(m, additional, from_date)
            return (
                f"Payment increase impact for +${float(additional):,.2f}/month from {from_date}:\n"
                f"  Interest saved:       ${float(result.interest_saved):,.2f}\n"
                f"  Months saved:         {result.months_saved}\n"
                f"  New payoff date:      {result.new_payoff_date.strftime('%B %Y')}\n"
                f"  Original payoff date: {result.baseline_payoff_date.strftime('%B %Y')}\n"
                f"  New total interest:   ${float(result.new_total_interest):,.2f}\n"
                f"  Baseline interest:    ${float(result.baseline_total_interest):,.2f}"
            )

        elif name == "compare_renewal_options":
            renewal_date = date.fromisoformat(inputs["renewal_date"])
            renewal_bal  = balance_at_date(schedule, renewal_date)
            rate_by_term = {
                opt["term_years"]: Decimal(str(round(opt["annual_rate_pct"] / 100, 6)))
                for opt in inputs["options"]
            }
            options = compare_renewal_options(renewal_bal, renewal_date, m, rate_by_term)
            lines = [f"Renewal comparison as of {renewal_date} (balance: ${float(renewal_bal):,.2f}):"]
            for o in options:
                lines.append(
                    f"\n  {o.term_years}-year @ {float(o.annual_rate)*100:.2f}%:\n"
                    f"    Monthly payment:  ${float(o.monthly_payment):,.2f}\n"
                    f"    Term interest:    ${float(o.term_total_interest):,.2f}\n"
                    f"    Balance at end:   ${float(o.balance_at_end):,.2f}\n"
                    f"    Projected payoff: {o.projected_payoff.strftime('%B %Y')}\n"
                    f"    Lifetime interest (from renewal): ${float(o.projected_total_interest):,.2f}"
                )
            return "\n".join(lines)

        elif name == "get_balance_at_date":
            as_of = date.fromisoformat(inputs["as_of_date"])
            bal   = balance_at_date(schedule, as_of)
            return f"Outstanding balance on {as_of}: ${float(bal):,.2f}"

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        return f"Tool error ({name}): {e}"

# ─────────────────────────────────────────────────────────────────────────────
# RAG status indicator (initialise once per session)
# ─────────────────────────────────────────────────────────────────────────────
if "rag_initialised" not in st.session_state:
    rag_ok, rag_err = rag_is_ready()
    st.session_state["rag_initialised"] = True
    st.session_state["rag_ok"]  = rag_ok
    st.session_state["rag_err"] = rag_err

# ─────────────────────────────────────────────────────────────────────────────
# System prompt  (query-aware: injects RAG chunks relevant to the latest msg)
# ─────────────────────────────────────────────────────────────────────────────
def _system_prompt(latest_query: str = "") -> str:
    context = build_mortgage_context(schedule)

    # Retrieve relevant knowledge chunks for the current query
    rag_section = ""
    if latest_query and st.session_state.get("rag_ok"):
        rag_section = retrieve(latest_query)
        if rag_section:
            rag_section = f"\n\n{rag_section}"

    return f"""You are an expert Canadian mortgage advisor embedded in a personal mortgage intelligence app. \
You have access to the homeowner's complete mortgage data, which is provided below. \
Your job is to answer questions accurately, run financial scenarios on request, and proactively \
highlight opportunities the homeowner may not have considered.

Guidelines:
- Be direct and specific — use the actual numbers from the mortgage data.
- For scenario questions ("what if I pay $10k extra?"), always use the calculate_prepayment_impact \
or calculate_payment_increase_impact tools to compute exact figures before answering.
- For renewal questions, use the compare_renewal_options tool with the rates the user specifies \
(or reasonable Canadian market rate assumptions if not provided).
- Speak in plain English — avoid jargon unless the user uses it first.
- Proactively mention the annual prepayment privilege if the user is asking about extra payments — \
tell them how much capacity they have left this year.
- When giving advice, always clarify you are not a licensed financial advisor and recommend \
consulting a mortgage broker for major decisions.
- Format numbers with dollar signs and commas. Keep responses concise but complete.
- Today's date is {date.today()}.
- When your answer draws on Canadian mortgage regulations (Interest Act compounding, OSFI B-20, \
CMHC rules, prepayment penalties), cite the relevant rule so the homeowner understands the basis.

{context}{rag_section}"""

# ─────────────────────────────────────────────────────────────────────────────
# Session state: chat history
# ─────────────────────────────────────────────────────────────────────────────
if "ai_messages" not in st.session_state:
    st.session_state["ai_messages"] = []

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar: controls + suggested prompts
# ─────────────────────────────────────────────────────────────────────────────
# RAG status badge in sidebar
with st.sidebar:
    if st.session_state.get("rag_ok"):
        st.success("🧠 Knowledge base active", icon="✅")
    else:
        err = st.session_state.get("rag_err", "")
        if err:
            st.warning(f"Knowledge base unavailable: {err}", icon="⚠️")

    st.subheader("💡 Try asking")
    prompts = [
        "What's my current outstanding balance and how much equity have I built?",
        "How much interest will I save if I make a $15,000 lump-sum payment today?",
        "If I increase my monthly payment by $300, when would I pay off the mortgage?",
        "How much of my annual prepayment privilege have I used this year?",
        "Compare a 3-year fixed at 4.5% vs a 5-year fixed at 4.2% at my next renewal.",
        "What's the best strategy to pay off my mortgage 3 years early?",
        "How much interest have I paid so far vs how much is still to come?",
        "Explain my rate history and how it has affected my payments.",
    ]
    for p in prompts:
        if st.button(p, use_container_width=True, key=f"prompt_{hash(p)}"):
            st.session_state["ai_messages"].append({"role": "user", "content": p})
            st.session_state["ai_trigger"] = True
            st.rerun()

    st.divider()
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state["ai_messages"] = []
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Chat display
# ─────────────────────────────────────────────────────────────────────────────
st.caption("Ask anything about your mortgage — balances, prepayments, renewal options, or strategy.")

for msg in st.session_state["ai_messages"]:
    role = msg["role"]
    content = msg["content"]
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    elif role == "assistant" and isinstance(content, str):
        with st.chat_message("assistant"):
            st.markdown(content)

# ─────────────────────────────────────────────────────────────────────────────
# Chat input + response
# ─────────────────────────────────────────────────────────────────────────────
user_input = st.chat_input("Ask your mortgage advisor anything…")

trigger = st.session_state.pop("ai_trigger", False)

if user_input:
    st.session_state["ai_messages"].append({"role": "user", "content": user_input})
    trigger = True
    with st.chat_message("user"):
        st.markdown(user_input)

if trigger and st.session_state["ai_messages"]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Extract the latest user query for RAG retrieval
    latest_query = ""
    for m in reversed(st.session_state["ai_messages"]):
        if m["role"] == "user" and isinstance(m.get("content"), str):
            latest_query = m["content"]
            break

    system = _system_prompt(latest_query)

    # Show RAG sources in sidebar if available
    if latest_query and st.session_state.get("rag_ok"):
        sources = retrieve_chunks_metadata(latest_query)
        if sources:
            with st.sidebar:
                with st.expander("📚 Knowledge sources used", expanded=False):
                    for s in sources:
                        st.caption(
                            f"**{s['title']}** ({s['category']})  "
                            f"— relevance: {s['similarity']:.0%}"
                        )

    messages = [
        m for m in st.session_state["ai_messages"]
        if isinstance(m.get("content"), str)
    ]

    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""

        # Agentic loop: handle tool calls
        loop_messages = list(messages)
        max_iterations = 5

        for iteration in range(max_iterations):
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=system,
                messages=loop_messages,
                tools=TOOLS,
            ) as stream:
                tool_calls = []
                text_chunks = []

                for event in stream:
                    event_type = type(event).__name__

                    if event_type == "RawContentBlockDeltaEvent":
                        delta = event.delta
                        if hasattr(delta, "text"):
                            text_chunks.append(delta.text)
                            full_response = "".join(text_chunks)
                            response_placeholder.markdown(full_response + "▌")

                    elif event_type == "RawMessageStopEvent":
                        pass

                final_msg = stream.get_final_message()

            # Collect tool use blocks
            tool_use_blocks = [b for b in final_msg.content if b.type == "tool_use"]
            text_blocks     = [b for b in final_msg.content if b.type == "text"]

            if not tool_use_blocks:
                # No more tool calls — done
                full_response = "".join(b.text for b in text_blocks)
                response_placeholder.markdown(full_response)
                break

            # Show partial text while tools run
            partial_text = "".join(b.text for b in text_blocks)
            if partial_text:
                response_placeholder.markdown(partial_text + "\n\n*Running calculations…*")

            # Execute tools
            tool_results = []
            for tb in tool_use_blocks:
                result_text = _run_tool(tb.name, tb.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tb.id,
                    "content": result_text,
                })

            # Add assistant message + tool results to loop
            loop_messages.append({"role": "assistant", "content": final_msg.content})
            loop_messages.append({"role": "user", "content": tool_results})

        else:
            # Exceeded max iterations
            response_placeholder.markdown(full_response or "I wasn't able to complete the calculation. Please try rephrasing.")

    st.session_state["ai_messages"].append({"role": "assistant", "content": full_response})
