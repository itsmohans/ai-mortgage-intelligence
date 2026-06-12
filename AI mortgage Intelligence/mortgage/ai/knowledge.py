"""
mortgage/ai/knowledge.py
=========================
Curated Canadian mortgage knowledge base.

Each entry is a dict with:
  - id       : unique slug
  - category : topic grouping
  - title    : short heading
  - content  : the knowledge chunk (2-6 sentences, self-contained)

These chunks are embedded into ChromaDB at startup and retrieved at query time
to ground the AI Advisor's answers in accurate Canadian mortgage policy.
"""

from __future__ import annotations

KNOWLEDGE_CHUNKS: list[dict] = [

    # ── INTEREST COMPOUNDING ──────────────────────────────────────────────────

    {
        "id": "compounding_semi_annual",
        "category": "Interest Calculation",
        "title": "Canadian Semi-Annual Compounding Rule",
        "content": (
            "Under the Canadian Interest Act, mortgage interest must be compounded "
            "no more frequently than semi-annually (twice per year). This differs from "
            "the US convention of monthly compounding. The effective monthly rate is "
            "calculated as: monthly_rate = (1 + annual_rate / 2)^(1/6) - 1. "
            "This means the advertised annual rate on a Canadian mortgage is a "
            "nominal rate compounded semi-annually, not an effective annual rate."
        ),
    },
    {
        "id": "actual_365_daycount",
        "category": "Interest Calculation",
        "title": "Actual/365 Day-Count Convention",
        "content": (
            "Canadian mortgages use the Actual/365 day-count convention for interest "
            "accrual. Interest for any period is calculated as: "
            "interest = balance × (annual_rate / 365) × actual_days_in_period. "
            "This means February generates less interest than March even at the same "
            "rate because it has fewer calendar days. Monthly payments therefore vary "
            "slightly from month to month in the amount attributed to interest vs principal."
        ),
    },
    {
        "id": "interest_adjustment_date",
        "category": "Interest Calculation",
        "title": "Interest Adjustment Date (IAD)",
        "content": (
            "When a mortgage is disbursed mid-month, the lender collects 'interest "
            "adjustment' for the period from the disbursement date to the first regular "
            "payment date. This stub-period interest is typically collected at closing "
            "and does not change the outstanding mortgage balance. For example, a "
            "mortgage disbursed May 21 with payments on the 1st of each month would "
            "have an interest adjustment for May 21 to June 1 (11 days). Regular "
            "monthly amortization then begins from June 1."
        ),
    },

    # ── PREPAYMENT PRIVILEGES ─────────────────────────────────────────────────

    {
        "id": "prepayment_privilege_overview",
        "category": "Prepayment",
        "title": "Annual Prepayment Privilege",
        "content": (
            "Most closed Canadian mortgages allow an annual lump-sum prepayment "
            "privilege of 10–20% of the original principal per calendar year, penalty-free. "
            "The exact percentage depends on the lender and mortgage contract. "
            "The limit resets on January 1 each year and unused room does not carry forward. "
            "Exceeding the prepayment limit triggers a prepayment penalty, typically "
            "the greater of 3 months' interest or the Interest Rate Differential (IRD)."
        ),
    },
    {
        "id": "prepayment_penalty_ird",
        "category": "Prepayment",
        "title": "Prepayment Penalty — IRD vs 3 Months Interest",
        "content": (
            "For fixed-rate mortgages broken early or prepaid beyond the annual privilege, "
            "the penalty is the greater of: (a) 3 months' interest on the amount prepaid, "
            "or (b) the Interest Rate Differential (IRD). The IRD compensates the lender "
            "for the difference between your contracted rate and the current rate for a "
            "term matching your remaining term. IRD penalties can be very large when "
            "rates have fallen significantly since you signed. Variable-rate mortgages "
            "typically only face a 3-months' interest penalty."
        ),
    },
    {
        "id": "payment_increase_privilege",
        "category": "Prepayment",
        "title": "Monthly Payment Increase Privilege",
        "content": (
            "In addition to lump-sum prepayments, most Canadian closed mortgages allow "
            "borrowers to increase their regular monthly payment by 10–20% per year "
            "without penalty. This is separate from the lump-sum prepayment limit. "
            "Increasing the payment accelerates principal repayment and reduces total "
            "interest paid. The increased payment must typically be set at the time of "
            "renewal or by contacting the lender — it cannot be arbitrarily changed "
            "mid-term without penalty."
        ),
    },
    {
        "id": "open_vs_closed_mortgage",
        "category": "Prepayment",
        "title": "Open vs Closed Mortgages",
        "content": (
            "An open mortgage allows the borrower to repay any amount at any time without "
            "penalty, but typically carries a higher interest rate (0.5–1.5% premium). "
            "A closed mortgage has prepayment restrictions and penalties but offers lower "
            "rates. Most Canadian homeowners choose closed mortgages. Open mortgages make "
            "sense if you expect to sell or refinance within the term, receive a large "
            "inheritance or bonus, or want maximum flexibility regardless of cost."
        ),
    },

    # ── STRESS TEST & QUALIFICATION ──────────────────────────────────────────

    {
        "id": "osfi_b20_stress_test",
        "category": "Qualification & Stress Test",
        "title": "OSFI B-20 Mortgage Stress Test",
        "content": (
            "Since January 2018, federally regulated lenders must qualify borrowers at "
            "the higher of: (a) the Bank of Canada's 5-year benchmark rate, or "
            "(b) the contracted mortgage rate plus 2%. This stress test applies to all "
            "insured and uninsured mortgages, including renewals at a new lender. "
            "The stress test reduces the maximum mortgage amount a borrower qualifies for "
            "by roughly 20% compared to qualifying at the contracted rate alone. "
            "It does not apply when renewing with your current lender at the same amount."
        ),
    },
    {
        "id": "gds_tds_ratios",
        "category": "Qualification & Stress Test",
        "title": "GDS and TDS Ratios",
        "content": (
            "Lenders use two debt-service ratios to assess affordability. "
            "Gross Debt Service (GDS) ratio = (mortgage payment + property tax + heat + "
            "50% of condo fees) / gross monthly income. Maximum GDS is typically 39%. "
            "Total Debt Service (TDS) ratio = GDS + all other debt payments / gross monthly income. "
            "Maximum TDS is typically 44%. Both ratios are calculated using the stress-test "
            "qualifying rate, not the actual contracted rate."
        ),
    },

    # ── CMHC & MORTGAGE INSURANCE ─────────────────────────────────────────────

    {
        "id": "cmhc_insurance_overview",
        "category": "CMHC & Insurance",
        "title": "CMHC Mortgage Default Insurance",
        "content": (
            "Mortgage default insurance (from CMHC, Sagen, or Canada Guaranty) is "
            "mandatory for mortgages with less than 20% down payment. The insurance "
            "premium is added to the mortgage principal and ranges from 2.80% (10–14.99% "
            "down) to 4.00% (5–9.99% down). Insured mortgages are capped at a purchase "
            "price of $1.5 million (as of 2024 rules). The maximum amortization for "
            "insured mortgages is 25 years."
        ),
    },
    {
        "id": "cmhc_insurance_premiums",
        "category": "CMHC & Insurance",
        "title": "CMHC Premium Rates by Down Payment",
        "content": (
            "CMHC mortgage insurance premiums as of 2024: "
            "5–9.99% down payment: 4.00% of mortgage amount. "
            "10–14.99% down payment: 3.10% of mortgage amount. "
            "15–19.99% down payment: 2.80% of mortgage amount. "
            "20%+ down payment: No insurance required (conventional mortgage). "
            "The premium is added to the mortgage balance and amortized over the mortgage term. "
            "Provincial sales tax (PST) is charged on the premium in some provinces."
        ),
    },
    {
        "id": "amortization_limits",
        "category": "CMHC & Insurance",
        "title": "Maximum Amortization Periods",
        "content": (
            "For insured mortgages (less than 20% down), the maximum amortization is "
            "25 years for existing homes and 30 years for newly constructed homes "
            "(a 2024 policy update for first-time buyers). For uninsured conventional "
            "mortgages (20%+ down payment), federally regulated lenders typically allow "
            "up to 30 years. Some credit unions and alternative lenders allow 35-year "
            "amortizations for conventional mortgages. Longer amortizations reduce "
            "monthly payments but significantly increase lifetime interest paid."
        ),
    },

    # ── RENEWAL & PORTING ────────────────────────────────────────────────────

    {
        "id": "renewal_process",
        "category": "Renewal & Porting",
        "title": "Mortgage Renewal Process in Canada",
        "content": (
            "Canadian mortgages renew at the end of each term (typically 1–5 years) "
            "until the mortgage is fully amortized. At renewal, the borrower and lender "
            "renegotiate the rate and term. Lenders must send a renewal statement at "
            "least 21 days before the term ends. Borrowers can switch lenders at renewal "
            "penalty-free, though the stress test applies when switching to a new federally "
            "regulated lender. Staying with the same lender is simpler but may not offer "
            "the best rate — shopping the market often yields better terms."
        ),
    },
    {
        "id": "porting_mortgage",
        "category": "Renewal & Porting",
        "title": "Porting a Mortgage",
        "content": (
            "Porting allows you to transfer your existing mortgage — including its rate "
            "and terms — to a new property when you move. This is useful if your current "
            "rate is lower than current market rates. Most lenders allow porting, but "
            "conditions apply: the new property must be approved, you typically have "
            "60–120 days to port, and you must qualify under current rules. If you need "
            "additional funds for the new purchase, the extra amount is typically advanced "
            "at the current market rate and blended with your ported rate."
        ),
    },
    {
        "id": "blend_extend",
        "category": "Renewal & Porting",
        "title": "Blend-and-Extend",
        "content": (
            "Blend-and-extend allows you to break your current mortgage mid-term and "
            "blend your existing rate with the current market rate into a new term, "
            "avoiding or reducing the prepayment penalty. The blended rate is typically "
            "a weighted average of your current rate and the new rate. This makes sense "
            "when current rates are significantly lower than your contracted rate and the "
            "penalty would otherwise be large. The new term is usually set at 5 years, "
            "resetting your amortization clock."
        ),
    },
    {
        "id": "term_selection_strategy",
        "category": "Renewal & Porting",
        "title": "Choosing the Right Mortgage Term",
        "content": (
            "The choice between short terms (1–2 years) and long terms (4–5 years) "
            "involves a trade-off between rate certainty and flexibility. "
            "Short terms make sense when rates are expected to fall (you'll renew at lower rates) "
            "or when you plan to sell or make large prepayments within 1–2 years. "
            "Long terms make sense when rates are expected to rise or when you want "
            "payment certainty for budgeting. Historically in Canada, a sequence of "
            "short terms has often been cheaper than long terms, but this varies with "
            "the rate environment."
        ),
    },

    # ── VARIABLE RATE MORTGAGES ───────────────────────────────────────────────

    {
        "id": "variable_rate_overview",
        "category": "Variable Rate",
        "title": "Variable-Rate Mortgages in Canada",
        "content": (
            "Variable-rate mortgages (VRM) in Canada are priced as Prime Rate ± a spread "
            "(e.g., Prime - 0.50%). The Bank of Canada sets the overnight rate, which "
            "directly influences the Prime Rate set by chartered banks (typically Prime = "
            "overnight rate + 2.20%). When Prime changes, the interest portion of the "
            "payment changes. In a traditional VRM, the total payment stays the same "
            "but the split between interest and principal changes. In an adjustable-rate "
            "mortgage (ARM), the payment itself changes with Prime."
        ),
    },
    {
        "id": "trigger_rate",
        "category": "Variable Rate",
        "title": "Trigger Rate on Variable Mortgages",
        "content": (
            "The trigger rate is the interest rate at which your fixed variable-rate "
            "mortgage payment no longer covers the interest owed, causing the balance "
            "to grow (negative amortization). When this happens, lenders typically "
            "require the borrower to increase their payment, make a lump-sum payment, "
            "or convert to a fixed rate. Many Canadian VRM holders hit their trigger rates "
            "during the 2022–2023 Bank of Canada rate-hiking cycle. The trigger rate can "
            "be calculated as: trigger_rate = regular_payment / (balance / 12)."
        ),
    },

    # ── TAX & FIRST-TIME BUYER PROGRAMS ──────────────────────────────────────

    {
        "id": "first_home_savings_account",
        "category": "Government Programs",
        "title": "First Home Savings Account (FHSA)",
        "content": (
            "The First Home Savings Account (FHSA), launched in 2023, allows first-time "
            "homebuyers to save up to $8,000 per year (lifetime limit $40,000) in a "
            "tax-sheltered account. Contributions are tax-deductible like an RRSP, and "
            "withdrawals for a qualifying home purchase are tax-free like a TFSA. "
            "Unused room carries forward (up to $8,000 extra per year). The account "
            "must be opened before making a qualifying home purchase."
        ),
    },
    {
        "id": "rrsp_home_buyers_plan",
        "category": "Government Programs",
        "title": "RRSP Home Buyers' Plan (HBP)",
        "content": (
            "The RRSP Home Buyers' Plan allows first-time homebuyers to withdraw up to "
            "$35,000 from their RRSP (per person, so $70,000 for couples) tax-free for "
            "a qualifying home purchase. The withdrawn amount must be repaid to the RRSP "
            "over 15 years (1/15th per year), or the unpaid amount is added to income. "
            "The RRSP funds must have been in the account for at least 90 days before "
            "withdrawal. The HBP can be combined with the FHSA."
        ),
    },
    {
        "id": "first_time_buyer_tax_credit",
        "category": "Government Programs",
        "title": "First-Time Home Buyers' Tax Credit",
        "content": (
            "First-time homebuyers in Canada can claim a $10,000 non-refundable tax credit "
            "on their federal income tax return in the year they purchase a qualifying home. "
            "At a 15% federal tax rate, this saves up to $1,500 in taxes. The credit is "
            "split between spouses if applicable. You are considered a first-time buyer if "
            "neither you nor your spouse has owned a home that you lived in during the "
            "current year or the four preceding calendar years."
        ),
    },

    # ── REFINANCING ───────────────────────────────────────────────────────────

    {
        "id": "refinancing_overview",
        "category": "Refinancing",
        "title": "Refinancing a Canadian Mortgage",
        "content": (
            "Refinancing replaces your current mortgage with a new one, typically to "
            "access home equity, consolidate debt, or get a better rate. You can refinance "
            "up to 80% of your home's appraised value (loan-to-value ratio). "
            "Refinancing mid-term triggers a prepayment penalty. Costs include the penalty, "
            "legal fees ($1,000–$2,000), appraisal fees (~$300), and potentially a new "
            "CMHC premium if LTV exceeds 80%. A breakeven analysis should compare penalty "
            "costs against interest savings from the new rate."
        ),
    },
    {
        "id": "heloc",
        "category": "Refinancing",
        "title": "Home Equity Line of Credit (HELOC)",
        "content": (
            "A HELOC allows you to borrow against your home equity at a variable rate "
            "(typically Prime + 0.5%) up to 65% of your home's appraised value. "
            "Combined with a mortgage, the total borrowing cannot exceed 80% LTV. "
            "HELOCs are revolving — you can borrow, repay, and re-borrow. Interest is "
            "charged only on the amount drawn. A HELOC does not require regular principal "
            "repayments (interest-only is allowed), which can be a debt-management risk. "
            "HELOCs are popular for renovations, investments, or emergency funds."
        ),
    },

    # ── STRATEGY & OPTIMIZATION ───────────────────────────────────────────────

    {
        "id": "accelerated_payments",
        "category": "Strategy",
        "title": "Accelerated Bi-Weekly vs Monthly Payments",
        "content": (
            "Switching from monthly to accelerated bi-weekly payments is one of the "
            "easiest ways to save interest. Accelerated bi-weekly = monthly payment / 2, "
            "paid every two weeks. This results in 26 payments per year — equivalent to "
            "13 monthly payments instead of 12. The extra month's payment each year goes "
            "entirely to principal, typically saving 2–3 years on a 25-year amortization "
            "and tens of thousands in interest. Most lenders allow this option at no charge."
        ),
    },
    {
        "id": "lump_sum_timing",
        "category": "Strategy",
        "title": "Optimal Timing for Lump-Sum Prepayments",
        "content": (
            "Lump-sum prepayments have the greatest impact when made early in the "
            "amortization period, because the interest savings compound over more years. "
            "A $10,000 prepayment in year 1 saves more than the same prepayment in year 10. "
            "In Canada, the annual prepayment privilege (typically 10–20%) resets each "
            "January 1, so making a prepayment in December and again in January maximizes "
            "the total you can prepay in a short window. Always verify your remaining "
            "prepayment room before making a lump sum to avoid penalties."
        ),
    },
    {
        "id": "invest_vs_prepay",
        "category": "Strategy",
        "title": "Invest vs Prepay: Decision Framework",
        "content": (
            "The invest-vs-prepay decision compares the after-tax return on investments "
            "against the after-tax cost of mortgage debt. If your mortgage rate is 5% and "
            "your expected investment return is 7% on a tax-sheltered account (TFSA/RRSP), "
            "investing wins mathematically. However, mortgage prepayment offers a guaranteed "
            "risk-free return equal to your mortgage rate, while investment returns are "
            "uncertain. Risk tolerance, remaining amortization, and tax situation all "
            "affect the decision. Many Canadians choose a balanced approach: maximize "
            "RRSP/TFSA contributions first, then prepay the mortgage."
        ),
    },
]
