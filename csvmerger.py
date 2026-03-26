import csv

# ── Read the first CSV (Severity Level) into a dictionary {lowercase name: sevLev}
sev_dict = {}
with open("sevLevel.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        key = row["Expense Name"].strip().lower()  # normalize
        sev_dict[key] = row["Severity Level"]

# ── Read the second CSV (Expense Amount) into a dictionary {lowercase name: (original name, amount)}
amount_dict = {}
with open("expenses_amount.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        key = row["Expense Name"].strip().lower()  # normalize
        amount_dict[key] = (row["Expense Name"], row["Expense Amount"])

# ── Combine into a single CSV
with open("combined_expenses.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Expense Name", "Expense Amount", "sevLev"])
    
    # Merge based on lowercase names
    for key in amount_dict:
        if key in sev_dict:
            original_name, amount = amount_dict[key]
            sevLev = sev_dict[key]
            writer.writerow([original_name, amount, sevLev])

print("Combined CSV 'combined_expenses.csv' created successfully!")