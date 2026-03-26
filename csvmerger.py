import csv

def merge_csvs(extracted_csv, severity_csv, output_csv="combined_expenses.csv"):
    import os
    # ── Read the first CSV (Severity Level) into a dictionary {lowercase name: sevLev}
    sev_dict = {}
    if os.path.exists(severity_csv):
        with open(severity_csv, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key_raw = row.get("Type of Expense") or row.get("Expense Name", "")
                key = key_raw.strip().lower()  # normalize
                # Handling if column is named slightly differently
                sev_val = row.get("Severity Level", row.get("sevLev", 5.0))
                sev_dict[key] = sev_val

    # ── Read the second CSV (Expense Amount) into a dictionary {lowercase name: (original name, amount)}
    amount_dict = {}
    if os.path.exists(extracted_csv):
        with open(extracted_csv, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key_raw = row.get("Expense Name", "")
                if not key_raw: continue
                key = key_raw.strip().lower()  # normalize
                amount_dict[key] = (key_raw, row.get("Expense Amount", 0))

    combined = []
    # ── Combine into a single CSV
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Expense Name", "Expense Amount", "sevLev"])
        
        # Merge based on lowercase names
        for key in amount_dict:
            original_name, amount = amount_dict[key]
            # Default severity to 5.0 if not found
            sevLev = sev_dict.get(key, 5.0)
            writer.writerow([original_name, amount, sevLev])
            combined.append({"name": original_name, "amount": float(amount), "sevLev": float(sevLev)})

    print(f"Combined CSV '{output_csv}' created successfully!")
    return combined

if __name__ == "__main__":
    merge_csvs("extracted_expenses_normalized.csv", "sevLevel.csv")