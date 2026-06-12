# 🏠 AI Mortgage Intelligence

[![GitHub](https://img.shields.io/badge/GitHub-itsmohans%2Fai--mortgage--intelligence-blue?logo=github)](https://github.com/itsmohans/ai-mortgage-intelligence)
![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35+-red?logo=streamlit)
![License](https://img.shields.io/badge/License-MIT-green)

A personal mortgage decision-support tool built with **Python**, **Streamlit**, and the **Claude AI API**. It takes your exact mortgage data as inputs through the UI, runs all calculations in code, and gives you a clear, interactive view of your mortgage — past, present, and future.

---

## ✨ Features

### Mortgage Setup
- Enter your mortgage principal, start date, amortization period, lender, and payment day
- Define multiple renewal terms (fixed or variable rate), including a **first payment date** for capitalised interest periods
- Record variable-rate changes within a term
- Add one-time, monthly, and annual prepayments with optional end dates

### Dashboard (12 Charts)
| # | Chart | Insight |
|---|-------|---------|
| 1 | Outstanding Balance Over Time | Actual vs projected balance curve |
| 2 | Equity Built vs Remaining Balance | Stacked area showing ownership growth |
| 3 | Payoff Progress Gauge | % of mortgage paid off to date |
| 4 | Principal vs Interest Split | How each monthly payment is allocated |
| 5 | Cumulative Interest Paid | Running total of interest cost |
| 6 | Annual Payment Breakdown | Yearly interest + principal + prepayments |
| 7 | Balance: With vs Without Prepayments | Impact of prepayments on balance curve |
| 8 | Interest Saved by Prepayments | Total interest and months saved |
| 9 | Interest Rate History | Step chart of rate changes over time |
| 10 | Term Comparison at Renewal | Monthly payment vs interest vs balance for 1–5yr options |
| 11 | Year-End Balance | One balance data point per calendar year |
| 12 | Interest vs Principal Ratio by Year | How the split shifts over 30 years |

### Amortization Schedule
- Full month-by-month schedule (up to 360 rows)
- Filter by term and year
- Four color-coded row types:
  - 🟡 **Amber** — Interest Adjustment Period (partial month at disbursement; balance unchanged)
  - 🟠 **Orange** — Capitalised Interest Period (no payment collected; interest added to balance)
  - 🟢 **Green** — Actual historical payments
  - 🔵 **Blue** — Projected future payments
- CSV export

### AI Advisor (V3 + V4)
- Natural language Q&A about your mortgage, powered by **Claude (claude-sonnet)**
- Answers are grounded in your live amortization schedule, balance, rate history, and prepayments
- **RAG pipeline**: retrieves the most relevant chunks from a curated Canadian mortgage knowledge base before each Claude call, so answers reflect Canadian-specific rules (stress test, CMHC, semi-annual compounding, prepayment privileges, etc.)
- Sidebar shows which knowledge sources were used for each answer, with similarity scores

---

## 🏗️ Architecture

```
AI mortgage Intelligence/
├── app/
│   ├── main.py                 # Home page / KPI summary
│   ├── state.py                # Streamlit session state + schedule cache
│   └── pages/
│       ├── 01_Setup.py         # Mortgage data entry
│       ├── 02_Dashboard.py     # All 12 charts
│       ├── 03_Amortization.py  # Full schedule table
│       └── 04_AI_Advisor.py    # Claude AI chat + RAG
├── mortgage/
│   ├── models/
│   │   └── entities.py         # Dataclasses: Mortgage, MortgageTerm, events, schedule
│   ├── engine/
│   │   ├── amortization.py     # Core schedule generator (Actual/365, event-driven)
│   │   ├── renewal.py          # PMT calculator (semi-annual + bank monthly_simple modes)
│   │   └── analytics.py        # Prepayment impact, payment increase impact, YTD
│   ├── ai/
│   │   ├── knowledge.py        # 25 curated Canadian mortgage knowledge chunks
│   │   └── retrieval.py        # ChromaDB + sentence-transformers RAG retrieval
│   └── storage/
│       ├── database.py         # SQLAlchemy Core table definitions + engine
│       └── repository.py       # Repository pattern — all DB reads/writes
├── tests/
│   ├── test_engine.py          # Amortization engine tests
│   └── test_storage.py         # Repository/storage tests
├── data/                       # SQLite database (gitignored)
├── .env                        # ANTHROPIC_API_KEY (gitignored)
├── requirements.txt
├── run.bat                     # Windows launcher
└── README.md
```

---

## 🔢 Calculation Design

### Canadian Mortgage Convention
Interest is compounded **semi-annually** (not monthly), as required by the Canadian Interest Act:

```
monthly_rate = (1 + annual_rate / 2) ^ (1/6) - 1
PMT = principal × monthly_rate / (1 − (1 + monthly_rate) ^ −n)
```

Some lenders compute the payment using `rate / 12` (simple monthly). The engine supports both via the `compounding` parameter — use `"monthly_simple"` to match your bank's statement exactly.

### Actual/365 Day-Count
Interest accrues daily using actual calendar days between payments:

```
interest = balance × (annual_rate / 365) × actual_days
```

### Interest Adjustment Period (IAD)
When the disbursement date doesn't fall on the regular payment day, a partial first month accrues interest without a payment. This is recorded as an amber row with no balance change.

### Capitalised Interest Period
When a lender collects interest at closing and the first regular payment is deferred beyond the first full month, each interim month accrues interest that is added to the outstanding balance (the balance grows). These are recorded as orange rows. Set the **First Payment Date** on a term to model this.

### Event-Driven Engine
The amortization engine is built around an event log:
- **RateChangeEvent** — records every rate change within a variable-rate term
- **PrepaymentEvent** — supports one-time, monthly, and annual recurrence with optional end dates

The engine replays all events chronologically to produce the full schedule. No Excel file is read at runtime — all inputs come from the Streamlit UI.

### Prepayment Privilege
The lender's annual prepayment limit (default 20% of original principal) is enforced per calendar year.

---

## 🤖 RAG Knowledge Base (V4)

The AI Advisor uses a **Retrieval-Augmented Generation** pipeline to answer Canadian mortgage questions accurately:

- **25 knowledge chunks** across 8 categories: interest calculation, prepayment rules, qualification (OSFI B-20 stress test, GDS/TDS), CMHC insurance, renewal & porting, variable rate mortgages, government programs (FHSA, RRSP HBP, FTHB tax credit), and strategy
- **Embedding model**: `all-MiniLM-L6-v2` via `sentence-transformers`
- **Vector store**: ChromaDB in-memory with cosine similarity
- On each query, the top-4 most relevant chunks are injected into Claude's system prompt alongside your live mortgage data

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- pip
- An [Anthropic API key](https://console.anthropic.com/) (for the AI Advisor)

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure AI (optional — required for AI Advisor only)

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=your-key-here
```

This file is gitignored and never committed.

### Run the app

**Windows:**
```bat
run.bat
```

**Mac / Linux:**
```bash
cd "AI mortgage Intelligence"
python -m streamlit run app/main.py
```

The app opens at `http://localhost:8501`.

### First-time setup
1. Go to **Setup → Mortgage Details** and save your mortgage.
2. Go to **Setup → Terms** and add your renewal terms. If your first payment was deferred (capitalised interest), set the **First Payment Date**.
3. Go to **Setup → Rate Changes** to record variable-rate changes (if applicable).
4. Go to **Setup → Prepayments** to add any lump-sum or recurring prepayments.
5. View your **Dashboard** and **Amortization Schedule**.
6. Ask questions in the **AI Advisor**.

---

## 🧪 Running Tests

```bash
cd "AI mortgage Intelligence"
python -m pytest tests/ -v
```

Tests cover the amortization engine, renewal calculator, analytics, and storage layer.

---

## 🗺️ Roadmap

| Version | Feature |
|---------|---------|
| ✅ V1 | Core amortization engine + Streamlit UI |
| ✅ V2 | Dashboard with 12 charts + Amortization table |
| ✅ V3 | Claude AI integration — natural language Q&A about your mortgage |
| ✅ V4 | RAG pipeline — Canadian mortgage knowledge base + amortization alignment |
| 🔜 V5 | Personal Financial Planning Assistant |

---

## ⚠️ Disclaimer

This tool is for personal financial planning and educational purposes only. It does not constitute financial or legal advice. Always consult a licensed mortgage professional before making decisions.

---

## 📄 License

MIT License — free to use, modify, and distribute.
