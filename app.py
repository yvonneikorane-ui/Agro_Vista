# app.py
import os
import io
import base64
import logging
import datetime
import pandas as pd
from functools import wraps

from flask import Flask, request, jsonify, Response, render_template, redirect, url_for
from flask_cors import CORS
from sqlalchemy import create_engine, text
import google.generativeai as genai
import plotly.express as px
import jwt
import stripe
import requests
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------- CONFIG ----------------
DATABASE_URL = os.getenv("DATABASE_URL")
GENAI_API_KEY = os.getenv("GENAI_API_KEY")
SHEET_ID = os.getenv("SHEET_ID")
LOOKER_URL = os.getenv("LOOKER_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret-key")
JWT_EXP_DAYS = int(os.getenv("JWT_EXP_DAYS", "7"))
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "10"))  # free tier daily ask limit

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
DOMAIN = os.getenv("DOMAIN", "")  # public domain

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

engine = create_engine(DATABASE_URL) if DATABASE_URL else None

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("agrovista")

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

# ---------------- BOOTSTRAP DB ----------------
def bootstrap_db():
    if not engine:
        logger.warning("No DATABASE_URL set; skipping DB bootstrap.")
        return
    with engine.begin() as conn:
        # users
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            tier TEXT DEFAULT 'free',
            daily_requests INT DEFAULT 0,
            last_request_date DATE
        );
        """))
        # payments
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id),
            provider TEXT,
            provider_charge_id TEXT,
            amount INT,
            currency TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
        # usage logs
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES users(id),
            endpoint TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """))
    logger.info("Database bootstrap complete.")

bootstrap_db()

# ---------------- JWT / AUTH HELPERS ----------------
def create_token(user_id, email, role):
    exp = datetime.datetime.utcnow() + datetime.timedelta(days=JWT_EXP_DAYS)
    payload = {"user_id": int(user_id), "email": email, "role": role, "exp": exp}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def decode_token(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception as e:
        logger.debug("JWT decode error: %s", e)
        return None

def auth_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            auth = request.headers.get("Authorization", "")
            token = None
            if auth.startswith("Bearer "):
                token = auth.replace("Bearer ", "").strip()
            else:
                token = request.args.get("token") or request.cookies.get("agro_token")
            if not token:
                return redirect(url_for('login_page'))
            decoded = decode_token(token)
            if not decoded:
                return redirect(url_for('login_page'))
            if role and decoded.get("role") != role:
                return jsonify({"error": "Unauthorized"}), 403
            request.user = decoded
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ---------------- SHEET / DATA LOADING ----------------
def load_all_sheets():
    dfs = []
    if engine:
        for s in sheet_names:
            table_name = s.lower()
            try:
                df = pd.read_sql_table(table_name, engine)
                df["Source_Sheet"] = s
                dfs.append(df)
            except Exception as e:
                logger.debug("table %s not found: %s", table_name, e)
                continue
    if not dfs and SHEET_ID:
        for s in sheet_names:
            try:
                url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={s}"
                df = pd.read_csv(url)
                df["Source_Sheet"] = s
                dfs.append(df)
            except Exception as e:
                logger.debug("sheet %s not found: %s", s, e)
                continue
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def increment_user_daily(user_id):
    today = datetime.date.today()
    with engine.begin() as conn:
        user = conn.execute(text("SELECT daily_requests, last_request_date FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        if not user:
            return
        last_date = user.last_request_date
        if not last_date or last_date != today:
            conn.execute(text("UPDATE users SET daily_requests=1, last_request_date=:d WHERE id=:id"), {"d": today, "id": user_id})
        else:
            conn.execute(text("UPDATE users SET daily_requests=daily_requests+1 WHERE id=:id"), {"id": user_id})
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO usage_logs (user_id, endpoint) VALUES (:u, :e)"), {"u": user_id, "e": "/ask"})

# ---------------- ERROR & HEALTH ----------------
@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled error: %s", e)
    return jsonify({"error": "Server error occurred", "details": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ---------------- AUTH ROUTES ----------------
@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return render_template("register.html")
    data = request.json or request.form
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", "user")
    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400
    hashed = generate_password_hash(password)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (email, password, role) VALUES (:e, :p, :r)"), {"e": email, "p": hashed, "r": role})
            user = conn.execute(text("SELECT id, email, role FROM users WHERE email=:e"), {"e": email}).fetchone()
        token = create_token(user.id, user.email, user.role)
        resp = redirect(url_for('app_page'))
        resp.set_cookie('agro_token', token, httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        logger.debug("Register error: %s", e)
        return render_template("register.html", error="Account creation failed; email may exist."), 400

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "GET":
        return render_template("login.html")
    data = request.json or request.form
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return render_template("login.html", error="Email and password required"), 400
    with engine.begin() as conn:
        user = conn.execute(text("SELECT id, email, password, role FROM users WHERE email=:e"), {"e": email}).fetchone()
    if not user or not check_password_hash(user.password, password):
        return render_template("login.html", error="Invalid login"), 401
    token = create_token(user.id, user.email, user.role)
    resp = redirect(url_for('app_page'))
    resp.set_cookie('agro_token', token, httponly=True, samesite='Lax')
    return resp

@app.route("/logout")
def logout():
    resp = redirect(url_for('login_page'))
    resp.delete_cookie('agro_token')
    return resp

# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin/dashboard")
@auth_required(role="admin")
def admin_dashboard():
    users_list = []
    payments_list = []
    with engine.begin() as conn:
        users = conn.execute(text("SELECT id, email, role, tier, daily_requests, last_request_date FROM users")).fetchall()
        payments = conn.execute(text("SELECT * FROM payments ORDER BY created_at DESC")).fetchall()
    for u in users:
        users_list.append(dict(u))
    for p in payments:
        payments_list.append(dict(p))
    return render_template("admin_dashboard.html", users=users_list, payments=payments_list)

# ---------------- STRIPE & PAYSTACK ----------------
@app.route("/create_checkout_session", methods=["POST"])
@auth_required()
def create_checkout_session():
    data = request.json or request.form
    amount = data.get("amount")
    provider = data.get("provider", "stripe")
    user_id = request.user["user_id"]
    user_email = request.user["email"]

    if provider == "stripe":
        if not STRIPE_SECRET_KEY:
            return jsonify({"error": "Stripe not configured"}), 500
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                customer_email=user_email,
                line_items=[{"price_data": {"currency": "ngn", "unit_amount": int(amount), "product_data": {"name": "AgroVista PRO Upgrade"}}, "quantity": 1}],
                mode="payment",
                success_url=(DOMAIN or request.host_url) + "payment_success?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=(DOMAIN or request.host_url) + "payment_cancelled"
            )
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO payments (user_id, provider, provider_charge_id, amount, currency, status)
                    VALUES (:u, 'stripe', :pc, :a, 'NGN', 'pending')
                """), {"u": user_id, "pc": session.id, "a": amount})
            return jsonify({"checkout_url": session.url, "session_id": session.id})
        except Exception as e:
            logger.exception("Stripe checkout failed")
            return jsonify({"error": str(e)}), 500
    elif provider == "paystack":
        if not PAYSTACK_SECRET_KEY:
            return jsonify({"error": "Paystack not configured"}), 500
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        payload = {"email": user_email, "amount": int(amount), "currency": "NGN", "callback_url": f"{DOMAIN or request.host_url}payment_success"}
        try:
            res = requests.post("https://api.paystack.co/transaction/initialize", headers=headers, json=payload)
            data = res.json()
            if data.get("status"):
                ref = data["data"]["reference"]
                with engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO payments (user_id, provider, provider_charge_id, amount, currency, status)
                        VALUES (:u, 'paystack', :ref, :a, 'NGN', 'pending')
                    """), {"u": user_id, "ref": ref, "a": amount})
                return jsonify({"checkout_url": data["data"]["authorization_url"], "reference": ref})
            else:
                return jsonify({"error": data.get("message", "Paystack error")}), 400
        except Exception as e:
            logger.exception("Paystack checkout failed")
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({"error": "Invalid payment provider"}), 400

# ---------------- PROTECTED APP PAGE ----------------
@app.route("/app", methods=["GET"])
@auth_required()
def app_page():
    LOOKER = LOOKER_URL or "#"
    token = request.cookies.get('agro_token') or ''
    # Fetch user tier + remaining free requests
    user_id = request.user["user_id"]
    daily_used = 0
    tier = "free"
    with engine.begin() as conn:
        user = conn.execute(text("SELECT tier, daily_requests, last_request_date FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        if user:
            tier = user.tier
            if user.last_request_date != datetime.date.today():
                daily_used = 0
            else:
                daily_used = user.daily_requests or 0
    remaining_free = max(FREE_DAILY_LIMIT - daily_used, 0)
    return render_template("app.html", looker_url=LOOKER, token=token, tier=tier, remaining_free=remaining_free)

# ---------------- ASK ENDPOINT ----------------
@app.route("/ask", methods=["POST"])
@auth_required()
def ask():
    try:
        q = request.json.get("question", "").strip()
        if not q:
            return jsonify({"answer": "Please ask a question."}), 400

        user_id = request.user["user_id"]
        with engine.begin() as conn:
            user = conn.execute(text("SELECT id, email, role, tier, daily_requests, last_request_date FROM users WHERE id=:id"), {"id": user_id}).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404

        today = datetime.date.today()
        if user.tier == "free":
            last = user.last_request_date
            if not last or last != today:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE users SET daily_requests=0, last_request_date=:d WHERE id=:id"), {"d": today, "id": user_id})
                daily_used = 0
            else:
                daily_used = user.daily_requests or 0
            if daily_used >= FREE_DAILY_LIMIT:
                return jsonify({"error": "Free limit reached. Upgrade to PRO"}), 403
            increment_user_daily(user_id)

        df = load_all_sheets()
        if df.empty:
            return jsonify({"answer": "No forecast data available."}), 200

        chart_b64 = None
        try:
            df_sample = df.groupby("Source_Sheet").head(3)
            fig = px.line(df_sample, title="AgroVista Multi-Sheet Forecast Overview", color="Source_Sheet")
            buf = io.BytesIO()
            fig.write_image(buf, format="png")
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.debug("Chart generation failed: %s", e)
            chart_b64 = None

        sheet_summary = ""
        for s in sheet_names:
            sheet_df = df[df["Source_Sheet"] == s].head(5)
            sheet_summary += f"\n--- {s} ---\n{sheet_df.to_dict(orient='records')}\n"

        prompt_text = f"""
        You are an agricultural AI analyst for Nigeria.
        Here are datasets from national systems:
        {sheet_summary}
        Question: '{q}'
        Provide numeric, data-driven insights.
        """
        answer = "No response generated."
        if GENAI_API_KEY:
            try:
                model = genai.GenerativeModel("models/gemini-2.0-flash")
                resp = model.generate_content(prompt_text)
                answer = resp.text or answer
            except Exception as e:
                logger.exception("GenAI call failed")
                answer = "AI unavailable; showing local data summary."
                counts = df['Source_Sheet'].value_counts().to_dict()
                answer += f" Data rows: {len(df)}; sheets: {len(counts)}; top_sheets: {counts}"
        else:
            counts = df['Source_Sheet'].value_counts().to_dict()
            answer = f"GENAI_API_KEY not set. Local summary: rows={len(df)}, sheets={len(counts)}"
        return jsonify({"answer": answer, "chart": chart_b64})
    except Exception as e:
        logger.exception("Server error in /ask: %s", e)
        return jsonify({"answer": f"Server error: {str(e)}"}), 500

# ---------------- CSV UPLOAD (admin only) ----------------
@app.route("/api/upload", methods=["POST"])
@auth_required(role="admin")
def upload_csv():
    file = request.files.get("file")
    sheet = request.form.get("sheet")
    if not file or not sheet:
        return jsonify({"error": "Missing file or sheet"}), 400
    df = pd.read_csv(file)
    df.to_sql(sheet.lower(), engine, if_exists="replace", index=False)
    return jsonify({"message": f"{sheet} updated"}), 200

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
