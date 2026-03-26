import os
import time
import threading
import concurrent.futures
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string

# Import our new modules
import normalization
import gemapi
import csvmerger
import dateAssign

app = Flask(__name__)

# --- CONFIGURATION (Feel free to change these!) ---
TOTAL_REVENUE = 12400500
PENDING_RECEIVABLES = 3500200

# Shared state
state = {
    "processing": False,
    "log": [],
    "expenses": [],    # Basic extraction
    "severity": {},    # output from gemapi
    "scheduled": []    # output from dateAssign
}

def log(msg):
    print(msg)
    state["log"].append(msg)

def run_pipeline(file_paths):
    state["processing"] = True
    state["log"] = []
    state["expenses"] = []
    state["severity"] = {}
    state["scheduled"] = []
    
    try:
        log("━━━ STEP 1: Parallel Extraction & Severity Scoring ━━━")
        
        # We run normalisation and severity scoring in parallel
        # Note: both now have internal time.sleep() to respect rate limits
        extracted_csv = "extracted_expenses_normalized.csv"
        severity_csv = "sevLevel.csv"
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_norm = executor.submit(normalization.process_and_save_expenses, file_paths, extracted_csv)
            future_sev = executor.submit(gemapi.generate_severity_scores)
            
            # Wait for both
            log("  ... running Gemini API calls for extraction and severity in parallel ...")
            severity_result = future_sev.result()
            future_norm.result() # Wait for normalization
        
        state["severity"] = severity_result
        log("  ✓ Parallel extraction and scoring complete.")
        
        log("━━━ STEP 2: Merging CSVs ━━━")
        merged_csv = "combined_expenses.csv"
        combined_data = csvmerger.merge_csvs(extracted_csv, severity_csv, merged_csv)
        state["expenses"] = combined_data
        log("  ✓ Merging complete.")
        
        log("━━━ STEP 3: Scheduling Payments (Cash Flow Rules) ━━━")
        scheduled_data = dateAssign.assign_dates(merged_csv, output_csv="scheduled_expenses.csv")
        state["scheduled"] = scheduled_data
        log("  ✓ Scheduling complete.")
        
        log("━━━ PIPELINE COMPLETE ✓ ━━━")
        log("  Check the tables below for scheduled tasks.")
    except Exception as e:
        log(f"✗ Error during pipeline: {str(e)}")
    finally:
        state["processing"] = False


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>TrustFlow Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
/* Modern CSS Styling */
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

body::before{
  content:"";position:fixed;inset:0;
  background-image:repeating-linear-gradient(0deg,transparent,transparent 39px,var(--border) 39px,var(--border) 40px),
                   repeating-linear-gradient(90deg,transparent,transparent 39px,var(--border) 39px,var(--border) 40px);
  opacity:.18;pointer-events:none;z-index:0;
}

#root{position:relative;z-index:1;min-height:100vh;display:flex;flex-direction:column}

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

main{display:flex;flex-direction:column;gap:18px;padding:24px 36px;flex:1}
.grid-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;}

.card{
  background:var(--card);border:1px solid var(--border);border-radius:16px;
  padding:22px;overflow:hidden;position:relative;
}
.card h2{font-size:1.05rem;font-weight:700;margin-bottom:16px}

.upload-zone{
  border:2px dashed var(--border);border-radius:12px;
  padding:28px;text-align:center;cursor:pointer;
  transition:.2s;margin-bottom:16px;
}
.upload-zone:hover{border-color:var(--accent);background:rgba(232,255,71,.03)}
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

#log-box{
  background:var(--surface);border-radius:8px;padding:14px;
  font-family:var(--mono);font-size:.72rem;color:#7dd5a8;
  height:160px;overflow-y:auto;white-space:pre-wrap;line-height:1.6;
}

.sev-table{width:100%;border-collapse:collapse;font-size:.82rem}
.sev-table th{text-align:left;padding:6px 10px;color:var(--muted);font-family:var(--mono);font-size:.67rem;letter-spacing:.08em;text-transform:uppercase;border-bottom:1px solid var(--border)}
.sev-table td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.04)}
.badge{display:inline-block;font-family:var(--mono);font-size:.65rem;padding:2px 8px;border-radius:4px;font-weight:600}
.badge-high{background:rgba(255,107,71,.15);color:var(--accent3);border:1px solid rgba(255,107,71,.3)}
.badge-med{background:rgba(71,200,255,.12);color:var(--accent2);border:1px solid rgba(71,200,255,.25)}
.badge-low{background:rgba(108,114,128,.12);color:var(--muted);border:1px solid rgba(108,114,128,.25)}
</style>
</head>
<body>
<div id="root">
<header>
  <div class="logo">Trust<span>Flow</span> V2</div>
  <div class="status-badge"><div class="dot" id="hdr-dot"></div><span id="hdr-status">IDLE</span></div>
</header>
<main>
  <div class="grid-row">
      <div class="card" style="grid-column: span 1;">
        <h2>Upload & Run</h2>
        <div class="upload-zone" id="drop-zone" onclick="document.getElementById('file-input').click()">
          <div class="upload-icon">⬆</div>
          <div style="font-weight:600;margin-bottom:4px">Drop files here</div>
          <div class="upload-hint">PDF · CSV · JPG · PNG</div>
        </div>
        <input type="file" id="file-input" multiple accept=".pdf,.csv,.jpg,.jpeg,.png" style="display:none" onchange="filesSelected(this.files)"/>
        <div id="file-list"></div>
        <button class="btn" id="run-btn" onclick="runPipeline()" disabled style="width:100%;justify-content:center">Run End-to-End Pipeline</button>
      </div>

      <div class="card" style="grid-column: span 2;">
        <h2>Pipeline Log</h2>
        <div id="log-box">Awaiting files...</div>
      </div>
  </div>
  
  <!-- Inventory & Income UI Part -->
  <div class="grid-row">
      <div class="card">
        <h2>Inventory Levels</h2>
        <div style="margin-top: 20px;">
            <div style="margin-bottom: 16px;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:6px;color:var(--muted);font-family:var(--mono);"><span>RAW MATERIALS</span><span style="color:#fff">85%</span></div>
                <div style="width:100%;background:var(--surface);height:6px;border-radius:4px;"><div style="width:85%;background:var(--accent);height:100%;border-radius:4px;box-shadow:0 0 8px var(--accent);"></div></div>
            </div>
            <div style="margin-bottom: 16px;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:6px;color:var(--muted);font-family:var(--mono);"><span>IN-PROGRESS (WIP)</span><span style="color:#fff">42%</span></div>
                <div style="width:100%;background:var(--surface);height:6px;border-radius:4px;"><div style="width:42%;background:var(--accent2);height:100%;border-radius:4px;box-shadow:0 0 8px var(--accent2);"></div></div>
            </div>
            <div style="margin-bottom: 16px;">
                <div style="display:flex;justify-content:space-between;font-size:0.8rem;margin-bottom:6px;color:var(--muted);font-family:var(--mono);"><span>FINISHED GOODS</span><span style="color:#fff">68%</span></div>
                <div style="width:100%;background:var(--surface);height:6px;border-radius:4px;"><div style="width:68%;background:var(--accent3);height:100%;border-radius:4px;box-shadow:0 0 8px var(--accent3);"></div></div>
            </div>
        </div>
      </div>
      
      <div class="card" style="grid-column: span 2; display: flex; flex-direction: column;">
        <h2 style="margin-bottom: 8px;">Income Overview</h2>
        <div style="display: flex; gap: 40px; align-items: center; margin-top: 15px; flex: 1;">
            <div style="flex: 1; background: var(--surface); padding: 20px; border-radius: 12px; border: 1px solid var(--border);">
                <div style="font-family: var(--mono); font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;">Total Revenue (YTD)</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #fff; margin: 4px 0;">₹{{TOTAL_REVENUE}}</div>
                <div style="font-size: 0.8rem; color: #34d399; font-weight: 700; display: flex; align-items: center; gap: 4px;">
                    <span style="font-size: 1.1rem;">↑</span> +14.5% vs last year
                </div>
            </div>
            <div style="flex: 1; background: var(--surface); padding: 20px; border-radius: 12px; border: 1px solid var(--border);">
                <div style="font-family: var(--mono); font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;">Pending Receivables</div>
                <div style="font-size: 2.2rem; font-weight: 800; color: #fff; margin: 4px 0;">₹{{PENDING_RECEIVABLES}}</div>
                <div style="font-size: 0.8rem; color: var(--accent2); font-weight: 700; display: flex; align-items: center; gap: 4px;">
                    <span style="font-size: 1.1rem;">↻</span> Expected in 30 days
                </div>
            </div>
        </div>
      </div>
  </div>
  
  <div class="card">
    <h2>Scheduled Expenses (dateAssign.py)</h2>
    <table class="sev-table">
      <thead><tr><th>Expense Name</th><th>Amount</th><th>Severity</th><th>Assigned Day</th><th>Cycle</th></tr></thead>
      <tbody id="sched-tbody"></tbody>
    </table>
  </div>
</main>
</div>

<script>
let selectedFiles = [];

function filesSelected(files) {
  selectedFiles = Array.from(files);
  document.getElementById('file-list').innerHTML = selectedFiles.map(f=>`<div>📎 ${f.name}</div>`).join('');
  document.getElementById('run-btn').disabled = selectedFiles.length === 0;
}

async function runPipeline() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = 'Processing...';
  document.getElementById('hdr-status').textContent = 'PROCESSING';
  document.getElementById('hdr-dot').className = 'dot processing';

  const fd = new FormData();
  selectedFiles.forEach(f => fd.append('files', f));

  try {
    const r = await fetch('/api/run', {method:'POST', body:fd});
    if (!r.ok) throw new Error(await r.text());
    pollLog();
  } catch(e) {
    document.getElementById('log-box').textContent += '\nError: ' + e.message;
    btn.disabled = false; btn.textContent = 'Run End-to-End Pipeline';
  }
}

function pollLog() {
  const iv = setInterval(async () => {
    const r = await fetch('/api/state');
    const s = await r.json();

    const el = document.getElementById('log-box');
    el.textContent = s.log.join('\n');
    el.scrollTop = el.scrollHeight;

    if (!s.processing) {
      clearInterval(iv);
      document.getElementById('run-btn').disabled = false;
      document.getElementById('run-btn').textContent = 'Run End-to-End Pipeline';
      document.getElementById('hdr-status').textContent = 'IDLE';
      document.getElementById('hdr-dot').className = 'dot live';
      
      updateTable(s.scheduled);
    }
  }, 1000);
}

function updateTable(scheduled) {
    const tbody = document.getElementById('sched-tbody');
    tbody.innerHTML = scheduled.map(e => {
        let sc = e["Priority Score"] || 0;
        let pCls = sc >= 0.70 ? 'badge-high' : sc >= 0.40 ? 'badge-med' : 'badge-low';
        let sevText = e.SevLev ? e.SevLev.toFixed(1) : "";
        return `<tr>
            <td style="font-weight:600">${e["Expense Name"]}</td>
            <td style="font-family:var(--mono);">₹${e["Expense Amount"].toLocaleString()}</td>
            <td><span class="badge ${pCls}">Sev ${sevText}</span></td>
            <td>Day ${e["Assigned Day"]}</td>
            <td style="color:var(--muted)">${e["Cycle"]}</td>
        </tr>`;
    }).join('');
}
</script>
</body>
</html>
"""

@app.route("/")
def index():
    html_rendered = HTML.replace("{{TOTAL_REVENUE}}", f"{TOTAL_REVENUE:,}").replace("{{PENDING_RECEIVABLES}}", f"{PENDING_RECEIVABLES:,}")
    return render_template_string(html_rendered)

@app.route("/api/run", methods=["POST"])
def api_run():
    if state["processing"]:
        return jsonify({"error": "already running"}), 409

    uploaded_paths = []
    for f in request.files.getlist("files"):
        dest = f"/tmp/{f.filename}"
        f.save(dest)
        uploaded_paths.append(dest)

    threading.Thread(target=run_pipeline, args=(uploaded_paths,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/api/state")
def api_state():
    return jsonify(state)

if __name__ == "__main__":
    print("Starting TrustFlow App Server on port 5000...")
    app.run(debug=False, host="0.0.0.0", port=5000)
