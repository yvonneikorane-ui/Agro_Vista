import os
import pandas as pd
from flask import Flask, request, jsonify, Response, abort
from sqlalchemy import create_engine
import google.generativeai as genai
import plotly.express as px
import io, base64
import logging
from functools import wraps
from time import time

# ---------------- Config ----------------
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway Postgres URL
GENAI_API_KEY = os.getenv("GENAI_API_KEY")  # Your Gemini API key
SHEET_ID = os.getenv("SHEET_ID")  # Optional Google Sheets fallback
LOOKER_URL = os.getenv("LOOKER_URL")  # Looker dashboard link
REDIS_URL = os.getenv("REDIS_URL")  # Optional Redis for caching (e.g. redis://...)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")  # Optional header-based protection for sensitive endpoints
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))

# ---------------- Additional Production Dependencies & Setup ----------------
# Configure Gemini client safely
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)

# SQLAlchemy engine (defer creation if no DB URL)
engine = create_engine(DATABASE_URL) if DATABASE_URL else None

# Basic logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("agrovista")

# Optional simple in-memory cache as fallback
try:
    # If redis is available, use it - minimal wrapper
    if REDIS_URL:
        import redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    else:
        redis_client = None
except Exception as e:
    logger.warning("Redis not available: %s", e)
    redis_client = None

# Simple decorator for optional API key protection on endpoints
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

app = Flask(__name__)

# ---------------- Forecast Sheets ----------------
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

def cache_get(key):
    try:
        if redis_client:
            return redis_client.get(key)
    except Exception as e:
        logger.debug("redis get error: %s", e)
    return None

def cache_set(key, value, expire=300):
    try:
        if redis_client:
            redis_client.set(key, value, ex=expire)
    except Exception as e:
        logger.debug("redis set error: %s", e)

def load_all_sheets():
    """Load all forecasts from Postgres, fallback to Google Sheets if empty."""
    cache_key = "agrovista:all_sheets_v1"
    cached = cache_get(cache_key)
    if cached:
        try:
            df = pd.read_json(cached, orient="split")
            return df
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
                logger.debug("table %s not found or error: %s", table_name, e)
                continue
    if not dfs and SHEET_ID:
        for s in sheet_names:
            try:
                url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={s}"
                df = pd.read_csv(url)
                df["Source_Sheet"] = s
                dfs.append(df)
            except Exception as e:
                logger.debug("sheet %s not found or error: %s", s, e)
                continue
    df_all = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    try:
        cache_set(cache_key, df_all.to_json(orient="split"), expire=300)
    except Exception:
        pass
    return df_all

# ---------------- Rate limiting (very simple) ----------------
# Minimal token-bucket per-IP in-memory limiter to avoid accidental abuse
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
    # clean old keys occasionally (very small mem)
    if len(rate_store) > 10000:
        rate_store.clear()
    return True

# ---------------- Routes ----------------
@app.route("/")
def index():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>AgroVista Forecast Intelligence</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #f7f9f7; color: #333; }}
            header {{ background: linear-gradient(90deg, #2e7d32, #66bb6a); color: white; padding: 20px; text-align: center; }}
            header h1 {{ margin: 0; font-size: 2.3em; }}
            main {{ margin: 40px auto; max-width: 900px; text-align: center; padding: 0 15px; }}
            .input-area {{ display: flex; flex-wrap: wrap; justify-content: center; align-items: center; gap: 10px; margin-bottom: 25px; }}
            input#q {{ flex: 1 1 300px; padding: 12px; font-size: 1em; border-radius: 6px; border: 1px solid #ccc; min-width: 200px; }}
            button {{ padding: 12px 20px; font-size: 1em; cursor: pointer; background-color: #4CAF50; color: white; border: none; border-radius: 5px; transition: 0.3s; }}
            button:hover {{ background-color: #388e3c; }}
            #answer {{ margin-top: 30px; font-weight: bold; font-size: 1.1em; color: #1b5e20; line-height: 1.6em; }}
            #chart {{ margin-top: 30px; }}
            footer {{ text-align: center; padding: 15px; margin-top: 50px; color: #555; border-top: 1px solid #ddd; }}
            @media (max-width: 600px) {{ header h1 {{ font-size: 1.8em; }} button {{ width: 100%; }} input#q {{ width: 100%; }} }}
        </style>
    </head>
    <body>
        <header>
            <h1>AgroVista Forecast Intelligence</h1>
            <p>AI-Powered Agricultural Forecasting for National Food Security</p>
        </header>
        <main>
            <div class="input-area">
                <input id="q" placeholder="Ask about yield, pests, investments, or climate...">
                <button onclick="ask()">Ask</button>
                <button onclick="startListening()">🎤 Speak</button>
                <button onclick="readResponse()">🔊 Read Aloud</button>
                <button onclick="openDashboard()">📊 Dashboard</button>
            </div>
            <div id="answer"></div>
            <div id="chart"></div>
        </main>
        <footer>© 2025 FMAFS | AgroVista AI Platform</footer>

        <script>
        let lastAnswer = "";
        let isReading = false;
        let currentUtterance = null;

        async function ask(){{
            const q = document.getElementById('q').value;
            if (!q) {{ document.getElementById('answer').innerText = "Please type a question first."; return; }}
            const res = await fetch('/ask', {{ method:"POST", headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{question:q}}) }});
            const data = await res.json();
            lastAnswer = data.answer;
            document.getElementById('answer').innerText = data.answer;
            if (data.chart) {{
                document.getElementById('chart').innerHTML = '<img src="data:image/png;base64,' + data.chart + '">';
            }}
        }}

        function startListening(){{
            const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = 'en-US';
            recognition.start();
            recognition.onresult = function(event){{
                document.getElementById('q').value = event.results[0][0].transcript;
            }};
        }}

        function readResponse(){{
            if (!lastAnswer){{
                alert("No response available to read aloud.");
                return;
            }}
            if (isReading){{
                speechSynthesis.cancel();
                isReading = false;
                currentUtterance = null;
                return;
            }}
            currentUtterance = new SpeechSynthesisUtterance(lastAnswer);
            isReading = true;
            currentUtterance.onend = () => {{ isReading = false; }};
            speechSynthesis.speak(currentUtterance);
        }}

        function openDashboard(){{
            const url = "{LOOKER_URL or '#'}";
            if(url === '#'){{
                alert("Looker dashboard link is not set.");
                return;
            }}
            window.open(url, "_blank");
        }}
        </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype="text/html")

# Health check and readiness endpoints
@app.route("/healthz")
def healthz():
    status = {"ok": True}
    try:
        if engine:
            # cheap DB check
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
    # Basic readiness (app dependencies)
    ready = {"ready": True, "genai": bool(GENAI_API_KEY)}
    return jsonify(ready)

# ============================
# BACKEND FORECAST ENDPOINT
# ============================
@app.route("/ask", methods=["POST"])
@require_api_key
def ask():
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"answer": "Rate limit exceeded. Try again in a minute."}), 429

    try:
        q = request.json.get("question", "")
        if not q:
            return jsonify({"answer": "Please ask a question."})

        df = load_all_sheets()
        if df.empty:
            return jsonify({"answer": "No forecast data available."})

        # Multi-sheet chart visualization
        chart_b64 = None
        try:
            df_sample = df.groupby("Source_Sheet").head(3)
            fig = px.line(df_sample, title="AgroVista Multi-Sheet Forecast Overview", color="Source_Sheet")
            buf = io.BytesIO()
            # Use kaleido engine for static image export; ensures deterministic PNG
            fig.write_image(buf, format="png", engine="kaleido")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.exception("chart generation failed: %s", e)
            chart_b64 = None

        # Combine summaries of all sheets
        sheet_summary = ""
        for s in sheet_names:
            sheet_df = df[df["Source_Sheet"] == s].head(5)
            sheet_summary += f"\n--- {s} ---\n{sheet_df.to_dict(orient='records')}\n"

        # Gemini prompt
        prompt_text = f"""
        You are an agricultural AI analyst for the Nigerian Ministry of Agriculture.
        Here are 14 forecast datasets from national systems (youth, tractors, climate, yield, etc.):
        {sheet_summary}
        Based on this combined data, answer this user query: '{q}'
        Provide insightful, data-informed forecasts and recommendations.
        Each section is shown as a well-formatted table. Use this data to answer the user’s query with insights and numeric reasoning
        """

        answer = "No response generated."
        if GENAI_API_KEY:
            try:
                # Use smaller model if token budget is limited
                model = genai.GenerativeModel("models/gemini-2.0-flash")
                resp = model.generate_content(prompt_text)
                answer = resp.text or answer
            except Exception as e:
                logger.exception("GenAI call failed: %s", e)
                # graceful fallback: basic rule-based summary
                answer = "AI temporarily unavailable; here's a short summary of available data:\n"
                counts = df['Source_Sheet'].value_counts().to_dict()
                answer += f"Data contains {len(df)} rows across {len(counts)} sheets. Top sheets: {counts}"
        else:
            # No API key; return local summary
            answer = "GENAI_API_KEY not set. Local summary:\n"
            counts = df['Source_Sheet'].value_counts().to_dict()
            answer += f"Data contains {len(df)} rows across {len(counts)} sheets. Top sheets: {counts}"

        return jsonify({"answer": answer, "chart": chart_b64})

    except Exception as e:
        logger.exception("Server error in /ask: %s", e)
        return jsonify({"answer": f"Server error: {str(e)}"}), 500

# ---------------- Run ----------------
if __name__ == "__main__":
    # expose for gunicorn to use as `app:gunicorn_app`
    gunicorn_app = app
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
