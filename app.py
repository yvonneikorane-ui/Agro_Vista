# app.py
"""
Production-ready Flask app that reads forecasts from PostgreSQL and exposes
simple endpoints for the UI. Reads DATABASE_URL and PORT from env vars.
"""

import os
import pandas as pd
from flask import Flask, jsonify, request
from sqlalchemy import create_engine
import google.generativeai as genai

# --- Config from environment ---
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway sets this if you added Postgres plugin
PORT = int(os.getenv("PORT", "8080"))
GENIE_API_KEY = os.getenv("GENIE_API_KEY")  # set this in Railway -> Environment

# --- Basic validation on startup to avoid crashes due to missing env ---
if not DATABASE_URL:
    # don't raise on import — instead show warnings and let endpoints handle it
    print("⚠️ WARNING: DATABASE_URL not set. Endpoints requiring DB will fail until provided.")

if GENIE_API_KEY:
    genai.configure(api_key=GENIE_API_KEY)
else:
    print("⚠️ WARNING: GENIE_API_KEY not set. Gemini calls will fail until provided.")

# --- Init Flask and DB engine lazily (avoid heavy work at import time) ---
app = Flask(__name__)

def get_engine():
    """Create SQLAlchemy engine on demand (safe for runtime)."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return create_engine(DATABASE_URL, future=True)

# List your expected table names (lower-case matching uploader naming)
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

# --- Helper to load all tables from DB safely ---
def load_all_sheets_from_db(limit_rows=1000):
    try:
        engine = get_engine()
    except Exception as e:
        raise RuntimeError(f"DB connection error: {e}")

    dfs = []
    for t in SHEET_NAMES:
        try:
            df = pd.read_sql_table(t, engine)
            df["source_table"] = t
            dfs.append(df)
        except Exception as e:
            # Log but keep going: some tables may not exist yet
            print(f"⚠️ Could not load table {t}: {e}")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# --- Basic routes ---
@app.route("/")
def home():
    return jsonify({
        "message": "AgroVista API running",
        "endpoints": ["/api/all_forecasts", "/api/forecast?sheet=<sheet_name>", "/ask (POST)"]
    })

@app.route("/api/all_forecasts", methods=["GET"])
def api_all_forecasts():
    try:
        df = load_all_sheets_from_db()
        if df.empty:
            return jsonify({"error": "No data - ensure DB tables exist"}), 404
        # limit payload to keep responses light (client can request specific sheet)
        return df.head(1000).to_json(orient="records")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/forecast", methods=["GET"])
def api_forecast_by_sheet():
    sheet = request.args.get("sheet", "").strip().lower()
    if not sheet:
        return jsonify({"error": "Please provide sheet parameter"}), 400
    try:
        engine = get_engine()
        df = pd.read_sql_table(sheet, engine)
        return df.to_json(orient="records")
    except Exception as e:
        return jsonify({"error": f"Could not read table {sheet}: {e}"}), 500

# --- Gemini-backed Q&A endpoint (POST) ---
@app.route("/ask", methods=["POST"])
def ask():
    payload = request.get_json(silent=True) or {}
    question = payload.get("question") or payload.get("q") or ""
    if not question:
        return jsonify({"error": "Missing question in JSON body"}), 400

    # Prepare data summary (only small sample rows to avoid huge prompts)
    try:
        df = load_all_sheets_from_db()
        sample = df.head(10).to_dict(orient="records")
    except Exception as e:
        sample = f"Could not load DB tables: {e}"

    prompt = f"""
You are an agricultural analyst. Use the data sample: {sample}
Answer this user question concisely and in simple language: {question}
"""

    try:
        # Ensure API key exists
        if not GENIE_API_KEY:
            return jsonify({"error": "Genie API key not configured (GENIE_API_KEY)"}), 500

        model = genai.GenerativeModel("models/gemini-2.0-flash")
        resp = model.generate_content(prompt)
        answer_text = getattr(resp, "text", None) or str(resp)
    except Exception as e:
        return jsonify({"error": f"Gemini error: {e}"}), 500

    return jsonify({"answer": answer_text})

# --- Run (only for local dev) ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)




