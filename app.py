import os
import pandas as pd
from flask import Flask, request, jsonify, Response
from sqlalchemy import create_engine
import google.generativeai as genai
import plotly.express as px
import io, base64

# ---------------- Config ----------------
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway Postgres URL
GENAI_API_KEY = os.getenv("GENAI_API_KEY")  # Your Gemini API key
SHEET_ID = os.getenv("SHEET_ID")  # Optional Google Sheets fallback

if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)

engine = create_engine(DATABASE_URL) if DATABASE_URL else None

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

def load_all_sheets():
    """Load all forecasts from Postgres, fallback to Google Sheets if empty."""
    dfs = []
    if engine:
        for s in sheet_names:
            table_name = s.lower()
            try:
                df = pd.read_sql_table(table_name, engine)
                df["Source_Sheet"] = s
                dfs.append(df)
            except:
                continue
    if not dfs and SHEET_ID:
        # Fallback: Google Sheets CSV
        for s in sheet_names:
            try:
                url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={s}"
                df = pd.read_csv(url)
                df["Source_Sheet"] = s
                dfs.append(df)
            except:
                continue
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

# ---------------- Routes ----------------
@app.route("/")
def index():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>AgroVista Forecast Intelligence</title>
      <style>
        body {
          font-family: 'Segoe UI', Arial, sans-serif;
          margin: 0;
          background: #f7f9f7;
          color: #333;
        }
        header {
          background: linear-gradient(90deg, #2e7d32, #66bb6a);
          color: white;
          padding: 20px;
          text-align: center;
        }
        header h1 {
          margin: 0;
          font-size: 2.3em;
          letter-spacing: 1px;
        }
        main {
          margin: 40px auto;
          max-width: 800px;
          text-align: center;
        }
        input#q {
          padding: 12px;
          width: 70%;
          font-size: 1em;
          border-radius: 6px;
          border: 1px solid #ccc;
        }
        button {
          padding: 12px 20px;
          margin: 5px;
          font-size: 1em;
          cursor: pointer;
          background-color: #4CAF50;
          color: white;
          border: none;
          border-radius: 5px;
        }
        button:hover {
          background-color: #45a049;
        }
        #answer {
          margin-top: 30px;
          font-weight: bold;
          font-size: 1.1em;
          color: #1b5e20;
          line-height: 1.6em;
        }
        #chart {
          margin-top: 30px;
        }
        footer {
          text-align: center;
          padding: 15px;
          margin-top: 50px;
          color: #555;
          border-top: 1px solid #ddd;
        }
      </style>
    </head>
    <body>
      <header>
        <h1>AgroVista Forecast Intelligence</h1>
        <p>AI-Powered Agricultural Forecasting for National Food Security</p>
      </header>
      <main>
        <input id="q" placeholder="Ask about yield, pests, investments, or climate...">
        <button onclick="ask()">Ask</button>
        <button onclick="startListening()">🎤 Speak</button>
        <div id="answer"></div>
        <div id="chart"></div>
      </main>
      <footer>
        © 2025 FMAFS | AgroVista AI Platform
      </footer>

      <script>
      async function ask(){
        const q = document.getElementById('q').value;
        if (!q) {
          document.getElementById('answer').innerText = "Please type a question first.";
          return;
        }
        const res = await fetch('/ask', {
          method:"POST",
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({question:q})
        });
        const data = await res.json();
        document.getElementById('answer').innerText = data.answer;
        if (data.chart) {
          document.getElementById('chart').innerHTML = '<img src="data:image/png;base64,' + data.chart + '">';
        }
        const utterance = new SpeechSynthesisUtterance(data.answer);
        speechSynthesis.speak(utterance);
      }

      function startListening(){
        const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.lang = 'en-US';
        recognition.start();
        recognition.onresult = function(event){
          document.getElementById('q').value = event.results[0][0].transcript;
        };
      }
      </script>
    </body>
    </html>
    """
    return Response(html_content, mimetype="text/html")

# ============================
# BACKEND FORECAST ENDPOINT
# ============================
@app.route("/ask", methods=["POST"])
def ask():
    try:
        q = request.json.get("question", "")
        if not q:
            return jsonify({"answer": "Please ask a question."})

        df = load_all_sheets()
        if df.empty:
            return jsonify({"answer": "No forecast data available."})

        # Generate forecast visualization
        try:
            fig = px.line(df.head(20), title="AgroVista Forecast Sample")
            buf = io.BytesIO()
            fig.write_image(buf, format="png")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception:
            chart_b64 = None

        # Gemini Prompt
        prompt_text = f"""
        You are an agricultural AI analyst.
        Given the forecast dataset below (representing Nigeria's agricultural projections):
        {df.head(15).to_dict(orient='records')}
        Provide insights or answers to: {q}
        """

        # ✅ Use the correct Gemini model
        model = genai.GenerativeModel("models/gemini-1.5-pro")
        resp = model.generate_content(prompt_text)
        answer = resp.text or "No response generated."

        return jsonify({"answer": answer, "chart": chart_b64})
    except Exception as e:
        return jsonify({"answer": f"Server error: {str(e)}"})

# ---------------- Run ----------------
if __name__ == "__main__":
    gunicorn_app = app
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
