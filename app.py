# app.py — Rewritten with safe DB fallback + append upload endpoint
import os
import pandas as pd
from flask import Flask, request, jsonify, Response
from sqlalchemy import create_engine, text
import google.generativeai as genai
import plotly.express as px
import io, base64
import logging
from functools import wraps
from time import time

# ---------------- Config ----------------
# Priority:
# 1) DATABASE_URL (env) - typical Railway var used by apps inside Railway (may be internal)
# 2) DATABASE_PUBLIC_URL (env) - public reachable URL (use this in Colab / external scripts)
# 3) FALLBACK_PUBLIC_URL - the known public URL you tested (used only if envs missing)
FALLBACK_PUBLIC_URL = "postgresql://postgres:DcYufJdqrTmSmAhRqRPgIAtODXcZHTqp@maglev.proxy.rlwy.net:34809/railway"

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL") or FALLBACK_PUBLIC_URL

# Gemini / Google GenAI
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
SHEET_ID = os.getenv("SHEET_ID")
LOOKER_URL = os.getenv("LOOKER_URL")
REDIS_URL = os.getenv("REDIS_URL")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))

# ---------------- Setup ----------------
# Configure Gemini client safely (best-effort)
if GENAI_API_KEY:
    try:
        genai.configure(api_key=GENAI_API_KEY)
    except Exception:
        logging.getLogger("agrovista").warning("Could not configure genai at startup")

# Create SQLAlchemy engine
engine = None
try:
    engine = create_engine(DATABASE_URL)
except Exception as e:
    logging.getLogger("agrovista").exception("Failed to create DB engine: %s", e)

# Basic logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("agrovista")

# Redis optional cache
try:
    if REDIS_URL:
        import redis
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    else:
        redis_client = None
except Exception as e:
    logger.warning("Redis not available: %s", e)
    redis_client = None

# Simple API key decorator
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if ADMIN_API_KEY:
            key = request.headers.get("x-api-key") or request.args.get("api_key")
            if not key or key != ADMIN_API_KEY:
                logger.warning("Unauthorized access attempt to protected endpoint")
                return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

app = Flask(__name__)

# ---------------- Forecast Sheets (display names you used) ----------------
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

# ---------------- Simple cache helpers ----------------
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

# ---------------- Robust loader: try multiple table-name variants ----------------
def load_all_sheets():
    """
    Load all forecasts from Postgres. Tries multiple candidate naming variants
    **without renaming tables**. Returns DataFrame with column Source_Sheet.
    """
    cache_key = "agrovista:all_sheets_v2"
    cached = cache_get(cache_key)
    if cached:
        try:
            df = pd.read_json(cached, orient="split")
            return df
        except Exception:
            pass

    if not engine:
        logger.warning("No DB engine configured")
        return pd.DataFrame()

    dfs = []

    def safe_select(conn, candidate):
        """
        Try a few SELECT forms for a candidate table name:
        1) quoted candidate (preserves case)
        2) quoted lower candidate
        3) unquoted lower candidate
        Returns DataFrame or None
        """
        try_variants = []
        # quoted original (handles tables created with mixed-case or uppercase names)
        try_variants.append(f'SELECT * FROM "{candidate}" LIMIT 10000')
        # quoted lower
        try_variants.append(f'SELECT * FROM "{candidate.lower()}" LIMIT 10000')
        # unquoted lower (standard practice)
        try_variants.append(f'SELECT * FROM {candidate.lower()} LIMIT 10000')

        for q in try_variants:
            try:
                df = pd.read_sql(text(q), conn)
                return df
            except Exception:
                continue
        return None

    with engine.connect() as conn:
        for s in sheet_names:
            # generate candidate strings to try (do NOT mutate names permanently)
            cand_list = []
            cand_list.append(s)                     # original
            cand_list.append(s.lower())             # lowercase
            if s.lower().endswith("_forecast"):
                cand_list.append(s.lower().replace("_forecast", ""))  # drop suffix
            if s.endswith("_forecast"):
                cand_list.append(s.replace("_forecast", ""))         # drop suffix keep casing
            cand_list.append(s.replace(" ", "_").lower())
            # unique preserve order
            cand_list = list(dict.fromkeys([c for c in cand_list if c]))

            found = False
            for cand in cand_list:
                df = safe_select(conn, cand)
                # df could be None or DataFrame
                if isinstance(df, pd.DataFrame):
                    # attach Source_Sheet as the display label
                    df["Source_Sheet"] = s
                    dfs.append(df)
                    found = True
                    break
            if not found:
                logger.debug("No table found for display name %s; tried: %s", s, cand_list)

    df_all = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    try:
        cache_set(cache_key, df_all.to_json(orient="split"), expire=300)
    except Exception:
        pass
    return df_all

# ---------------- Rate limiting (very simple) ----------------
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

# ---------------- Routes (UI preserved exactly) ----------------
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
            #answer {{ margin-top: 30px; font-weight: bold; font-size: 1.1em; color: #1b5e20; line-height: 1.6em; white-space: pre-wrap; }}
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
            document.getElementById('answer').innerText = "Thinking...";
            document.getElementById('chart').innerHTML = "";
            try {{
                const res = await fetch('/ask', {{ method:"POST", headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{question:q}}) }});
                const data = await res.json();
                lastAnswer = data.answer || data.response || JSON.stringify(data);
                document.getElementById('answer').innerText = lastAnswer;
                if (data.chart) {{
                    document.getElementById('chart').innerHTML = '<img src="data:image/png;base64,' + data.chart + '">';
                }}
            }} catch (e) {{
                document.getElementById('answer').innerText = "Request failed: " + e.message;
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

# Health and readiness endpoints
@app.route("/healthz")
def healthz():
    status = {"ok": True, "db": None}
    try:
        if engine:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status["db"] = True
    except Exception as e:
        logger.exception("DB healthcheck failed")
        status["db"] = False
        status["ok"] = False
        status["error"] = str(e)
    return jsonify(status)

@app.route("/readyz")
def readyz():
    ready = {"ready": True, "genai": bool(GENAI_API_KEY)}
    return jsonify(ready)

# ============================
# ADMIN CSV UPLOAD (APPEND mode)
# ============================
@app.route("/upload_csv", methods=["POST"])
@require_api_key
def upload_csv():
    """
    Protected endpoint to upload a CSV from a raw URL into Postgres.
    Request JSON:
    {
      "csv_url": "https://raw.githubusercontent.com/..../file.csv",
      "table_name": "Exact_Table_Name_In_Postgres"  # keep exact if you care about casing
    }
    Behavior: APPEND rows to the table; if table doesn't exist it will be created.
    """
    try:
        payload = request.get_json(force=True)
        csv_url = payload.get("csv_url")
        table_name = payload.get("table_name")
        if not csv_url or not table_name:
            return jsonify({"error": "csv_url and table_name are required"}), 400

        # Download CSV
        try:
            df = pd.read_csv(csv_url)
        except Exception as e:
            logger.exception("Failed to read CSV from %s: %s", csv_url, e)
            return jsonify({"error": f"Failed to read CSV: {str(e)}"}), 400

        # Clean column names to be stable but do not change table_name
        df.columns = (
            df.columns.str.strip()
            .str.lower()
            .str.replace(" ", "_")
            .str.replace("-", "_")
        )

        # Append to DB using to_sql (if table doesn't exist it will be created)
        try:
            # Using if_exists='append' per your choice B
            df.to_sql(table_name, engine, if_exists="append", index=False)
        except Exception as e:
            logger.exception("Failed to write to table %s: %s", table_name, e)
            return jsonify({"error": f"DB write failed: {str(e)}"}), 500

        return jsonify({"ok": True, "rows": len(df), "table": table_name})
    except Exception as e:
        logger.exception("upload_csv server error: %s", e)
        return jsonify({"error": f"Server error: {str(e)}"}), 500

# ============================
# BACKEND FORECAST ENDPOINT (/ask)
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
            # Provide helpful debug info to aid diagnosis
            # Do NOT expose sensitive details in production; here it's helpful for debugging
            tables_list = []
            try:
                with engine.connect() as conn:
                    res = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
                    tables_list = [r[0] for r in res.fetchall()]
            except Exception:
                tables_list = []
            return jsonify({
                "answer": "No forecast data available. (DB connected: %s)" % bool(engine),
                "db_tables": tables_list
            })

        # Build chart image (sample rows per sheet)
        chart_b64 = None
        try:
            if "Source_Sheet" not in df.columns:
                df["Source_Sheet"] = "unknown"
            df_sample = df.groupby("Source_Sheet").head(3).reset_index(drop=True)
            numeric_cols = df_sample.select_dtypes(include=["number"]).columns.tolist()
            if numeric_cols:
                y_col = numeric_cols[0]
                fig = px.line(df_sample, x=df_sample.index, y=y_col, title="AgroVista Multi-Sheet Forecast Overview", color="Source_Sheet")
            else:
                counts = df_sample["Source_Sheet"].value_counts().reset_index()
                counts.columns = ["Source_Sheet", "count"]
                fig = px.bar(counts, x="Source_Sheet", y="count", title="Rows per Source_Sheet")
            buf = io.BytesIO()
            fig.write_image(buf, format="png", engine="kaleido")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.exception("chart generation failed: %s", e)
            chart_b64 = None

        # Sheet summary
        sheet_summary = ""
        for s in sheet_names:
            subset = df[df["Source_Sheet"] == s]
            if subset.empty:
                sheet_summary += f"\n--- {s} ---\n(No rows)\n"
            else:
                sheet_summary += f"\n--- {s} ---\n{subset.head(5).to_dict(orient='records')}\n"

        # Gemini prompt and response
        prompt_text = f"""
        You are an agricultural AI analyst for the Nigerian Ministry of Agriculture.
        Here are combined forecast extracts from the national datasets:
        {sheet_summary}
        Based on this data, answer the user query: '{q}'
        Provide clear, concise, and numeric recommendations.
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
                answer = "AI temporarily unavailable; here's a short local summary:\n"
                answer += f"Data rows: {len(df)}; sheets: {len(counts)}; top_sheets: {counts}"
        else:
            counts = df['Source_Sheet'].value_counts().to_dict()
            answer = "GENAI_API_KEY not set. Local summary:\n"
            answer += f"Data rows: {len(df)}; sheets: {len(counts)}; top_sheets: {counts}"

        return jsonify({"answer": answer, "chart": chart_b64})

    except Exception as e:
        logger.exception("Server error in /ask: %s", e)
        return jsonify({"answer": f"Server error: {str(e)}"}), 500

# ---------------- Run ----------------
if __name__ == "__main__":
    gunicorn_app = app
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
