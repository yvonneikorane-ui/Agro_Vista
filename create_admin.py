# create_admin.py
import os
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash

DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@agrovista.test")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "Admin@1234")

engine = create_engine(DATABASE_URL)
with engine.begin() as conn:
    hashed = generate_password_hash(ADMIN_PASS)
    try:
        conn.execute(text("INSERT INTO users (email, password, role, tier) VALUES (:e,:p,'admin','pro')"), {"e": ADMIN_EMAIL, "p": hashed})
        print("Admin created:", ADMIN_EMAIL)
    except Exception as e:
        print("Admin creation may have failed (exists?):", e)
