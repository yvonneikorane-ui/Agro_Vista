import os
import pandas as pd
from flask import Flask, request, jsonify, Response
from sqlalchemy import create_engine
import google.generativeai as genai
import plotly.express as px
import io, base64
import logging
from functools import wraps
from time import time

# ---------------- Config ----------------
# Use public URL for Colab / external testing
DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://postgres:zXIZJfkngAsqkHAdVpOGsRwgBybwryRc@shinkansen.proxy.rlwy.net:13515/railway"
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")  # Your Gemini API key
SHEET_ID = os.getenv("SHEET_ID")  # Optional Google Sheets fallback
LOOKER_URL = os.getenv("LOOKER_URL")  # Looker dashboard link
REDIS_URL = os.getenv("REDIS_URL")  # Optional Redis for caching
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")  # Optional header-based protection
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))

# ---------------- Setup ----------------
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)

engine = create_engine(DATABASE_URL) if DATABASE_URL else None

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("agrovista")

# Redis fallback
try:
    if REDIS_URL:
        import redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    else:
        redis_client = None
except Exception as e:
    logger.warning("Redis not available: %s", e)
    redis_client = None

# ---------------- Utils ----------------
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if ADMIN_API_KEY:
            key = request.headers.get("x-api-key") or request.args.get("api_key")
            if not key or key != ADMIN_API_KEY:
                logger.warning("Unauthorized access attempt")
                return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

sheet_names = [
    "youth_women_empowerment_forecast",
    "tractor_registry_forecast",
    "national_agro_farmer_mapping_forecast",
    "stakeholders_partners_forecast",
    "knowledge_innovation_tracker_forecast",
    "project_overview_forecast",
    "e_voucher_forecast",
    "farmers_registry_forecast",
    "investment_kpis_forecast",
    "policy_simulator_forecast",
    "rainfed_crops_forecast",
    "climate_carbon_credits_forecast",
    "yield_food_security_forecast",
    "input_pest_disease_alert_forecast"
]

def cache_get(key):
    try:
        if redis_client:
            return redis_client.get(key)
    except Exception as e:
        logger.debug("Redis get error: %s", e)
    return None

def cache_set(key, value, expire=300):
    try:
        if redis_client:
            redis_client.set(key, value, ex=expire)
    except Exception as e:
        logger.debug("Redis set error: %s", e)

def load_all_sheets():
    cache_key = "agrovista:all_sheets_v1"
    cached = cache_get(cache_key)
    if cached:
        try:
            return pd.read_json(cached, orient="split")
        except Exception:
            pass

    dfs = []
    if engine:
        for s in sheet_names:
            table_name = s.lower()
            try:
                df = pd.read_sql_table(table_name, engine)
                df["Source_Sheet"] = s
                dfs.append(df)
            except Exception as e:
                logger.debug("Table %s error: %s", table_name, e)
                continue

    if not dfs and SHEET_ID:
        for s in sheet_names:
            try:
                url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={s}"
                df = pd.read_csv(url)
                df["Source_Sheet"] = s
                dfs.append(df)
            except Exception as e:
                logger.debug("Sheet %s error: %s", s, e)
                continue

    df_all = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    try:
        cache_set(cache_key, df_all.to_json(orient="split"), expire=300)
    except Exception:
        pass
    return df_all

# ---------------- Rate Limiting ----------------
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))  # requests per minute
rate_store = {}

def check_rate_limit(ip):
    now = int(time())
    window = now // 60
    key = f"{ip}:{window}"
    count = rate_store.get(key, 0)
    if count >= RATE_LIMIT:
        return False
    rate_store[key] = count + 1
    if len(rate_store) > 10000:
        rate_store.clear()
    return True

# ---------------- Flask App ----------------
app = Flask(__name__)

@app.route("/")
def index():
    html_content = f"""
    <html>
    <head><title>AgroVista Forecast Intelligence</title></head>
    <body>
    <h1>AgroVista AI Forecast</h1>
    <p>Ask about yield, pests, investments, or climate...</p>
    </body>
    </html>
    """
    return Response(html_content, mimetype="text/html")

@app.route("/healthz")
def healthz():
    status = {"ok": True}
    try:
        if engine:
            with engine.connect() as conn:
                conn.execute("SELECT 1")
    except Exception as e:
        logger.exception("DB healthcheck failed")
        status["db"] = False
        status["ok"] = False
        status["error"] = str(e)
    return jsonify(status)

@app.route("/readyz")
def readyz():
    return jsonify({"ready": True, "genai": bool(GENAI_API_KEY)})

@app.route("/ask", methods=["POST"])
@require_api_key
def ask():
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"answer": "Rate limit exceeded. Try again in a minute."}), 429

    q = request.json.get("question", "")
    if not q:
        return jsonify({"answer": "Please ask a question."})

    df = load_all_sheets()
    if df.empty:
        return jsonify({"answer": "No forecast data available."})

    chart_b64 = None
    try:
        df_sample = df.groupby("Source_Sheet").head(3)
        fig = px.line(df_sample, title="AgroVista Multi-Sheet Forecast Overview", color="Source_Sheet")
        buf = io.BytesIO()
        fig.write_image(buf, format="png", engine="kaleido")
        buf.seek(0)
        chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        logger.exception("Chart generation failed: %s", e)

    sheet_summary = ""
    for s in sheet_names:
        sheet_df = df[df["Source_Sheet"] == s].head(5)
        sheet_summary += f"\n--- {s} ---\n{sheet_df.to_dict(orient='records')}\n"

    prompt_text = f"""
    You are an agricultural AI analyst for the Nigerian Ministry of Agriculture.
    Here are 14 forecast datasets from national systems:
    {sheet_summary}
    Based on this combined data, answer this user query: '{q}'
    """

    answer = "No response generated."
    if GENAI_API_KEY:
        try:
            model = genai.GenerativeModel("models/gemini-2.0-flash")
            resp = model.generate_content(prompt_text)
            answer = resp.text or answer
        except Exception as e:
            logger.exception("GenAI call failed: %s", e)
            counts = df['Source_Sheet'].value_counts().to_dict()
            answer = f"AI temporarily unavailable; Data contains {len(df)} rows across {len(counts)} sheets. Top sheets: {counts}"
    else:
        counts = df['Source_Sheet'].value_counts().to_dict()
        answer = f"GENAI_API_KEY not set. Local summary: Data contains {len(df)} rows across {len(counts)} sheets. Top sheets: {counts}"

    return jsonify({"answer": answer, "chart": chart_b64})

# ---------------- Run ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
