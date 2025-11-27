# ----------------------------------------------------
# FULL INTEGRATED app.py FOR AGROVISTA
# Includes login/session protection, /ask, /upload_csv, and robust DB handling
# ----------------------------------------------------

import os
import io
import base64
import logging
import pandas as pd
from time import time
from functools import wraps
from flask import Flask, request, jsonify, Response, session, redirect, url_for
from sqlalchemy import create_engine, text
import plotly.express as px
import google.generativeai as genai

# ---------------- CONFIG ----------------
FALLBACK_PUBLIC_URL = "postgresql://postgres:DcYufJdqrTmSmAhRqRPgIAtODXcZHTqp@maglev.proxy.rlwy.net:34809/railway"
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL") or FALLBACK_PUBLIC_URL
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
LOOKER_URL = os.getenv("LOOKER_URL")
REDIS_URL = os.getenv("REDIS_URL")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))  # requests per minute

# ---------------- SETUP ----------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change_this_secret")

# Logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("agrovista")

# SQLAlchemy engine
engine = None
try:
    engine = create_engine(DATABASE_URL)
except Exception as e:
    logger.exception("Failed to create DB engine: %s", e)

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

# Configure Gemini client
if GENAI_API_KEY:
    try:
        genai.configure(api_key=GENAI_API_KEY)
    except Exception:
        logger.warning("Could not configure GenAI at startup")

# ---------------- SIMPLE USERS ----------------
USERS = {
    "admin": "password123",
    "user1": "userpass"
}

# ---------------- HELPERS ----------------
def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

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

RATE_STORE = {}
def check_rate_limit(ip):
    now = int(time())
    window = now // 60
    key = f"{ip}:{window}"
    count = RATE_STORE.get(key, 0)
    if count >= RATE_LIMIT:
        return False
    RATE_STORE[key] = count + 1
    if len(RATE_STORE) > 10000:
        RATE_STORE.clear()
    return True

# ---------------- SHEETS ----------------
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

def load_all_sheets():
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
        variants = [f'SELECT * FROM "{candidate}" LIMIT 10000',
                    f'SELECT * FROM "{candidate.lower()}" LIMIT 10000',
                    f'SELECT * FROM {candidate.lower()} LIMIT 10000']
        for q in variants:
            try:
                df = pd.read_sql(text(q), conn)
                return df
            except Exception:
                continue
        return None
    with engine.connect() as conn:
        for s in sheet_names:
            cand_list = [s, s.lower()]
            if s.lower().endswith("_forecast"):
                cand_list.append(s.lower().replace("_forecast", ""))
            if s.endswith("_forecast"):
                cand_list.append(s.replace("_forecast", ""))
            cand_list = list(dict.fromkeys([c for c in cand_list if c]))
            found = False
            for cand in cand_list:
                df = safe_select(conn, cand)
                if isinstance(df, pd.DataFrame):
                    df["Source_Sheet"] = s
                    dfs.append(df)
                    found = True
                    break
            if not found:
                logger.debug("No table found for %s", s)
    df_all = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    try:
        cache_set(cache_key, df_all.to_json(orient="split"), expire=300)
    except Exception:
        pass
    return df_all

# ---------------- LOGIN ENDPOINT ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    try:
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            if username in USERS and USERS[username] == password:
                session["username"] = username
                return redirect(url_for("index"))
            else:
                return Response(
                    "<h3>Login Failed. Invalid username or password.</h3>"
                    '<a href="/login">Try again</a>', mimetype="text/html"
                )
        login_html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Login - AgroVista</title>
            <style>
                body { font-family: Arial, sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; }
                .login-box { background: white; padding: 40px; border-radius: 10px; box-shadow: 0px 0px 10px rgba(0,0,0,0.1); width: 300px; text-align: center; }
                input { width: 100%; padding: 10px; margin: 10px 0; border-radius: 5px; border: 1px solid #ccc; }
                button { padding: 10px 20px; width: 100%; border: none; border-radius: 5px; background: #4CAF50; color: white; cursor: pointer; }
                button:hover { background: #388e3c; }
            </style>
        </head>
        <body>
            <div class="login-box">
                <h2>Login</h2>
                <form method="POST">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="password" name="password" placeholder="Password" required>
                    <button type="submit">Login</button>
                </form>
            </div>
        </body>
        </html>
        """
        return Response(login_html, mimetype="text/html")
    except Exception as e:
        return jsonify({"error": f"Failed to load login page: {str(e)}"}), 500

# ---------------- INDEX (protected) ----------------
@app.route("/")
@require_login
def index():
    html_content = f"<h2>Welcome {session.get('username')}</h2><p>AgroVista Forecast Dashboard</p>"
    return Response(html_content, mimetype="text/html")

# ---------------- HEALTH ----------------
@app.route("/healthz")
def healthz():
    status = {"ok": True, "db": None}
    try:
        if engine:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status["db"] = True
    except Exception as e:
        status["db"] = False
        status["ok"] = False
        status["error"] = str(e)
    return jsonify(status)

@app.route("/readyz")
def readyz():
    ready = {"ready": True, "genai": bool(GENAI_API_KEY)}
    return jsonify(ready)

# ---------------- CSV UPLOAD ----------------
@app.route("/upload_csv", methods=["POST"])
@require_api_key
def upload_csv():
    try:
        payload = request.get_json(force=True)
        csv_url = payload.get("csv_url")
        table_name = payload.get("table_name")
        if not csv_url or not table_name:
            return jsonify({"error": "csv_url and table_name are required"}), 400
        df = pd.read_csv(csv_url)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_").str.replace("-", "_")
        df.to_sql(table_name, engine, if_exists="append", index=False)
        return jsonify({"ok": True, "rows": len(df), "table": table_name})
    except Exception as e:
        logger.exception("upload_csv failed: %s", e)
        return jsonify({"error": str(e)}), 500

# ---------------- ASK ENDPOINT ----------------
@app.route("/ask", methods=["POST"])
@require_api_key
def ask():
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"answer": "Rate limit exceeded"}), 429
    try:
        q = request.json.get("question", "")
        if not q:
            return jsonify({"answer": "Please ask a question."})
        df = load_all_sheets()
        if df.empty:
            return jsonify({"answer": "No forecast data available.", "db_connected": bool(engine)})
        chart_b64 = None
        try:
            df_sample = df.groupby("Source_Sheet").head(3).reset_index(drop=True)
            numeric_cols = df_sample.select_dtypes(include=["number"]).columns.tolist()
            if numeric_cols:
                y_col = numeric_cols[0]
                fig = px.line(df_sample, x=df_sample.index, y=y_col, color="Source_Sheet")
            else:
                counts = df_sample["Source_Sheet"].value_counts().reset_index()
                counts.columns = ["Source_Sheet", "count"]
                fig = px.bar(counts, x="Source_Sheet", y="count")
            buf = io.BytesIO()
            fig.write_image(buf, format="png", engine="kaleido")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception:
            chart_b64 = None
        answer = "No response generated."
        if GENAI_API_KEY:
            try:
                model = genai.GenerativeModel("models/gemini-2.0-flash")
                resp = model.generate_content(q)
                answer = resp.text or answer
            except Exception:
                answer = "AI temporarily unavailable; here's a local summary."
        else:
            answer = f"GENAI_API_KEY not set; rows: {len(df)}"
        return jsonify({"answer": answer, "chart": chart_b64})
    except Exception as e:
        logger.exception("Error in /ask: %s", e)
        return jsonify({"answer": f"Server error: {str(e)}"}), 500

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
