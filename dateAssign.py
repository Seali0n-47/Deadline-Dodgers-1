import csv
import sys
import os
import argparse

REQUIRED_COLUMNS = {"expense name", "expense amount", "sevlev"}
MAX_DAY = 25

def load_csv(filepath):
    if not os.path.exists(filepath):
        print(f"[ERROR] File not found: '{filepath}'")
        return []

    expenses = []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
            
        normalised = {h.strip().lower(): h for h in reader.fieldnames}
        missing = REQUIRED_COLUMNS - set(normalised.keys())
        if missing:
            return []

        col_name   = normalised["expense name"]
        col_amount = normalised["expense amount"]
        col_sev    = normalised["sevlev"]

        for row in reader:
            raw_name   = row[col_name].strip()
            raw_amount = row[col_amount].strip()
            raw_sev    = row[col_sev].strip()

            if not raw_name and not raw_amount and not raw_sev: continue
            if not raw_name: continue

            try: amount = float(raw_amount.replace(",", "").replace("$", ""))
            except ValueError: continue
            if amount < 0: continue

            try: sev = float(raw_sev)
            except ValueError: continue
            sev = max(0.0, min(10.0, sev))

            expenses.append({
                "Expense Name":   raw_name,
                "Expense Amount": amount,
                "SevLev":         sev,
            })
    return expenses

def priority_band(score):
    if score >= 0.85: return (1,  5)
    if score >= 0.70: return (4,  9)
    if score >= 0.55: return (7, 13)
    if score >= 0.40: return (10, 18)
    return (16, 25)

def priority_label(score):
    if score >= 0.85: return "Critical"
    if score >= 0.70: return "High"
    if score >= 0.55: return "Medium-High"
    if score >= 0.40: return "Medium"
    return "Low"

def assign_dates(csv_file="combined_expenses.csv", liquid_flow=600000.0, goods_payment=400000.0, output_csv="scheduled_expenses.csv"):
    expenses = load_csv(csv_file)
    if not expenses:
        print("[ERROR] No valid expense rows found.")
        return []

    max_amount = max(e["Expense Amount"] for e in expenses)
    min_amount = min(e["Expense Amount"] for e in expenses)
    max_sev    = max(e["SevLev"]         for e in expenses)
    min_sev    = min(e["SevLev"]         for e in expenses)

    amount_range = max_amount - min_amount if max_amount != min_amount else 1.0
    sev_range    = max_sev    - min_sev    if max_sev    != min_sev    else 1.0

    def compute_priority(expense_amount, sev_lev):
        norm_sev   = (sev_lev       - min_sev)    / sev_range
        norm_amt   = (expense_amount - min_amount) / amount_range
        inv_amount = 1.0 - norm_amt
        return round(0.70 * norm_sev + 0.30 * inv_amount, 6)

    for e in expenses:
        e["Priority Score"] = compute_priority(e["Expense Amount"], e["SevLev"])

    expenses.sort(key=lambda x: x["Priority Score"], reverse=True)

    cycle1_budget = liquid_flow
    cycle2_budget = liquid_flow + goods_payment

    spent_cycle1 = 0.0
    spent_cycle2 = 0.0
    day_log = {d: [] for d in range(1, MAX_DAY + 1)}

    def can_afford(day, amount, s_cyc1, s_cyc2):
        if day <= 15: return s_cyc1 + amount <= cycle1_budget
        else: return s_cyc1 + s_cyc2 + amount <= cycle2_budget

    def assign_day(expense, s_cyc1, s_cyc2):
        amount = expense["Expense Amount"]
        score  = expense["Priority Score"]

        start, end   = priority_band(score)
        preferred    = list(range(start, end + 1))
        fallback     = [d for d in range(1, MAX_DAY + 1) if d < start or d > end]
        search_order = preferred + fallback

        for day in search_order:
            if can_afford(day, amount, s_cyc1, s_cyc2):
                if day <= 15: s_cyc1 += amount
                else: s_cyc2 += amount
                day_log[day].append(expense["Expense Name"])
                return day, s_cyc1, s_cyc2

        # Fallback if truly exhausted: just pick best matching day ignoring budget
        return start, s_cyc1, s_cyc2

    for e in expenses:
        day, spent_cycle1, spent_cycle2 = assign_day(e, spent_cycle1, spent_cycle2)
        e["Assigned Day"] = day
        e["Cycle"] = "Cycle 1 (Day 1-15)" if day <= 15 else "Cycle 2 (Day 16-25)"

    expenses.sort(key=lambda x: (x["Assigned Day"], -x["Priority Score"]))

    def cash_at_payment(expense):
        day = expense["Assigned Day"]
        cumulative_paid = sum(e["Expense Amount"] for e in expenses if e["Assigned Day"] <= day)
        if day <= 15: return liquid_flow - cumulative_paid
        else: return liquid_flow + goods_payment - cumulative_paid

    for e in expenses:
        e["Cash After Payment"] = cash_at_payment(e)

    # Save to CSV
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Expense Name", "Expense Amount", "SevLev", "Priority Score", "Assigned Day", "Cycle", "Cash After Payment"])
        for e in expenses:
            writer.writerow([
                e["Expense Name"], e["Expense Amount"], e["SevLev"],
                e["Priority Score"], e["Assigned Day"], e["Cycle"], e["Cash After Payment"]
            ])

    print(f"Assigned dates written to {output_csv}")
    return expenses

if __name__ == "__main__":
    assign_dates()