from google import genai
import json
import re
import csv


client = genai.Client()

# ── Service and factor definitions ──────────────────────────────────────────
SERVICES = [
    "Raw Materials (RM) – cost of inputs",
    "Labor (L) – wages, overtime, contract workers",
    "Machine Maintenance (MM) – repairs, servicing",
    "Utilities (U) – electricity, water, fuel",
    "Inventory Holding (IH) – storage, obsolescence",
    "Logistics (LG) – transportation, shipping",
    "Quality Costs (QC) – rework, scrap, inspection",
    "Capital Expenditure (CE) – new machines, upgrades",
]

FACTORS = {
    "D": "Impact on Demand – How much this affects customer demand or order fulfillment.",
    "P": "Delay – How much production or service will be delayed if ignored.",
    "R": "Risk – Potential risk if ignored (safety, legal, or breakdown issues).",
    "E": "Efficiency Loss – How much productivity or workflow is lost if ignored.",
    "S": "Strategic Value – Importance for long-term goals or company strategy.",
}

SEVERITY_FORMULA = "(0.25×D) + (0.25×P) + (0.25×R) + (0.15×E) + (0.10×S)"

# ── Build the prompt ─────────────────────────────────────────────────────────
prompt = f"""
You are a manufacturing operations analyst. Your task is to rate each cost/service category
in a manufacturing industry across five impact factors, each scored from 0 to 10.

--- SERVICES TO EVALUATE ---
{chr(10).join(f"  {i+1}. {s}" for i, s in enumerate(SERVICES))}

--- AFFECTING FACTORS (score 0–10 each) ---
{chr(10).join(f"  {k}: {v}" for k, v in FACTORS.items())}

Scoring guide:
  0–2  = Negligible impact
  3–4  = Low impact
  5–6  = Moderate impact
  7–8  = High impact
  9–10 = Critical impact

For EVERY service, assign a score (0–10, integers only) for each of the five factors (D, P, R, E, S),
based on typical manufacturing industry conditions.

Return ONLY a valid JSON object — no markdown, no explanation, no extra text.
Use this exact structure:

{{
  "Raw Materials": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Labor": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Machine Maintenance": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Utilities": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Inventory Holding": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Logistics": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Quality Costs": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}},
  "Capital Expenditure": {{"D": 0, "P": 0, "R": 0, "E": 0, "S": 0}}
}}

Replace every 0 with the actual integer score you assign.
"""

# ── Call the Gemini API ──────────────────────────────────────────────────────
print("Querying Gemini for factor ratings...\n")
response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents=prompt,
)

raw = response.text.strip()

# Strip markdown fences if present
raw = re.sub(r"^```[a-z]*\n?", "", raw)
raw = re.sub(r"\n?```$", "", raw)

ratings = json.loads(raw)

# ── Store all factor values in arrays ────────────────────────────────────────
D_values  = []
P_values  = []
R_values  = []
E_values  = []
S_values  = []
service_names = []

for service, factors in ratings.items():
    service_names.append(service)
    D_values.append(factors["D"])
    P_values.append(factors["P"])
    R_values.append(factors["R"])
    E_values.append(factors["E"])
    S_values.append(factors["S"])

# ── Compute severity levels ───────────────────────────────────────────────────
# Formula: (0.25×D) + (0.25×P) + (0.25×R) + (0.15×E) + (0.10×S)
severity_levels = {}
for i, service in enumerate(service_names):
    severity_levels[service] = round(
        (0.25 * D_values[i]) +
        (0.25 * P_values[i]) +
        (0.25 * R_values[i]) +
        (0.15 * E_values[i]) +
        (0.10 * S_values[i]),
        2
    )

# ── Print results ─────────────────────────────────────────────────────────────
print("=" * 60)
print("  FACTOR RATINGS BY SERVICE")
print("=" * 60)
print(f"{'Service':<25} {'D':>4} {'P':>4} {'R':>4} {'E':>4} {'S':>4}")
print("-" * 60)
for i, service in enumerate(service_names):
    print(f"{service:<25} {D_values[i]:>4} {P_values[i]:>4} {R_values[i]:>4} {E_values[i]:>4} {S_values[i]:>4}")

print()
print("=" * 60)
print("  FACTOR ARRAYS")
print("=" * 60)
print(f"Services      : {service_names}")
print(f"D (Demand)    : {D_values}")
print(f"P (Delay)     : {P_values}")
print(f"R (Risk)      : {R_values}")
print(f"E (Efficiency): {E_values}")
print(f"S (Strategic) : {S_values}")

print()
print("=" * 60)
print(f"  SEVERITY LEVELS  [{SEVERITY_FORMULA}]")
print("=" * 60)
for service, level in sorted(severity_levels.items(), key=lambda x: x[1], reverse=True):
    bar = "█" * int(level)
    print(f"{service:<25} {level:>5}  {bar}")

print()
print("Raw severity_levels dict:")
print(severity_levels)


csv_filename = "sevLevel.csv"
with open(csv_filename, mode='w', newline='') as csv_file:
    writer = csv.writer(csv_file)
    # Header
    writer.writerow(["Type of Expense", "Severity Level"])
    # Use existing service_names and severity_levels
    for service in service_names:
        writer.writerow([service, severity_levels[service]])

print(f"\nCSV file '{csv_filename}' created successfully!")