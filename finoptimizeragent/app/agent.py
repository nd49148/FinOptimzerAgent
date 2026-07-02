# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

import os
import google.auth
from google.cloud import firestore

# Configure Vertex AI and credentials
_, project_id = google.auth.default()
os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


def get_service_account_path() -> str:
    """Traverses up directories from this file to find the serviceAccountKey.json file."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir:
        candidate = os.path.join(current_dir, "serviceAccountKey.json")
        if os.path.exists(candidate):
            return candidate
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            break
        current_dir = parent_dir
    # Fallback default location
    return r"C:\Users\ndham\Documents\FinOptimizer\serviceAccountKey.json"


# Initialize Firestore pointing to the project finoptimzer-4dd17
try:
    key_path = get_service_account_path()
    db = firestore.Client.from_service_account_json(key_path)
except Exception:
    db = firestore.Client()

MONTHS_ORDER = [
    "January", "Feburary", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def get_user_finance_summary(user_id: str = "user-1") -> str:
    """Retrieves an aggregated monthly budget summary for the specified user,
    including total income, total spending, net savings, and savings rate.

    Args:
        user_id: The unique identifier of the user (defaults to "user-1").

    Returns:
        A text report detailing monthly breakdowns and overall financial metrics.
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

        sorted_months = sorted(
            monthly_data.keys(),
            key=lambda m: MONTHS_ORDER.index(m) if m in MONTHS_ORDER else 99
        )

        report = [
            f"=== FINANCIAL SUMMARY FOR USER: {user_id} ===",
            f"{'Month':<12} | {'Income':<10} | {'Expenses':<10} | {'Net Savings':<11} | {'Savings Rate':<12}",
            "-" * 65
        ]

        total_income = 0.0
        total_outgoing = 0.0
        month_count = len(sorted_months)

        for m in sorted_months:
            inc = monthly_data[m]["Incoming"]
            out = monthly_data[m]["Outgoing"]
            savings = inc - out
            rate = (savings / inc * 100) if inc > 0 else 0.0
            
            total_income += inc
            total_outgoing += out
            
            rate_str = f"{rate:.1f}%" if inc > 0 else "0.0%"
            report.append(
                f"{m:<12} | ${inc:<8.2f} | ${out:<8.2f} | ${savings:<10.2f} | {rate_str:<12}"
            )

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
        return f"Error retrieving financial summary: {str(e)}"


def get_transactions_overview(category: str = None, record_type: str = None, user_id: str = "user-1") -> str:
    """Analyzes user spending categories, recurring subscription patterns,
    and flags any negative values or anomalies.

    Args:
        category: Optional category filter (e.g., 'Rent', 'Food').
        record_type: Optional transaction type filter ('Incoming' or 'Outgoing').
        user_id: The unique identifier of the user (defaults to "user-1").

    Returns:
        A detailed breakdown of category spending, recurring transactions, and detected anomalies.
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
                subscriptions.append({
                    "category": cat,
                    "amount": amt,
                    "frequency": frequency,
                    "month": month
                })

            if amt < 0 or "negative" in notes.lower():
                anomalies.append(f"Negative value flagged: '{cat}' of ${amt} in {month} ({notes})")

        report = [f"=== TRANSACTION OVERVIEW FOR USER: {user_id} ==="]
        if category:
            report.append(f"Filtered by Category: {category}")
        if record_type:
            report.append(f"Filtered by Type: {record_type}")
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
            
            report.append(f"{'Category/Service':<30} | {'Est. Amount':<12} | {'Frequency':<10}")
            report.append("-" * 58)
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
        return f"Error retrieving transaction overview: {str(e)}"


def simulate_scenario(change_description: str, amount_change: float, category: str, record_type: str, user_id: str = "user-1") -> str:
    """Simulates a future budget scenario (e.g. rent increase, expense cuts, or salary changes)
    and computes the comparative impact on average monthly savings and savings rate.

    Args:
        change_description: Brief description of what is changing (e.g. 'Rent Increase', 'Bonus').
        amount_change: The numerical change in amount (can be positive or negative).
        category: The category affected (e.g., 'Rent', 'Salary', 'Groceries').
        record_type: Whether the change affects 'Incoming' (income) or 'Outgoing' (expense).
        user_id: The unique identifier of the user (defaults to "user-1").

    Returns:
        A comparison report showing baseline vs simulated outcomes.
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

        if not monthly_data:
            return "Cannot perform simulation: no baseline data found."

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
            report.append(f"  To offset this ${abs(sim_savings):.2f} deficit, you will need to increase income or reduce other expenses.")
        elif diff_savings < 0:
            report.append("  📉 This change will reduce your monthly savings and lower your savings rate.")
            report.append(f"  Consider reducing discretionary expenses by ${abs(diff_savings):.2f} to maintain your baseline savings of ${avg_savings:.2f}.")
        else:
            report.append("  🚀 Congratulations! This scenario improves your net savings and cash-flow.")
            report.append(f"  We recommend transferring the extra ${diff_savings:.2f} monthly surplus directly to your high-yield savings account or emergency fund.")

        report.append("\nDisclaimer: This simulation is an estimate. It assumes your baseline income and spending remain consistent with your historical averages.")
        return "\n".join(report)

    except Exception as e:
        return f"Error running simulation: {str(e)}"


def update_goal(goal_type: str, target_amount: float, target_date: str, user_id: str = "user-1") -> str:
    """Sets or updates a personal savings or debt goal, calculates the required monthly savings,
    and compares it with the user's actual averages to determine if they are on track.

    Args:
        goal_type: Type of goal, e.g. 'Savings Goal', 'Emergency Fund', 'Debt Payoff'.
        target_amount: The financial target amount (e.g. 5000.0).
        target_date: Target completion date in YYYY-MM-DD or Month YYYY format (e.g. '2026-12-01' or 'December 2026').
        user_id: The unique identifier of the user (defaults to "user-1").

    Returns:
        A report with required monthly savings, on-track status, and helpful budgeting suggestions.
    """
    try:
        # Save goal to Firestore
        goal_ref = db.collection("users").document(user_id).collection("goals").document("current_goal")
        goal_data = {
            "goal_type": goal_type,
            "target_amount": target_amount,
            "target_date": target_date,
            "updated_at": firestore.SERVER_TIMESTAMP
        }
        goal_ref.set(goal_data)

        # Retrieve current average savings
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
            month_count = len(monthly_data)
            avg_savings = (total_inc - total_out) / month_count

        remaining_months = 6
        try:
            today = datetime.date.today()
            if "-" in target_date:
                parts = target_date.split("-")
                target_year = int(parts[0])
                target_month = int(parts[1])
            else:
                clean_date = target_date.strip()
                months_name_map = {m.lower(): i+1 for i, m in enumerate(MONTHS_ORDER)}
                months_name_map["february"] = 2
                months_name_map["feburary"] = 2
                
                parts = clean_date.split()
                if len(parts) == 2:
                    m_name = parts[0].lower()
                    target_year = int(parts[1])
                    target_month = months_name_map.get(m_name, 12)
                else:
                    target_year = today.year
                    target_month = 12
            
            remaining_months = (target_year - today.year) * 12 + (target_month - today.month)
            if remaining_months <= 0:
                remaining_months = 1
        except Exception:
            pass

        required_monthly = target_amount / remaining_months

        status = "ON TRACK" if avg_savings >= required_monthly else "BEHIND"
        diff = avg_savings - required_monthly

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

        if status == "ON TRACK":
            report.append(f"  - Surplus Margin:                  +${diff:.2f} per month")
            report.append("\n🎉 EXCELLENT WORK!")
            report.append(f"  Your current average monthly savings of ${avg_savings:.2f} are more than sufficient to reach your ${target_amount:.2f} goal by {target_date}.")
            report.append("  Keep up your current spending discipline, and consider automating your savings.")
        else:
            report.append(f"  - Monthly Shortfall:               -${abs(diff):.2f} per month")
            report.append("\n⚠️ ACTION REQUIRED:")
            report.append(f"  To stay on track for your goal, you need to find an additional **${abs(diff):.2f}** in monthly savings.")
            report.append("  Suggested Strategies:")
            report.append("    1. Run a simulation via `simulate_scenario` to see if cutting subscriptions or utilities helps.")
            report.append("    2. Try to reduce discretionary spending in higher categories.")
            report.append("    3. Explore secondary revenue streams to boost your monthly net income.")

        report.append("\nDisclaimer: This progress analysis is an estimate. It assumes your historical monthly income and spending averages remain stable.")
        return "\n".join(report)

    except Exception as e:
        return f"Error setting goal: {str(e)}"


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

### Tool Selection Matrix
* Use `get_user_finance_summary` when the user asks about their overall budget, income, spending totals, or savings rate.
* Use `get_transactions_overview` when the user asks about specific expense categories, recurring subscriptions, or transaction anomalies/flags.
* Use `simulate_scenario` when the user asks hypothetical "what if" questions (e.g., changes in rent, cutting out subscriptions, or salary bumps) to model future impacts.
* Use `update_goal` when the user wants to set or adjust a savings or debt payoff goal, check if they are on track, or see how much they need to save monthly.
"""


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=INSTRUCTION,
    tools=[
        get_user_finance_summary,
        get_transactions_overview,
        simulate_scenario,
        update_goal
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
