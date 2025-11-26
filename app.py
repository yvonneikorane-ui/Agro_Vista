import os
import pandas as pd
from flask import Flask, request, jsonify, Response, abort
from sqlalchemy import create_engine, text
import google.generativeai as genai
import plotly.express as px
import io, base64
import logging
from functools import wraps

# ---------------- Config ----------------
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or "postgresql://postgres:zXIZJfkngAsqkHAdVpOGsRwgBybwryRc@shinkansen.proxy.rlwy.net:13515/railway"
)

GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
SHEET_ID = os.getenv("SHEET_ID")
LOOKER_URL = os.getenv("LOOKER_URL")
REDIS_URL = os.getenv("REDIS_URL")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))

# ---------------- Additional Production Dependencies & Setup ----------------
# Configure Gemini client
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)

# SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("agrovista")

# Optional Redis
try:
    if REDIS_URL:
        import redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    else:
        redis_client = None
except Exception as e:
    logger.warning("Redis not available: %s", e)
    redis_client = None


# ---------------- Helper: cache ----------------
def cache_get(key):
    try:
        if redis_client:
            return redis_client.get(key)
    except Exception:
        pass
    return None


def cache_set(key, value, expire=300):
    try:
        if redis_client:
            redis_client.set(key, value, ex=expire)
    except Exception:
        pass


# ---------------- API Key Decorator ----------------
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if ADMIN_API_KEY:
            key = request.headers.get("x-api-key") or request.args.get("api_key")
            if not key or key != ADMIN_API_KEY:
                return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ---------------- Flask App ----------------
app = Flask(__name__)

# ---------------- Forecast Table Names ----------------
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


# ---------------- Load Data ----------------
def load_all_sheets():
    """Load all forecasts from Postgres."""
    if not engine:
        return {}

    results = {}
    try:
        with engine.connect() as conn:
            for sheet in sheet_names:
                try:
                    df = pd.read_sql(f"SELECT * FROM {sheet}", conn)
                    results[sheet] = df.to_dict(orient="records")
                except Exception:
                    results[sheet] = []
    except Exception as e:
        logger.error("DB load error: %s", e)
        return {}
    return results


# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return jsonify({
        "message": "AgroVista API is running",
        "looker_dashboard": LOOKER_URL or "LOOKER_URL not set",
        "database_connected": bool(engine)
    })


@app.route("/forecasts")
def get_forecasts():
    cache_key = "all_forecasts"

    cached = cache_get(cache_key)
    if cached:
        return Response(cached, mimetype="application/json")

    data = load_all_sheets()
    if not data:
        return jsonify({"error": "No forecast data found"}), 404

    import json
    json_data = json.dumps(data)
    cache_set(cache_key, json_data)
    return Response(json_data, mimetype="application/json")


@app.route("/db_test")
def db_test():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public';"))
            tables = [r[0] for r in result]
        return jsonify({"connected": True, "tables": tables})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})


# ---------------- Run ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
