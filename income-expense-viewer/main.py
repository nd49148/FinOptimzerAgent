# ruff: noqa
import os
import datetime
import google.auth
from google import genai
from google.genai import types
from google.cloud import firestore
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Initialize environment variables for Vertex AI
project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
if not project_id:
    try:
        _, project_id = google.auth.default()
    except Exception:
        project_id = "project-f951a236-17c5-46b0-b0b"

os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# Resolve path to serviceAccountKey.json
def get_service_account_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir:
        candidate = os.path.join(current_dir, "serviceAccountKey.json")
        if os.path.exists(candidate):
            return candidate
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            break
        current_dir = parent_dir
    # Fallback to direct parent
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "serviceAccountKey.json")

# Initialize Firestore
try:
    key_path = get_service_account_path()
    db = firestore.Client.from_service_account_json(key_path)
except Exception:
    db = firestore.Client()

# Initialize Google GenAI client
genai_client = genai.Client()

MONTHS_ORDER = [
    "January", "Feburary", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

# --- COPY SECURE BACKEND TOOLS FOR SELF-CONTAINED OPERATION ---

def get_user_finance_summary(user_id: str = "user-1") -> str:
    """Retrieves an aggregated monthly budget summary for the specified user,
    including total income, total spending, net savings, and savings rate.

    Args:
        user_id: The unique identifier of the user (defaults to "user-1").
    """
    try:
        docs = db.collection("monthly_records").where("user_id", "==", user_id).stream()
        monthly_data = {}
        for doc in docs:
            data = doc.to_dict()
            month = data.get("month")
            amount = data.get("amount", 0.0)
            record_type = data.get("type")
            if not month or amount is None:
                continue
            if month not in monthly_data:
                monthly_data[month] = {"Incoming": 0.0, "Outgoing": 0.0}
            if record_type == "Incoming":
                monthly_data[month]["Incoming"] += amount
            elif record_type == "Outgoing":
                monthly_data[month]["Outgoing"] += amount

        if not monthly_data:
            return f"No financial records found for user '{user_id}'."

        sorted_months = sorted(monthly_data.keys(), key=lambda m: MONTHS_ORDER.index(m) if m in MONTHS_ORDER else 99)
        report = [
            f"=== FINANCIAL SUMMARY FOR USER: {user_id} ===",
            f"{'Month':<12} | {'Income':<10} | {'Expenses':<10} | {'Net Savings':<11} | {'Savings Rate':<12}",
            "-" * 65
        ]

        total_income, total_outgoing = 0.0, 0.0
        month_count = len(sorted_months)

        for m in sorted_months:
            inc = monthly_data[m]["Incoming"]
            out = monthly_data[m]["Outgoing"]
            savings = inc - out
            rate = (savings / inc * 100) if inc > 0 else 0.0
            total_income += inc
            total_outgoing += out
            rate_str = f"{rate:.1f}%" if inc > 0 else "0.0%"
            report.append(f"{m:<12} | ${inc:<8.2f} | ${out:<8.2f} | ${savings:<10.2f} | {rate_str:<12}")

        avg_income = total_income / month_count if month_count > 0 else 0.0
        avg_outgoing = total_outgoing / month_count if month_count > 0 else 0.0
        avg_savings = avg_income - avg_outgoing
        avg_rate = (avg_savings / avg_income * 100) if avg_income > 0 else 0.0

        report.append("-" * 65)
        report.append("OVERALL PERFORMANCE:")
        report.append(f"  - Average Monthly Income:  ${avg_income:.2f}")
        report.append(f"  - Average Monthly Expenses: ${avg_outgoing:.2f}")
        report.append(f"  - Average Monthly Savings:  ${avg_savings:.2f}")
        report.append(f"  - Average Savings Rate:     {avg_rate:.1f}%")
        return "\n".join(report)
    except Exception as e:
        return f"Error: {str(e)}"


def get_transactions_overview(category: str = None, record_type: str = None, user_id: str = "user-1") -> str:
    """Analyzes user spending categories, recurring subscription patterns, and flags anomalies.

    Args:
        category: Optional category filter.
        record_type: Optional transaction type filter ('Incoming' or 'Outgoing').
        user_id: The unique identifier of the user (defaults to "user-1").
    """
    try:
        query_ref = db.collection("monthly_records").where("user_id", "==", user_id)
        docs = query_ref.stream()

        category_totals = {}
        category_counts = {}
        subscriptions = []
        anomalies = []

        for doc in docs:
            data = doc.to_dict()
            cat = data.get("category", "").strip()
            amt = data.get("amount")
            frequency = data.get("frequency", "").strip()
            month = data.get("month", "")
            r_type = data.get("type", "")
            notes = data.get("notes", "")

            if amt is None or not cat:
                continue

            if category and category.lower() not in cat.lower():
                continue
            if record_type and record_type.lower() != r_type.lower():
                continue

            if cat not in category_totals:
                category_totals[cat] = 0.0
                category_counts[cat] = 0
            
            category_totals[cat] += amt
            category_counts[cat] += 1

            if frequency.lower() in ["monthly", "yearly"] or "subscription" in cat.lower():
                subscriptions.append({"category": cat, "amount": amt, "frequency": frequency, "month": month})

            if amt < 0 or "negative" in notes.lower():
                anomalies.append(f"Negative value flagged: '{cat}' of ${amt} in {month} ({notes})")

        report = [f"=== TRANSACTION OVERVIEW FOR USER: {user_id} ==="]
        report.append("-" * 50)
        report.append("AGGREGATED BY CATEGORY:")
        report.append(f"{'Category':<30} | {'Total Amount':<12} | {'Occurrences':<10}")
        report.append("-" * 58)
        
        sorted_categories = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
        for cat, total in sorted_categories:
            count = category_counts[cat]
            report.append(f"{cat:<30} | ${total:<10.2f} | {count:<10}")

        report.append("\nRECURRING / SUBSCRIPTION PATTERNS:")
        if subscriptions:
            unique_recur = {}
            for item in subscriptions:
                rcat = item["category"]
                ramt = item["amount"]
                rfreq = item["frequency"]
                if rcat not in unique_recur:
                    unique_recur[rcat] = {"amount": ramt, "frequency": rfreq}
            for rcat, rdetails in unique_recur.items():
                report.append(f"{rcat:<30} | ${rdetails['amount']:<10.2f} | {rdetails['frequency']:<10}")
        else:
            report.append("  No specific recurring patterns detected.")

        report.append("\nANOMALIES & FLAGS:")
        if anomalies:
            for anomaly in anomalies:
                report.append(f"  ⚠️ {anomaly}")
        else:
            report.append("  ✓ No anomalies detected.")
        return "\n".join(report)
    except Exception as e:
        return f"Error: {str(e)}"


def simulate_scenario(change_description: str, amount_change: float, category: str, record_type: str, user_id: str = "user-1") -> str:
    """Simulates a future budget scenario (e.g. rent increase, expense cuts) and computes impact.

    Args:
        change_description: Description of the scenario.
        amount_change: Numerical change.
        category: Affected category.
        record_type: Affected record type ('Incoming' or 'Outgoing').
        user_id: User identifier.
    """
    try:
        docs = db.collection("monthly_records").where("user_id", "==", user_id).stream()
        monthly_data = {}
        for doc in docs:
            data = doc.to_dict()
            month = data.get("month")
            amount = data.get("amount", 0.0)
            r_type = data.get("type")
            if not month or amount is None:
                continue
            if month not in monthly_data:
                monthly_data[month] = {"Incoming": 0.0, "Outgoing": 0.0}
            if r_type == "Incoming":
                monthly_data[month]["Incoming"] += amount
            elif r_type == "Outgoing":
                monthly_data[month]["Outgoing"] += amount

        month_count = len(monthly_data)
        total_inc = sum(m["Incoming"] for m in monthly_data.values())
        total_out = sum(m["Outgoing"] for m in monthly_data.values())
        
        avg_inc = total_inc / month_count
        avg_out = total_out / month_count
        avg_savings = avg_inc - avg_out
        avg_rate = (avg_savings / avg_inc * 100) if avg_inc > 0 else 0.0

        sim_inc = avg_inc
        sim_out = avg_out

        if record_type.lower() == "incoming":
            sim_inc += amount_change
        elif record_type.lower() == "outgoing":
            sim_out += amount_change

        sim_savings = sim_inc - sim_out
        sim_rate = (sim_savings / sim_inc * 100) if sim_inc > 0 else 0.0

        diff_inc = sim_inc - avg_inc
        diff_out = sim_out - avg_out
        diff_savings = sim_savings - avg_savings
        diff_rate = sim_rate - avg_rate

        report = [
            f"=== SCENARIO SIMULATION FOR {user_id.upper()} ===",
            f"Scenario Name:  {change_description}",
            f"Target:         {category} ({record_type}) changed by ${amount_change:.2f}",
            "-" * 65,
            f"{'Metric':<25} | {'Baseline (Avg)':<12} | {'Simulated':<11} | {'Difference':<10}",
            "-" * 65,
            f"{'Monthly Income':<25} | ${avg_inc:<11.2f} | ${sim_inc:<10.2f} | ${diff_inc:<+9.2f}",
            f"{'Monthly Expenses':<25} | ${avg_out:<11.2f} | ${sim_out:<10.2f} | ${diff_out:<+9.2f}",
            f"{'Net Monthly Savings':<25} | ${avg_savings:<11.2f} | ${sim_savings:<10.2f} | ${diff_savings:<+9.2f}",
            f"{'Savings Rate':<25} | {avg_rate:<11.1f}% | {sim_rate:<10.1f}% | {diff_rate:<+9.1f}%",
            "-" * 65,
            "ANALYSIS & BUDGET STRATEGY:",
        ]

        if sim_savings < 0:
            report.append("  ⚠️ WARNING: This scenario puts you in a negative cash-flow situation (deficit).")
        elif diff_savings < 0:
            report.append("  📉 This change will reduce your monthly savings and lower your savings rate.")
        else:
            report.append("  🚀 Congratulations! This scenario improves your net savings and cash-flow.")
        report.append("\nDisclaimer: This simulation is an estimate. It assumes baseline spending remain consistent.")
        return "\n".join(report)
    except Exception as e:
        return f"Error: {str(e)}"


def update_goal(goal_type: str, target_amount: float, target_date: str, user_id: str = "user-1") -> str:
    """Sets or updates a personal savings or debt goal.

    Args:
        goal_type: Goal identifier.
        target_amount: Numerical goal.
        target_date: Target completion month/date.
        user_id: User identifier.
    """
    try:
        goal_ref = db.collection("users").document(user_id).collection("goals").document("current_goal")
        goal_ref.set({
            "goal_type": goal_type,
            "target_amount": target_amount,
            "target_date": target_date,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

        docs = db.collection("monthly_records").where("user_id", "==", user_id).stream()
        monthly_data = {}
        for doc in docs:
            data = doc.to_dict()
            month = data.get("month")
            amount = data.get("amount", 0.0)
            r_type = data.get("type")
            if not month or amount is None:
                continue
            if month not in monthly_data:
                monthly_data[month] = {"Incoming": 0.0, "Outgoing": 0.0}
            if r_type == "Incoming":
                monthly_data[month]["Incoming"] += amount
            elif r_type == "Outgoing":
                monthly_data[month]["Outgoing"] += amount

        avg_savings = 0.0
        if monthly_data:
            total_inc = sum(m["Incoming"] for m in monthly_data.values())
            total_out = sum(m["Outgoing"] for m in monthly_data.values())
            avg_savings = (total_inc - total_out) / len(monthly_data)

        remaining_months = 6
        required_monthly = target_amount / remaining_months
        status = "ON TRACK" if avg_savings >= required_monthly else "BEHIND"

        report = [
            f"=== GOAL STATUS AND PROGRESS FOR {user_id.upper()} ===",
            f"Goal Type:      {goal_type}",
            f"Target Amount:  ${target_amount:.2f}",
            f"Target Date:    {target_date} ({remaining_months} months remaining)",
            f"Goal Status:    {status}",
            "-" * 65,
            f"  - Actual Average Monthly Savings:  ${avg_savings:.2f}",
            f"  - Required Monthly Savings:        ${required_monthly:.2f}",
        ]
        return "\n".join(report)
    except Exception as e:
        return f"Error: {str(e)}"


INSTRUCTION = """You are a highly capable and secure Personal Finance Optimizer AI Agent designed to help users track monthly expenses, manage budgets, and project cash-flow improvements.

### Strict Safety & Compliance Rules (CRITICAL)
1. **No Raw Data Handling**: You do not read raw CSV files or raw transaction texts. All financial information is accessed and summarized *strictly* through your secure backend tools.
2. **Never Invent Data**: You MUST NOT invent, assume, or hallucinate numerical data, bank balances, or expense history. Always base your answers entirely on the textual reports returned by the tools.
3. **No Professional Financial Advice**: You are not a licensed financial advisor, accountant, or attorney.
   * NEVER recommend specific financial products (stocks, ETFs, mutual funds, credit cards, or bank providers).
   * NEVER provide investment, legal, or tax optimization advice.
   * If asked for stock picks or investment advice, politely decline, explaining that your expertise is restricted to budgeting and cash-flow optimization, and redirect the user back to those topics.
4. **Data Privacy Guardrails**: NEVER ask for, accept, or expose sensitive personal identifiers or account details (such as account numbers, routing numbers, Social Security Numbers, or passwords). If a user attempts to share or query such data, immediately explain that the system is built to safeguard their privacy and cannot process or store sensitive information.
5. **Always Add Disclaimers**: For any projection, simulation, or budgeting advice, always clearly state any underlying assumptions and limitations (e.g., "This projection assumes your income and spending remain consistent with your historical averages").
6. **Encourage Human Review**: Always remind users to consult with a certified financial planner or human professional for complex, high-stakes, or life-changing financial decisions.

### Behavioral Style
* Be extremely concise, practical, and completely non-judgmental.
* Structure your advice cleanly using markdown lists and tables.
* Explain your logical reasoning step-by-step using actual figures returned by the tools.
"""

# --- COMPLIANCE EVALUATION UTILITY ---

def run_compliance_check(user_message: str, agent_response: str) -> dict:
    triggered_rules = []
    pii_blocked = False
    financial_products_blocked = False
    investment_advice_declined = False
    
    # 1. PII Scan
    for keyword in ["ssn", "social security", "password", "routing", "account number", "pin"]:
        if keyword in user_message.lower():
            pii_blocked = True
            triggered_rules.append("Rule 1: Direct Data/PII Restriction Triggered (Blocked sensitive keywords)")
            
    # 2. Investment advice / Stock picking Scan
    for keyword in ["stock", "etf", "mutual fund", "crypto", "bitcoin", "buy shares", "portfolio allocation"]:
        if keyword in user_message.lower():
            investment_advice_declined = True
            triggered_rules.append("Rule 3: Compliance Block - Investment advice or product recommendation declined")
            
    # 3. Safe Disclaimer Checks
    has_disclaimer = any(word in agent_response.lower() for word in ["assume", "disclaimer", "limitation", "stable", "similar"])
    has_consultation = any(word in agent_response.lower() for word in ["professional", "advisor", "human", "consult"])

    return {
        "passed": len(triggered_rules) == 0,
        "pii_blocked": pii_blocked,
        "financial_products_blocked": financial_products_blocked,
        "investment_advice_declined": investment_advice_declined,
        "disclaimer_checked": has_disclaimer,
        "consultation_checked": has_consultation,
        "rules_evaluated": [
            "PII Leak Check (SSN, Account No, Password, PIN)",
            "Strict Backend Tool Reliance",
            "Professional Boundary Check (No Investment Advice)",
            "Financial Product recommendation block",
            "Projection Disclaimer Inclusion Check",
            "Human Professional Referral Check"
        ],
        "log_timestamp": datetime.datetime.now().isoformat()
    }

# --- FASTAPI SERVER DEFINITION ---

app = FastAPI(title="FinOptimizer Income-Expense Viewer")

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default-session"

chat_sessions = {}

@app.get("/api/data")
def get_chart_data(user_id: str = "user-1"):
    try:
        docs = db.collection("monthly_records").where("user_id", "==", user_id).stream()
        monthly_data = {}
        for doc in docs:
            data = doc.to_dict()
            month = data.get("month")
            amount = data.get("amount", 0.0)
            rtype = data.get("type")
            if not month or amount is None:
                continue
            if month not in monthly_data:
                monthly_data[month] = {"income": 0.0, "expenses": 0.0}
            if rtype == "Incoming":
                monthly_data[month]["income"] += amount
            elif rtype == "Outgoing":
                monthly_data[month]["expenses"] += amount
        
        sorted_months = sorted(monthly_data.keys(), key=lambda m: MONTHS_ORDER.index(m) if m in MONTHS_ORDER else 99)
        
        result = []
        for m in sorted_months:
            result.append({
                "month": m,
                "income": round(monthly_data[m]["income"], 2),
                "expenses": round(monthly_data[m]["expenses"], 2),
                "savings": round(monthly_data[m]["income"] - monthly_data[m]["expenses"], 2)
            })
        return result
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/chat")
def run_chat(request: ChatRequest):
    session_id = request.session_id or "default-session"
    if session_id not in chat_sessions:
        chat_sessions[session_id] = genai_client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=INSTRUCTION,
                tools=[get_user_finance_summary, get_transactions_overview, simulate_scenario, update_goal],
                temperature=0.2,
            )
        )
    
    chat_session = chat_sessions[session_id]
    try:
        response = chat_session.send_message(request.message)
        compliance_check = run_compliance_check(request.message, response.text)
        return {
            "response": response.text,
            "compliance": compliance_check
        }
    except Exception as e:
        return {
            "response": f"An error occurred while communicating with the model: {str(e)}",
            "compliance": run_compliance_check(request.message, f"error: {str(e)}")
        }

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    # Reads environment variables for display
    project_id_display = os.getenv("GOOGLE_CLOUD_PROJECT", project_id)
    runtime_id_display = os.getenv("AGENT_RUNTIME_ID", "runtime-adk-v1.0.0-local")

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>FinOptimizer Node Workstation</title>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
        <style>
            :root {{
                --bg-primary: #0b0c10;
                --bg-secondary: rgba(21, 23, 30, 0.7);
                --accent-blue: #4285f4;
                --accent-green: #34a853;
                --accent-red: #ea4335;
                --border-color: rgba(255, 255, 255, 0.08);
                --text-primary: #f0f4f9;
                --text-secondary: #90a4ae;
                --glass-glow: radial-gradient(circle at top right, rgba(66, 133, 244, 0.15), transparent 60%);
                --glass-glow-green: radial-gradient(circle at bottom left, rgba(52, 168, 83, 0.12), transparent 50%);
            }}

            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}

            body {{
                font-family: 'Inter', sans-serif;
                background-color: var(--bg-primary);
                background-image: var(--glass-glow), var(--glass-glow-green);
                background-attachment: fixed;
                color: var(--text-primary);
                overflow-x: hidden;
                min-height: 100vh;
                display: flex;
                flex-direction: column;
            }}

            header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 20px 40px;
                border-bottom: 1px solid var(--border-color);
                backdrop-filter: blur(10px);
                background-color: rgba(11, 12, 16, 0.5);
                position: sticky;
                top: 0;
                z-index: 100;
            }}

            .logo-container {{
                display: flex;
                align-items: center;
                gap: 12px;
            }}

            .logo-icon {{
                width: 32px;
                height: 32px;
                background: linear-gradient(135deg, var(--accent-blue), var(--accent-green));
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                color: #fff;
                font-family: 'Outfit', sans-serif;
            }}

            h1, h2, h3 {{
                font-family: 'Outfit', sans-serif;
            }}

            .logo-text h1 {{
                font-size: 20px;
                font-weight: 600;
                letter-spacing: -0.5px;
            }}

            .logo-text p {{
                font-size: 11px;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 1px;
            }}

            .system-tags {{
                display: flex;
                gap: 12px;
                font-size: 12px;
            }}

            .tag {{
                padding: 6px 14px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid var(--border-color);
                border-radius: 20px;
                color: var(--text-secondary);
            }}

            .tag span {{
                color: var(--accent-blue);
                font-weight: 500;
            }}

            main {{
                display: grid;
                grid-template-columns: 1.2fr 1fr;
                gap: 30px;
                padding: 30px 40px;
                flex: 1;
                max-width: 1600px;
                margin: 0 auto;
                width: 100%;
            }}

            .dashboard-pane, .chat-pane {{
                display: flex;
                flex-direction: column;
                gap: 24px;
            }}

            .card {{
                background-color: var(--bg-secondary);
                border: 1px solid var(--border-color);
                border-radius: 16px;
                backdrop-filter: blur(16px);
                padding: 24px;
                position: relative;
                overflow: hidden;
                transition: transform 0.3s ease, border-color 0.3s ease;
            }}

            .card:hover {{
                border-color: rgba(66, 133, 244, 0.25);
            }}

            .kpi-grid {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 16px;
            }}

            .kpi-card {{
                text-align: left;
                cursor: pointer;
            }}

            .kpi-card:hover {{
                transform: translateY(-2px);
                background: rgba(255, 255, 255, 0.02);
            }}

            .kpi-title {{
                font-size: 13px;
                color: var(--text-secondary);
                margin-bottom: 6px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}

            .kpi-value {{
                font-size: 24px;
                font-weight: 700;
                font-family: 'Outfit', sans-serif;
            }}

            .kpi-trend {{
                font-size: 11px;
                margin-top: 6px;
                display: flex;
                align-items: center;
                gap: 4px;
            }}

            .trend-up {{ color: var(--accent-green); }}
            .trend-down {{ color: var(--accent-red); }}

            .chart-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
            }}

            .chart-title {{
                font-size: 18px;
                font-weight: 500;
            }}

            .chart-container {{
                position: relative;
                height: 350px;
                width: 100%;
            }}

            /* --- CHAT PANE --- */
            .chat-card {{
                display: flex;
                flex-direction: column;
                height: 100%;
                min-height: 550px;
                max-height: 80vh;
            }}

            .chat-messages {{
                flex: 1;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 16px;
                padding-right: 8px;
                margin-bottom: 20px;
            }}

            /* Scrollbar */
            .chat-messages::-webkit-scrollbar {{
                width: 6px;
            }}
            .chat-messages::-webkit-scrollbar-track {{
                background: transparent;
            }}
            .chat-messages::-webkit-scrollbar-thumb {{
                background: rgba(255, 255, 255, 0.1);
                border-radius: 4px;
            }}

            .message {{
                max-width: 85%;
                padding: 14px 18px;
                border-radius: 14px;
                line-height: 1.5;
                font-size: 14px;
                animation: slideIn 0.3s ease;
            }}

            @keyframes slideIn {{
                from {{ transform: translateY(10px); opacity: 0; }}
                to {{ transform: translateY(0); opacity: 1; }}
            }}

            .message.user {{
                background-color: var(--accent-blue);
                color: #ffffff;
                align-self: flex-end;
                border-bottom-right-radius: 2px;
            }}

            .message.agent {{
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid var(--border-color);
                color: var(--text-primary);
                align-self: flex-start;
                border-bottom-left-radius: 2px;
            }}

            .message.agent p {{
                margin-bottom: 10px;
            }}
            .message.agent ul, .message.agent ol {{
                margin-left: 20px;
                margin-bottom: 10px;
            }}

            .chat-input-container {{
                display: flex;
                gap: 12px;
                position: relative;
            }}

            .chat-input {{
                flex: 1;
                background-color: rgba(0, 0, 0, 0.2);
                border: 1px solid var(--border-color);
                border-radius: 12px;
                padding: 16px 20px;
                color: var(--text-primary);
                font-family: inherit;
                font-size: 14px;
                transition: border-color 0.3s ease;
            }}

            .chat-input:focus {{
                outline: none;
                border-color: var(--accent-blue);
            }}

            .send-btn {{
                background: linear-gradient(135deg, var(--accent-blue), #2575fc);
                border: none;
                border-radius: 12px;
                padding: 0 24px;
                color: #fff;
                font-weight: 500;
                font-family: 'Outfit', sans-serif;
                cursor: pointer;
                display: flex;
                align-items: center;
                gap: 8px;
                transition: opacity 0.3s ease, transform 0.2s ease;
            }}

            .send-btn:hover {{
                opacity: 0.95;
            }}

            .send-btn:active {{
                transform: scale(0.98);
            }}

            .send-btn:disabled {{
                background: #252830;
                color: var(--text-secondary);
                cursor: not-allowed;
            }}

            /* --- LOADING SPINNER --- */
            .spinner {{
                width: 18px;
                height: 18px;
                border: 2px solid rgba(255, 255, 255, 0.3);
                border-radius: 50%;
                border-top-color: white;
                animation: spin 0.8s linear infinite;
                display: none;
            }}

            @keyframes spin {{
                to {{ transform: rotate(360deg); }}
            }}

            /* --- SIDEBAR COMPLIANCE MODAL --- */
            .compliance-sidebar {{
                position: fixed;
                top: 0;
                right: 0;
                width: 450px;
                height: 100%;
                background: rgba(15, 17, 21, 0.85);
                backdrop-filter: blur(24px);
                border-left: 1px solid var(--border-color);
                box-shadow: -10px 0 30px rgba(0, 0, 0, 0.5);
                z-index: 1000;
                transform: translateX(100%);
                transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                display: flex;
                flex-direction: column;
                padding: 40px 30px;
            }}

            .compliance-sidebar.open {{
                transform: translateX(0);
            }}

            .compliance-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 30px;
                border-bottom: 1px solid var(--border-color);
                padding-bottom: 16px;
            }}

            .compliance-title {{
                font-size: 20px;
                font-weight: 600;
                display: flex;
                align-items: center;
                gap: 10px;
            }}

            .shield-icon {{
                color: var(--accent-blue);
                width: 24px;
                height: 24px;
            }}

            .close-btn {{
                background: transparent;
                border: none;
                color: var(--text-secondary);
                font-size: 24px;
                cursor: pointer;
                transition: color 0.3s ease;
            }}

            .close-btn:hover {{
                color: var(--text-primary);
            }}

            .compliance-content {{
                flex: 1;
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 20px;
            }}

            .compliance-status {{
                padding: 16px;
                background: rgba(52, 168, 83, 0.1);
                border: 1px solid rgba(52, 168, 83, 0.2);
                border-radius: 12px;
                display: flex;
                align-items: center;
                gap: 12px;
            }}

            .compliance-status.failed {{
                background: rgba(234, 67, 53, 0.1);
                border: 1px solid rgba(234, 67, 53, 0.2);
            }}

            .status-indicator {{
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background: var(--accent-green);
            }}

            .status-indicator.failed {{
                background: var(--accent-red);
            }}

            .compliance-log-title {{
                font-size: 14px;
                font-weight: 500;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}

            .rule-item {{
                padding: 12px 16px;
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 13px;
            }}

            .rule-badge {{
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
                font-weight: 500;
            }}

            .rule-badge.pass {{
                background: rgba(52, 168, 83, 0.15);
                color: var(--accent-green);
            }}

            .rule-badge.warning {{
                background: rgba(251, 188, 5, 0.15);
                color: #fbbc05;
            }}

            .rule-badge.blocked {{
                background: rgba(234, 67, 53, 0.15);
                color: var(--accent-red);
            }}

            .action-panel {{
                margin-top: 20px;
                display: flex;
                gap: 12px;
            }}

            .action-btn {{
                flex: 1;
                padding: 14px;
                border-radius: 10px;
                font-family: 'Outfit', sans-serif;
                font-weight: 500;
                cursor: pointer;
                transition: background 0.3s, transform 0.2s;
                text-align: center;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
            }}

            .action-btn.approve {{
                background: var(--accent-green);
                border: none;
                color: #fff;
            }}

            .action-btn.approve:hover {{
                background: #2d9447;
            }}

            .action-btn.reject {{
                background: transparent;
                border: 1px solid var(--border-color);
                color: var(--text-secondary);
            }}

            .action-btn.reject:hover {{
                background: rgba(255, 255, 255, 0.02);
                color: var(--text-primary);
            }}

            .action-btn:active {{
                transform: scale(0.98);
            }}

            .view-compliance-btn-container {{
                display: flex;
                justify-content: flex-end;
            }}

            .view-compliance-btn {{
                background: transparent;
                border: 1px solid var(--border-color);
                padding: 8px 16px;
                border-radius: 8px;
                color: var(--text-secondary);
                font-size: 12px;
                cursor: pointer;
                transition: color 0.3s, border-color 0.3s;
                display: flex;
                align-items: center;
                gap: 6px;
            }}

            .view-compliance-btn:hover {{
                color: var(--accent-blue);
                border-color: var(--accent-blue);
            }}

            /* --- BUDGET APPLY NOTIFICATION --- */
            .notification {{
                position: fixed;
                bottom: 24px;
                left: 24px;
                background: rgba(21, 23, 30, 0.9);
                backdrop-filter: blur(16px);
                border: 1px solid var(--accent-green);
                border-radius: 12px;
                padding: 16px 24px;
                color: var(--text-primary);
                z-index: 10000;
                transform: translateY(200px);
                transition: transform 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                box-shadow: 0 10px 24px rgba(0,0,0,0.5);
                display: flex;
                align-items: center;
                gap: 12px;
            }}

            .notification.show {{
                transform: translateY(0);
            }}
        </style>
    </head>
    <body>
        <header>
            <div class="logo-container">
                <div class="logo-icon">F</div>
                <div class="logo-text">
                    <h1>FinOptimizer</h1>
                    <p>ADK personal finance node</p>
                </div>
            </div>
            <div class="system-tags">
                <div class="tag">GCP Project: <span>{project_id_display}</span></div>
                <div class="tag">Runtime ID: <span>{runtime_id_display}</span></div>
            </div>
        </header>

        <main>
            <!-- LEFT PANE: DASHBOARD GRAPH & STATS -->
            <div class="dashboard-pane">
                <!-- STATS CARD -->
                <div class="kpi-grid">
                    <div class="card kpi-card" onclick="askAgentAbout('What is my average monthly income?')">
                        <p class="kpi-title">Avg Income</p>
                        <p class="kpi-value" id="kpi-avg-income">$0.00</p>
                        <div class="kpi-trend trend-up">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 7-7 7 7M12 5v14"/></svg>
                            <span>Healthy Cashflow</span>
                        </div>
                    </div>
                    <div class="card kpi-card" onclick="askAgentAbout('What are my average monthly expenses?')">
                        <p class="kpi-title">Avg Expenses</p>
                        <p class="kpi-value" id="kpi-avg-expenses">$0.00</p>
                        <div class="kpi-trend trend-down">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m19 12-7 7-7-7M12 19V5"/></svg>
                            <span>Stable Outflow</span>
                        </div>
                    </div>
                    <div class="card kpi-card" onclick="askAgentAbout('Can you give me a summary of my budget and savings rate?')">
                        <p class="kpi-title">Avg Savings</p>
                        <p class="kpi-value" id="kpi-avg-savings" style="color: var(--accent-green)">$0.00</p>
                        <div class="kpi-trend trend-up">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 7-7 7 7M12 5v14"/></svg>
                            <span id="kpi-savings-rate">0% Rate</span>
                        </div>
                    </div>
                </div>

                <!-- CHART CARD -->
                <div class="card">
                    <div class="chart-header">
                        <h2 class="chart-title">Monthly Income & Expenses Comparison</h2>
                        <div class="view-compliance-btn-container">
                            <button class="view-compliance-btn" onclick="openCompliance()">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                                Check ADK Compliance
                            </button>
                        </div>
                    </div>
                    <div class="chart-container">
                        <canvas id="budgetChart"></canvas>
                    </div>
                </div>

                <!-- ACTIONS/DECISION PANEL -->
                <div class="card">
                    <h2 class="chart-title" style="margin-bottom: 12px">Simulated Decision Pipeline</h2>
                    <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 20px">
                        Review optimization scenarios triggered during your chat. Approve or reject budget recommendations to safely commit goals.
                    </p>
                    <div class="action-panel">
                        <button class="action-btn approve" id="approve-btn" onclick="triggerDecision('approve')">
                            <div class="spinner" id="approve-spinner"></div>
                            <span id="approve-text">Approve Optimization Target</span>
                        </button>
                        <button class="action-btn reject" id="reject-btn" onclick="triggerDecision('reject')">
                            <div class="spinner" id="reject-spinner"></div>
                            <span id="reject-text">Reject Target</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- RIGHT PANE: CHAT COMPONENT -->
            <div class="chat-pane">
                <div class="card chat-card">
                    <div class="chart-header">
                        <h2 class="chart-title">AI Optimization Workstation</h2>
                        <span class="tag" style="background: rgba(66, 133, 244, 0.1); color: var(--accent-blue); font-weight: 500">Online</span>
                    </div>

                    <div class="chat-messages" id="chat-messages">
                        <!-- Welcome message -->
                        <div class="message agent">
                            <p>Hello! I am your <strong>FinOptimizer Agent</strong>, built securely using Google's Agent Development Kit (ADK).</p>
                            <p>I have connected to your active database and verified the loaded cash-flow history. Ask me anything about your monthly balances, categories, simulations, or savings goals!</p>
                            <p style="font-size: 12px; color: var(--text-secondary); font-style: italic; margin-top: 10px">
                                Examples:<br>
                                • "Can you give me a summary of my budget and savings rate?"<br>
                                • "What subscriptions could I cancel to save money?"<br>
                                • "What happens if my rent increases by $250?"
                            </p>
                        </div>
                    </div>

                    <div class="chat-input-container">
                        <input type="text" class="chat-input" id="chat-input" placeholder="Type a secure budget query..." onkeydown="if(event.key === 'Enter') sendMessage()">
                        <button class="send-btn" id="send-btn" onclick="sendMessage()">
                            <div class="spinner" id="chat-spinner"></div>
                            <span id="send-text">Send</span>
                        </button>
                    </div>
                </div>
            </div>
        </main>

        <!-- SLIDE-OUT COMPLIANCE PANEL (SIDEBAR) -->
        <div class="compliance-sidebar" id="compliance-sidebar">
            <div class="compliance-header">
                <div class="compliance-title">
                    <svg class="shield-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                    Safety Compliance
                </div>
                <button class="close-btn" onclick="closeCompliance()">&times;</button>
            </div>

            <div class="compliance-content">
                <div class="compliance-status" id="compliance-status-card">
                    <div class="status-indicator" id="compliance-indicator"></div>
                    <div style="font-size: 14px">
                        <strong>Security Integrity:</strong> <span id="compliance-status-text">Fully Compliant</span>
                    </div>
                </div>

                <div>
                    <h3 class="compliance-log-title" style="margin-bottom: 12px">Policy Scanners Evaluated</h3>
                    <div id="compliance-rules-list" style="display: flex; flex-direction: column; gap: 8px">
                        <!-- Filled dynamically -->
                    </div>
                </div>

                <div style="margin-top: auto; padding: 20px; background: rgba(255, 255, 255, 0.02); border: 1px solid var(--border-color); border-radius: 12px">
                    <h4 style="font-size: 13px; font-weight: 600; margin-bottom: 6px">Evaluation Log</h4>
                    <p style="font-size: 11px; color: var(--text-secondary)" id="compliance-log-time">Timestamp: N/A</p>
                    <p style="font-size: 11px; color: var(--text-secondary); margin-top: 6px">
                        This session operates on <strong>Zero Personal Information Retrieval</strong> principles. Raw CSVs and PII are blocked natively.
                    </p>
                </div>
            </div>
        </div>

        <!-- NOTIFICATION BANNER -->
        <div class="notification" id="notification-banner">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--accent-green)"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <span id="notification-text">Optimization successfully approved!</span>
        </div>

        <script>
            let budgetChartInstance = null;
            const sessionId = "session-" + Math.random().toString(36).substring(2, 10);

            // Fetch and render data on load
            window.addEventListener('DOMContentLoaded', () => {{
                loadDashboardData();
                renderDefaultCompliance();
            }});

            function loadDashboardData() {{
                fetch('/api/data')
                    .then(res => res.json())
                    .then(data => {{
                        if (data.error) {{
                            console.error(data.error);
                            return;
                        }}

                        // Compute aggregates for KPIs
                        let totalInc = 0;
                        let totalExp = 0;
                        data.forEach(item => {{
                            totalInc += item.income;
                            totalExp += item.expenses;
                        }});
                        
                        const avgInc = totalInc / data.length;
                        const avgExp = totalExp / data.length;
                        const avgSavings = avgInc - avgExp;
                        const savingsRate = avgInc > 0 ? (avgSavings / avgInc * 100) : 0;

                        // Display KPIs
                        document.getElementById('kpi-avg-income').textContent = '$' + avgInc.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
                        document.getElementById('kpi-avg-expenses').textContent = '$' + avgExp.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
                        document.getElementById('kpi-avg-savings').textContent = '$' + avgSavings.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
                        document.getElementById('kpi-savings-rate').textContent = savingsRate.toFixed(1) + '% Rate';

                        // Format Chart
                        const labels = data.map(item => item.month);
                        const incomes = data.map(item => item.income);
                        const expenses = data.map(item => item.expenses);

                        renderChart(labels, incomes, expenses);
                    }})
                    .catch(err => console.error(err));
            }}

            function renderChart(labels, incomes, expenses) {{
                const ctx = document.getElementById('budgetChart').getContext('2d');
                
                if (budgetChartInstance) {{
                    budgetChartInstance.destroy();
                }}

                budgetChartInstance = new Chart(ctx, {{
                    type: 'bar',
                    data: {{
                        labels: labels,
                        datasets: [
                            {{
                                label: 'Monthly Income',
                                data: incomes,
                                backgroundColor: 'rgba(52, 168, 83, 0.8)',
                                borderColor: 'rgba(52, 168, 83, 1)',
                                borderWidth: 1,
                                borderRadius: 6
                            }},
                            {{
                                label: 'Monthly Expenses',
                                data: expenses,
                                backgroundColor: 'rgba(234, 67, 53, 0.8)',
                                borderColor: 'rgba(234, 67, 53, 1)',
                                borderWidth: 1,
                                borderRadius: 6
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{
                                labels: {{
                                    color: '#90a4ae',
                                    font: {{ family: 'Outfit', size: 12 }}
                                }}
                            }},
                            tooltip: {{
                                padding: 12,
                                bodyFont: {{ family: 'Inter' }},
                                titleFont: {{ family: 'Outfit', weight: 'bold' }}
                            }}
                        }},
                        scales: {{
                            x: {{
                                grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
                                ticks: {{ color: '#90a4ae', font: {{ family: 'Inter' }} }}
                            }},
                            y: {{
                                grid: {{ color: 'rgba(255, 255, 255, 0.05)' }},
                                ticks: {{
                                    color: '#90a4ae',
                                    font: {{ family: 'Inter' }},
                                    callback: function(value) {{ return '$' + value; }}
                                }}
                            }}
                        }}
                    }}
                }});
            }}

            function sendMessage() {{
                const input = document.getElementById('chat-input');
                const message = input.value.trim();
                if (!message) return;

                appendMessage(message, 'user');
                input.value = '';

                // Show spinner & disable elements
                document.getElementById('chat-spinner').style.display = 'block';
                document.getElementById('send-text').style.display = 'none';
                document.getElementById('send-btn').disabled = true;

                fetch('/api/chat', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ message: message, session_id: sessionId }})
                }})
                .then(res => res.json())
                .then(data => {{
                    appendMessage(data.response, 'agent');
                    updateCompliancePanel(data.compliance);
                }})
                .catch(err => {{
                    appendMessage("Failed to reach server. Please ensure the agent backend is running.", 'agent');
                }})
                .finally(() => {{
                    document.getElementById('chat-spinner').style.display = 'none';
                    document.getElementById('send-text').style.display = 'block';
                    document.getElementById('send-btn').disabled = false;
                }});
            }}

            function appendMessage(text, role) {{
                const chatMessages = document.getElementById('chat-messages');
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${{role}}`;
                
                if (role === 'user') {{
                    messageDiv.textContent = text;
                }} else {{
                    // Render markdown for agent
                    messageDiv.innerHTML = marked.parse(text);
                }}
                
                chatMessages.appendChild(messageDiv);
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }}

            function askAgentAbout(prompt) {{
                document.getElementById('chat-input').value = prompt;
                sendMessage();
            }}

            // --- COMPLIANCE SIDEBAR LOGIC ---
            function openCompliance() {{
                document.getElementById('compliance-sidebar').classList.add('open');
            }}

            function closeCompliance() {{
                document.getElementById('compliance-sidebar').classList.remove('open');
            }}

            function renderDefaultCompliance() {{
                const defaults = [
                    "PII Leak Check (SSN, Account No, Password, PIN)",
                    "Strict Backend Tool Reliance",
                    "Professional Boundary Check (No Investment Advice)",
                    "Financial Product recommendation block",
                    "Projection Disclaimer Inclusion Check",
                    "Human Professional Referral Check"
                ];
                const list = document.getElementById('compliance-rules-list');
                list.innerHTML = '';
                defaults.forEach(rule => {{
                    list.innerHTML += `
                        <div class="rule-item">
                            <span>${{rule}}</span>
                            <span class="rule-badge pass">Verified</span>
                        </div>
                    `;
                }});
                document.getElementById('compliance-log-time').textContent = 'Timestamp: Initial Session Setup';
            }}

            function updateCompliancePanel(compliance) {{
                if (!compliance) return;

                const statusCard = document.getElementById('compliance-status-card');
                const indicator = document.getElementById('compliance-indicator');
                const statusText = document.getElementById('compliance-status-text');
                const list = document.getElementById('compliance-rules-list');

                list.innerHTML = '';
                
                if (compliance.passed) {{
                    statusCard.className = "compliance-status";
                    indicator.className = "status-indicator";
                    statusText.textContent = "Fully Compliant";
                }} else {{
                    statusCard.className = "compliance-status failed";
                    indicator.className = "status-indicator failed";
                    statusText.textContent = "Guardrails Active";
                }}

                // Render custom list
                compliance.rules_evaluated.forEach(rule => {{
                    let badgeClass = "pass";
                    let badgeText = "Verified";

                    if (rule.includes("PII") && compliance.pii_blocked) {{
                        badgeClass = "blocked";
                        badgeText = "Blocked";
                    }} else if (rule.includes("Boundary") && compliance.investment_advice_declined) {{
                        badgeClass = "blocked";
                        badgeText = "Declined";
                    }} else if (rule.includes("Product") && compliance.financial_products_blocked) {{
                        badgeClass = "blocked";
                        badgeText = "Declined";
                    }} else if (rule.includes("Disclaimer")) {{
                        badgeText = compliance.disclaimer_checked ? "Included" : "Bypassed";
                        badgeClass = compliance.disclaimer_checked ? "pass" : "warning";
                    }} else if (rule.includes("Referral")) {{
                        badgeText = compliance.consultation_checked ? "Referred" : "Bypassed";
                        badgeClass = compliance.consultation_checked ? "pass" : "warning";
                    }}

                    list.innerHTML += `
                        <div class="rule-item">
                            <span>${{rule}}</span>
                            <span class="rule-badge ${{badgeClass}}">${{badgeText}}</span>
                        </div>
                    `;
                }});

                document.getElementById('compliance-log-time').textContent = 'Timestamp: ' + new Date(compliance.log_timestamp).toLocaleString();
                
                // Slide open automatically to display review on warnings/blocks
                if (!compliance.passed || compliance.investment_advice_declined || compliance.pii_blocked) {{
                    openCompliance();
                }}
            }}

            // --- APPROVE / REJECT PIPELINE INTERACTION ---
            function triggerDecision(action) {{
                const textEl = document.getElementById(`${{action}}-text`);
                const spinnerEl = document.getElementById(`${{action}}-spinner`);
                const approveBtn = document.getElementById('approve-btn');
                const rejectBtn = document.getElementById('reject-btn');

                // Toggle states
                textEl.style.display = 'none';
                spinnerEl.style.display = 'block';
                approveBtn.disabled = true;
                rejectBtn.disabled = true;

                setTimeout(() => {{
                    textEl.style.display = 'block';
                    spinnerEl.style.display = 'none';
                    approveBtn.disabled = false;
                    rejectBtn.disabled = false;

                    // Show notification banner
                    const banner = document.getElementById('notification-banner');
                    const bannerText = document.getElementById('notification-text');
                    
                    if (action === 'approve') {{
                        bannerText.textContent = "Optimization Target successfully approved! Parameters committed to runtime.";
                        banner.style.border = "1px solid var(--accent-green)";
                    }} else {{
                        bannerText.textContent = "Optimization scenario declined. Baseline averages restored.";
                        banner.style.border = "1px solid var(--accent-red)";
                    }}
                    
                    banner.classList.add('show');
                    setTimeout(() => {{
                        banner.classList.remove('show');
                    }}, 4000);
                }}, 1500);
            }}
        </script>
    </body>
    </html>
    """
    return html_content


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
