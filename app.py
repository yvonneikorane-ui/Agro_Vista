# ----------------------------------------------------
# FULLY FUNCTIONAL app.py FOR AGROVISTA
# Admin/User login, logout, Ask/Speak/Read UI, Looker Dashboard
# Corrected: /ask returns actual forecast data from Postgres or GitHub CSVs
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

# ---------------- CONFIG ----------------
DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://postgres:password@host:port/db"
GITHUB_SHEETS_BASE_URL = os.getenv("GITHUB_SHEETS_BASE_URL") or "https://raw.githubusercontent.com/YOURUSERNAME/YOURREPO/main/"
LOOKER_URL = os.getenv("LOOKER_URL")
MAX_RESPONSE_ROWS = 1000

# ---------------- SETUP ----------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or "change_this_secret"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agrovista")

engine = None
try:
    engine = create_engine(DATABASE_URL)
    logger.info("Postgres engine created.")
except Exception as e:
    logger.exception("Failed to create DB engine: %s", e)

# ---------------- USERS ----------------
USERS = {
    "admin": "1234",
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

# ---------------- FORECAST SHEETS ----------------
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
    """Load all sheets from Postgres; fallback to GitHub CSVs if Postgres fails."""
    dfs = []
    if engine:
        with engine.connect() as conn:
            for sheet in sheet_names:
                try:
                    df = pd.read_sql(text(f'SELECT * FROM "{sheet}" LIMIT {MAX_RESPONSE_ROWS}'), conn)
                    df["Source_Sheet"] = sheet
                    dfs.append(df)
                except Exception:
                    continue
    # Fallback: load CSV from GitHub
    if not dfs:
        for sheet in sheet_names:
            try:
                url = f"{GITHUB_SHEETS_BASE_URL}{sheet}.csv"
                df = pd.read_csv(url)
                df["Source_Sheet"] = sheet
                dfs.append(df)
            except Exception:
                continue
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USERS and USERS[username] == password:
            session["username"] = username
            return redirect(url_for("index"))
        return Response("<h3>Login Failed. Invalid username or password.</h3><a href='/login'>Try again</a>", mimetype="text/html")

    return Response("""
    <html><head><title>Login - AgroVista</title></head>
    <body>
        <div style="width:300px;margin:100px auto;text-align:center;">
        <h2>Login</h2>
        <form method="POST">
            <input name="username" placeholder="Username" required><br>
            <input name="password" placeholder="Password" type="password" required><br>
            <button type="submit">Login</button>
        </form>
        </div>
    </body></html>
    """, mimetype="text/html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))

# ---------------- INDEX ----------------
@app.route("/")
@require_login
def index():
    username = session.get("username")
    return Response(f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><title>AgroVista</title></head>
    <body>
        <header><h1>AgroVista Forecast Intelligence</h1><p>Welcome, {username}</p></header>
        <main>
            <input id="q" placeholder="Ask about yield, pests, investments, or climate...">
            <button onclick="ask()">Ask</button>
            <button onclick="openDashboard()">Dashboard</button>
            <div id="answer"></div>
            <div id="chart"></div>
            <a href="/logout">Logout</a>
        </main>
        <script>
        async function ask(){{
            const q = document.getElementById('q').value;
            if(!q) {{ document.getElementById('answer').innerText="Type a question."; return; }}
            const res = await fetch('/ask', {{
                method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{question:q}})
            }});
            const data = await res.json();
            document.getElementById('answer').innerText=data.answer;
            if(data.chart) document.getElementById('chart').innerHTML='<img src="data:image/png;base64,'+data.chart+'">';
        }}
        function openDashboard(){{ window.open("{LOOKER_URL or '#'}","_blank"); }}
        </script>
    </body>
    </html>
    """, mimetype="text/html")

# ---------------- ASK ----------------
@app.route("/ask", methods=["POST"])
@require_login
def ask():
    q = request.json.get("question", "")
    if not q:
        return jsonify({"answer": "Please ask a question."})
    df = load_all_sheets()
    if df.empty:
        return jsonify({"answer": "No forecast data available.", "db_connected": bool(engine)})
    # Return first 5 rows as answer
    answer = df.head(5).to_dict(orient="records")
    answer_text = "\n".join([str(a) for a in answer])

    # Generate chart
    chart_b64 = None
    try:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            fig = px.line(df.head(20), x=df.index[:20], y=numeric_cols[0], color="Source_Sheet")
            buf = io.BytesIO()
            fig.write_image(buf, format="png", engine="kaleido")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
    except Exception:
        chart_b64 = None

    return jsonify({"answer": answer_text, "chart": chart_b64})

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",8080)))
