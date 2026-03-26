"""
TrustFlow — Integrated Manufacturing Expense Intelligence Platform
=================================================================
Single-file app combining:
  • normalization.py  – Gemini extracts & normalises expense data from PDF/CSV/image
  • gemapi.py         – Gemini scores 8 expense categories on 5 impact factors → severity
  • csvmerger.py      – Merges expense amounts with severity levels
  • CSVtoDB.py        – Pushes combined data to PostgreSQL
  • app.py            – Full dashboard UI (now via Flask + HTML/JS)

Run:
    pip install flask google-genai sqlalchemy psycopg2-binary
    python trustflow_app.py

Then open http://localhost:5000
"""

import os, time, csv, json, re, io, base64, threading
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string

# ── Optional imports (graceful degradation) ──────────────────────────────────
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠  google-genai not installed. AI features disabled.")

try:
    from sqlalchemy import create_engine, Column, Integer, Float, String, text
    from sqlalchemy.orm import declarative_base, sessionmaker
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("⚠  sqlalchemy not installed. DB features disabled.")

# ── Configuration ─────────────────────────────────────────────────────────────
GEMINI_MODEL   = "gemini-3.0-flash"
DB_USER        = os.getenv("DB_USER",     "postgres")
DB_PASSWORD    = os.getenv("DB_PASSWORD", "1234")
DB_HOST        = os.getenv("DB_HOST",     "localhost")
DB_PORT        = os.getenv("DB_PORT",     "5432")
DB_NAME        = os.getenv("DB_NAME",     "ExpenseRecord")

NORM_CSV       = "extracted_expenses_normalized.csv"
SEV_CSV        = "sevLevel.csv"
COMBINED_CSV   = "combined_expenses.csv"

SERVICES = [
    "Raw Materials", "Labor", "Machine Maintenance", "Utilities",
    "Inventory Holding", "Logistics", "Quality Costs", "Capital Expenditure"
]

CATEGORY_MAP = {
    "Raw Materials":       "Raw Materials (RM) – cost of inputs",
    "Labor":               "Labor (L) – wages, overtime, contract workers",
    "Machine Maintenance": "Machine Maintenance (MM) – repairs, servicing",
    "Utilities":           "Utilities (U) – electricity, water, fuel",
    "Inventory Holding":   "Inventory Holding (IH) – storage, obsolescence",
    "Logistics":           "Logistics (LG) – transportation, shipping",
    "Quality Costs":       "Quality Costs (QC) – rework, scrap, inspection",
    "Capital Expenditure": "Capital Expenditure (CE) – new machines, upgrades",
}

FACTORS = {
    "D": "Impact on Demand",
    "P": "Delay",
    "R": "Risk",
    "E": "Efficiency Loss",
    "S": "Strategic Value",
}

# ── Shared in-memory state ────────────────────────────────────────────────────
state = {
    "log":         [],
    "expenses":    [],   # [{name, amount, sevLev}]
    "severity":    {},   # {category: sevLev}
    "processing":  False,
    "db_status":   "not_attempted",
}

def log(msg):
    print(msg)
    state["log"].append(msg)
    if len(state["log"]) > 200:
        state["log"] = state["log"][-200:]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 – NORMALISATION  (normalization.py logic)
# ─────────────────────────────────────────────────────────────────────────────
MAPPING_INSTRUCTIONS = """
Extract every 'Expense Name' and 'Expense Amount' from this file.

CRITICAL CATEGORIZATION RULES:
Categorize every expense into exactly one of these 8 Base Categories:
1. Raw Materials: cost of inputs, iron ore, scrap, pellets.
2. Labor: wages, overtime, contract workers, technicians.
3. Machine Maintenance: repairs, servicing, spare parts.
4. Utilities: electricity, water, fuel, power.
5. Inventory Holding: storage, obsolescence, warehousing.
6. Logistics: transportation, shipping, freight, delivery.
7. Quality Costs: rework, scrap, inspection, audits.
8. Capital Expenditure: new machines, upgrades, large equipment purchases.

Return ONLY a JSON list:
[{"Expense Name": "Base Category Name", "Expense Amount": 123.45}]
"""

def run_normalisation(file_paths: list[str]) -> bool:
    if not GEMINI_AVAILABLE:
        log("⚠  Gemini not available – skipping AI extraction.")
        return False
    client = genai.Client()
    all_data = []
    for fp in file_paths:
        if not os.path.exists(fp):
            log(f"  File not found: {fp}")
            continue
        log(f"  Uploading {fp} …")
        ext = Path(fp).suffix.lower()
        mime = {".pdf":"application/pdf",".csv":"text/csv",
                ".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png"
               }.get(ext, "application/octet-stream")
        try:
            uf = client.files.upload(file=fp, config=types.UploadFileConfig(mime_type=mime))
            while uf.state.name == "PROCESSING":
                time.sleep(2)
                uf = client.files.get(name=uf.name)
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[uf, MAPPING_INSTRUCTIONS],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
            )
            items = json.loads(resp.text)
            if isinstance(items, list):
                all_data.extend(items)
                log(f"  ✓ Extracted {len(items)} items from {Path(fp).name}")
            client.files.delete(name=uf.name)
        except Exception as e:
            log(f"  ✗ Error processing {fp}: {e}")
    if all_data:
        with open(NORM_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["Expense Name","Expense Amount"])
            w.writeheader(); w.writerows(all_data)
        log(f"  ✓ Saved {NORM_CSV}")
        return True
    return False

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – SEVERITY SCORING  (gemapi.py logic)
# ─────────────────────────────────────────────────────────────────────────────
def run_severity_scoring() -> dict:
    if not GEMINI_AVAILABLE:
        log("⚠  Gemini not available – using default severity scores.")
        defaults = {"Raw Materials":8.25,"Labor":7.75,"Machine Maintenance":6.50,
                    "Utilities":6.00,"Inventory Holding":4.75,"Logistics":5.25,
                    "Quality Costs":5.50,"Capital Expenditure":5.00}
        _save_sev_csv(defaults)
        return defaults

    client = genai.Client()
    svc_list = "\n".join(f"  {i+1}. {v}" for i,(k,v) in enumerate(CATEGORY_MAP.items()))
    factor_list = "\n".join(f"  {k}: {v}" for k,v in FACTORS.items())

    prompt = f"""You are a manufacturing operations analyst.
Rate each cost category across five impact factors (0-10 integers).

SERVICES:
{svc_list}

FACTORS (0=negligible … 10=critical):
{factor_list}

Formula: (0.25×D)+(0.25×P)+(0.25×R)+(0.15×E)+(0.10×S)

Return ONLY valid JSON, no markdown:
{{
  "Raw Materials": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Labor": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Machine Maintenance": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Utilities": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Inventory Holding": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Logistics": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Quality Costs": {{"D":0,"P":0,"R":0,"E":0,"S":0}},
  "Capital Expenditure": {{"D":0,"P":0,"R":0,"E":0,"S":0}}
}}
Replace every 0 with the actual integer score."""

    log("  Querying Gemini for severity ratings …")
    try:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = re.sub(r"^```[a-z]*\n?","",resp.text.strip())
        raw = re.sub(r"\n?```$","",raw)
        ratings = json.loads(raw)
    except Exception as e:
        log(f"  ✗ Gemini severity error: {e}. Using defaults.")
        ratings = {s:{"D":7,"P":7,"R":7,"E":6,"S":5} for s in SERVICES}

    sev = {}
    for s, f in ratings.items():
        sev[s] = round(0.25*f["D"]+0.25*f["P"]+0.25*f["R"]+0.15*f["E"]+0.10*f["S"], 2)
        log(f"  {s:<25} → severity {sev[s]}")

    _save_sev_csv(sev)
    return sev

def _save_sev_csv(sev: dict):
    with open(SEV_CSV,"w",newline="") as f:
        w = csv.writer(f)
        w.writerow(["Expense Name","Severity Level"])
        for k,v in sev.items():
            w.writerow([k,v])
    log(f"  ✓ Saved {SEV_CSV}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – CSV MERGE  (csvmerger.py logic)
# ─────────────────────────────────────────────────────────────────────────────
def run_csv_merge() -> list[dict]:
    sev_dict = {}
    if os.path.exists(SEV_CSV):
        with open(SEV_CSV) as f:
            for row in csv.DictReader(f):
                sev_dict[row["Expense Name"].strip().lower()] = row["Severity Level"]

    amount_dict = {}
    src = NORM_CSV if os.path.exists(NORM_CSV) else None
    if src:
        with open(src) as f:
            for row in csv.DictReader(f):
                k = row["Expense Name"].strip().lower()
                amount_dict[k] = (row["Expense Name"], row["Expense Amount"])

    combined = []
    with open(COMBINED_CSV,"w",newline="") as f:
        w = csv.writer(f)
        w.writerow(["Expense Name","Expense Amount","sevLev"])
        for k,(name,amt) in amount_dict.items():
            sl = sev_dict.get(k, sev_dict.get(name.strip().lower(), 5.0))
            w.writerow([name, amt, sl])
            combined.append({"name":name,"amount":float(amt),"sevLev":float(sl)})

    log(f"  ✓ Merged {len(combined)} rows → {COMBINED_CSV}")
    return combined

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – DATABASE PUSH  (CSVtoDB.py logic)
# ─────────────────────────────────────────────────────────────────────────────
def run_db_push() -> str:
    if not SQLALCHEMY_AVAILABLE:
        return "sqlalchemy_missing"
    if not os.path.exists(COMBINED_CSV):
        return "no_csv"
    try:
        url = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        Base = declarative_base()

        class Expense(Base):
            __tablename__ = "expenses"
            id           = Column(Integer, primary_key=True, autoincrement=True)
            expense_name = Column(String(100), nullable=False)
            expense_amount = Column(Float, nullable=False)
            sevLev       = Column(Float, nullable=False)

        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        with open(COMBINED_CSV) as f:
            for row in csv.DictReader(f):
                session.add(Expense(
                    expense_name=row["Expense Name"].strip(),
                    expense_amount=float(row["Expense Amount"]),
                    sevLev=float(row["sevLev"])
                ))
        session.commit(); session.close()
        log("  ✓ Data pushed to PostgreSQL.")
        return "success"
    except Exception as e:
        log(f"  ✗ DB error: {e}")
        return f"error: {e}"

# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────
def run_full_pipeline(file_paths: list[str]):
    state["processing"] = True
    state["log"] = []
    try:
        log("━━━ STEP 1: Expense Normalisation ━━━")
        run_normalisation(file_paths)

        log("━━━ STEP 2: Severity Scoring ━━━")
        sev = run_severity_scoring()
        state["severity"] = sev

        log("━━━ STEP 3: Merging CSVs ━━━")
        combined = run_csv_merge()
        state["expenses"] = combined

        log("━━━ STEP 4: Database Push ━━━")
        db_result = run_db_push()
        state["db_status"] = db_result

        log("━━━ Pipeline Complete ✓ ━━━")
    except Exception as e:
        log(f"✗ Pipeline error: {e}")
    finally:
        state["processing"] = False

# ─────────────────────────────────────────────────────────────────────────────
# DEMO DATA  (pre-populate so dashboard looks good on first load)
# ─────────────────────────────────────────────────────────────────────────────
DEMO_SEVERITY = {
    "Raw Materials":8.50,"Labor":7.75,"Machine Maintenance":6.75,
    "Utilities":6.25,"Inventory Holding":4.75,"Logistics":5.50,
    "Quality Costs":5.75,"Capital Expenditure":5.25
}
DEMO_EXPENSES = [
    {"name":"Raw Materials",      "amount":142000,"sevLev":8.50},
    {"name":"Labor",              "amount":98000, "sevLev":7.75},
    {"name":"Machine Maintenance","amount":34000, "sevLev":6.75},
    {"name":"Utilities",          "amount":27000, "sevLev":6.25},
    {"name":"Inventory Holding",  "amount":18500, "sevLev":4.75},
    {"name":"Logistics",          "amount":22000, "sevLev":5.50},
    {"name":"Quality Costs",      "amount":15000, "sevLev":5.75},
    {"name":"Capital Expenditure","amount":55000, "sevLev":5.25},
]
state["severity"] = DEMO_SEVERITY
state["expenses"] = DEMO_EXPENSES

# ─────────────────────────────────────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>TrustFlow</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {
  --bg:       #0a0c10;
  --surface:  #12151c;
  --card:     #181c25;
  --border:   #252c3a;
  --accent:   #e8ff47;
  --accent2:  #47c8ff;
  --accent3:  #ff6b47;
  --text:     #e8eaf0;
  --muted:    #6b7280;
  --font:     'Syne', sans-serif;
  --mono:     'JetBrains Mono', monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);overflow-x:hidden}

/* grid noise */
body::before{
  content:"";position:fixed;inset:0;
  background-image:repeating-linear-gradient(0deg,transparent,transparent 39px,var(--border) 39px,var(--border) 40px),
                   repeating-linear-gradient(90deg,transparent,transparent 39px,var(--border) 39px,var(--border) 40px);
  opacity:.18;pointer-events:none;z-index:0;
}

#root{position:relative;z-index:1;min-height:100vh;display:flex;flex-direction:column}

/* ── HEADER ── */
header{
  display:flex;align-items:center;justify-content:space-between;
  padding:20px 36px;border-bottom:1px solid var(--border);
  background:rgba(10,12,16,.85);backdrop-filter:blur(12px);
  position:sticky;top:0;z-index:100;
}
.logo{font-size:1.55rem;font-weight:800;letter-spacing:-.02em}
.logo span{color:var(--accent)}
.status-badge{
  font-family:var(--mono);font-size:.75rem;
  padding:5px 14px;border-radius:99px;
  background:var(--card);border:1px solid var(--border);
  display:flex;align-items:center;gap:8px;
}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.dot.live{background:var(--accent);box-shadow:0 0 8px var(--accent)}
.dot.processing{background:var(--accent3);animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

/* ── MAIN LAYOUT ── */
main{display:grid;grid-template-columns:1fr 1fr 1fr;grid-template-rows:auto auto auto;gap:18px;padding:24px 36px;flex:1}

/* ── CARDS ── */
.card{
  background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:22px;overflow:hidden;position:relative;
}
.card::after{
  content:"";position:absolute;inset:0;border-radius:inherit;
  background:linear-gradient(135deg,rgba(255,255,255,.03) 0%,transparent 60%);
  pointer-events:none;
}
.card-label{
  font-family:var(--mono);font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);margin-bottom:12px;
}
.card-title{font-size:1.05rem;font-weight:700;margin-bottom:4px}
.card h2{font-size:1.05rem;font-weight:700;margin-bottom:16px}

/* spans */
.span2{grid-column:span 2}
.span3{grid-column:span 3}

/* ── KPI row ── */
.kpi-row{grid-column:span 3;display:grid;grid-template-columns:repeat(4,1fr);gap:18px}
.kpi-val{font-size:2.1rem;font-weight:800;letter-spacing:-.03em;color:var(--accent)}
.kpi-sub{font-size:.78rem;color:var(--muted);margin-top:4px;font-family:var(--mono)}

/* ── CHART ── */
.chart-wrap{position:relative;height:220px}

/* ── SEVERITY TABLE ── */
.sev-table{width:100%;border-collapse:collapse;font-size:.82rem}
.sev-table th{text-align:left;padding:6px 10px;color:var(--muted);font-family:var(--mono);font-size:.67rem;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--border)}
.sev-table td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.04)}
.sev-table tr:last-child td{border:none}
.sev-bar-bg{background:var(--surface);border-radius:4px;height:6px;width:100%;min-width:80px}
.sev-bar{height:6px;border-radius:4px;transition:width .6s ease}
.badge{display:inline-block;font-family:var(--mono);font-size:.65rem;padding:2px 8px;border-radius:4px;font-weight:600}
.badge-high{background:rgba(255,107,71,.15);color:var(--accent3);border:1px solid rgba(255,107,71,.3)}
.badge-med{background:rgba(71,200,255,.12);color:var(--accent2);border:1px solid rgba(71,200,255,.25)}
.badge-low{background:rgba(108,114,128,.12);color:var(--muted);border:1px solid rgba(108,114,128,.25)}

/* ── UPLOAD PANEL ── */
.upload-zone{
  border:2px dashed var(--border);border-radius:12px;
  padding:28px;text-align:center;cursor:pointer;
  transition:.2s;margin-bottom:16px;
}
.upload-zone:hover{border-color:var(--accent);background:rgba(232,255,71,.03)}
.upload-zone.drag{border-color:var(--accent);background:rgba(232,255,71,.06)}
.upload-icon{font-size:2rem;margin-bottom:8px;color:var(--muted)}
.upload-hint{font-size:.78rem;color:var(--muted);font-family:var(--mono)}
#file-list{margin-bottom:14px;font-size:.78rem;font-family:var(--mono);color:var(--accent2)}

.btn{
  display:inline-flex;align-items:center;gap:8px;
  padding:10px 22px;border-radius:8px;font-family:var(--font);font-size:.85rem;
  font-weight:700;cursor:pointer;transition:.15s;border:none;
  background:var(--accent);color:#0a0c10;letter-spacing:.01em;
}
.btn:hover{filter:brightness(1.1);transform:translateY(-1px)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none}
.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text)}
.btn-outline:hover{border-color:var(--accent);color:var(--accent)}

/* ── LOG ── */
#log-box{
  background:var(--surface);border-radius:8px;padding:14px;
  font-family:var(--mono);font-size:.72rem;color:#7dd5a8;
  height:160px;overflow-y:auto;white-space:pre-wrap;line-height:1.6;
}
#log-box::-webkit-scrollbar{width:4px}
#log-box::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}

/* ── STEP PROGRESS ── */
.steps{display:flex;gap:0;margin-bottom:18px}
.step{flex:1;text-align:center;position:relative;font-size:.72rem;font-family:var(--mono)}
.step::after{content:"";position:absolute;top:11px;left:50%;width:100%;height:2px;background:var(--border);z-index:0}
.step:last-child::after{display:none}
.step-dot{
  width:24px;height:24px;border-radius:50%;background:var(--surface);
  border:2px solid var(--border);margin:0 auto 6px;position:relative;z-index:1;
  display:flex;align-items:center;justify-content:center;font-size:.65rem;font-weight:700;
  transition:.3s;
}
.step.done .step-dot{background:var(--accent);border-color:var(--accent);color:#0a0c10}
.step.active .step-dot{border-color:var(--accent3);box-shadow:0 0 12px rgba(255,107,71,.5);animation:pulse 1s infinite}
.step-label{color:var(--muted)}
.step.done .step-label{color:var(--accent)}

/* ── DB STATUS ── */
.db-indicator{
  display:flex;align-items:center;gap:10px;
  font-family:var(--mono);font-size:.78rem;padding:12px 16px;
  border-radius:8px;background:var(--surface);border:1px solid var(--border);
  margin-top:10px;
}

/* ── RADAR PLACEHOLDER ── */
.chart-wrap-sm{position:relative;height:200px}

/* animations */
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.card{animation:fadeUp .4s ease both}
.card:nth-child(2){animation-delay:.06s}
.card:nth-child(3){animation-delay:.12s}
.card:nth-child(4){animation-delay:.18s}
.card:nth-child(5){animation-delay:.24s}
.card:nth-child(6){animation-delay:.30s}

/* ── RESPONSIVE ── */
@media(max-width:900px){
  main{grid-template-columns:1fr;padding:16px}
  .kpi-row{grid-template-columns:1fr 1fr}
  .span2,.span3{grid-column:span 1}
  .kpi-row{grid-column:span 1}
}
</style>
</head>
<body>
<div id="root">
<header>
  <div class="logo">Trust<span>Flow</span></div>
  <div style="display:flex;gap:12px;align-items:center">
    <div class="status-badge"><div class="dot" id="hdr-dot"></div><span id="hdr-status" style="font-family:var(--mono)">IDLE</span></div>
    <button class="btn btn-outline" style="padding:7px 16px;font-size:.78rem" onclick="refreshData()">↻ Refresh</button>
  </div>
</header>

<main>
  <!-- KPI row -->
  <div class="kpi-row">
    <div class="card">
      <div class="card-label">Total Expenses</div>
      <div class="kpi-val" id="kpi-total">—</div>
      <div class="kpi-sub">across all categories</div>
    </div>
    <div class="card">
      <div class="card-label">Highest Severity</div>
      <div class="kpi-val" id="kpi-topsev" style="color:var(--accent3)">—</div>
      <div class="kpi-sub" id="kpi-topsev-name">—</div>
    </div>
    <div class="card">
      <div class="card-label">Categories Tracked</div>
      <div class="kpi-val" id="kpi-cats" style="color:var(--accent2)">—</div>
      <div class="kpi-sub">expense buckets</div>
    </div>
    <div class="card">
      <div class="card-label">Pipeline Status</div>
      <div class="kpi-val" id="kpi-pipe" style="font-size:1.4rem">—</div>
      <div class="kpi-sub" id="kpi-pipe-sub">—</div>
    </div>
  </div>

  <!-- Bar chart -->
  <div class="card span2">
    <h2>Expense Distribution</h2>
    <div class="chart-wrap"><canvas id="barChart"></canvas></div>
  </div>

  <!-- Radar -->
  <div class="card">
    <h2>Severity Radar</h2>
    <div class="chart-wrap-sm"><canvas id="radarChart"></canvas></div>
  </div>

  <!-- Severity Table -->
  <div class="card span2">
    <h2>Category Severity Analysis</h2>
    <table class="sev-table">
      <thead><tr><th>Category</th><th>Severity</th><th>Level</th><th>Amount</th></tr></thead>
      <tbody id="sev-tbody"></tbody>
    </table>
  </div>

  <!-- Upload -->
  <div class="card">
    <h2>Data Upload</h2>
    <div class="upload-zone" id="drop-zone" onclick="document.getElementById('file-input').click()"
         ondragover="ev(event,'drag')" ondragleave="ev(event,'')" ondrop="drop(event)">
      <div class="upload-icon">⬆</div>
      <div style="font-weight:600;margin-bottom:4px">Drop files here</div>
      <div class="upload-hint">PDF · CSV · JPG · PNG</div>
    </div>
    <input type="file" id="file-input" multiple accept=".pdf,.csv,.jpg,.jpeg,.png" style="display:none" onchange="filesSelected(this.files)"/>
    <div id="file-list"></div>
    <button class="btn" id="run-btn" onclick="runPipeline()" disabled style="width:100%;justify-content:center">
      Run Pipeline
    </button>
  </div>

  <!-- Log + Steps -->
  <div class="card span3">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
      <h2 style="margin:0">Pipeline Progress</h2>
      <button class="btn btn-outline" style="padding:5px 14px;font-size:.75rem" onclick="clearLog()">Clear</button>
    </div>
    <div class="steps" id="steps">
      <div class="step" id="s1"><div class="step-dot">1</div><div class="step-label">Extract</div></div>
      <div class="step" id="s2"><div class="step-dot">2</div><div class="step-label">Score</div></div>
      <div class="step" id="s3"><div class="step-dot">3</div><div class="step-label">Merge</div></div>
      <div class="step" id="s4"><div class="step-dot">4</div><div class="step-label">Database</div></div>
    </div>
    <div id="log-box">Waiting for pipeline…</div>
    <div class="db-indicator" id="db-indicator" style="display:none">
      <span id="db-icon">○</span><span id="db-text">PostgreSQL status</span>
    </div>
  </div>
</main>
</div>

<script>
let barChart, radarChart;
let selectedFiles = [];

// ── File selection ────────────────────────────────────────────────────────
function filesSelected(files) {
  selectedFiles = Array.from(files);
  document.getElementById('file-list').innerHTML =
    selectedFiles.map(f=>`<div>📎 ${f.name}</div>`).join('');
  document.getElementById('run-btn').disabled = selectedFiles.length === 0;
}
function ev(e, cls) { e.preventDefault(); document.getElementById('drop-zone').className='upload-zone '+cls; }
function drop(e) { e.preventDefault(); filesSelected(e.dataTransfer.files); document.getElementById('drop-zone').className='upload-zone'; }

// ── Run pipeline ──────────────────────────────────────────────────────────
async function runPipeline() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = 'Processing…';
  updateHeader('PROCESSING', true);
  resetSteps();

  const fd = new FormData();
  selectedFiles.forEach(f => fd.append('files', f));

  try {
    const r = await fetch('/api/run', {method:'POST', body:fd});
    if (!r.ok) throw new Error(await r.text());
    pollLog();
  } catch(e) {
    appendLog('Error: ' + e.message);
    btn.disabled = false; btn.textContent = 'Run Pipeline';
    updateHeader('ERROR', false);
  }
}

// ── Polling ───────────────────────────────────────────────────────────────
let logOffset = 0;
function pollLog() {
  const iv = setInterval(async () => {
    const r = await fetch('/api/state');
    const s = await r.json();

    setLog(s.log);
    inferSteps(s.log);
    updateHeader(s.processing ? 'PROCESSING':'IDLE', s.processing);

    if (!s.processing) {
      clearInterval(iv);
      document.getElementById('run-btn').disabled = false;
      document.getElementById('run-btn').textContent = 'Run Pipeline';
      updateCharts(s);
      showDB(s.db_status);
    }
  }, 1200);
}

function setLog(lines) {
  const el = document.getElementById('log-box');
  el.textContent = lines.join('\n');
  el.scrollTop = el.scrollHeight;
}
function appendLog(msg) {
  const el = document.getElementById('log-box');
  el.textContent += '\n' + msg;
  el.scrollTop = el.scrollHeight;
}
function clearLog() { document.getElementById('log-box').textContent = 'Log cleared.'; }

function inferSteps(log) {
  const txt = log.join(' ');
  const mark = (id, cls) => { document.getElementById(id).className='step '+cls; };
  if (txt.includes('STEP 1')) mark('s1','active');
  if (txt.includes('STEP 2')) { mark('s1','done'); mark('s2','active'); }
  if (txt.includes('STEP 3')) { mark('s2','done'); mark('s3','active'); }
  if (txt.includes('STEP 4')) { mark('s3','done'); mark('s4','active'); }
  if (txt.includes('Pipeline Complete')) { mark('s4','done'); }
}
function resetSteps() {
  ['s1','s2','s3','s4'].forEach(id => document.getElementById(id).className='step');
}

function updateHeader(txt, processing) {
  document.getElementById('hdr-status').textContent = txt;
  const dot = document.getElementById('hdr-dot');
  dot.className = 'dot' + (processing ? ' processing' : txt==='IDLE' ? ' live' : '');
}

function showDB(status) {
  const el = document.getElementById('db-indicator');
  el.style.display = 'flex';
  if (!status || status === 'not_attempted') { el.style.display='none'; return; }
  if (status === 'success') {
    document.getElementById('db-icon').textContent = '✓';
    document.getElementById('db-text').textContent = 'Data saved to PostgreSQL';
    el.style.background = 'rgba(71,200,255,.08)';
    el.style.borderColor = 'rgba(71,200,255,.3)';
    document.getElementById('db-icon').style.color = 'var(--accent2)';
  } else {
    document.getElementById('db-icon').textContent = '✗';
    document.getElementById('db-text').textContent = 'DB: ' + status;
    el.style.background = 'rgba(255,107,71,.08)';
    el.style.borderColor = 'rgba(255,107,71,.3)';
    document.getElementById('db-icon').style.color = 'var(--accent3)';
  }
}

// ── Charts ────────────────────────────────────────────────────────────────
const COLORS = ['#e8ff47','#47c8ff','#ff6b47','#a78bfa','#34d399','#f472b6','#fb923c','#60a5fa'];

function buildCharts(expenses, severity) {
  const names  = expenses.map(e=>e.name);
  const amounts = expenses.map(e=>e.amount);
  const sevs   = expenses.map(e=>e.sevLev);

  // Bar
  if (barChart) barChart.destroy();
  barChart = new Chart(document.getElementById('barChart'), {
    type:'bar',
    data:{
      labels: names,
      datasets:[{
        label:'Expense Amount',
        data: amounts,
        backgroundColor: COLORS,
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false},
        tooltip:{ callbacks:{ label: ctx => ' ₹'+ctx.parsed.y.toLocaleString() }}},
      scales:{
        x:{ grid:{color:'rgba(255,255,255,.05)'}, ticks:{color:'#6b7280',font:{family:'JetBrains Mono',size:10}} },
        y:{ grid:{color:'rgba(255,255,255,.05)'}, ticks:{color:'#6b7280', callback:v=>'₹'+v.toLocaleString()} }
      }
    }
  });

  // Radar
  if (radarChart) radarChart.destroy();
  radarChart = new Chart(document.getElementById('radarChart'), {
    type:'radar',
    data:{
      labels: Object.keys(severity).map(s=>s.length>10?s.slice(0,10)+'…':s),
      datasets:[{
        label:'Severity',
        data: Object.values(severity),
        borderColor:'#e8ff47',
        backgroundColor:'rgba(232,255,71,.12)',
        pointBackgroundColor:'#e8ff47',
        borderWidth:2,
      }]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{ legend:{display:false}},
      scales:{ r:{
        grid:{color:'rgba(255,255,255,.07)'},
        ticks:{color:'#6b7280',backdropColor:'transparent',font:{size:9}},
        pointLabels:{color:'#9ca3af',font:{size:9}},
        min:0,max:10,
      }}
    }
  });
}

function buildTable(expenses, severity) {
  const tbody = document.getElementById('sev-tbody');
  const sorted = [...expenses].sort((a,b)=>b.sevLev-a.sevLev);
  tbody.innerHTML = sorted.map(e => {
    const pct = (e.sevLev/10*100).toFixed(0);
    const cls = e.sevLev>=7 ? 'badge-high' : e.sevLev>=5 ? 'badge-med' : 'badge-low';
    const lbl = e.sevLev>=7 ? 'HIGH' : e.sevLev>=5 ? 'MED' : 'LOW';
    const barColor = e.sevLev>=7 ? 'var(--accent3)' : e.sevLev>=5 ? 'var(--accent2)' : 'var(--muted)';
    return `<tr>
      <td style="font-weight:600">${e.name}</td>
      <td>
        <div class="sev-bar-bg"><div class="sev-bar" style="width:${pct}%;background:${barColor}"></div></div>
      </td>
      <td><span class="badge ${cls}">${lbl} ${e.sevLev}</span></td>
      <td style="font-family:var(--mono);color:var(--muted)">₹${e.amount.toLocaleString()}</td>
    </tr>`;
  }).join('');
}

function buildKPIs(expenses, severity) {
  const total = expenses.reduce((a,e)=>a+e.amount, 0);
  document.getElementById('kpi-total').textContent = '₹'+total.toLocaleString();
  document.getElementById('kpi-cats').textContent  = expenses.length;
  const top = [...expenses].sort((a,b)=>b.sevLev-a.sevLev)[0];
  if (top) {
    document.getElementById('kpi-topsev').textContent      = top.sevLev;
    document.getElementById('kpi-topsev-name').textContent = top.name;
  }
}

function updateCharts(s) {
  if (!s.expenses || !s.expenses.length) return;
  buildCharts(s.expenses, s.severity||{});
  buildTable(s.expenses, s.severity||{});
  buildKPIs(s.expenses, s.severity||{});
  document.getElementById('kpi-pipe').textContent     = s.processing ? '⚙' : '✓';
  document.getElementById('kpi-pipe-sub').textContent = s.processing ? 'Running…' : 'Pipeline complete';
}

// ── Refresh from server ───────────────────────────────────────────────────
async function refreshData() {
  const r = await fetch('/api/state');
  const s = await r.json();
  updateCharts(s);
  setLog(s.log.length ? s.log : ['No pipeline run yet. Upload files to begin.']);
  updateHeader(s.processing ? 'PROCESSING':'IDLE', s.processing);
  showDB(s.db_status);
}

// ── Init ──────────────────────────────────────────────────────────────────
window.onload = () => refreshData();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/run", methods=["POST"])
def api_run():
    if state["processing"]:
        return jsonify({"error": "already running"}), 409

    uploaded_paths = []
    for f in request.files.getlist("files"):
        dest = Path("/tmp") / f.filename
        f.save(dest)
        uploaded_paths.append(str(dest))

    threading.Thread(target=run_full_pipeline, args=(uploaded_paths,), daemon=True).start()
    return jsonify({"ok": True, "files": [p for p in uploaded_paths]})

@app.route("/api/state")
def api_state():
    return jsonify({
        "processing": state["processing"],
        "log":        state["log"],
        "expenses":   state["expenses"],
        "severity":   state["severity"],
        "db_status":  state["db_status"],
    })

@app.route("/api/demo")
def api_demo():
    """Re-seed with demo data."""
    state["expenses"] = DEMO_EXPENSES
    state["severity"] = DEMO_SEVERITY
    state["db_status"] = "not_attempted"
    return jsonify({"ok": True})

if __name__ == "__main__":
    print("=" * 55)
    print("  TrustFlow  –  Manufacturing Expense Intelligence")
    print("=" * 55)
    print(f"  Gemini available : {GEMINI_AVAILABLE}")
    print(f"  SQLAlchemy avail : {SQLALCHEMY_AVAILABLE}")
    print(f"  DB target        : {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print()
    print("  → Open http://localhost:5000")
    print("=" * 55)
    app.run(debug=False, host="0.0.0.0", port=5000)
