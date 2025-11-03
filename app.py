# app.py
"""
Agro_Vista Flask app (production-ready)
- Reads tables from PostgreSQL using DATABASE_URL env var
- Falls back to Google Sheets if DB empty (optional)
- Serves a simple HTML UI at / (mobile responsive)
- API endpoints: /api/all_forecasts and /api/forecast?sheet=<name>
"""
import os
import pandas as pd
from flask import Flask, request, jsonify, Response
from sqlalchemy import create_engine, text
import google.generativeai as genai  # keep if you need Gemini (set GENIE_API_KEY)

# -------- Configuration (read secrets from env) ----------------
DATABASE_URL = os.getenv("DATABASE_URL")  # must be provided in Railway env
GENIE_API_KEY = os.getenv("GENIE_API_KEY")  # optional, for Gemini
# optional Google Sheets fallback (only used if DB empty)
SHEET_ID = os.getenv("SHEET_ID")  # keep blank or set if you want fallback read
# ----------------------------------------------------------------

if GENIE_API_KEY:
    genai.configure(api_key=GENIE_API_KEY)

# Create SQLAlchemy engine; enable sslmode if host requires it
# Railway provides a full DATABASE_URL; for external DBs you might need sslmode=require
connect_args = {}
if DATABASE_URL and ("sslmode" not in DATABASE_URL):
    # If using an external DB that requires SSL, append ?sslmode=require when creating engine
    if DATABASE_URL.startswith("postgresql://") and "render.com" in DATABASE_URL:
        # Render external DB usually accepts standard URL; if you hit connect issues try adding ?sslmode=require
        pass

engine = create_engine(DATABASE_URL, connect_args=connect_args) if DATABASE_URL else None

app = Flask(__name__)

# List of expected tables (keeps same naming as you used)
SHEET_NAMES = [
    "youth_women_empowerment_forecast",
    "tractor_registry_forecast",
    "national_agro_farmer_mapping_forecast",
    "stakeholders_partners_forecast",
    "knowledge_innocvation_tracker_forecast",
    "project_overview_forecast",
    "e_voucher_forecast",
    "farmers_registry_forecast",
    "investment_kpis_forecast",
    "policy_simulator_forecast",
    "rainified_crops_forecast",
    "climate_carbon_credits_forecast",
    "yield_food_security_forecast",
    "input_pest_disease_alert_forecast"
]

def load_all_sheets_from_db():
    """Load all expected tables from Postgres into a single DataFrame."""
    if engine is None:
        return pd.DataFrame()
    dfs = []
    for t in SHEET_NAMES:
        table_name = t.lower()
        try:
            df = pd.read_sql_table(table_name, engine)
            df["Source_Sheet"] = t
            dfs.append(df)
        except Exception as e:
            # table may not exist - skip
            app.logger.debug(f"load_all_sheets_from_db: skipping {table_name}: {e}")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def load_forecasts_fallback_from_sheets(sheet_id=SHEET_ID):
    """Optional fallback: read the youth sheet from Google Sheets if DB is empty."""
    if not sheet_id:
        return pd.DataFrame()
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=youth_women_empowerment_forecast"
    try:
        return pd.read_csv(url)
    except Exception as e:
        app.logger.debug(f"Google Sheets fallback failed: {e}")
        return pd.DataFrame()

# ------------------ Routes ------------------
@app.route("/", methods=["GET"])
def index():
    # Minimal responsive HTML UI (keeps design from your previous code)
    html = """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>AgroVista Forecast Intelligence</title>
      <style>
        body{font-family:Segoe UI,Arial; margin:0; background:#f7f9f7; color:#333}
        header{background:linear-gradient(90deg,#2e7d32,#66bb6a); color:#fff; padding:18px; text-align:center}
        main{max-width:960px;margin:28px auto;padding:0 16px;text-align:center}
        .input-area{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
        input#q{flex:1 1 300px;padding:10px;border-radius:6px;border:1px solid #ccc}
        button{padding:10px 14px;border-radius:6px;background:#4CAF50;color:#fff;border:none}
        #answer{margin-top:20px;color:#1b5e20;font-weight:600}
        table{margin:16px auto;border-collapse:collapse;width:100%;max-width:900px}
        th,td{padding:8px;border:1px solid #ddd;text-align:left}
        @media(max-width:600px){button{width:100%}}
      </style>
    </head>
    <body>
      <header><h1>AgroVista Forecast Intelligence</h1><p>AI-Powered Agricultural Forecasts</p></header>
      <main>
        <div class="input-area">
          <input id="q" placeholder="Ask about yield, pests, investments, or climate..." />
          <button onclick="ask()">Ask</button>
        </div>
        <div id="answer"></div>
        <div id="table"></div>
      </main>
    <script>
    async function ask(){
      const q = document.getElementById('q').value;
      if(!q){document.getElementById('answer').innerText='Please type a question';return;}
      const res = await fetch('/api/query', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({question:q})});
      const data = await res.json();
      document.getElementById('answer').innerText = data.answer || JSON.stringify(data, null, 2);
      if (data.table_html) { document.getElementById('table').innerHTML = data.table_html; }
    }
    </script>
    </body>
    </html>
    """
    return Response(html, mimetype="text/html")

@app.route("/api/all_forecasts", methods=["GET"])
def api_all_forecasts():
    df = load_all_sheets_from_db()
    if df.empty:
        df = load_forecasts_fallback_from_sheets()
        if df.empty:
            return jsonify({"error": "No data found."}), 404
    return jsonify(df.to_dict(orient="records"))

@app.route("/api/forecast", methods=["GET"])
def api_forecast_by_sheet():
    sheet = request.args.get("sheet")
    if not sheet:
        return jsonify({"error":"please provide sheet parameter e.g. ?sheet=youth_women_empowerment_forecast"}), 400
    try:
        df = pd.read_sql_table(sheet.lower(), engine)
        return jsonify(df.to_dict(orient="records"))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/query", methods=["POST"])
def api_query():
    """
    Lightweight "query" endpoint:
    - Loads combined DF from DB
    - Sends a short summary table plus the user question to Gemini (if API key provided)
    - Returns answer + small HTML table preview to display in UI
    """
    req = request.get_json(force=True)
    q = req.get("question","")
    df = load_all_sheets_from_db()
    if df.empty:
        df = load_forecasts_fallback_from_sheets()
        if df.empty:
            return jsonify({"answer":"No forecast data available."})

    # Prepare a small preview table HTML (first 8 rows)
    preview = df.head(8).fillna("").to_html(classes="preview", index=False)

    answer_text = ""
    if GENIE_API_KEY:
        # Prepare concise prompt with sheet names and small sample
        sample = df.head(6).to_dict(orient="records")
        prompt = f"You are an agricultural analyst. Given this dataset (sample): {sample}\nUser question: {q}\nAnswer concisely."
        try:
            model = genai.GenerativeModel("models/gemini-2.0-flash")
            resp = model.generate_content(prompt)
            answer_text = resp.text or ""
        except Exception as e:
            answer_text = f"Gemini error: {e}"
    else:
        # Simple fallback local answer
        answer_text = f"(No GENIE_API_KEY) Received question: {q}. Showing a preview of data."
    return jsonify({"answer": answer_text, "table_html": preview})

# ------------------ Run (for local testing) ------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    # When running locally: app.run(host='0.0.0.0', port=port, debug=True)
    app.run(host="0.0.0.0", port=port)
