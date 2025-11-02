from flask import Flask, jsonify, request
from flask_cors import CORS
import pandas as pd
from sqlalchemy import create_engine

# -----------------------------------------------------------
# 1️⃣ Flask app setup
# -----------------------------------------------------------
app = Flask(__name__)
CORS(app)

# -----------------------------------------------------------
# 2️⃣ PostgreSQL connection
# -----------------------------------------------------------
# Replace with your actual Render EXTERNAL DB URL + ?sslmode=require
DB_URL = "postgresql://agro_vista_forecast_db_user:SF01pXR4eSoMHHxI2db7GezQvphdddWq@dpg-d435d2uuk2gs738oc6i0-a.oregon-postgres.render.com/agro_vista_forecast_db"
engine = create_engine(DB_URL)

# -----------------------------------------------------------
# 3️⃣ Define your forecast sheet names
# -----------------------------------------------------------
sheet_names = [
    "youth_women_empowerment_forecast",
    "Tractor_Registry_forecast",
    "National_Agro_Farmer_Mapping_Forecast",
    "Stakeholders_Partners_Forecast",
    "Knowledge_Innocvation_Tracker_Forecast",
    "Project_Overview_Forecast",
    "E_Voucher_Forecast",
    "Farmers_Registry_Forecast",
    "Investment_KPIs_Forecast",
    "Policy_Simulator_Forecast",
    "Rainified_Crops_Forecast",
    "Climate_Carbon_Credits_Forecast",
    "Yield_Food_Security_Forecast",
    "Input_Pest_Disease_Alert_Forecast"
]

# -----------------------------------------------------------
# 4️⃣ Load all tables dynamically from PostgreSQL
# -----------------------------------------------------------
def load_all_sheets():
    """Loads all forecast tables from PostgreSQL and combines them"""
    dfs = []
    for s in sheet_names:
        try:
            df = pd.read_sql_table(s.lower(), engine)
            df["Source_Sheet"] = s
            dfs.append(df)
        except Exception as e:
            print(f"⚠️ Error loading {s}: {e}")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# -----------------------------------------------------------
# 5️⃣ API endpoints
# -----------------------------------------------------------
@app.route('/')
def home():
    return jsonify({
        "message": "🌾 AgroVista API is running successfully!",
        "endpoints": ["/api/all_forecasts", "/api/forecast?sheet=<sheet_name>"]
    })

@app.route('/api/all_forecasts', methods=['GET'])
def get_all_forecasts():
    """Return combined data from all tables"""
    df = load_all_sheets()
    if df.empty:
        return jsonify({"error": "No data found or unable to connect to PostgreSQL"}), 500
    return df.to_json(orient="records")

@app.route('/api/forecast', methods=['GET'])
def get_forecast_by_sheet():
    """Return forecast data for one sheet"""
    sheet = request.args.get("sheet")
    if not sheet:
        return jsonify({"error": "Please specify a sheet name"}), 400
    try:
        df = pd.read_sql_table(sheet.lower(), engine)
        return df.to_json(orient="records")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -----------------------------------------------------------
# 6️⃣ Main app runner
# -----------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
