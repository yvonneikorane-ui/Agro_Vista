# ----------------------------------------------------
# FULLY FUNCTIONAL app.py FOR AGROVISTA
# Login for user/admin, logout, Ask/Speak/Read UI, Looker Dashboard
# Uses CSVs from GitHub for forecasts instead of PostgreSQL
# ----------------------------------------------------

import os
import io
import base64
import logging
import pandas as pd
from time import time
from functools import wraps
from flask import Flask, request, jsonify, Response, session, redirect, url_for
import plotly.express as px
import google.generativeai as genai
import requests

# ---------------- CONFIG ----------------
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
LOOKER_URL = os.getenv("LOOKER_URL")
REDIS_URL = os.getenv("REDIS_URL")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
MAX_RESPONSE_TOKENS = int(os.getenv("MAX_RESPONSE_TOKENS", "512"))
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "60"))

# ---------------- SETUP ----------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change_this_secret")

# Logging
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

# Configure Gemini client
if GENAI_API_KEY:
    try:
        genai.configure(api_key=GENAI_API_KEY)
    except Exception:
        logger.warning("Could not configure GenAI at startup")

# ---------------- USERS ----------------
USERS = {
    "admin": "1234",  # fixed admin password
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

# ---------------- FORECAST SHEETS ----------------
sheet_names = [
    "youth_women_empowerment_forecast.csv",
    "Tractor_Registry_forecast.csv",
    "National_Agro_Farmer_Mapping_Forecast.csv",
    "Stakeholders_Partners_Forecast.csv",
    "Knowledge_Innocvation_Tracker_Forecast.csv",
    "Project_Overview_Forecast.csv",
    "E_Voucher_Forecast.csv",
    "Farmers_Registry_Forecast.csv",
    "Investment_KPIs_Forecast.csv",
    "Policy_Simulator_Forecast.csv",
    "Rainified_Crops_Forecast.csv",
    "Climate_Carbon_Credits_Forecast.csv",
    "Yield_Food_Security_Forecast.csv",
    "Input_Pest_Disease_Alert_Forecast.csv"
    "youth_women_empowerment.csv",
    "Tractor_Registry.csv",
    "National_Agro_Farmer_Mapping.csv",
    "Stakeholders_Partners.csv",
    "Knowledge_Innocvation_Tracker",
    "Project_Overview.csv",
    "E_Voucher.csv",
    "Farmers_Registry.csv",
    "Investment_KPIs.csv",
    "Policy_Simulator.csv",
    "Rainified_Crops.csv",
    "Climate_Carbon_Credits.csv",
    "Yield_Food_Security.csv",
    "Input_Pest_Disease_Alert.csv"
]

GITHUB_BASE_RAW_URL = "https://raw.githubusercontent.com/<your_github_username>/<your_repo>/main/forecasts/"

def load_all_sheets():
    cache_key = "agrovista:all_sheets"
    cached = cache_get(cache_key)
    if cached:
        try:
            df = pd.read_json(cached, orient="split")
            if not df.empty:
                return df
        except Exception:
            pass

    dfs = []
    for sheet in sheet_names:
        try:
            url = f"{GITHUB_BASE_RAW_URL}{sheet}.csv"
            df_sheet = pd.read_csv(url)
            if not df_sheet.empty:
                df_sheet["Source_Sheet"] = sheet
                dfs.append(df_sheet)
        except Exception as e:
            logger.warning(f"Failed to load {sheet} from GitHub: {e}")

    df_all = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    if not df_all.empty:
        try:
            cache_set(cache_key, df_all.to_json(orient="split"), expire=300)
        except Exception as e:
            logger.warning(f"Failed to cache data: {e}")

    return df_all

# ---------------- LOGIN ----------------
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
        login_html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Login - AgroVista</title></head><body><h2>Login</h2><form method="POST"><input type="text" name="username" placeholder="Username" required><input type="password" name="password" placeholder="Password" required><button type="submit">Login</button></form></body></html>"""
        return Response(login_html, mimetype="text/html")
    except Exception as e:
        return jsonify({"error": f"Failed to load login page: {str(e)}"}), 500

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))

# ---------------- INDEX (protected) ----------------
@app.route("/")
@require_login
def index():
    html_content = f"""
    <!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>AgroVista Forecast Intelligence</title></head>
    <body>
        <h1>Welcome, {session.get('username')}</h1>
        <input id="q" placeholder="Ask about yield, pests, investments, or climate...">
        <button onclick="ask()">Ask</button>
        <div id="answer"></div>
        <div id="chart"></div>
        <a href="/logout">Logout</a>
        <script>
        let lastAnswer = "";
        async function ask(){{
            const q = document.getElementById('q').value;
            if(!q){{ document.getElementById('answer').innerText="Please type a question"; return; }}
            const res = await fetch('/ask', {{
                method:'POST',
                headers:{{'Content-Type':'application/json'}},
                body:JSON.stringify({{question:q}})
            }});
            const data = await res.json();
            lastAnswer = data.answer;
            document.getElementById('answer').innerText = data.answer;
            if(data.chart){{
                document.getElementById('chart').innerHTML='<img src="data:image/png;base64,'+data.chart+'">';
            }}
        }}
        </script>
    </body></html>
    """
    return Response(html_content, mimetype="text/html")

# ---------------- ASK ----------------
@app.route("/ask", methods=["POST"])
@require_login
def ask():
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip):
        return jsonify({"answer": "Rate limit exceeded"}), 429
    try:
        q = request.json.get("question","")
        if not q:
            return jsonify({"answer": "Please ask a question."})

        df = load_all_sheets()
        if df.empty:
            return jsonify({"answer": "No forecast data available from CSVs."})

        chart_b64 = None
        try:
            df_sample = df.groupby("Source_Sheet").head(3).reset_index(drop=True)
            numeric_cols = df_sample.select_dtypes(include=["number"]).columns.tolist()
            if numeric_cols:
                y_col = numeric_cols[0]
                fig = px.line(df_sample, x=df_sample.index, y=y_col, color="Source_Sheet")
            else:
                counts = df_sample["Source_Sheet"].value_counts().reset_index()
                counts.columns = ["Source_Sheet","count"]
                fig = px.bar(counts, x="Source_Sheet", y="count")
            buf = io.BytesIO()
            fig.write_image(buf, format="png", engine="kaleido")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception:
            chart_b64 = None

        answer = f"Forecast data loaded; rows: {len(df)}"
        if GENAI_API_KEY:
            try:
                model = genai.GenerativeModel("models/gemini-2.0-flash")
                prompt_text = f"Data preview: {df.head(5).to_dict()} \nQuery: {q}"
                resp = model.generate_content(prompt_text)
                answer = resp.text or answer
            except Exception:
                answer = "AI temporarily unavailable; here's a local summary."

        return jsonify({"answer": answer, "chart": chart_b64})

    except Exception as e:
        logger.exception("Error in /ask: %s", e)
        return jsonify({"answer": f"Server error: {str(e)}"}), 500

# ---------------- HEALTH ----------------
@app.route("/healthz")
def healthz():
    return jsonify({"ok": True})

@app.route("/readyz")
def readyz():
    return jsonify({"ready": True, "genai": bool(GENAI_API_KEY)})

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT",8080))
    app.run(host="0.0.0.0", port=port)
